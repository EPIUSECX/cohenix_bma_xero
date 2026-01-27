# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error

@frappe.whitelist()
def enqueue_sync_stock_ledger(doc, method):
    """Enqueue background job to sync a stock level change to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_inventory_levels"): # Assume a new setting
        return

    # Only sync for transactions that affect stock levels
    if doc.voucher_type in ["Delivery Note", "Purchase Receipt", "Stock Reconciliation", "Stock Entry"]:
        frappe.enqueue(
            "xero.api.xero_stock.sync_stock_ledger_to_xero",
            queue="short",
            sle_name=doc.name
        )
        frappe.logger().info(f"Queued stock sync for SLE {doc.name} to Xero.", "Xero Sync")


def sync_stock_ledger_to_xero(sle_name):
    """
    Updates the inventory quantity of an item in Xero based on a Stock Ledger Entry.
    """
    try:
        settings = get_xero_settings()
        
        if not settings.enable_xero_sync:
            return
        
        # Check directional toggle for outbound sync
        if not settings.enable_sync_to_xero:
            log_xero_error(
                message=f"Sync to Xero is disabled. Skipping Stock Ledger Entry {sle_name} outbound sync.",
                status="Info",
                erpnext_doc_type="Stock Ledger Entry",
                erpnext_doc_name=sle_name,
                category="System Monitoring"
            )
            return
        
        if not settings.get("sync_inventory_levels"):
            return
        
        sle = frappe.get_doc("Stock Ledger Entry", sle_name)
        
        # 1. Get the Xero Item ID from the ERPNext Item
        xero_item_id = frappe.db.get_value("Item", sle.item_code, "xero_item_id")
        if not xero_item_id:
            # If the item isn't tracked in Xero, we can't update its inventory
            return

        # 2. Get the current quantity on hand for the item in ERPNext
        # This provides the absolute quantity to set in Xero
        # Note: This assumes a single warehouse is synced with Xero. Multi-warehouse requires more complex logic.
        current_qty = frappe.db.get_value("Bin", {"item_code": sle.item_code}, "actual_qty")
        if current_qty is None:
            current_qty = 0

        # 3. Construct the Item payload for update
        # We only need to send the fields we want to change.
        # Xero's API for inventory is part of the Items endpoint.
        item_payload = {
            "ItemID": xero_item_id,
            "QuantityOnHand": current_qty,
        }

        # 4. Make API Call
        response = xero_request("POST", "Items", data={"Items": [item_payload]})

        # 5. Process response
        if response and response.get("Items"):
            log_xero_error(
                message=f"Successfully updated inventory for Item {sle.item_code} to {current_qty} in Xero.",
                status="Success",
                erpnext_doc_type="Stock Ledger Entry",
                erpnext_doc_name=sle.name,
                xero_entity_id=xero_item_id,
                xero_entity_type="Item"
            )
        else:
            raise Exception("Invalid response from Xero Items API when updating inventory.")

    except Exception as e:
        log_xero_error(
            message=f"Failed to sync stock level for SLE {sle_name}.",
            erpnext_doc_type="Stock Ledger Entry",
            erpnext_doc_name=sle_name,
            error_details=frappe.get_traceback()
        )