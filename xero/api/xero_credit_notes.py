# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate
import hashlib
import json
import re
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff


# --- Validation Functions ---


def validate_credit_note_description(description, item_name=None, item_code=None):
    """
    Validate and sanitize credit note line item description for Xero.
    Xero requires: min 1 char, max 4000 chars
    """
    description = (description or "").strip()

    # Strip HTML tags if description contains them
    if description and "<" in description:
        description = re.sub(r"<[^>]+>", "", description).strip()

    # Fallback if empty
    if not description:
        description = item_name or item_code or "Item"

    # Xero max length is 4000 chars
    if len(description) > 4000:
        description = description[:3997] + "..."

    return description


def validate_credit_note_number(cn_name):
    """
    Validate credit note number for Xero.
    Xero requires: max 255 chars, printable ASCII only
    ACCRECCREDIT must be unique in Xero.
    """
    if not cn_name:
        return None

    # Truncate to 255 chars
    cn_number = cn_name[:255]

    # Remove non-printable ASCII characters (keep 32-126)
    cn_number = "".join(c for c in cn_number if 32 <= ord(c) <= 126)

    return cn_number or None


def validate_credit_note_reference(reference):
    """
    Validate credit note reference for Xero.
    Xero requires: max 255 chars
    Note: Reference is only for ACCRECCREDIT (Sales Credit Notes)
    """
    if not reference:
        return None

    # Truncate to 255 chars
    reference = str(reference)[:255]

    return reference or None


# --- Hash Functions for Change Detection ---


def compute_credit_note_hash(doc):
    """
    Compute MD5 hash of credit note data for change detection.
    """
    hash_data = {
        "posting_date": str(doc.posting_date),
        "currency": doc.currency,
        "customer": doc.get("customer") or doc.get("supplier"),
        "items": [],
        "taxes": [],
    }

    # Add line items
    for item in doc.items:
        hash_data["items"].append(
            {
                "item_code": item.item_code,
                "description": item.description,
                "qty": flt(item.qty),
                "rate": flt(item.rate),
                "amount": flt(item.amount),
                "income_account": item.get("income_account")
                or item.get("expense_account"),
            }
        )

    # Add taxes
    for tax in doc.taxes:
        hash_data["taxes"].append(
            {
                "account_head": tax.account_head,
                "tax_amount": flt(tax.tax_amount_after_discount_amount),
            }
        )

    # Compute hash
    hash_string = json.dumps(hash_data, sort_keys=True)
    return hashlib.md5(hash_string.encode()).hexdigest()


def credit_note_data_changed(doc):
    """
    Check if credit note data has changed since last sync.
    Returns True if data has changed or no hash exists.
    """
    stored_hash = doc.get("xero_data_hash")
    if not stored_hash:
        return True

    current_hash = compute_credit_note_hash(doc)
    return current_hash != stored_hash


# --- Helper Functions ---


def get_xero_account_code(erpnext_account, settings=None):
    """Maps an ERPNext account name to a Xero Account Code using the mapping table."""
    if not settings:
        settings = get_xero_settings()
    account_map = settings.get_account_map()
    return account_map.get(erpnext_account)


def map_erpnext_tax_to_xero(erpnext_tax_template, settings=None):
    """Maps ERPNext tax templates to Xero TaxTypes using the mapping table."""
    if not erpnext_tax_template:
        return "NONE"

    if not settings:
        settings = get_xero_settings()
    tax_map = settings.get_tax_map()
    xero_tax_code = tax_map.get(erpnext_tax_template)

    if not xero_tax_code:
        log_xero_error(
            f"Xero TaxType mapping not found for ERPNext Tax Template: {erpnext_tax_template}. Defaulting to NONE.",
            status="Warning",
        )
        return "NONE"

    return xero_tax_code


# --- Outbound Sync (ERPNext to Xero) ---


@frappe.whitelist()
def enqueue_sync_return(doc, method):
    """
    Enqueue background job to sync a return document (Credit Note) to Xero.

    ERPNext Sales Invoice (is_return=1) → Xero ACCRECCREDIT
    ERPNext Purchase Invoice (is_return=1) → Xero ACCPAYCREDIT
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_credit_notes"):
        return

    # Double-trigger guard: Only sync if not already synced or data has changed
    # This prevents infinite loops when syncing FROM Xero triggers on_submit
    if doc.get("xero_sync_status") == "Synced" and doc.get("xero_credit_note_id"):
        if not credit_note_data_changed(doc):
            log_xero_error(
                message=f"Skipping sync for {doc.doctype} {doc.name}: already synced and data unchanged",
                status="Info",
                erpnext_doc_type=doc.doctype,
                erpnext_doc_name=doc.name,
                category="System Monitoring",
            )
            return

    frappe.enqueue(
        "xero.api.xero_credit_notes.sync_return_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        doc_name=doc.name,
        doc_type=doc.doctype,
    )
    frappe.logger().info(
        f"Queued sync for return document {doc.name} to Xero.", "Xero Sync"
    )


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_return_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs a submitted ERPNext return document to Xero.

    - Sales Invoice with is_return=1 → Xero Credit Note (Type ACCRECCREDIT)
    - Purchase Invoice with is_return=1 → Xero Credit Note (Type ACCPAYCREDIT)

    Uses POST for both create and update (Xero API requirement).

    Ref: https://developer.xero.com/documentation/api/accounting/creditnotes
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return

    # Check per-entity directional toggle for outbound sync
    if not settings.get("sync_credit_notes_to_xero"):
        log_xero_error(
            message=f"Credit note outbound sync is disabled. Skipping {doc_type} {doc_name}.",
            status="Info",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            category="System Monitoring",
        )
        return

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_cn_id = doc.get("xero_credit_note_id")

        # --- Basic Validation ---
        if doc.docstatus != 1 or not doc.is_return:
            log_xero_error(
                f"Cannot sync non-submitted or non-return document: {doc_type} {doc_name}",
                status="Info",
            )
            return

        # --- Check if data has changed (for already synced credit notes) ---
        if xero_cn_id:
            if not credit_note_data_changed(doc):
                log_xero_error(
                    message=f"{doc_type} {doc_name} already synced and data unchanged. Skipping.",
                    status="Info",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=xero_cn_id,
                    xero_entity_type="CreditNote",
                    category="System Monitoring",
                )
                return

        # --- Determine Credit Note Type and Contact ---
        if doc_type == "Sales Invoice":
            cn_type = "ACCRECCREDIT"
            party_type = "Customer"
            party_name = doc.customer
            party_account_field = "debit_to"
        elif doc_type == "Purchase Invoice":
            cn_type = "ACCPAYCREDIT"
            party_type = "Supplier"
            party_name = doc.supplier
            party_account_field = "credit_to"
        else:
            return  # Not a return document we handle here

        # --- Get Linked Xero Contact ID ---
        xero_contact_id = frappe.db.get_value(party_type, party_name, "xero_contact_id")
        if not xero_contact_id:
            # Queue contact sync asynchronously
            frappe.logger().info(
                f"Xero Contact ID not found for {party_type} {party_name}. Queuing contact sync.",
                "Xero Sync",
            )

            from .xero_contacts import enqueue_sync_contact

            try:
                enqueue_sync_contact(party_name, party_type)
            except Exception as e:
                frappe.log_error(
                    f"Failed to queue contact sync: {str(e)}",
                    "Xero Contact Queue Error",
                )

            # Mark as pending prerequisites
            frappe.db.set_value(
                doc_type,
                doc_name,
                {"xero_sync_status": "Pending Prerequisites"},
                update_modified=False,
            )
            frappe.db.commit()

            log_xero_error(
                message=f"{doc_type} {doc_name} sync deferred: {party_type} {party_name} must be synced to Xero first.",
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="System Monitoring",
            )

            # Re-queue for later
            frappe.enqueue(
                "xero.api.xero_credit_notes.sync_return_to_xero",
                queue="short",
                timeout=600,
                retry=1,
                doc_name=doc_name,
                doc_type=doc_type,
                enqueue_after_commit=True,
            )
            return

        # --- Map Line Items ---
        line_items = []
        for item in doc.items:
            # Get Xero Account Code
            erpnext_account = (
                item.income_account
                if doc_type == "Sales Invoice"
                else item.expense_account
            )
            xero_account_code = get_xero_account_code(erpnext_account, settings)
            if not xero_account_code:
                raise Exception(
                    f"Xero Account Code mapping not found for ERPNext Account: {erpnext_account} "
                    f"(Item: {item.item_code or item.description})"
                )

            # Validate description
            description = validate_credit_note_description(
                item.description, item.item_name, item.item_code
            )

            # Build line item
            # For returns, amounts are negative in ERPNext, but Xero expects positive for credit notes
            line_item = {
                "Description": description,
                "Quantity": abs(item.qty),
                "UnitAmount": item.rate,
                "AccountCode": xero_account_code,
                "LineAmount": abs(item.amount),
                "TaxType": map_erpnext_tax_to_xero(item.item_tax_template, settings),
            }

            # Add ItemCode if item has been synced to Xero
            if item.item_code:
                xero_item_id = frappe.db.get_value(
                    "Item", item.item_code, "xero_item_id"
                )
                if xero_item_id:
                    line_item["ItemCode"] = item.item_code

            # Add discount if present
            if item.discount_percentage and item.discount_percentage > 0:
                line_item["DiscountRate"] = item.discount_percentage

            line_items.append(line_item)

        # --- Map Taxes and Charges ---
        for tax in doc.taxes:
            tax_account_code = get_xero_account_code(tax.account_head, settings)
            if not tax_account_code:
                raise Exception(
                    f"Xero Account Code mapping not found for Tax/Charge Account: {tax.account_head}"
                )

            tax_description = validate_credit_note_description(
                tax.description, "Tax/Charge"
            )

            tax_line_item = {
                "Description": tax_description,
                "Quantity": 1,
                "UnitAmount": abs(tax.tax_amount_after_discount_amount),
                "AccountCode": tax_account_code,
                "TaxType": "NONE",
            }
            line_items.append(tax_line_item)

        # --- Construct Credit Note Payload ---
        cn_payload = {
            "Type": cn_type,
            "Contact": {"ContactID": xero_contact_id},
            "Date": getdate(doc.posting_date).isoformat(),
            "LineItems": line_items,
            "CreditNoteNumber": validate_credit_note_number(doc.name),
            "Status": "AUTHORISED",
            "LineAmountTypes": "Exclusive",  # ERPNext default
        }

        # Add Reference field for ACCRECCREDIT only
        if cn_type == "ACCRECCREDIT":
            reference = validate_credit_note_reference(
                doc.get("remarks") or doc.get("po_no")
            )
            if reference:
                cn_payload["Reference"] = reference

        # If updating, include the Xero Credit Note ID
        if xero_cn_id:
            cn_payload["CreditNoteID"] = xero_cn_id

        # --- Make API Call (POST for both create and update) ---
        # Xero API: POST creates OR updates (if CreditNoteID provided, updates; otherwise creates)
        response = xero_request(
            "POST", "CreditNotes", data={"CreditNotes": [cn_payload]}
        )

        # --- Process Response ---
        if response and response.get("CreditNotes"):
            updated_cn = response["CreditNotes"][0]
            new_xero_id = updated_cn.get("CreditNoteID")

            if new_xero_id:
                # Compute hash for change detection
                data_hash = compute_credit_note_hash(doc)

                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {
                        "xero_credit_note_id": new_xero_id,
                        "xero_sync_status": "Synced",
                        "xero_data_hash": data_hash,
                    },
                    update_modified=False,
                )
                frappe.db.commit()

                log_xero_error(
                    message=f"Successfully synced {doc_type} (Return) {doc_name} to Xero.",
                    status="Success",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=new_xero_id,
                    xero_entity_type="CreditNote",
                    direction="ERPNext to Xero",
                )
            else:
                raise Exception("Xero API response did not contain a CreditNoteID.")
        else:
            raise Exception("Invalid response received from Xero CreditNotes API.")

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        # Check if this is an "already exists" type error from Xero API
        if is_already_exists_error(str(e), error_traceback):
            if doc_name and doc_type:
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {"xero_sync_status": "Synced"},
                    update_modified=False,
                )
                frappe.db.commit()

            log_xero_error(
                message=f"{doc_type} (Return) {doc_name} already exists in Xero. No action needed.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                direction="ERPNext to Xero",
            )
        else:
            from ..utils.logging import format_sync_error_message

            if doc_name and doc_type:
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {"xero_sync_status": "Error"},
                    update_modified=False,
                )
                frappe.db.commit()

            user_message = format_sync_error_message(
                doc_type, doc_name, doc_name, "ERPNext to Xero", e
            )

            log_xero_error(
                message=user_message,
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                error_details=error_traceback,
                direction="ERPNext to Xero",
            )


# --- Void/Delete Functions ---


def enqueue_void_credit_note(doc, method):
    """
    Enqueue background job to void a cancelled credit note in Xero.
    Called from on_cancel hook for return documents.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_credit_notes"):
        return

    frappe.enqueue(
        "xero.api.xero_credit_notes.void_credit_note_in_xero",
        queue="short",
        doc_name=doc.name,
        doc_type=doc.doctype,
    )
    frappe.logger().info(
        f"Queued void for {doc.doctype} {doc.name} in Xero.", "Xero Sync"
    )


def void_credit_note_in_xero(doc_name, doc_type):
    """
    Finds the corresponding Xero credit note and voids or deletes it.

    - DRAFT credit notes can be DELETED
    - AUTHORISED credit notes can be VOIDED (if no payments applied)
    """
    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_cn_id = doc.get("xero_credit_note_id")

        if not xero_cn_id:
            log_xero_error(
                f"Cannot void credit note {doc_name}: Xero Credit Note ID not found.",
                status="Info",
            )
            return

        # First, get the current status from Xero
        try:
            xero_data = xero_request("GET", f"CreditNotes/{xero_cn_id}")
            if not xero_data or not xero_data.get("CreditNotes"):
                log_xero_error(
                    message=f"Could not fetch Xero credit note {xero_cn_id} for void/delete",
                    status="Warning",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=xero_cn_id,
                )
                return

            xero_cn = xero_data["CreditNotes"][0]
            xero_status = xero_cn.get("Status")
        except Exception as fetch_error:
            log_xero_error(
                message=f"Error fetching Xero credit note status: {str(fetch_error)}",
                status="Warning",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=xero_cn_id,
            )
            # Default to VOIDED if we can't fetch status
            xero_status = "AUTHORISED"

        # Determine the appropriate status change
        # DRAFT or SUBMITTED → DELETED
        # AUTHORISED → VOIDED
        if xero_status in ["DRAFT", "SUBMITTED"]:
            new_status = "DELETED"
            action = "delete"
        else:
            new_status = "VOIDED"
            action = "void"

        cn_payload = {"CreditNoteID": xero_cn_id, "Status": new_status}

        # Xero API for voiding/deleting is a POST to the CreditNotes endpoint
        response = xero_request(
            "POST", "CreditNotes", data={"CreditNotes": [cn_payload]}
        )

        if response and response.get("CreditNotes"):
            frappe.db.set_value(
                doc_type,
                doc_name,
                "xero_sync_status",
                f"{action.capitalize()}d in Xero",
                update_modified=False,
            )
            frappe.db.commit()
            log_xero_error(
                message=f"Successfully {action}d {doc_type} {doc_name} in Xero (status: {new_status}).",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=xero_cn_id,
                xero_entity_type="CreditNote",
                direction="ERPNext to Xero",
            )
        else:
            raise Exception(
                "Invalid response received from Xero when voiding/deleting credit note."
            )

    except Exception as e:
        log_xero_error(
            message=f"Failed to void/delete {doc_type} {doc_name} in Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback(),
        )


# --- Inbound Sync (Xero to ERPNext) ---


def sync_credit_notes_from_xero(modified_since=None):
    """
    Fetches credit notes from Xero and creates/updates corresponding
    return invoices in ERPNext.

    Args:
        modified_since: ISO date string to fetch only recent credit notes
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return

    # Check per-entity directional toggle for inbound sync
    if not settings.get("sync_credit_notes_from_xero"):
        log_xero_error(
            message="Credit note inbound sync is disabled. Skipping credit notes from Xero.",
            status="Info",
            category="System Monitoring",
        )
        return

    if not settings.get("sync_credit_notes"):
        return

    try:
        page = 1
        params = {"page": page}

        if modified_since:
            params["ModifiedSince"] = modified_since

        while True:
            frappe.logger().info(f"Fetching Xero Credit Notes page {page}", "Xero Sync")
            response = xero_request("GET", "CreditNotes", params=params)

            if not response or not response.get("CreditNotes"):
                break

            credit_notes = response["CreditNotes"]
            if not credit_notes:
                break

            for cn_data in credit_notes:
                try:
                    process_xero_credit_note(cn_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Credit Note ID {cn_data.get('CreditNoteID')}",
                        xero_entity_id=cn_data.get("CreditNoteID"),
                        xero_entity_type="CreditNote",
                        error_details=frappe.get_traceback(),
                    )

            if len(credit_notes) < 100:
                break
            page += 1
            params["page"] = page

        log_xero_error(
            message="Finished syncing credit notes from Xero.", status="Info"
        )

    except Exception as e:
        log_xero_error(
            message="Error during sync_credit_notes_from_xero",
            error_details=frappe.get_traceback(),
        )


def process_xero_credit_note(xero_cn_data, settings):
    """
    Creates or updates an ERPNext return invoice from Xero credit note data.

    Xero ACCRECCREDIT → ERPNext Sales Invoice (is_return=1)
    Xero ACCPAYCREDIT → ERPNext Purchase Invoice (is_return=1)
    """
    from .xero_invoices import (
        parse_xero_date,
        get_or_create_item_from_xero_code,
        get_erpnext_account_from_xero_code,
        get_erpnext_tax_from_xero_type,
    )

    xero_cn_id = xero_cn_data.get("CreditNoteID")
    cn_number = xero_cn_data.get("CreditNoteNumber")
    cn_type = xero_cn_data.get("Type")  # ACCRECCREDIT or ACCPAYCREDIT
    cn_status = xero_cn_data.get("Status", "DRAFT")
    remaining_credit = flt(xero_cn_data.get("RemainingCredit", 0))
    allocations = xero_cn_data.get("Allocations", [])

    if not xero_cn_id or not cn_type:
        log_xero_error(
            message=f"Skipping Xero credit note due to missing ID or Type",
            status="Info",
        )
        return

    # Skip VOIDED or DELETED credit notes
    if cn_status in ["VOIDED", "DELETED"]:
        log_xero_error(
            message=f"Skipping Xero credit note {cn_number}: Status is {cn_status}",
            status="Info",
            xero_entity_id=xero_cn_id,
            xero_entity_type="CreditNote",
        )
        return

    # Determine ERPNext DocType
    erpnext_doctype = (
        "Sales Invoice" if cn_type == "ACCRECCREDIT" else "Purchase Invoice"
    )

    # Check if credit note already exists
    erpnext_doc_name = frappe.db.get_value(
        erpnext_doctype, {"xero_credit_note_id": xero_cn_id}, "name"
    )

    # Get contact information
    xero_contact_id = xero_cn_data.get("Contact", {}).get("ContactID")
    if not xero_contact_id:
        log_xero_error(
            message=f"Skipping Xero credit note {cn_number}: No contact information",
            status="Info",
        )
        return

    # Find corresponding ERPNext customer/supplier
    party_doctype = "Customer" if cn_type == "ACCRECCREDIT" else "Supplier"
    party_name = frappe.db.get_value(
        party_doctype, {"xero_contact_id": xero_contact_id}, "name"
    )

    if not party_name:
        log_xero_error(
            message=f"Skipping Xero credit note {cn_number}: {party_doctype} not found for Xero Contact {xero_contact_id}",
            status="Info",
            xero_entity_id=xero_cn_id,
            xero_entity_type="CreditNote",
        )
        return

    try:
        # Get company
        company = frappe.defaults.get_global_default("company")
        if not company:
            company = frappe.get_all("Company", limit=1, pluck="name")[0]

        # Build remarks with allocation info
        remarks_parts = [
            f"Xero Credit Note: {cn_number}" if cn_number else "Xero Credit Note"
        ]
        if remaining_credit > 0:
            remarks_parts.append(f"Remaining Credit: {remaining_credit}")
        if allocations:
            alloc_info = ", ".join(
                [
                    f"{a.get('Invoice', {}).get('InvoiceNumber', 'Unknown')}: {a.get('Amount', 0)}"
                    for a in allocations
                ]
            )
            remarks_parts.append(f"Allocations: {alloc_info}")
        remarks = " | ".join(remarks_parts)

        # Map header fields
        erpnext_data = {
            "xero_credit_note_id": xero_cn_id,
            "xero_sync_status": "Synced",
            "is_return": 1,  # Mark as return invoice
            "company": company,
            "posting_date": parse_xero_date(xero_cn_data.get("Date")),
            "currency": xero_cn_data.get("CurrencyCode", "USD"),
            "conversion_rate": flt(xero_cn_data.get("CurrencyRate", 1.0)),
            "remarks": remarks,
        }

        # Add party-specific fields
        if erpnext_doctype == "Sales Invoice":
            erpnext_data["customer"] = party_name
            erpnext_data["customer_name"] = xero_cn_data.get("Contact", {}).get("Name")
            erpnext_data["debit_to"] = frappe.get_cached_value(
                "Company", company, "default_receivable_account"
            )
        else:  # Purchase Invoice
            erpnext_data["supplier"] = party_name
            erpnext_data["supplier_name"] = xero_cn_data.get("Contact", {}).get("Name")
            erpnext_data["credit_to"] = frappe.get_cached_value(
                "Company", company, "default_payable_account"
            )

        # Create or update credit note
        if erpnext_doc_name:
            # Update existing
            doc = frappe.get_doc(erpnext_doctype, erpnext_doc_name)
            doc.update(erpnext_data)
            doc.save(ignore_permissions=True)
            log_message = f"Updated {erpnext_doctype} (Return) {erpnext_doc_name} from Xero Credit Note {xero_cn_id}"
        else:
            # Create new
            doc = frappe.new_doc(erpnext_doctype)
            doc.update(erpnext_data)

            # Add line items
            line_items = xero_cn_data.get("LineItems", [])
            for line in line_items:
                item_code = get_or_create_item_from_xero_code(
                    line.get("ItemCode"), line.get("Description"), settings
                )
                account = get_erpnext_account_from_xero_code(
                    line.get("AccountCode"), settings
                )

                if not account:
                    log_xero_error(
                        message=f"Skipping line item in credit note {cn_number}: No account mapping for Xero AccountCode {line.get('AccountCode')}",
                        status="Warning",
                        xero_entity_id=xero_cn_id,
                        xero_entity_type="CreditNote",
                    )
                    continue

                # For credit notes, quantities should be negative in ERPNext
                item_dict = {
                    "description": line.get("Description", "Item from Xero"),
                    "qty": -abs(flt(line.get("Quantity", 1))),  # Negative for return
                    "rate": flt(line.get("UnitAmount", 0)),
                    "amount": -abs(
                        flt(line.get("LineAmount", 0))
                    ),  # Negative for return
                }

                if item_code:
                    item_dict["item_code"] = item_code
                    item_dict["item_name"] = line.get("Description")
                else:
                    item_dict["item_name"] = line.get("Description", "Xero Item")

                # Add account
                if erpnext_doctype == "Sales Invoice":
                    item_dict["income_account"] = account
                else:
                    item_dict["expense_account"] = account

                # Add tax template if mapped
                tax_template = get_erpnext_tax_from_xero_type(
                    line.get("TaxType"), settings
                )
                if tax_template:
                    item_dict["item_tax_template"] = tax_template

                # Add discount if present
                discount_rate = flt(line.get("DiscountRate", 0))
                if discount_rate > 0:
                    item_dict["discount_percentage"] = discount_rate

                doc.append("items", item_dict)

            if not doc.items:
                log_xero_error(
                    message=f"Skipping Xero credit note {cn_number}: No valid line items",
                    status="Warning",
                    xero_entity_id=xero_cn_id,
                    xero_entity_type="CreditNote",
                )
                return

            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created {erpnext_doctype} (Return) {erpnext_doc_name} from Xero Credit Note {xero_cn_id} ({cn_number})"

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type=erpnext_doctype,
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_cn_id,
            xero_entity_type="CreditNote",
            direction="Xero to ERPNext",
        )

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        # Check if this is an "already exists" type error (e.g. DocstatusTransitionError)
        if is_already_exists_error(str(e), error_traceback):
            if erpnext_doc_name:
                frappe.db.set_value(
                    erpnext_doctype,
                    erpnext_doc_name,
                    "xero_sync_status",
                    "Synced",
                    update_modified=False,
                )
                frappe.db.commit()

            log_xero_error(
                message=f"Xero Credit Note {xero_cn_id} ({cn_number}) already exists in ERPNext as {erpnext_doc_name or 'submitted document'}. Skipping update.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=erpnext_doctype
                if "erpnext_doctype" in locals()
                else None,
                erpnext_doc_name=erpnext_doc_name
                if "erpnext_doc_name" in locals()
                else None,
                xero_entity_id=xero_cn_id,
                xero_entity_type="CreditNote",
                direction="Xero to ERPNext",
            )
        else:
            from ..utils.logging import format_sync_error_message

            sync_status = "Error"
            if erpnext_doc_name:
                frappe.db.set_value(
                    erpnext_doctype,
                    erpnext_doc_name,
                    "xero_sync_status",
                    sync_status,
                    update_modified=False,
                )
                frappe.db.commit()

            user_message = format_sync_error_message(
                "Xero Credit Note", xero_cn_id, cn_number, "Xero to ERPNext", e
            )

            log_xero_error(
                message=user_message,
                erpnext_doc_type=erpnext_doctype
                if "erpnext_doctype" in locals()
                else None,
                erpnext_doc_name=erpnext_doc_name
                if "erpnext_doc_name" in locals()
                else None,
                xero_entity_id=xero_cn_id,
                xero_entity_type="CreditNote",
                direction="Xero to ERPNext",
                error_details=error_traceback,
            )
