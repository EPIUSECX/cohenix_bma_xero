# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff
from .xero_invoices import get_xero_account_code, map_erpnext_tax_to_xero

# --- Quote Sync (ERPNext to Xero) ---

@frappe.whitelist()
def enqueue_sync_quotation(doc, method):
    """Enqueue background job to sync a Quotation to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_quotes"):
        return

    frappe.enqueue(
        "xero.api.xero_quotes.sync_quotation_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync")


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_quotation_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs a submitted ERPNext Quotation to Xero as a Quote.
    Uses PUT for create/update.
    Ref: https://developer.xero.com/documentation/api/accounting/quotes
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return # Master switch disabled
    
    # Check directional toggle for outbound sync
    if not settings.enable_sync_to_xero:
        log_xero_error(
            message=f"Sync to Xero is disabled. Skipping {doc_type} {doc_name} outbound sync.",
            status="Info",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_quotes"):
        return # Quote sync specifically disabled

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_quote_id = doc.get("xero_quote_id")

        # --- Basic Validation ---
        if doc.docstatus != 1:
            log_xero_error(f"Cannot sync non-submitted document: {doc_type} {doc_name}", status="Info")
            return

        # Only sync Sales Quotations (not Purchase)
        if doc.quotation_to != "Customer":
            log_xero_error(f"Only Customer quotations can be synced to Xero: {doc_name}", status="Info")
            frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Skipped", update_modified=False)
            frappe.db.commit()
            return

        # --- Get Linked Xero Contact ID ---
        xero_contact_id = frappe.db.get_value("Customer", doc.party_name, "xero_contact_id")
        if not xero_contact_id:
            # Attempt to sync the contact first
            frappe.logger().info(f"Xero Contact ID not found for Customer {doc.party_name}. Attempting to sync contact first.", "Xero Sync")
            from .xero_contacts import sync_contact_to_xero
            try:
                sync_contact_to_xero(doc.party_name, "Customer")
                xero_contact_id = frappe.db.get_value("Customer", doc.party_name, "xero_contact_id")
                if not xero_contact_id:
                    raise Exception(f"Failed to sync and retrieve Xero Contact ID for Customer {doc.party_name}.")
            except Exception as contact_sync_e:
                raise Exception(f"Prerequisite failed: Could not sync Customer {doc.party_name} to Xero. Error: {contact_sync_e}")

        # --- Map ERPNext Quotation Data to Xero Quote Format ---
        quote_payload = {
            "Contact": {
                "ContactID": xero_contact_id
            },
            "Date": getdate(doc.transaction_date).isoformat(),
            "ExpiryDate": getdate(doc.valid_till).isoformat() if doc.valid_till else None,
            "LineItems": [],
            "QuoteNumber": doc.name,
            "Reference": doc.customer_name,
            "Title": doc.title or f"Quote for {doc.customer_name}",
            "Summary": doc.terms or "Quote generated from ERPNext",
            "Status": "DRAFT",  # Xero quotes start as DRAFT
            "CurrencyCode": doc.currency,
        }

        # If updating, include the Xero Quote ID
        if xero_quote_id:
            quote_payload["QuoteID"] = xero_quote_id

        # --- Map Line Items ---
        for item in doc.items:
            # Get Xero Account Code from mapping in settings
            erpnext_account = item.income_account
            xero_account_code = get_xero_account_code(erpnext_account, settings)
            if not xero_account_code:
                raise Exception(f"Xero Account Code mapping not found in Xero Settings for ERPNext Account: {erpnext_account} (Item: {item.item_code or item.description})")

            line_item = {
                "Description": item.description,
                "Quantity": item.qty,
                "UnitAmount": item.rate,
                "AccountCode": xero_account_code,
                "LineAmount": item.amount,
                # Map Tax Type using mapping in settings
                "TaxType": map_erpnext_tax_to_xero(item.item_tax_template, settings),
            }
            quote_payload["LineItems"].append(line_item)

        # Remove None values from payload
        quote_payload = {k: v for k, v in quote_payload.items() if v is not None}

        # --- Make API Call (PUT for create/update) ---
        response = xero_request("PUT", "Quotes", data={"Quotes": [quote_payload]})

        if response and response.get("Quotes"):
            updated_quote = response["Quotes"][0]
            new_xero_quote_id = updated_quote.get("QuoteID")

            # --- Update ERPNext Document ---
            if new_xero_quote_id:
                frappe.db.set_value(doc_type, doc_name, {
                    "xero_quote_id": new_xero_quote_id,
                    "xero_sync_status": "Synced"
                }, update_modified=False)
                frappe.db.commit()

                log_xero_error(
                    message=f"Successfully synced {doc_type} {doc_name} to Xero.",
                    status="Success",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=new_xero_quote_id,
                    xero_entity_type="Quote",
                    direction="ERPNext to Xero"
                )
            else:
                raise Exception("Xero API response did not contain a QuoteID.")
        else:
            raise Exception("Invalid response received from Xero Quotes API.")

    except Exception as e:
        # Ensure status is updated even if doc object wasn't fetched initially
        if doc_name and doc_type:
            frappe.db.set_value(doc_type, doc_name, {"xero_sync_status": "Error"}, update_modified=False)
            frappe.db.commit()

        log_xero_error(
            message=f"Failed to sync {doc_type} {doc_name} to Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )


# --- Quote Sync (Xero to ERPNext) ---

def sync_quotes_from_xero():
    """
    Fetches quotes from Xero and creates/updates corresponding Quotations in ERPNext.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping quotes inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_quotes"): return

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Quotes page {page}", "Xero Sync")
            response = xero_request("GET", "Quotes", params={"page": page})

            if not response or not response.get("Quotes"):
                break

            quotes = response["Quotes"]
            if not quotes:
                break

            for quote_data in quotes:
                try:
                    process_xero_quote(quote_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Quote ID {quote_data.get('QuoteID')}",
                        xero_entity_id=quote_data.get('QuoteID'),
                        xero_entity_type="Quote",
                        error_details=frappe.get_traceback()
                    )

            # Check if it was the last page
            if len(quotes) < 100:
                break
            page += 1

        log_xero_error(message="Finished syncing quotes from Xero.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_quotes_from_xero",
            error_details=frappe.get_traceback()
        )


def process_xero_quote(xero_quote_data, settings):
    """Creates or updates an ERPNext Quotation from Xero quote data."""
    xero_quote_id = xero_quote_data.get("QuoteID")
    quote_number = xero_quote_data.get("QuoteNumber")

    if not xero_quote_id or not quote_number:
        log_xero_error(message=f"Skipping Xero quote due to missing ID or Number: {xero_quote_data}", status="Info")
        return

    # Check if ERPNext quotation already exists
    erpnext_doc_name = frappe.db.get_value("Quotation", {"xero_quote_id": xero_quote_id}, "name")

    # Get contact information
    xero_contact_id = xero_quote_data.get("Contact", {}).get("ContactID")
    if not xero_contact_id:
        log_xero_error(message=f"Skipping Xero quote {quote_number}: No contact information", status="Info")
        return

    # Find corresponding ERPNext customer
    customer_name = frappe.db.get_value("Customer", {"xero_contact_id": xero_contact_id}, "name")
    if not customer_name:
        log_xero_error(message=f"Skipping Xero quote {quote_number}: Customer not found for Xero Contact {xero_contact_id}", status="Info")
        return

    try:
        # Map Xero Data to ERPNext Fields
        erpnext_data = {
            "quotation_to": "Customer",
            "party_name": customer_name,
            "transaction_date": getdate(xero_quote_data.get("Date")),
            "valid_till": getdate(xero_quote_data.get("ExpiryDate")) if xero_quote_data.get("ExpiryDate") else None,
            "title": xero_quote_data.get("Title"),
            "terms": xero_quote_data.get("Summary"),
            "currency": xero_quote_data.get("CurrencyCode", "USD"),
            "xero_quote_id": xero_quote_id,
            "xero_sync_status": "Synced",
        }

        if erpnext_doc_name:
            # Update existing quotation
            doc = frappe.get_doc("Quotation", erpnext_doc_name)
            doc.update(erpnext_data)
            doc.save(ignore_permissions=True)
            log_message = f"Updated Quotation {erpnext_doc_name} from Xero Quote {xero_quote_id}"
        else:
            # Create new quotation
            doc = frappe.new_doc("Quotation")
            doc.update(erpnext_data)
            
            # Add line items if available
            if xero_quote_data.get("LineItems"):
                for line_item in xero_quote_data["LineItems"]:
                    doc.append("items", {
                        "item_name": line_item.get("Description", "Xero Item"),
                        "description": line_item.get("Description"),
                        "qty": line_item.get("Quantity", 1),
                        "rate": line_item.get("UnitAmount", 0),
                        "amount": line_item.get("LineAmount", 0),
                    })
            
            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created Quotation {erpnext_doc_name} from Xero Quote {xero_quote_id}"

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type="Quotation",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_quote_id,
            xero_entity_type="Quote",
            direction="Xero to ERPNext"
        )

    except Exception as e:
        sync_status = "Error"
        if erpnext_doc_name:
            frappe.db.set_value("Quotation", erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
            frappe.db.commit()

        log_xero_error(
            message=f"Failed to sync Xero Quote {xero_quote_id} to ERPNext Quotation",
            erpnext_doc_type="Quotation",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_quote_id,
            xero_entity_type="Quote",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )