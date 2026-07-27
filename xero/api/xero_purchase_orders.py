# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
from ..utils.transactions import commit_checkpoint, commit_error_state, commit_external_outcome
from frappe import _
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from .xero_line_builder import build_xero_lines
from frappe.utils import getdate

@frappe.whitelist()
def enqueue_sync_purchase_order(doc, method):
    """Enqueue background job to sync a Purchase Order to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_purchase_orders"): # Assume a new setting
        return

    frappe.enqueue(
        "xero.api.xero_purchase_orders.sync_purchase_order_to_xero",
        queue="short",
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync")


def sync_purchase_order_to_xero(doc_name, doc_type):
    """
    Syncs a submitted ERPNext Purchase Order to Xero as a Purchase Order.
    Ref: https://developer.xero.com/documentation/api/accounting/purchaseorders
    """
    try:
        doc = frappe.get_doc(doc_type, doc_name)
        settings = get_xero_settings()
        
        if not settings.enable_xero_sync:
            return
        
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
        
        if not settings.get("sync_purchase_orders"):
            return
        
        xero_po_id = doc.get("xero_purchase_order_id")

        if doc.docstatus != 1:
            return

        # 1. Get Xero Contact ID
        xero_contact_id = frappe.db.get_value("Supplier", doc.supplier, "xero_contact_id")
        if not xero_contact_id:
            raise Exception(f"Xero Contact ID not found for Supplier: {doc.supplier}.")

        # 2. Map Line Items via the shared builder: sanitised descriptions,
        # mapped AccountCodes where available, per-line TaxType/TaxAmount and
        # LineAmountTypes. Sending no TaxType made Xero fall back to each
        # account's DEFAULT tax rate, inflating every PO by that rate (H2).
        # AccountCode stays optional on PO lines (require_account=False);
        # rounding is off because nothing allocates payments against a PO.
        built = build_xero_lines(
            doc, doc_type, settings, require_account=False, include_rounding=False
        )

        # 3. Construct Purchase Order Payload
        po_payload = {
            "Contact": { "ContactID": xero_contact_id },
            "Date": getdate(doc.transaction_date).isoformat(),
            "LineItems": built.line_items,
            "LineAmountTypes": built.line_amount_types,
            "PurchaseOrderNumber": doc.name,
            "CurrencyCode": doc.currency,
            "Status": "AUTHORISED",
        }
        if doc.schedule_date:
            po_payload["DeliveryDate"] = getdate(doc.schedule_date).isoformat()

        if xero_po_id:
            po_payload["PurchaseOrderID"] = xero_po_id

        # 4. Make API Call
        # Xero API: POST handles both create (no ID) and update (ID in payload).
        # PUT only creates new records and will not update existing ones.
        # Key the create so a retry after a lost response cannot duplicate the PO.
        response = xero_request(
            "POST",
            "PurchaseOrders",
            data={"PurchaseOrders": [po_payload]},
            idempotency_key=None if xero_po_id else f"{doc_type}:{doc_name}:create-purchase-order",
        )

        # 5. Process response
        if response and response.get("PurchaseOrders"):
            new_xero_id = response["PurchaseOrders"][0].get("PurchaseOrderID")
            frappe.db.set_value(doc_type, doc_name, "xero_purchase_order_id", new_xero_id, update_modified=False)
            frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Synced", update_modified=False)
            commit_external_outcome()
            log_xero_error(
                message=f"Successfully synced {doc_type} {doc.name} to Xero.",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc.name,
                xero_entity_id=new_xero_id,
                xero_entity_type="PurchaseOrder"
            )
        else:
            raise Exception("Invalid response from Xero PurchaseOrders API.")

    except Exception as e:
        from ..utils.logging import is_already_exists_error
        error_traceback = frappe.get_traceback()
        
        if is_already_exists_error(str(e), error_traceback):
            frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Synced", update_modified=False)
            commit_error_state()
            log_xero_error(
                message=f"{doc_type} {doc_name} already exists in Xero. No action needed.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                direction="ERPNext to Xero"
            )
        else:
            from ..utils.logging import build_error_details, format_sync_error_message
            # Permanent Xero rejections go terminal ("Failed") so the hourly
            # retry task stops re-queuing an unsatisfiable document.
            sync_status = "Failed" if getattr(e, "is_permanent", False) else "Error"
            frappe.db.set_value(doc_type, doc_name, "xero_sync_status", sync_status, update_modified=False)
            commit_error_state()
            user_message = format_sync_error_message(
                doc_type, doc_name, doc_name, "ERPNext to Xero", e
            )
            log_xero_error(
                message=user_message,
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                error_details=build_error_details(e, error_traceback),
                direction="ERPNext to Xero"
            )


# --- Purchase Order Sync (Xero to ERPNext) ---

def sync_purchase_orders_from_xero(modified_since=None):
    """
    Fetches purchase orders from Xero and creates/updates corresponding
    Purchase Orders in ERPNext.
    
    Args:
        modified_since: ISO date string to fetch only recent orders
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping purchase orders inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_purchase_orders"): return

    # Incremental sync: fetch only purchase orders changed since the last
    # successful run. An explicit modified_since argument overrides the stored
    # watermark. Xero ignores a ModifiedSince query param — the value must go in
    # the If-Modified-Since header via modified_since= on the GET.
    from ..utils.xero_client import (
        incremental_since,
        commit_watermark,
        start_incremental_run,
    )

    watermark_key = "purchase_orders"
    run_started_at = start_incremental_run()
    if_modified_since = modified_since or incremental_since(watermark_key)

    try:
        page = 1
        params = {"page": page}

        while True:
            frappe.logger().info(f"Fetching Xero Purchase Orders page {page}", "Xero Sync")
            response = xero_request(
                "GET", "PurchaseOrders", params=params, modified_since=if_modified_since
            )
            
            if not response or not response.get("PurchaseOrders"):
                break
            
            orders = response["PurchaseOrders"]
            if not orders:
                break
            
            # Filter for purchase orders only (has supplier contact)
            for order_data in orders:
                try:
                    # Check if this is a purchase order (has supplier contact)
                    contact_id = order_data.get("Contact", {}).get("ContactID")
                    if contact_id:
                        # Check if contact is a supplier
                        is_supplier = frappe.db.exists("Supplier", {"xero_contact_id": contact_id})
                        if is_supplier:
                            process_xero_purchase_order(order_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Purchase Order ID {order_data.get('PurchaseOrderID')}",
                        xero_entity_id=order_data.get('PurchaseOrderID'),
                        xero_entity_type="PurchaseOrder",
                        error_details=frappe.get_traceback()
                    )
            
            if len(orders) < 100:
                break
            page += 1
            params["page"] = page

        # Only advance the watermark after a fully successful sweep — if an
        # exception aborted the loop, the next run re-fetches from the old
        # watermark so nothing is missed.
        commit_watermark(watermark_key, run_started_at)
        log_xero_error(message="Finished syncing purchase orders from Xero.", status="Info")
    
    except Exception as e:
        log_xero_error(
            message="Error during sync_purchase_orders_from_xero",
            error_details=frappe.get_traceback()
        )


def process_xero_purchase_order(xero_order_data, settings):
    """Creates or updates an ERPNext Purchase Order from Xero order data."""
    from .xero_invoices import get_erpnext_tax_from_xero_type, parse_xero_date
    from .xero_items import get_or_create_item_for_xero_line
    from .xero_line_builder import apply_inbound_taxes, inbound_line_rate
    
    xero_order_id = xero_order_data.get("PurchaseOrderID")
    order_number = xero_order_data.get("PurchaseOrderNumber")
    
    if not xero_order_id:
        log_xero_error(message=f"Skipping Xero order due to missing ID", status="Info")
        return
    
    # Check if order already exists
    erpnext_doc_name = frappe.db.get_value("Purchase Order", {"xero_purchase_order_id": xero_order_id}, "name")

    # Inbound is create-once: if already mirrored, skip (never overwrite local
    # edits or fail on a submitted document).
    if erpnext_doc_name:
        log_xero_error(
            message=f"Xero Purchase Order {xero_order_id} already mirrored as {erpnext_doc_name}; skipping (create-once).",
            status="Info", category="Duplicate Entity",
            erpnext_doc_type="Purchase Order", erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_order_id, xero_entity_type="PurchaseOrder", direction="Xero to ERPNext",
        )
        return

    # Get contact information
    xero_contact_id = xero_order_data.get("Contact", {}).get("ContactID")
    if not xero_contact_id:
        log_xero_error(message=f"Skipping Xero order {order_number}: No contact information", status="Info")
        return
    
    # Find corresponding ERPNext supplier
    supplier_name = frappe.db.get_value("Supplier", {"xero_contact_id": xero_contact_id}, "name")
    
    if not supplier_name:
        log_xero_error(
            message=f"Skipping Xero order {order_number}: Supplier not found for Xero Contact {xero_contact_id}",
            status="Info",
            xero_entity_id=xero_order_id,
            xero_entity_type="PurchaseOrder"
        )
        return
    
    try:
        # Get company
        company = frappe.defaults.get_global_default("company")
        if not company:
            company = frappe.get_all("Company", limit=1, pluck="name")[0]

        # ME-5(a): default to the COMPANY base currency, not a hardcoded "USD",
        # when Xero does not supply a CurrencyCode.
        company_currency = frappe.get_cached_value("Company", company, "default_currency")
        currency = xero_order_data.get("CurrencyCode") or company_currency

        transaction_date = parse_xero_date(xero_order_data.get("Date"))

        # ME-5(b): resolve the conversion rate from ERPNext when Xero omits it
        # (or sends a falsy value) and the document currency differs from the
        # company base currency. Only fall back to 1.0 when currencies match.
        conversion_rate = frappe.utils.flt(xero_order_data.get("CurrencyRate"))
        if not conversion_rate:
            if currency and currency != company_currency:
                from erpnext.setup.utils import get_exchange_rate
                conversion_rate = get_exchange_rate(
                    currency, company_currency, transaction_date
                )
            else:
                conversion_rate = 1.0

        # Map header fields
        erpnext_data = {
            "xero_purchase_order_id": xero_order_id,
            "xero_sync_status": "Synced",
            "supplier": supplier_name,
            "supplier_name": xero_order_data.get("Contact", {}).get("Name"),
            "company": company,
            "transaction_date": transaction_date,
            # PO (and its rows) require a Required-By date; Xero POs often have no
            # DeliveryDate, so fall back to the order date.
            "schedule_date": parse_xero_date(xero_order_data.get("DeliveryDate")) or transaction_date,
            "currency": currency,
            "conversion_rate": conversion_rate,
        }
        
        # Store Xero order number in remarks
        if order_number:
            erpnext_data["remarks"] = f"Xero Order: {order_number}"
        
        # Create the new Purchase Order as a Draft (existing docs were skipped
        # above; inbound is create-once).
        doc = frappe.new_doc("Purchase Order")
        doc.update(erpnext_data)

        # Add line items. Purchase Order rows REQUIRE item_code and a schedule
        # (Required By) date, so always resolve/create an item and carry the
        # header schedule date onto each row.
        po_schedule_date = erpnext_data.get("schedule_date") or erpnext_data.get("transaction_date")
        # Rates are always stored tax-exclusive; Xero's tax is reconstructed as
        # a taxes row below so the ERPNext grand total matches Xero's Total.
        inclusive = xero_order_data.get("LineAmountTypes") == "Inclusive"
        line_items = xero_order_data.get("LineItems", [])
        for line in line_items:
            item_code = get_or_create_item_for_xero_line(
                line.get("ItemCode"), line.get("Description"), settings, is_purchase=True
            )
            row = {
                "item_code": item_code,
                "item_name": (line.get("Description") or item_code)[:140],
                "description": line.get("Description") or "Item from Xero",
                # PO qty must be > 0
                "qty": frappe.utils.flt(line.get("Quantity", 1)) or 1,
                "rate": inbound_line_rate(line, inclusive),
                "schedule_date": po_schedule_date,
            }
            tax_template = get_erpnext_tax_from_xero_type(line.get("TaxType"), settings)
            if tax_template:
                row["item_tax_template"] = tax_template
            doc.append("items", row)

        if not doc.items:
            log_xero_error(
                message=f"Skipping Xero order {order_number}: No line items",
                status="Warning",
                xero_entity_id=xero_order_id,
                xero_entity_type="PurchaseOrder"
            )
            return

        apply_inbound_taxes(doc, xero_order_data, "Purchase Order")

        doc.insert(ignore_permissions=True)
        erpnext_doc_name = doc.name
        log_message = f"Created Purchase Order {erpnext_doc_name} from Xero Order {xero_order_id} ({order_number})"

        # Flag a total that does not reconcile with Xero (missing tax mapping,
        # skipped lines). POs import as drafts so nothing posts to the GL, but
        # a silent price divergence must still be operator-visible.
        xero_total = frappe.utils.flt(xero_order_data.get("Total", 0))
        erpnext_total = frappe.utils.flt(doc.get("grand_total"))
        if xero_total and abs(erpnext_total - xero_total) > 0.02:
            log_xero_error(
                message=(
                    f"Total mismatch on inbound Purchase Order {erpnext_doc_name} "
                    f"(Xero PO {order_number}): ERPNext grand_total {erpnext_total} "
                    f"vs Xero Total {xero_total}. Check tax mappings for the "
                    "order's TaxTypes."
                ),
                status="Error",
                xero_entity_id=xero_order_id,
                xero_entity_type="PurchaseOrder",
                erpnext_doc_type="Purchase Order",
                erpnext_doc_name=erpnext_doc_name,
                direction="Xero to ERPNext",
                category="Validation Errors",
            )

        commit_checkpoint()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type="Purchase Order",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_order_id,
            xero_entity_type="PurchaseOrder",
            direction="Xero to ERPNext"
        )
    
    except Exception as e:
        from ..utils.logging import is_already_exists_error
        error_traceback = frappe.get_traceback()
        
        if is_already_exists_error(str(e), error_traceback):
            if erpnext_doc_name:
                frappe.db.set_value("Purchase Order", erpnext_doc_name, "xero_sync_status", "Synced", update_modified=False)
                commit_error_state()
            
            log_xero_error(
                message=f"Xero Purchase Order {xero_order_id} ({order_number}) already exists in ERPNext. Skipping update.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type="Purchase Order",
                erpnext_doc_name=erpnext_doc_name if 'erpnext_doc_name' in locals() else None,
                xero_entity_id=xero_order_id,
                xero_entity_type="PurchaseOrder",
                direction="Xero to ERPNext"
            )
        else:
            from ..utils.logging import format_sync_error_message
            sync_status = "Error"
            if erpnext_doc_name:
                frappe.db.set_value("Purchase Order", erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
                commit_error_state()
            
            user_message = format_sync_error_message(
                "Xero Purchase Order", xero_order_id, order_number, "Xero to ERPNext", e
            )
            
            log_xero_error(
                message=user_message,
                erpnext_doc_type="Purchase Order",
                erpnext_doc_name=erpnext_doc_name if 'erpnext_doc_name' in locals() else None,
                xero_entity_id=xero_order_id,
                xero_entity_type="PurchaseOrder",
                direction="Xero to ERPNext",
                error_details=error_traceback
            )