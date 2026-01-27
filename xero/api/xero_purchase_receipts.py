# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from .xero_invoices import sync_invoice_to_xero # Reuse invoice sync logic

@frappe.whitelist()
def enqueue_sync_purchase_receipt(doc, method):
    """Enqueue background job to sync a Purchase Receipt as a Bill to Xero."""
    settings = get_xero_settings()
    # Assume a new setting `sync_purchase_receipts_as_bills`
    if not settings.enable_xero_sync or not settings.get("sync_purchase_receipts_as_bills"):
        return

    frappe.enqueue(
        "xero.api.xero_purchase_receipts.sync_purchase_receipt_to_xero_bill",
        queue="short",
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued Purchase Receipt {doc.name} for sync as Xero Bill.", "Xero Sync")


def sync_purchase_receipt_to_xero_bill(doc_name, doc_type):
    """
    Creates an in-memory Purchase Invoice from a submitted Purchase Receipt,
    then syncs that Purchase Invoice to Xero as a Bill (ACCPAY Invoice).
    """
    try:
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
        
        if not settings.get("sync_purchase_receipts_as_bills"):
            return
        
        # 1. Create a Purchase Invoice from the Purchase Receipt in memory
        purchase_invoice = get_mapped_doc(
            "Purchase Receipt",
            doc_name,
            {
                "Purchase Receipt": {
                    "doctype": "Purchase Invoice",
                    "validation": {
                        "docstatus": ["=", 1]
                    }
                }
            }
        )
        purchase_invoice.run_method("set_missing_values")
        purchase_invoice.run_method("calculate_taxes_and_totals")

        # 2. Save the temporary Purchase Invoice to sync it
        purchase_invoice.flags.ignore_permissions = True
        purchase_invoice.insert()
        
        log_xero_error(
            message=f"Created temporary Purchase Invoice {purchase_invoice.name} from Purchase Receipt {doc_name} for Xero sync.",
            status="Info"
        )

        # Call the existing invoice sync function
        sync_invoice_to_xero(purchase_invoice.name, "Purchase Invoice")

        # 3. Clean up the temporary Purchase Invoice
        frappe.delete_doc("Purchase Invoice", purchase_invoice.name, ignore_permissions=True, force=True)
        
        log_xero_error(
            message=f"Successfully synced Purchase Receipt {doc_name} as Xero Bill and cleaned up temporary PI {purchase_invoice.name}.",
            status="Success",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name
        )

    except Exception as e:
        log_xero_error(
            message=f"Failed to sync Purchase Receipt {doc_name} as Xero Bill.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )