# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from .xero_invoices import get_xero_account_code # Reuse account mapping

# --- Helper Functions ---

def clean_item_payload(payload):
    """
    Recursively removes None values, empty strings, and empty dictionaries from payload.
    This ensures only valid data is sent to Xero API.
    """
    cleaned = {}
    for k, v in payload.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, dict):
            cleaned_dict = clean_item_payload(v)
            if cleaned_dict:  # Only add if dict has content
                cleaned[k] = cleaned_dict
        else:
            cleaned[k] = v
    return cleaned

# --- Item Sync (ERPNext to Xero) ---

@frappe.whitelist()
def enqueue_sync_item(item_code):
    """Enqueue background job to sync Item to Xero."""
    settings = get_xero_settings()
    if not settings.sync_items:
        frappe.msgprint(_("Xero Item Sync is disabled in settings."))
        return

    frappe.enqueue(
        "xero.api.xero_items.sync_item_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        item_code=item_code
    )
    frappe.msgprint(_("Item sync to Xero queued for {0}.").format(item_code))


def sync_item_to_xero(item_code, **kwargs):
    """
    Syncs an ERPNext Item to Xero Items (Products & Services).
    Uses PUT for create/update.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        log_xero_error(
            message=f"Item sync skipped: Xero sync is disabled",
            status="Info",
            erpnext_doc_type="Item",
            erpnext_doc_name=item_code
        )
        return # Master switch disabled
    if not settings.sync_items:
        log_xero_error(
            message=f"Item sync skipped: Item sync is disabled in settings",
            status="Info",
            erpnext_doc_type="Item",
            erpnext_doc_name=item_code
        )
        return # Item sync specifically disabled

    try:
        doc = frappe.get_doc("Item", item_code)
        xero_item_id = doc.get("xero_item_id")

        # --- Validate Required Fields ---
        if not doc.item_code or not str(doc.item_code).strip():
            raise ValueError(f"Item Code is required for Item {item_code}")
        if not doc.item_name or not str(doc.item_name).strip():
            raise ValueError(f"Item Name is required for Item {item_code}")

        # --- Map ERPNext Item Data to Xero Item Format ---
        # Ref: https://developer.xero.com/documentation/api/accounting/items
        item_payload = {
            "Code": doc.item_code, # Use ERPNext item_code as Xero Code
            "Name": doc.item_name,
            "Description": doc.get("description"), # Sales Description
            "PurchaseDescription": doc.get("purchase_description"), # Purchase Description
        }

        # --- Handle Sales & Purchase Details (Price, Account, Tax) ---
        # Xero requires specifying if an item is sold, purchased, or both.
        # We'll assume both if relevant fields exist in ERPNext Item.

        # Sales Details - only add if account mapping exists
        if doc.is_sales_item and doc.standard_selling_rate:
            sales_account = doc.income_account # Get default income account
            sales_account_code = get_xero_account_code(sales_account, settings) if sales_account else None
            if sales_account_code:
                item_payload["IsSold"] = True
                item_payload["SalesDetails"] = {
                    "UnitPrice": doc.standard_selling_rate,
                    "AccountCode": sales_account_code,
                    # TODO: Map default sales tax template?
                    # "TaxType": map_erpnext_tax_to_xero(doc.sales_tax_template, settings)
                }
            else:
                log_xero_error(
                    message=f"Skipping sales details for Item {item_code}: Xero Account Code mapping not found for Income Account {sales_account}.",
                    status="Warning",
                    erpnext_doc_type="Item",
                    erpnext_doc_name=item_code
                )

        # Purchase Details - only add if account mapping exists
        if doc.is_purchase_item and doc.standard_buying_rate:
            purchase_account = doc.expense_account # Get default expense account
            purchase_account_code = get_xero_account_code(purchase_account, settings) if purchase_account else None
            if purchase_account_code:
                item_payload["IsPurchased"] = True
                item_payload["PurchaseDetails"] = {
                    "UnitPrice": doc.standard_buying_rate,
                    "AccountCode": purchase_account_code,
                     # TODO: Map default purchase tax template?
                    # "TaxType": map_erpnext_tax_to_xero(doc.purchase_tax_template, settings) # Need different mapping for purchase tax?
                }
            else:
                log_xero_error(
                    message=f"Skipping purchase details for Item {item_code}: Xero Account Code mapping not found for Expense Account {purchase_account}.",
                    status="Warning",
                    erpnext_doc_type="Item",
                    erpnext_doc_name=item_code
                )

        # Inventory Asset Account (for tracked items)
        if doc.is_stock_item:
            company = doc.get("company")
            inventory_account = doc.stock_account
            if not inventory_account and company:
                inventory_account = frappe.get_cached_value('Company', company, 'stock_account')
            inventory_account_code = get_xero_account_code(inventory_account, settings) if inventory_account else None
            if inventory_account_code:
                item_payload["InventoryAssetAccountCode"] = inventory_account_code
                item_payload["IsTrackedAsInventory"] = True # Mark as tracked
            else:
                log_xero_error(
                    message=f"Cannot track Item {item_code} in Xero: Xero Account Code mapping not found for Inventory Account {inventory_account}.",
                    status="Warning",
                    erpnext_doc_type="Item",
                    erpnext_doc_name=item_code
                )
                item_payload["IsTrackedAsInventory"] = False


        # If updating, include the Xero ItemID
        if xero_item_id:
            item_payload["ItemID"] = xero_item_id

        # --- Clean Payload (Remove None/Empty Values) ---
        item_payload = clean_item_payload(item_payload)

        # --- Make API Call (PUT for create/update) ---
        response = xero_request("PUT", "Items", data={"Items": [item_payload]})

        if response and response.get("Items"):
            updated_item = response["Items"][0]
            new_xero_item_id = updated_item.get("ItemID")

            # --- Update ERPNext Document ---
            if new_xero_item_id:
                frappe.db.set_value("Item", item_code, {
                    "xero_item_id": new_xero_item_id,
                    "xero_sync_status": "Synced"
                }, update_modified=False)
                frappe.db.commit()

                log_xero_error(
                    message=f"Successfully synced Item {item_code} to Xero.",
                    status="Success",
                    erpnext_doc_type="Item",
                    erpnext_doc_name=item_code,
                    xero_entity_id=new_xero_item_id,
                    xero_entity_type="Item",
                    direction="ERPNext to Xero"
                )
            else:
                raise Exception("Xero API response did not contain an ItemID.")
        else:
            raise Exception("Invalid response received from Xero Items API.")

    except Exception as e:
        # Update sync status on error
        if item_code:
             frappe.db.set_value("Item", item_code, {"xero_sync_status": "Error"}, update_modified=False)
             frappe.db.commit()
        log_xero_error(
            message=f"Failed to sync Item {item_code} to Xero.",
            erpnext_doc_type="Item",
            erpnext_doc_name=item_code,
            error_details=frappe.get_traceback()
        )
        # raise e

# --- Item Sync (Xero to ERPNext) ---

def sync_items_from_xero():
    """
    Fetches items from Xero and creates/updates corresponding Items in ERPNext.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    if not settings.sync_items: return

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Items page {page}", "Xero Sync")
            # Use If-Modified-Since header for efficiency? Requires storing last sync time.
            response = xero_request("GET", "Items", params={"page": page})

            if not response or not response.get("Items"):
                break

            items = response["Items"]
            if not items:
                break

            for item_data in items:
                try:
                    process_xero_item(item_data, settings)
                except Exception as e:
                     log_xero_error(
                        message=f"Failed to process Xero Item ID {item_data.get('ItemID')}",
                        xero_entity_id=item_data.get('ItemID'),
                        xero_entity_type="Item",
                        error_details=frappe.get_traceback()
                    )

            if len(items) < 100: # Default page size
                break
            page += 1

        log_xero_error(message="Finished syncing items from Xero.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_items_from_xero",
            error_details=frappe.get_traceback()
        )

def process_xero_item(xero_item_data, settings):
    """Creates or updates an ERPNext Item from Xero item data."""
    xero_item_id = xero_item_data.get("ItemID")
    item_code = xero_item_data.get("Code") # Use Xero Code as ERPNext Item Code

    if not xero_item_id or not item_code:
        log_xero_error(message=f"Skipping Xero item due to missing ID or Code: {xero_item_data}", status="Info")
        return

    # --- Check if ERPNext Item Exists ---
    erpnext_doc_name = frappe.db.get_value("Item", {"item_code": item_code}, "name")
    if not erpnext_doc_name:
         # Optionally check by xero_item_id if item_code might differ
         erpnext_doc_name = frappe.db.get_value("Item", {"xero_item_id": xero_item_id}, "name")

    # --- Map Xero Data to ERPNext Fields ---
    erpnext_data = {
        "item_code": item_code,
        "item_name": xero_item_data.get("Name", item_code), # Default name to code if missing
        "item_group": frappe.db.get_default("item_group") or "All Item Groups", # Default group
        "stock_uom": frappe.db.get_default("stock_uom") or "Nos", # Default UOM
        "description": xero_item_data.get("Description"), # Sales description
        "purchase_description": xero_item_data.get("PurchaseDescription"),
        "xero_item_id": xero_item_id,
        "xero_sync_status": "Synced",
        "is_stock_item": 1 if xero_item_data.get("IsTrackedAsInventory") else 0,
        "is_sales_item": 1 if xero_item_data.get("IsSold") else 0,
        "is_purchase_item": 1 if xero_item_data.get("IsPurchased") else 0,
    }

    # Map Sales/Purchase details if they exist
    if xero_item_data.get("SalesDetails"):
        erpnext_data["standard_selling_rate"] = xero_item_data["SalesDetails"].get("UnitPrice")
        # Map Account Code back to ERPNext Account? Requires reverse lookup on mapping table.
        # erpnext_data["income_account"] = get_erpnext_account_from_xero_code(xero_item_data["SalesDetails"].get("AccountCode"), settings)
        # Map TaxType back to ERPNext Tax Template? Requires reverse lookup.
        # erpnext_data["sales_tax_template"] = get_erpnext_tax_template_from_xero_type(xero_item_data["SalesDetails"].get("TaxType"), settings)

    if xero_item_data.get("PurchaseDetails"):
        erpnext_data["standard_buying_rate"] = xero_item_data["PurchaseDetails"].get("UnitPrice")
        # erpnext_data["expense_account"] = get_erpnext_account_from_xero_code(xero_item_data["PurchaseDetails"].get("AccountCode"), settings)
        # erpnext_data["purchase_tax_template"] = get_erpnext_tax_template_from_xero_type(xero_item_data["PurchaseDetails"].get("TaxType"), settings)

    if xero_item_data.get("IsTrackedAsInventory"):
        # erpnext_data["stock_account"] = get_erpnext_account_from_xero_code(xero_item_data.get("InventoryAssetAccountCode"), settings)
        pass # Reverse mapping needed

    # --- Create or Update ERPNext Item ---
    try:
        if erpnext_doc_name:
            doc = frappe.get_doc("Item", erpnext_doc_name)
            # Be careful about overwriting user-maintained fields in ERPNext
            # Only update specific fields?
            doc.update({
                "item_name": erpnext_data["item_name"],
                "description": erpnext_data["description"],
                "purchase_description": erpnext_data["purchase_description"],
                "standard_selling_rate": erpnext_data.get("standard_selling_rate"),
                "standard_buying_rate": erpnext_data.get("standard_buying_rate"),
                "xero_item_id": xero_item_id, # Ensure ID is set
                "xero_sync_status": "Synced",
                # Avoid changing is_stock_item, is_sales_item etc. based on Xero? Or allow it?
            })
            doc.save(ignore_permissions=True)
            log_message = f"Updated Item {erpnext_doc_name} from Xero Item {xero_item_id}"
        else:
            doc = frappe.new_doc("Item")
            doc.update(erpnext_data)
            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created Item {erpnext_doc_name} from Xero Item {xero_item_id}"

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type="Item",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_item_id,
            xero_entity_type="Item",
            direction="Xero to ERPNext"
        )

    except Exception as e:
        sync_status = "Error"
        if erpnext_doc_name:
             frappe.db.set_value("Item", erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
             frappe.db.commit()

        log_xero_error(
            message=f"Failed to sync Xero Item {xero_item_id} to ERPNext Item",
            erpnext_doc_type="Item",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_item_id,
            xero_entity_type="Item",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )

# TODO: Implement reverse mapping helpers (get_erpnext_account_from_xero_code, etc.) if needed.
# TODO: Add Item sync to scheduled tasks (sync_all_enabled in tasks.py).
# TODO: Consider how to handle conflicts (e.g., if item exists in both but isn't linked).
