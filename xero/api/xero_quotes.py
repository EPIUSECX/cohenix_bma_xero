# Copyright (c) 2024, EPI-USE Global Services and contributors
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
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync")


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_quotation_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs a submitted ERPNext Quotation to Xero as a Quote.
    Uses POST for both create and update (POST with ID in payload updates; without ID creates).
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
            "Title": doc.get("title") or f"Quote for {doc.customer_name}",
            "Summary": doc.terms or "Quote generated from ERPNext",
            # NOTE: Do NOT send Status. Xero rejected an explicit "DRAFT" with
            # "Please provide a valid Status Code", and a newly-created quote
            # defaults to DRAFT on Xero's side anyway. Omitting Status also
            # preserves the existing Xero status on update rather than forcing a
            # transition. (Status-transition mapping can be added later if the
            # business wants ERPNext quotation states pushed to Xero.)
            "CurrencyCode": doc.currency,
        }

        # If updating, include the Xero Quote ID
        if xero_quote_id:
            quote_payload["QuoteID"] = xero_quote_id

        # --- Map Line Items ---
        for item in doc.items:
            # QuotationItem doesn't have income_account - try item_defaults child table, then company default
            erpnext_account = item.get("income_account")
            if not erpnext_account and item.item_code:
                # Item's income_account is in item_defaults child table, not a direct field
                company = frappe.db.get_default("company")
                erpnext_account = frappe.db.get_value("Item Default",
                    {"parent": item.item_code, "company": company}, "income_account")
            if not erpnext_account:
                company = company if 'company' in dir() else frappe.db.get_default("company")
                erpnext_account = frappe.get_cached_value("Company", company, "default_income_account")

            # Get Xero Account Code - optional for quotes
            xero_account_code = get_xero_account_code(erpnext_account, settings) if erpnext_account else None

            # Xero requires Description to be non-empty
            description = (item.description or "").strip()
            if description and "<" in description:
                import re
                description = re.sub(r'<[^>]+>', '', description).strip()
            if not description:
                description = item.item_name or item.item_code or "Item"

            line_item = {
                "Description": description,
                "Quantity": item.qty,
                "UnitAmount": item.rate,
                "LineAmount": item.amount,
                # Map Tax Type using mapping in settings
                "TaxType": map_erpnext_tax_to_xero(item.get("item_tax_template"), settings),
            }
            # AccountCode is optional for Xero quotes
            if xero_account_code:
                line_item["AccountCode"] = xero_account_code
            quote_payload["LineItems"].append(line_item)

        # Remove None values from payload
        quote_payload = {k: v for k, v in quote_payload.items() if v is not None}

        # --- Make API Call ---
        # Xero API: POST handles both create (no ID) and update (ID in payload).
        # PUT only creates new records and will not update existing ones.
        response = xero_request("POST", "Quotes", data={"Quotes": [quote_payload]})

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
        from ..utils.logging import is_already_exists_error
        error_traceback = frappe.get_traceback()
        
        if is_already_exists_error(str(e), error_traceback):
            if doc_name and doc_type:
                frappe.db.set_value(doc_type, doc_name, {"xero_sync_status": "Synced"}, update_modified=False)
                frappe.db.commit()
            
            log_xero_error(
                message=f"{doc_type} {doc_name} already exists in Xero. No action needed.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                direction="ERPNext to Xero"
            )
        else:
            from ..utils.logging import format_sync_error_message
            if doc_name and doc_type:
                frappe.db.set_value(doc_type, doc_name, {"xero_sync_status": "Error"}, update_modified=False)
                frappe.db.commit()

            user_message = format_sync_error_message(
                doc_type, doc_name, doc_name, "ERPNext to Xero", e
            )

            log_xero_error(
                message=user_message,
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                error_details=error_traceback,
                direction="ERPNext to Xero"
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

    from ..utils.xero_client import (
        incremental_since,
        commit_watermark,
        start_incremental_run,
    )

    watermark_key = "quotes"
    run_started_at = start_incremental_run()
    if_modified_since = incremental_since(watermark_key)

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Quotes page {page}", "Xero Sync")
            response = xero_request(
                "GET", "Quotes", params={"page": page}, modified_since=if_modified_since
            )

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

        # Only advance the watermark after a fully successful sweep — if an
        # exception aborted the loop, the next run re-fetches from the old
        # watermark so nothing is missed.
        commit_watermark(watermark_key, run_started_at)
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

    # Inbound is create-once: if already mirrored, skip (never overwrite local
    # edits or fail on a submitted document).
    if erpnext_doc_name:
        log_xero_error(
            message=f"Xero Quote {xero_quote_id} already mirrored as {erpnext_doc_name}; skipping (create-once).",
            status="Info", category="Duplicate Entity",
            erpnext_doc_type="Quotation", erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_quote_id, xero_entity_type="Quote", direction="Xero to ERPNext",
        )
        return

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
        from .xero_invoices import parse_xero_date
        from .xero_items import get_or_create_item_for_xero_line

        company = frappe.defaults.get_global_default("company") or frappe.get_all("Company", limit=1, pluck="name")[0]

        # ME-5(a): default to the COMPANY base currency, not a hardcoded "USD",
        # when Xero does not supply a CurrencyCode.
        company_currency = frappe.get_cached_value("Company", company, "default_currency")
        currency = xero_quote_data.get("CurrencyCode") or company_currency

        transaction_date = parse_xero_date(xero_quote_data.get("Date"))

        # ME-5(b): resolve the conversion rate from ERPNext when Xero omits it
        # (or sends a falsy value) and the document currency differs from the
        # company base currency. Only fall back to 1.0 when currencies match.
        conversion_rate = frappe.utils.flt(xero_quote_data.get("CurrencyRate"))
        if not conversion_rate:
            if currency and currency != company_currency:
                from erpnext.setup.utils import get_exchange_rate
                conversion_rate = get_exchange_rate(
                    currency, company_currency, transaction_date
                )
            else:
                conversion_rate = 1.0

        # Map Xero Data to ERPNext Fields. Xero serialises dates as
        # /Date(ms+offset)/ — use the shared parser, NOT getdate().
        erpnext_data = {
            "quotation_to": "Customer",
            "party_name": customer_name,
            "company": company,
            "transaction_date": transaction_date,
            "valid_till": parse_xero_date(xero_quote_data.get("ExpiryDate")),
            "title": xero_quote_data.get("Title"),
            "terms": xero_quote_data.get("Summary"),
            "currency": currency,
            "conversion_rate": conversion_rate,
            "xero_quote_id": xero_quote_id,
            "xero_sync_status": "Synced",
        }

        # Create the new Quotation as a Draft (existing docs were skipped above;
        # inbound is create-once).
        doc = frappe.new_doc("Quotation")
        doc.update(erpnext_data)

        # Add line items. Quotation rows REQUIRE item_code, so resolve/create an
        # item for each Xero line.
        for line_item in (xero_quote_data.get("LineItems") or []):
            item_code = get_or_create_item_for_xero_line(
                line_item.get("ItemCode"), line_item.get("Description"), settings, is_sales=True
            )
            doc.append("items", {
                "item_code": item_code,
                "item_name": (line_item.get("Description") or item_code)[:140],
                "description": line_item.get("Description") or "Item from Xero",
                "qty": frappe.utils.flt(line_item.get("Quantity", 1)) or 1,
                "rate": frappe.utils.flt(line_item.get("UnitAmount", 0)),
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
        from ..utils.logging import is_already_exists_error
        error_traceback = frappe.get_traceback()
        
        if is_already_exists_error(str(e), error_traceback):
            if erpnext_doc_name:
                frappe.db.set_value("Quotation", erpnext_doc_name, "xero_sync_status", "Synced", update_modified=False)
                frappe.db.commit()
            
            log_xero_error(
                message=f"Xero Quote {xero_quote_id} already exists in ERPNext as {erpnext_doc_name or 'existing document'}. Skipping update.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type="Quotation",
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_quote_id,
                xero_entity_type="Quote",
                direction="Xero to ERPNext"
            )
        else:
            from ..utils.logging import format_sync_error_message
            sync_status = "Error"
            if erpnext_doc_name:
                frappe.db.set_value("Quotation", erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
                frappe.db.commit()

            user_message = format_sync_error_message(
                "Xero Quote", xero_quote_id, xero_quote_id, "Xero to ERPNext", e
            )

            log_xero_error(
                message=user_message,
                erpnext_doc_type="Quotation",
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_quote_id,
                xero_entity_type="Quote",
                direction="Xero to ERPNext",
                error_details=error_traceback
            )