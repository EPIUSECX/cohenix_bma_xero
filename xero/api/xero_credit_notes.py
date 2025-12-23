# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from frappe.utils import getdate

@frappe.whitelist()
def enqueue_sync_return(doc, method):
    """Enqueue background job to sync a return document (Credit/Debit Note) to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_credit_notes"): # Assume a new setting
        return

    frappe.enqueue(
        "xero.api.xero_credit_notes.sync_return_to_xero",
        queue="short",
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued sync for return document {doc.name} to Xero.", "Xero Sync")


def sync_return_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs a submitted ERPNext return document to Xero.
    - Sales Invoice with is_return=1 -> Xero Credit Note (Type ACCRECCREDIT)
    - Purchase Invoice with is_return=1 -> Xero Debit Note (Type ACCPAYCREDIT)
    Ref: https://developer.xero.com/documentation/api/accounting/creditnotes
    """
    try:
        doc = frappe.get_doc(doc_type, doc_name)
        settings = get_xero_settings()
        xero_cn_id = doc.get("xero_credit_note_id")

        if doc.docstatus != 1 or not doc.is_return:
            return

        # Determine type and party
        if doc.doctype == "Sales Invoice":
            cn_type = "ACCRECCREDIT"
            party_type = "Customer"
            party_name = doc.customer
        elif doc.doctype == "Purchase Invoice":
            cn_type = "ACCPAYCREDIT"
            party_type = "Supplier"
            party_name = doc.supplier
        else:
            return # Not a return document we handle here

        # 1. Get Xero Contact ID
        xero_contact_id = frappe.db.get_value(party_type, party_name, "xero_contact_id")
        if not xero_contact_id:
            raise Exception(f"Xero Contact ID not found for {party_type}: {party_name}.")

        # 2. Map Line Items
        line_items = []
        for item in doc.items:
            # For returns, amounts are negative, but Xero expects positive values for credit notes
            line_items.append({
                "Description": item.description,
                "Quantity": abs(item.qty),
                "UnitAmount": item.rate,
                "AccountCode": frappe.db.get_value("Account", item.income_account or item.expense_account, "account_number"),
                "LineAmount": abs(item.amount),
            })

        # 3. Construct Credit Note Payload
        cn_payload = {
            "Type": cn_type,
            "Contact": { "ContactID": xero_contact_id },
            "Date": getdate(doc.posting_date).isoformat(),
            "LineItems": line_items,
            "CreditNoteNumber": doc.name,
            "Status": "AUTHORISED",
        }

        if xero_cn_id:
            cn_payload["CreditNoteID"] = xero_cn_id

        # 4. Make API Call
        response = xero_request("PUT", "CreditNotes", data={"CreditNotes": [cn_payload]})

        # 5. Process response
        if response and response.get("CreditNotes"):
            new_xero_id = response["CreditNotes"][0].get("CreditNoteID")
            frappe.db.set_value(doc_type, doc_name, "xero_credit_note_id", new_xero_id, update_modified=False)
            frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Synced", update_modified=False)
            frappe.db.commit()
            log_xero_error(
                message=f"Successfully synced return {doc.name} to Xero.",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc.name,
                xero_entity_id=new_xero_id,
                xero_entity_type="CreditNote"
            )
        else:
            raise Exception("Invalid response from Xero CreditNotes API.")

    except Exception as e:
        frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Error", update_modified=False)
        frappe.db.commit()
        log_xero_error(
            message=f"Failed to sync return {doc_name} to Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )
