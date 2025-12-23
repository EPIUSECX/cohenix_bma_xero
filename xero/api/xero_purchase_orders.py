# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
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
        xero_po_id = doc.get("xero_purchase_order_id")

        if doc.docstatus != 1:
            return

        # 1. Get Xero Contact ID
        xero_contact_id = frappe.db.get_value("Supplier", doc.supplier, "xero_contact_id")
        if not xero_contact_id:
            raise Exception(f"Xero Contact ID not found for Supplier: {doc.supplier}.")

        # 2. Map Line Items
        line_items = []
        for item in doc.items:
            line_items.append({
                "Description": item.description,
                "Quantity": item.qty,
                "UnitAmount": item.rate,
                "ItemCode": item.item_code,
                "LineAmount": item.amount,
            })

        # 3. Construct Purchase Order Payload
        po_payload = {
            "Contact": { "ContactID": xero_contact_id },
            "Date": getdate(doc.transaction_date).isoformat(),
            "DeliveryDate": getdate(doc.schedule_date).isoformat() if doc.schedule_date else None,
            "LineItems": line_items,
            "PurchaseOrderNumber": doc.name,
            "Status": "AUTHORISED",
        }

        if xero_po_id:
            po_payload["PurchaseOrderID"] = xero_po_id

        # 4. Make API Call
        response = xero_request("PUT", "PurchaseOrders", data={"PurchaseOrders": [po_payload]})

        # 5. Process response
        if response and response.get("PurchaseOrders"):
            new_xero_id = response["PurchaseOrders"][0].get("PurchaseOrderID")
            frappe.db.set_value(doc_type, doc_name, "xero_purchase_order_id", new_xero_id, update_modified=False)
            frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Synced", update_modified=False)
            frappe.db.commit()
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
        frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Error", update_modified=False)
        frappe.db.commit()
        log_xero_error(
            message=f"Failed to sync {doc_type} {doc_name} to Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )