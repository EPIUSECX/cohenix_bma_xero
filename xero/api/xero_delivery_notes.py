# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from .xero_invoices import sync_invoice_to_xero # We can reuse the invoice sync logic

@frappe.whitelist()
def enqueue_sync_delivery_note(doc, method):
    """Enqueue background job to sync a Delivery Note as an Invoice to Xero."""
    settings = get_xero_settings()
    # Assume a new setting `sync_delivery_notes_as_invoices`
    if not settings.enable_xero_sync or not settings.get("sync_delivery_notes_as_invoices"):
        return

    frappe.enqueue(
        "xero.api.xero_delivery_notes.sync_delivery_note_to_xero_invoice",
        queue="short",
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued Delivery Note {doc.name} for sync as Xero Invoice.", "Xero Sync")


def sync_delivery_note_to_xero_invoice(doc_name, doc_type):
    """
    Creates an in-memory Sales Invoice from a submitted Delivery Note,
    then syncs that Sales Invoice to Xero.
    """
    try:
        # 1. Create a Sales Invoice from the Delivery Note in memory
        # This uses the standard Frappe mapper to correctly pull in all details
        sales_invoice = get_mapped_doc(
            "Delivery Note",
            doc_name,
            {
                "Delivery Note": {
                    "doctype": "Sales Invoice",
                    "validation": {
                        "docstatus": ["=", 1]
                    }
                }
            }
        )
        # The mapped doc is not saved to the database, it only exists in memory
        sales_invoice.run_method("set_missing_values")
        sales_invoice.run_method("calculate_taxes_and_totals")

        # 2. Call the existing sync_invoice_to_xero function
        # We pass the in-memory doc object directly to avoid needing to save it
        # Note: This requires modifying sync_invoice_to_xero to accept a doc object
        # For now, we will save the invoice, sync it, then delete the temporary invoice.
        # This is less efficient but avoids refactoring the existing function for now.
        
        # A better long-term approach is to refactor sync_invoice_to_xero to accept a doc object.
        # For this implementation, we will proceed with a temporary save-sync-delete.

        sales_invoice.flags.ignore_permissions = True
        sales_invoice.insert()
        
        log_xero_error(
            message=f"Created temporary Sales Invoice {sales_invoice.name} from Delivery Note {doc_name} for Xero sync.",
            status="Info"
        )

        # Call the existing invoice sync function with the new SI name
        sync_invoice_to_xero(sales_invoice.name, "Sales Invoice")

        # 3. Clean up the temporary Sales Invoice
        frappe.delete_doc("Sales Invoice", sales_invoice.name, ignore_permissions=True, force=True)
        
        log_xero_error(
            message=f"Successfully synced Delivery Note {doc_name} as Xero Invoice and cleaned up temporary SI {sales_invoice.name}.",
            status="Success",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name
        )

    except Exception as e:
        log_xero_error(
            message=f"Failed to sync Delivery Note {doc_name} as Xero Invoice.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )