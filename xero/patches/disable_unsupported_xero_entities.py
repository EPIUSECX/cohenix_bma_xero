# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe


def execute():
    """
    Migration patch to remove unsupported Xero entity references.
    
    Removes:
    - Custom fields for Sales Order, Delivery Note, Purchase Receipt, 
      Cost Center (tracking fields), Project (tracking fields)
    - Xero Project DocType records
    
    This patch runs after the feature flag fields have been removed from
    Xero Settings JSON and the API modules have been deleted.
    """
    print("Starting removal of unsupported Xero entity references...")
    
    # 1. Remove custom fields for unsupported entities
    custom_fields_to_remove = {
        "Sales Order": ["xero_sales_order_id", "xero_sync_status", "xero_last_sales_order_sync"],
        "Delivery Note": ["xero_delivery_note_id", "xero_sync_status", "xero_last_delivery_note_sync"],
        "Purchase Receipt": ["xero_purchase_receipt_id", "xero_sync_status", "xero_last_purchase_receipt_sync"],
        "Cost Center": ["xero_tracking_category_id", "xero_tracking_option_id"],
        "Project": ["xero_tracking_category_id", "xero_tracking_option_id"],
    }
    
    removed_count = 0
    for doctype, fields in custom_fields_to_remove.items():
        for fieldname in fields:
            cf_name = f"{doctype}-{fieldname}"
            if frappe.db.exists("Custom Field", cf_name):
                try:
                    frappe.delete_doc("Custom Field", cf_name, ignore_permissions=True, force=True)
                    removed_count += 1
                    print(f"  ✓ Removed custom field: {cf_name}")
                except Exception as e:
                    print(f"  ⚠ Warning: Could not remove {cf_name}: {e}")
    
    frappe.db.commit()
    print(f"Removed {removed_count} custom fields")
    
    # 2. Delete Xero Project records if the DocType still exists
    if frappe.db.exists("DocType", "Xero Project"):
        try:
            projects = frappe.get_all("Xero Project", pluck="name")
            for p in projects:
                frappe.delete_doc("Xero Project", p, ignore_permissions=True, force=True)
            if projects:
                print(f"  ✓ Deleted {len(projects)} Xero Project records")
            frappe.db.commit()
        except Exception as e:
            print(f"  ⚠ Warning: Could not clean Xero Project records: {e}")
    
    print("✓ Unsupported Xero entity removal complete")
