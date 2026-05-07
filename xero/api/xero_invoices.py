# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate, now_datetime
from frappe.model.mapper import get_mapped_doc
import hashlib
import json
import re
from ..utils.xero_client import (
    xero_request,
    get_xero_settings,
    check_xero_entity_exists,
)
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff
# from .xero_accounts import get_xero_tax_rates # No longer needed here directly

# --- Validation Functions ---


def validate_invoice_description(description, item_name=None, item_code=None):
    """
    Validate and sanitize invoice line item description for Xero.
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


def validate_invoice_number(invoice_name):
    """
    Validate invoice number for Xero.
    Xero requires: max 255 chars, printable ASCII only
    """
    if not invoice_name:
        return None

    # Truncate to 255 chars
    invoice_number = invoice_name[:255]

    # Remove non-printable ASCII characters (keep 32-126)
    invoice_number = "".join(c for c in invoice_number if 32 <= ord(c) <= 126)

    return invoice_number or None


def validate_invoice_reference(reference):
    """
    Validate invoice reference for Xero.
    Xero requires: max 255 chars
    """
    if not reference:
        return None

    # Truncate to 255 chars
    reference = str(reference)[:255]

    return reference or None


# --- Hash Functions for Change Detection ---


def compute_invoice_hash(doc):
    """
    Compute MD5 hash of invoice data for change detection.
    """
    hash_data = {
        "posting_date": str(doc.posting_date),
        "due_date": str(doc.due_date),
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


def invoice_data_changed(doc):
    """
    Check if invoice data has changed since last sync.
    Returns True if data has changed or no hash exists.
    """
    stored_hash = doc.get("xero_data_hash")
    if not stored_hash:
        return True

    current_hash = compute_invoice_hash(doc)
    return current_hash != stored_hash


# --- Invoice Sync (ERPNext to Xero) ---


@frappe.whitelist()
def enqueue_sync_invoice_or_return(doc, method):
    """
    Wrapper function for on_submit event.
    Checks if the document is a return and enqueues the correct sync job.
    """
    if doc.get("is_return"):
        from .xero_credit_notes import enqueue_sync_return

        enqueue_sync_return(doc, method)
    else:
        enqueue_sync_invoice(doc, method)


def enqueue_sync_invoice(doc, method):
    """Enqueue background job to sync a standard invoice to Xero."""
    settings = get_xero_settings()
    # Use the correct per-entity directional flag at enqueue time
    if doc.doctype == "Sales Invoice":
        if not settings.get("sync_invoices_to_xero"):
            return
    else:  # Purchase Invoice
        if not settings.get("sync_bills_to_xero"):
            return

    # Double-trigger guard: read current sync state from DB, NOT from the
    # hook-passed doc object. The hook doc reflects the pre-save in-memory
    # state; the DB holds the authoritative committed values. Reading from
    # the doc can cause the guard to pass on already-synced invoices when
    # the object was loaded before the last set_value committed.
    db_xero_status = frappe.db.get_value(doc.doctype, doc.name, "xero_sync_status")
    db_xero_id = frappe.db.get_value(doc.doctype, doc.name, "xero_invoice_id")
    if db_xero_status == "Synced" and db_xero_id:
        # Check if data has changed since last sync
        if not invoice_data_changed(doc):
            log_xero_error(
                message=f"Skipping sync for {doc.doctype} {doc.name}: already synced and data unchanged",
                status="Info",
                erpnext_doc_type=doc.doctype,
                erpnext_doc_name=doc.name,
                category="System Monitoring",
            )
            return

    frappe.enqueue(
        "xero.api.xero_invoices.sync_invoice_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        doc_name=doc.name,
        doc_type=doc.doctype,
    )
    frappe.logger().info(
        f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync"
    )


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_invoice_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs a submitted ERPNext Sales Invoice or Purchase Invoice to Xero.
    Uses POST for both create and update (Xero API requirement).
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        # frappe.logger().info("Xero Sync master switch is disabled.", "Xero Info")
        return  # Master switch disabled

    # Check per-entity directional toggle for outbound sync
    if doc_type == "Sales Invoice":
        if not settings.get("sync_invoices_to_xero"):
            log_xero_error(
                message=f"Sales Invoice outbound sync is disabled. Skipping {doc_name}.",
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="System Monitoring",
            )
            return
    elif doc_type == "Purchase Invoice":
        if not settings.get("sync_bills_to_xero"):
            log_xero_error(
                message=f"Bills (Purchase Invoice) outbound sync is disabled. Skipping {doc_name}.",
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="System Monitoring",
            )
            return

    try:
        doc = frappe.get_doc(doc_type, doc_name)

        # Always read xero_invoice_id directly from DB — never trust the
        # in-memory doc, which may reflect a stale pre-commit state when
        # the function is retried by the decorator after a partial failure.
        xero_invoice_id = frappe.db.get_value(doc_type, doc_name, "xero_invoice_id")

        # --- Basic Validation ---
        if doc.docstatus != 1:
            log_xero_error(
                f"Cannot sync non-submitted document: {doc_type} {doc_name}",
                status="Info",
            )
            return

        # --- Check if data has changed (for already synced invoices) ---
        if xero_invoice_id:
            if not invoice_data_changed(doc):
                log_xero_error(
                    message=f"{doc_type} {doc_name} already synced and data unchanged. Skipping.",
                    status="Info",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=xero_invoice_id,
                    xero_entity_type="Invoice",
                    category="System Monitoring",
                )
                return

        # --- Determine Invoice Type and Contact ---
        if doc_type == "Sales Invoice":
            xero_invoice_type = "ACCREC"  # Accounts Receivable
            contact_party_type = "Customer"
            contact_party_name = doc.customer
            party_account_field = "debit_to"  # Account receivable
        elif doc_type == "Purchase Invoice":
            xero_invoice_type = "ACCPAY"  # Accounts Payable
            contact_party_type = "Supplier"
            contact_party_name = doc.supplier
            party_account_field = "credit_to"  # Account payable
        else:
            raise ValueError("Unsupported DocType for Xero Invoice sync.")

        # --- Get Linked Xero Contact ID ---
        xero_contact_id = frappe.db.get_value(
            contact_party_type, contact_party_name, "xero_contact_id"
        )
        if not xero_contact_id:
            # Queue contact sync asynchronously instead of inline
            frappe.logger().info(
                f"Xero Contact ID not found for {contact_party_type} {contact_party_name}. Queuing contact sync.",
                "Xero Sync",
            )

            # Queue contact sync (pass party name and type so worker gets correct doc_name, doc_type)
            from .xero_contacts import enqueue_sync_contact

            try:
                enqueue_sync_contact(contact_party_name, contact_party_type)
            except Exception as e:
                frappe.log_error(
                    f"Failed to queue contact sync: {str(e)}",
                    "Xero Contact Queue Error",
                )

            # Mark invoice as pending prerequisites
            frappe.db.set_value(
                doc_type,
                doc_name,
                {"xero_sync_status": "Pending Prerequisites"},
                update_modified=False,
            )
            frappe.db.commit()

            log_xero_error(
                message=f"{doc_type} {doc_name} sync deferred: {contact_party_type} {contact_party_name} must be synced to Xero first. Contact sync queued.",
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="System Monitoring",
            )

            # Re-queue this invoice for later (after contact sync completes)
            frappe.enqueue(
                "xero.api.xero_invoices.sync_invoice_to_xero",
                queue="short",
                timeout=600,
                retry=1,
                doc_name=doc_name,
                doc_type=doc_type,
                enqueue_after_commit=True,
                at_front=False,  # Don't jump the queue
                # Delay by 60 seconds to give contact sync time to complete
                job_id=f"invoice_retry_{doc_name}_{frappe.utils.now()}",
            )
            return

        # --- Map ERPNext Invoice Data to Xero Format ---
        # Ref: https://developer.xero.com/documentation/api/accounting/invoices
        # For Purchase Invoices, use bill_date (supplier's invoice date) if set; fall back to posting_date
        bill_date = doc.get("bill_date") if doc_type == "Purchase Invoice" else None
        invoice_payload = {
            "Type": xero_invoice_type,
            "Contact": {"ContactID": xero_contact_id},
            "Date": getdate(bill_date or doc.posting_date).isoformat(),
            "DueDate": getdate(doc.due_date).isoformat(),
            "LineItems": [],
            "InvoiceNumber": validate_invoice_number(
                doc.name
            ),  # Validate invoice number
            "CurrencyCode": doc.currency,
            "Status": "AUTHORISED",  # Or SUBMITTED? AUTHORISED seems more appropriate for synced invoices.
            # LineAmountTypes: Inclusive, Exclusive, NoTax (default Exclusive)
            # ERPNext invoices are typically tax-exclusive; use Exclusive as safe default
            "LineAmountTypes": "Exclusive",
        }

        # Add Reference field (max 255 chars)
        # Sales Invoice: po_no (customer's PO number)
        # Purchase Invoice: bill_no (supplier's invoice number — the primary Bill identifier in Xero)
        if doc_type == "Sales Invoice":
            reference = validate_invoice_reference(doc.get("po_no"))
        else:
            reference = validate_invoice_reference(doc.get("bill_no"))
        if reference:
            invoice_payload["Reference"] = reference

        # If updating, include the Xero Invoice ID
        if xero_invoice_id:
            invoice_payload["InvoiceID"] = xero_invoice_id

        # --- Map Line Items ---
        for item in doc.items:
            # Get Xero Account Code from mapping in settings
            erpnext_account = (
                item.income_account
                if doc_type == "Sales Invoice"
                else item.expense_account
            )
            xero_account_code = get_xero_account_code(
                erpnext_account, settings
            )  # Pass settings
            if not xero_account_code:
                raise Exception(
                    f"Xero Account Code mapping not found in Xero Settings for ERPNext Account: {erpnext_account} (Item: {item.item_code or item.description})"
                )

            # Validate description (min 1 char, max 4000 chars)
            description = validate_invoice_description(
                item.description, item.item_name, item.item_code
            )

            line_item = {
                "Description": description,
                "Quantity": item.qty,
                "UnitAmount": item.rate,
                "AccountCode": xero_account_code,
                "LineAmount": item.amount,
                # Map Tax Type using mapping in settings
                "TaxType": map_erpnext_tax_to_xero(
                    item.item_tax_template, settings
                ),  # Pass settings
            }

            # Add ItemCode if item has been synced to Xero
            if item.item_code:
                xero_item_code = frappe.db.get_value(
                    "Item", item.item_code, "xero_item_id"
                )
                if xero_item_code:
                    line_item["ItemCode"] = item.item_code

            # Add discount if present
            if item.discount_percentage and item.discount_percentage > 0:
                line_item["DiscountRate"] = item.discount_percentage

            invoice_payload["LineItems"].append(line_item)

        # --- Map Taxes and Charges ---
        # Add each tax/charge as a separate line item, as per Xero's recommendation for non-standard taxes/charges.
        for tax in doc.taxes:
            tax_account_code = get_xero_account_code(tax.account_head, settings)
            if not tax_account_code:
                raise Exception(
                    f"Xero Account Code mapping not found for Tax/Charge Account: {tax.account_head}"
                )

            tax_description = validate_invoice_description(
                tax.description, "Tax/Charge"
            )

            tax_line_item = {
                "Description": tax_description,
                "Quantity": 1,
                "UnitAmount": tax.tax_amount_after_discount_amount,
                "AccountCode": tax_account_code,
                # We set the tax type to NONE for the charge itself, as the tax is part of the line total.
                # The tax on the main items should handle the actual tax calculation.
                "TaxType": "NONE",
            }
            invoice_payload["LineItems"].append(tax_line_item)

        # --- Make API Call (POST for both create and update) ---
        # Xero API: POST creates OR updates (if InvoiceID provided, updates; otherwise creates)
        response = xero_request(
            "POST", "Invoices", data={"Invoices": [invoice_payload]}
        )

        if response and response.get("Invoices"):
            updated_invoice = response["Invoices"][0]
            new_xero_invoice_id = updated_invoice.get("InvoiceID")

            # --- Update ERPNext Document ---
            if new_xero_invoice_id:
                # IMPORTANT: Commit xero_invoice_id to DB immediately and
                # unconditionally BEFORE computing the hash or writing anything
                # else. This ensures that if any subsequent step raises (e.g.
                # a stale-document ValidationError on set_value), a retry of
                # this function will see the ID already present in the DB,
                # include it in the payload as InvoiceID, and Xero will UPDATE
                # the existing invoice rather than CREATE a second one.
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {"xero_invoice_id": new_xero_invoice_id},
                    update_modified=False,
                )
                frappe.db.commit()

                # Now write the remaining sync fields
                data_hash = compute_invoice_hash(doc)
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {
                        "xero_sync_status": "Synced",
                        "xero_data_hash": data_hash,
                    },
                    update_modified=False,
                )
                frappe.db.commit()

                log_xero_error(
                    message=f"Successfully synced {doc_type} {doc_name} to Xero.",
                    status="Success",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=new_xero_invoice_id,
                    xero_entity_type="Invoice",
                    direction="ERPNext to Xero",
                )
            else:
                raise Exception("Xero API response did not contain an InvoiceID.")
        else:
            raise Exception("Invalid response received from Xero Invoices API.")

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        # Check if this is an "already exists" type error from Xero API
        # These are not real sync failures — the entity already exists in Xero
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
                message=f"{doc_type} {doc_name} already exists in Xero. No action needed.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                direction="ERPNext to Xero",
            )
        else:
            from ..utils.logging import format_sync_error_message

            # Genuine sync error
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


def enqueue_void_invoice(doc, method):
    """Enqueue background job to void a cancelled invoice in Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.sync_invoices:
        return

    # Route return documents to credit note void handler
    if doc.get("is_return"):
        from .xero_credit_notes import enqueue_void_credit_note

        enqueue_void_credit_note(doc, method)
        return

    frappe.enqueue(
        "xero.api.xero_invoices.void_invoice_in_xero",
        queue="short",
        doc_name=doc.name,
        doc_type=doc.doctype,
    )
    frappe.logger().info(
        f"Queued void for {doc.doctype} {doc.name} to Xero.", "Xero Sync"
    )


def void_invoice_in_xero(doc_name, doc_type):
    """
    Finds the corresponding Xero invoice and voids or deletes it.
    - DRAFT/SUBMITTED invoices can be DELETED
    - AUTHORISED invoices can be VOIDED (if no payments applied)
    """
    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_invoice_id = doc.get("xero_invoice_id")

        if not xero_invoice_id:
            log_xero_error(
                f"Cannot void invoice {doc_name}: Xero Invoice ID not found.",
                status="Info",
            )
            return

        # First, get the current status from Xero
        try:
            xero_data = xero_request("GET", f"Invoices/{xero_invoice_id}")
            if not xero_data or not xero_data.get("Invoices"):
                log_xero_error(
                    message=f"Could not fetch Xero invoice {xero_invoice_id} for void/delete",
                    status="Warning",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=xero_invoice_id,
                )
                return

            xero_invoice = xero_data["Invoices"][0]
            xero_status = xero_invoice.get("Status")
        except Exception as fetch_error:
            log_xero_error(
                message=f"Error fetching Xero invoice status: {str(fetch_error)}",
                status="Warning",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=xero_invoice_id,
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

        invoice_payload = {"InvoiceID": xero_invoice_id, "Status": new_status}

        # Xero API for voiding/deleting is a POST to the Invoices endpoint
        response = xero_request(
            "POST", "Invoices", data={"Invoices": [invoice_payload]}
        )

        if response and response.get("Invoices"):
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
                xero_entity_id=xero_invoice_id,
                xero_entity_type="Invoice",
                direction="ERPNext to Xero",
            )
        else:
            raise Exception(
                "Invalid response received from Xero when voiding/deleting invoice."
            )

    except Exception as e:
        log_xero_error(
            message=f"Failed to void/delete {doc_type} {doc_name} in Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback(),
        )


# --- Invoice Sync (Xero to ERPNext - Payments) ---


def check_invoice_payments():
    """
    Scheduled task to check for payments on synced invoices in Xero
    and update ERPNext status / create Payment Entries.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        # frappe.logger().info("Xero Sync master switch is disabled.", "Xero Info")
        return  # Master switch disabled
    if not settings.sync_payments:
        return  # Payment sync specifically disabled

    frappe.logger().info("Starting Xero Payment Check", "Xero Sync")
    processed_count = 0

    # Get ERPNext invoices (SI & PI) linked to Xero and not fully paid
    linked_invoices = []
    for doctype in ["Sales Invoice", "Purchase Invoice"]:
        filters = {
            "docstatus": 1,
            "status": ["not in", ["Paid", "Cancelled"]],
            "xero_invoice_id": ["is", "set"],
        }
        invoices = frappe.get_all(
            doctype,
            filters=filters,
            fields=["name", "xero_invoice_id", "grand_total", "outstanding_amount"],
        )
        for inv in invoices:
            inv.doctype = doctype  # Add doctype info for processing
            linked_invoices.append(inv)

    if not linked_invoices:
        frappe.logger().info(
            "No unpaid linked invoices found to check for payments.", "Xero Sync"
        )
        return

    for inv in linked_invoices:
        try:
            # Fetch invoice details from Xero using the ID
            xero_inv_data = xero_request("GET", f"Invoices/{inv.xero_invoice_id}")

            if not xero_inv_data or not xero_inv_data.get("Invoices"):
                log_xero_error(
                    f"Could not fetch details for Xero Invoice ID {inv.xero_invoice_id}",
                    status="Warning",
                    erpnext_doc_type=inv.doctype,
                    erpnext_doc_name=inv.name,
                )
                continue

            xero_invoice = xero_inv_data["Invoices"][0]
            xero_status = xero_invoice.get("Status")
            amount_paid = flt(xero_invoice.get("AmountPaid", 0.0))
            amount_due = flt(xero_invoice.get("AmountDue", 0.0))

            # Load the ERPNext invoice doc once — needed by both branches below.
            # This fixes a NameError where erpnext_inv_doc was only defined
            # inside the 'if amount_due <= 0' block but referenced in the elif.
            erpnext_inv_doc = frappe.get_doc(inv.doctype, inv.name)

            # Compare Xero payment status with ERPNext
            if amount_due <= 0 and inv.outstanding_amount > 0:
                # Invoice is paid in Xero but not (fully) in ERPNext
                log_xero_error(
                    message=f"Invoice {inv.doctype} {inv.name} paid in Xero (ID: {inv.xero_invoice_id}). Updating ERPNext.",
                    status="Info",
                    erpnext_doc_type=inv.doctype,
                    erpnext_doc_name=inv.name,
                    xero_entity_id=inv.xero_invoice_id,
                    xero_entity_type="Invoice",
                    direction="Xero to ERPNext",
                )

                if erpnext_inv_doc.outstanding_amount > 0:
                    # Create Payment Entry if enabled
                    if settings.create_payment_entry_on_sync:
                        create_payment_entry_for_xero_payment(
                            erpnext_inv_doc, xero_invoice, settings
                        )
                    else:
                        # Just update status if PE creation is disabled
                        erpnext_inv_doc.db_set("status", "Paid")
                        frappe.db.commit()  # Commit status change

                    processed_count += 1

            # Handle other status discrepancies if needed (e.g., VOIDED in Xero?)
            elif xero_status == "VOIDED" and erpnext_inv_doc.docstatus == 1:
                log_xero_error(
                    message=f"Invoice {inv.doctype} {inv.name} VOIDED in Xero (ID: {inv.xero_invoice_id}). Consider cancelling in ERPNext.",
                    status="Warning",  # Log as warning, manual action might be needed
                    erpnext_doc_type=inv.doctype,
                    erpnext_doc_name=inv.name,
                    xero_entity_id=inv.xero_invoice_id,
                    xero_entity_type="Invoice",
                    direction="Xero to ERPNext",
                )
                # Optionally attempt to cancel if possible? Be careful with automation here.
                # try:
                #     erpnext_inv_doc.cancel()
                # except Exception as cancel_e:
                #     log_xero_error(f"Failed to auto-cancel {inv.doctype} {inv.name} after Xero void: {cancel_e}", status="Error")

        except Exception as e:
            log_xero_error(
                message=f"Error checking payment for {inv.doctype} {inv.name} (Xero ID: {inv.xero_invoice_id})",
                erpnext_doc_type=inv.doctype,
                erpnext_doc_name=inv.name,
                xero_entity_id=inv.xero_invoice_id,
                xero_entity_type="Invoice",
                direction="Xero to ERPNext",
                error_details=frappe.get_traceback(),
            )

    log_xero_error(
        message=f"Finished Xero Payment Check. Updated {processed_count} invoices.",
        status="Info",
    )


# --- Helper Functions ---


# Cache for mappings to avoid fetching settings repeatedly within a request/job
@frappe.whitelist(allow_guest=True)  # Allow use in JS? Maybe not needed.
def get_cached_mapping(map_type):
    """Gets account or tax mapping from cache or settings."""
    cache_key = f"xero_{map_type}_map"
    mapping = frappe.cache().get_value(cache_key)
    if mapping is None:
        settings = get_xero_settings()
        if map_type == "account":
            mapping = settings.get_account_map()
        elif map_type == "tax":
            mapping = settings.get_tax_map()
        else:
            mapping = {}
        frappe.cache().set_value(
            cache_key, mapping
        )  # Cache for short duration? e.g., 5 mins
    return mapping


def get_xero_account_code(erpnext_account, settings=None):
    """Maps an ERPNext account name to a Xero Account Code using the mapping table."""
    if not settings:
        settings = get_xero_settings()  # Fetch if not passed
    account_map = settings.get_account_map()  # Use method on settings doc
    return account_map.get(erpnext_account)


def map_erpnext_tax_to_xero(erpnext_tax_template, settings=None):
    """Maps ERPNext tax templates to Xero TaxTypes using the mapping table."""
    if not erpnext_tax_template:
        return "NONE"  # Default if no tax template applied

    if not settings:
        settings = get_xero_settings()  # Fetch if not passed
    tax_map = settings.get_tax_map()  # Use method on settings doc
    xero_tax_code = tax_map.get(erpnext_tax_template)

    if not xero_tax_code:
        log_xero_error(
            f"Xero TaxType mapping not found for ERPNext Tax Template: {erpnext_tax_template}. Defaulting to NONE.",
            status="Warning",
        )
        return "NONE"  # Default if no mapping found

    return xero_tax_code


def create_payment_entry_for_xero_payment(invoice_doc, xero_invoice_data, settings):
    """Creates and submits a Payment Entry in ERPNext based on Xero payment."""
    if not settings.create_payment_entry_on_sync or not settings.default_bank_account:
        log_xero_error(
            f"Skipping PE creation for {invoice_doc.doctype} {invoice_doc.name}: Setting disabled or default bank account missing.",
            status="Info",
        )
        # Still update status if PE creation skipped
        if invoice_doc.status != "Paid":
            invoice_doc.db_set("status", "Paid")
            frappe.db.commit()
        return

    try:
        # Basic details
        paid_amount = flt(xero_invoice_data.get("AmountPaid", 0.0))
        if paid_amount <= 0:
            log_xero_error(
                f"Skipping PE creation for {invoice_doc.doctype} {invoice_doc.name}: Xero AmountPaid is zero or missing.",
                status="Info",
            )
            return

        # Check if a PE already exists for this payment (simple check based on amount and invoice)
        # More robust check might involve storing Xero Payment ID if available
        existing_pe = frappe.db.exists(
            "Payment Entry Reference",
            {
                "reference_doctype": invoice_doc.doctype,
                "reference_name": invoice_doc.name,
                # Check amount? This might be tricky with partial payments
            },
        )
        if existing_pe:
            log_xero_error(
                f"Skipping PE creation for {invoice_doc.doctype} {invoice_doc.name}: Payment Entry reference already exists.",
                status="Info",
            )
            # Ensure invoice status is Paid if PE exists but status wasn't updated
            if invoice_doc.status != "Paid":
                invoice_doc.db_set("status", "Paid")
                frappe.db.commit()
            return

        # Determine party type and account
        if invoice_doc.doctype == "Sales Invoice":
            party_type = "Customer"
            party = invoice_doc.customer
            party_account = invoice_doc.debit_to
            mode_of_payment = frappe.db.get_value(
                "Mode of Payment", {"type": "General"}, "name"
            )  # Find a generic MOP
        else:  # Purchase Invoice
            party_type = "Supplier"
            party = invoice_doc.supplier
            party_account = invoice_doc.credit_to
            mode_of_payment = frappe.db.get_value(
                "Mode of Payment", {"type": "Pay"}, "name"
            )  # Find a generic MOP

        # Use default bank account from settings
        paid_from_or_to_account = settings.default_bank_account

        # Create Payment Entry doc
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive" if invoice_doc.doctype == "Sales Invoice" else "Pay"
        pe.party_type = party_type
        pe.party = party
        pe.party_account = party_account
        # Assign to correct field based on payment type
        if pe.payment_type == "Pay":
            pe.paid_from = paid_from_or_to_account
        else:  # Receive
            pe.paid_to = paid_from_or_to_account
        pe.paid_amount = paid_amount
        pe.received_amount = (
            paid_amount  # Assuming payment currency matches invoice currency
        )
        pe.base_paid_amount = (
            paid_amount * invoice_doc.conversion_rate
        )  # Adjust for multi-currency
        pe.base_received_amount = paid_amount * invoice_doc.conversion_rate
        pe.target_exchange_rate = invoice_doc.conversion_rate
        pe.posting_date = (
            nowdate()
        )  # Use today's date for payment? Or try to get from Xero?
        pe.mode_of_payment = mode_of_payment
        pe.reference_no = (
            f"XERO-{xero_invoice_data.get('InvoiceID', invoice_doc.name)}"  # Reference
        )
        pe.reference_date = nowdate()

        pe.append(
            "references",
            {
                "reference_doctype": invoice_doc.doctype,
                "reference_name": invoice_doc.name,
                "bill_no": invoice_doc.bill_no
                if invoice_doc.doctype == "Purchase Invoice"
                else None,
                "due_date": invoice_doc.due_date,
                "total_amount": invoice_doc.grand_total,
                "outstanding_amount": invoice_doc.outstanding_amount,
                "allocated_amount": paid_amount,  # Allocate the full paid amount
            },
        )

        pe.flags.ignore_permissions = True
        pe.flags.ignore_mandatory = True  # May need this depending on PE config
        pe.insert()
        pe.submit()

        log_xero_error(
            f"Created Payment Entry {pe.name} for paid {invoice_doc.doctype} {invoice_doc.name} from Xero.",
            status="Success",
            erpnext_doc_type=invoice_doc.doctype,
            erpnext_doc_name=invoice_doc.name,
            xero_entity_id=xero_invoice_data.get("InvoiceID"),
            xero_entity_type="Invoice/Payment",
        )

    except Exception as e:
        # Log error but don't stop main sync process
        log_xero_error(
            f"Failed to create Payment Entry for {invoice_doc.doctype} {invoice_doc.name}",
            status="Error",
            erpnext_doc_type=invoice_doc.doctype,
            erpnext_doc_name=invoice_doc.name,
            xero_entity_id=xero_invoice_data.get("InvoiceID"),
            error_details=frappe.get_traceback(),
        )
        # Ensure invoice status is still updated even if PE fails? Or mark as error?
        # For safety, let's not mark as Paid if PE creation failed. User needs to resolve.
        # invoice_doc.db_set("status", "Paid") # Maybe don't do this on PE failure


# --- Invoice Sync (Xero to ERPNext) ---


def parse_xero_date(xero_date_string):
    """
    Parse Xero date format /Date(milliseconds+timezone)/ to Python date
    Example: /Date(1769126400000+0000)/ → 2026-01-23

    NOTE: Xero always serialises invoice Date / DueDate as midnight UTC
    milliseconds. We must parse as UTC, NOT local server time, otherwise
    servers west of UTC (e.g. America/*) shift the date back by one day,
    which can spuriously make due_date < posting_date and break ERPNext
    validation.
    """
    if not xero_date_string:
        return None

    # Check if it's already in ISO format
    if not xero_date_string.startswith("/Date("):
        try:
            return getdate(xero_date_string)
        except:
            return None

    # Extract milliseconds from /Date(milliseconds+timezone)/
    import re

    match = re.search(r"/Date\((\d+)", xero_date_string)
    if match:
        milliseconds = int(match.group(1))
        # Convert milliseconds to seconds and create datetime IN UTC
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)
        return dt.date()

    return None


def get_erpnext_account_from_xero_code(
    xero_account_code, settings=None, erpnext_doc_type=None
):
    """
    Reverse lookup: Xero AccountCode → ERPNext Account
    Returns ERPNext account name or None if not found
    """
    if not settings:
        settings = get_xero_settings()

    # Get existing mapping (ERPNext → Xero)
    account_map = settings.get_account_map()

    # Reverse lookup
    for erpnext_account, xero_code in account_map.items():
        if xero_code == xero_account_code:
            return erpnext_account

    # Not found - log warning
    log_xero_error(
        message=f"No ERPNext account mapping found for Xero AccountCode: {xero_account_code}",
        status="Warning",
        category="Mapping Errors",
        xero_entity_type="Invoice",
        erpnext_doc_type=erpnext_doc_type,
        direction="Xero to ERPNext",
    )
    return None


def get_erpnext_tax_from_xero_type(xero_tax_type, settings=None):
    """
    Reverse lookup: Xero TaxType → ERPNext Tax Template
    Returns ERPNext tax template name or None if not found
    """
    if not xero_tax_type or xero_tax_type == "NONE":
        return None

    if not settings:
        settings = get_xero_settings()

    # Get existing mapping (ERPNext → Xero)
    tax_map = settings.get_tax_map()

    # Reverse lookup
    for erpnext_tax, xero_type in tax_map.items():
        if xero_type == xero_tax_type:
            return erpnext_tax

    # Not found - return None (will use no tax)
    return None


def get_or_create_item_from_xero_code(xero_item_code, description, settings=None):
    """
    Lookup ERPNext item by item_code
    Returns item_code or None if not found
    """
    if not xero_item_code:
        return None

    # Check if item exists
    if frappe.db.exists("Item", xero_item_code):
        return xero_item_code

    # Item doesn't exist - log info and return None (will use description only)
    log_xero_error(
        message=f"Item {xero_item_code} not found in ERPNext. Line will use description only.",
        status="Info",
        category="Mapping Errors",
    )
    return None


def sync_invoices_from_xero(invoice_type=None, modified_since=None, status=None):
    """
    Fetches invoices from Xero and creates/updates corresponding
    Sales/Purchase Invoices in ERPNext.

    Args:
        invoice_type: "ACCREC" (Sales) or "ACCPAY" (Purchase) or None (both)
        modified_since: ISO date string to fetch only recent invoices
        status: Filter by status (DRAFT, AUTHORISED, PAID, etc.)
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return

    # Check per-entity directional toggles for inbound sync
    # Allow through if EITHER Sales Invoice or Bills inbound is ON
    if not settings.get("sync_invoices_from_xero") and not settings.get(
        "sync_bills_from_xero"
    ):
        log_xero_error(
            message="Invoice inbound sync is disabled (both Sales Invoices and Bills are OFF). Skipping.",
            status="Info",
            category="System Monitoring",
        )
        return

    try:
        page = 1
        params = {"page": page}

        if invoice_type:
            params["Type"] = invoice_type
        if modified_since:
            params["ModifiedSince"] = modified_since
        if status:
            params["Status"] = status

        while True:
            frappe.logger().info(f"Fetching Xero Invoices page {page}", "Xero Sync")
            response = xero_request("GET", "Invoices", params=params)

            if not response or not response.get("Invoices"):
                break

            invoices = response["Invoices"]
            if not invoices:
                break

            for invoice_data in invoices:
                try:
                    process_xero_invoice(invoice_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Invoice ID {invoice_data.get('InvoiceID')}",
                        xero_entity_id=invoice_data.get("InvoiceID"),
                        xero_entity_type="Invoice",
                        error_details=frappe.get_traceback(),
                    )

            if len(invoices) < 100:
                break
            page += 1
            params["page"] = page

        log_xero_error(message="Finished syncing invoices from Xero.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_invoices_from_xero",
            error_details=frappe.get_traceback(),
        )


def process_xero_invoice(xero_invoice_data, settings):
    """
    Creates or updates an ERPNext Sales/Purchase Invoice from Xero invoice data.
    """
    xero_invoice_id = xero_invoice_data.get("InvoiceID")
    invoice_number = xero_invoice_data.get("InvoiceNumber")
    invoice_type = xero_invoice_data.get("Type")  # ACCREC or ACCPAY

    if not xero_invoice_id or not invoice_type:
        log_xero_error(
            message=f"Skipping Xero invoice due to missing ID or Type", status="Info"
        )
        return

    # Respect per-entity direction toggle for inbound
    if invoice_type == "ACCREC" and not settings.get("sync_invoices_from_xero"):
        return  # Sales Invoice inbound disabled
    if invoice_type == "ACCPAY" and not settings.get("sync_bills_from_xero"):
        return  # Bills inbound disabled

    # Determine ERPNext DocType
    erpnext_doctype = (
        "Sales Invoice" if invoice_type == "ACCREC" else "Purchase Invoice"
    )

    # Check if invoice already exists
    erpnext_doc_name = frappe.db.get_value(
        erpnext_doctype, {"xero_invoice_id": xero_invoice_id}, "name"
    )

    # Get contact information
    xero_contact_id = xero_invoice_data.get("Contact", {}).get("ContactID")
    if not xero_contact_id:
        log_xero_error(
            message=f"Skipping Xero invoice {invoice_number}: No contact information",
            status="Info",
        )
        return

    # Find corresponding ERPNext customer/supplier
    party_doctype = "Customer" if invoice_type == "ACCREC" else "Supplier"
    party_name = frappe.db.get_value(
        party_doctype, {"xero_contact_id": xero_contact_id}, "name"
    )

    if not party_name:
        log_xero_error(
            message=f"Skipping Xero invoice {invoice_number}: {party_doctype} not found for Xero Contact {xero_contact_id}. Please sync contacts first.",
            status="Info",
            xero_entity_id=xero_invoice_id,
            xero_entity_type="Invoice",
        )
        return

    try:
        # Get company - use default company
        company = frappe.defaults.get_global_default("company")
        if not company:
            # Get first company
            company = frappe.get_all("Company", limit=1, pluck="name")[0]

        # Map header fields
        posting_date = parse_xero_date(xero_invoice_data.get("Date"))
        due_date = parse_xero_date(xero_invoice_data.get("DueDate"))

        # Fall back to posting_date if Xero did not supply a DueDate
        if not due_date:
            due_date = posting_date
            if posting_date:
                log_xero_error(
                    message=(
                        f"Xero invoice {invoice_number} had no DueDate; "
                        f"defaulting due_date to posting_date {posting_date}."
                    ),
                    status="Warning",
                    xero_entity_id=xero_invoice_id,
                    xero_entity_type="Invoice",
                    erpnext_doc_type=erpnext_doctype,
                    direction="Xero to ERPNext",
                    category="Validation Errors",
                )

        # Clamp: ERPNext rejects due_date < posting_date. Some Xero invoices
        # (back-dated, immediate-payment, imported) have DueDate before Date.
        # Allow the sync to proceed by clamping due_date up to posting_date,
        # and surface the discrepancy on the dashboard via Xero Log.
        if due_date and posting_date and due_date < posting_date:
            log_xero_error(
                message=(
                    f"Xero invoice {invoice_number} had DueDate {due_date} "
                    f"before posting Date {posting_date}; clamping due_date "
                    f"to posting_date so the invoice can sync."
                ),
                status="Warning",
                xero_entity_id=xero_invoice_id,
                xero_entity_type="Invoice",
                erpnext_doc_type=erpnext_doctype,
                direction="Xero to ERPNext",
                category="Validation Errors",
            )
            due_date = posting_date

        erpnext_data = {
            "xero_invoice_id": xero_invoice_id,
            "xero_sync_status": "Synced",
            "company": company,
            "posting_date": posting_date,
            "due_date": due_date,
            "currency": xero_invoice_data.get("CurrencyCode", "USD"),
            "conversion_rate": flt(xero_invoice_data.get("CurrencyRate", 1.0)),
            # Trust Xero's Date / DueDate as the source of truth for inbound
            # invoices. ignore_default_payment_terms_template=1 skips ERPNext's
            # validate_due_date() entirely (see accounts_controller.py:660-662),
            # and clearing payment_terms_template prevents set_payment_schedule()
            # from generating template-driven rows that would conflict with the
            # dates we just clamped above.
            "ignore_default_payment_terms_template": 1,
            "payment_terms_template": None,
        }

        # Add party-specific fields
        if erpnext_doctype == "Sales Invoice":
            erpnext_data["customer"] = party_name
            erpnext_data["customer_name"] = xero_invoice_data.get("Contact", {}).get(
                "Name"
            )
            # Get default debit_to account
            erpnext_data["debit_to"] = frappe.get_cached_value(
                "Company", company, "default_receivable_account"
            )
        else:  # Purchase Invoice
            erpnext_data["supplier"] = party_name
            erpnext_data["supplier_name"] = xero_invoice_data.get("Contact", {}).get(
                "Name"
            )
            # Get default credit_to account
            erpnext_data["credit_to"] = frappe.get_cached_value(
                "Company", company, "default_payable_account"
            )
            # bill_date: map from the already-parsed/clamped posting_date
            # (NOT a fresh parse of Xero Date). For Purchase Invoices, ERPNext
            # validates due_date against bill_date, not posting_date — so this
            # must use the same value we just clamped above.
            erpnext_data["bill_date"] = posting_date

        # Map reference fields
        reference = xero_invoice_data.get("Reference")
        if reference:
            if erpnext_doctype == "Sales Invoice":
                erpnext_data["po_no"] = reference
            else:
                erpnext_data["bill_no"] = reference

        # Map status - always create as Draft for safety
        xero_status = xero_invoice_data.get("Status", "DRAFT")
        erpnext_data["docstatus"] = 0  # Always create as Draft

        # Store Xero invoice number in remarks field (title doesn't exist on Sales/Purchase Invoice)
        if invoice_number:
            erpnext_data["remarks"] = f"Xero Invoice: {invoice_number}"

        # Create or update invoice
        if erpnext_doc_name:
            # Update existing invoice
            doc = frappe.get_doc(erpnext_doctype, erpnext_doc_name)
            doc.update(erpnext_data)
            doc.save(ignore_permissions=True)
            log_message = f"Updated {erpnext_doctype} {erpnext_doc_name} from Xero Invoice {xero_invoice_id}"
        else:
            # Create new invoice
            doc = frappe.new_doc(erpnext_doctype)
            doc.update(erpnext_data)

            # Add line items
            line_items = xero_invoice_data.get("LineItems", [])
            for line in line_items:
                # Get item code if available
                item_code = get_or_create_item_from_xero_code(
                    line.get("ItemCode"), line.get("Description"), settings
                )

                # Get account mapping
                account = get_erpnext_account_from_xero_code(
                    line.get("AccountCode"), settings, erpnext_doctype
                )

                if not account:
                    # Skip line if account not mapped
                    log_xero_error(
                        message=f"Skipping line item in invoice {invoice_number}: No account mapping for Xero AccountCode {line.get('AccountCode')}",
                        status="Warning",
                        xero_entity_id=xero_invoice_id,
                        xero_entity_type="Invoice",
                        erpnext_doc_type=erpnext_doctype,
                        direction="Xero to ERPNext",
                        category="Mapping Errors",
                    )
                    continue

                # Build line item dict
                item_dict = {
                    "description": line.get("Description", "Item from Xero"),
                    "qty": flt(line.get("Quantity", 1)),
                    "rate": flt(line.get("UnitAmount", 0)),
                    "amount": flt(line.get("LineAmount", 0)),
                }

                # Add item code if found
                if item_code:
                    item_dict["item_code"] = item_code
                    item_dict["item_name"] = line.get("Description")
                else:
                    # Use description as item_name when no item_code
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

            # Check if we have at least one line item
            if not doc.items:
                log_xero_error(
                    message=f"Skipping Xero invoice {invoice_number}: No valid line items (all skipped due to missing account mappings)",
                    status="Warning",
                    xero_entity_id=xero_invoice_id,
                    xero_entity_type="Invoice",
                    erpnext_doc_type=erpnext_doctype,
                    direction="Xero to ERPNext",
                    category="Mapping Errors",
                )
                return

            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created {erpnext_doctype} {erpnext_doc_name} from Xero Invoice {xero_invoice_id} ({invoice_number})"

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type=erpnext_doctype,
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_invoice_id,
            xero_entity_type="Invoice",
            direction="Xero to ERPNext",
        )

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        # Check if this is an "already exists" type error (e.g. DocstatusTransitionError)
        # These are not real sync failures — the entity already exists and is synced
        if is_already_exists_error(str(e), error_traceback):
            # Don't mark as Error — the document already exists and is synced
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
                message=f"Xero Invoice {xero_invoice_id} ({invoice_number}) already exists in ERPNext as {erpnext_doc_name or 'submitted document'}. Skipping update.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=erpnext_doctype
                if "erpnext_doctype" in locals()
                else None,
                erpnext_doc_name=erpnext_doc_name
                if "erpnext_doc_name" in locals()
                else None,
                xero_entity_id=xero_invoice_id,
                xero_entity_type="Invoice",
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
                "Xero Invoice", xero_invoice_id, invoice_number, "Xero to ERPNext", e
            )

            log_xero_error(
                message=user_message,
                erpnext_doc_type=erpnext_doctype
                if "erpnext_doctype" in locals()
                else None,
                erpnext_doc_name=erpnext_doc_name
                if "erpnext_doc_name" in locals()
                else None,
                xero_entity_id=xero_invoice_id,
                xero_entity_type="Invoice",
                direction="Xero to ERPNext",
                error_details=error_traceback,
            )


# TODO: Implement Journal Entry sync
# TODO: Implement Credit Note sync
