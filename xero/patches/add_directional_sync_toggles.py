# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

"""Prompt - Write me a migration script to add the directional sync toggle 
fields I built to the existing Xero Settings. Set default values to maintain current 
behavior (both directions enabled)."""

import frappe

def execute():
    """
    Migration script to add directional sync toggle fields to existing Xero Settings.
    Sets default values to maintain current behavior (both directions enabled).
    """
    try:
        # Check if Xero Settings exists
        if frappe.db.exists("Xero Settings", "Xero Settings"):
            settings = frappe.get_doc("Xero Settings", "Xero Settings")
            
            # Set default values for new fields (both enabled to maintain current behavior)
            # Always set to 1 if currently 0 or None
            if not settings.enable_sync_to_xero:
                settings.enable_sync_to_xero = 1
            
            if not settings.enable_sync_from_xero:
                settings.enable_sync_from_xero = 1
            
            settings.save(ignore_permissions=True)
            frappe.db.commit()
            
            print("✓ Xero Settings updated with directional sync toggles (both enabled by default)")
            
            # Log the migration
            from xero.utils.logging import log_xero_error
            log_xero_error(
                message="Directional sync toggles added to Xero Settings. Both directions enabled by default.",
                status="Success",
                category="System Monitoring"
            )
        else:
            print("⚠ Xero Settings not found. Skipping migration.")
    
    except Exception as e:
        print(f"✗ Error during migration: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Xero Directional Sync Migration Error")
