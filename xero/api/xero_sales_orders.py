# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from frappe.utils import getdate

@frappe.whitelist()
def enqueue_sync_sales_order(doc, method):
    """Enqueue background job to sync a Sales Order to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_sales_orders"): # Assume a new setting
        return

    frappe.enqueue(
        "xero.api.xero_sales_orders.sync_sales_order_to_xero",
        queue="short",
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync")


def sync_sales_order_to_xero(doc_name, doc_type):
    """
    Syncs a submitted ERPNext Sales Order to Xero as a Sales Order.
    Ref: https://developer.xero.com/documentation/api/accounting/purchaseorders
    Note: Xero uses the same endpoint for Sales Orders and Purchase Orders.
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
        
        if not settings.get("sync_sales_orders"):
            return
        
        xero_so_id = doc.get("xero_sales_order_id")

        if doc.docstatus != 1:
            return

        # 1. Get Xero Contact ID
        xero_contact_id = frappe.db.get_value("Customer", doc.customer, "xero_contact_id")
        if not xero_contact_id:
            raise Exception(f"Xero Contact ID not found for Customer: {doc.customer}.")

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

        # 3. Construct Sales Order Payload
        so_payload = {
            "Contact": { "ContactID": xero_contact_id },
            "Date": getdate(doc.transaction_date).isoformat(),
            "DeliveryDate": getdate(doc.delivery_date).isoformat() if doc.delivery_date else None,
            "LineItems": line_items,
            "OrderNumber": doc.name,
            "Status": "DRAFT", # Start as Draft in Xero, can be approved there
        }

        if xero_so_id:
            so_payload["PurchaseOrderID"] = xero_so_id

        # 4. Make API Call (Xero uses PurchaseOrders endpoint for Sales Orders)
        response = xero_request("PUT", "PurchaseOrders", data={"PurchaseOrders": [so_payload]})

        # 5. Process response
        if response and response.get("PurchaseOrders"):
            new_xero_id = response["PurchaseOrders"][0].get("PurchaseOrderID")
            frappe.db.set_value(doc_type, doc_name, "xero_sales_order_id", new_xero_id, update_modified=False)
            frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Synced", update_modified=False)
            frappe.db.commit()
            log_xero_error(
                message=f"Successfully synced {doc_type} {doc.name} to Xero.",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc.name,
                xero_entity_id=new_xero_id,
                xero_entity_type="SalesOrder"
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