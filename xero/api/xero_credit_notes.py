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
        
        if not settings.get("sync_credit_notes"):
            return
        
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


# --- Credit Note Sync (Xero to ERPNext) ---

def sync_credit_notes_from_xero(modified_since=None):
    """
    Fetches credit notes from Xero and creates/updates corresponding
    return invoices in ERPNext.
    
    Args:
        modified_since: ISO date string to fetch only recent credit notes
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping credit notes inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_credit_notes"): return
    
    try:
        page = 1
        params = {"page": page}
        
        if modified_since:
            params["ModifiedSince"] = modified_since
        
        while True:
            frappe.logger().info(f"Fetching Xero Credit Notes page {page}", "Xero Sync")
            response = xero_request("GET", "CreditNotes", params=params)
            
            if not response or not response.get("CreditNotes"):
                break
            
            credit_notes = response["CreditNotes"]
            if not credit_notes:
                break
            
            for cn_data in credit_notes:
                try:
                    process_xero_credit_note(cn_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Credit Note ID {cn_data.get('CreditNoteID')}",
                        xero_entity_id=cn_data.get('CreditNoteID'),
                        xero_entity_type="CreditNote",
                        error_details=frappe.get_traceback()
                    )
            
            if len(credit_notes) < 100:
                break
            page += 1
            params["page"] = page
        
        log_xero_error(message="Finished syncing credit notes from Xero.", status="Info")
    
    except Exception as e:
        log_xero_error(
            message="Error during sync_credit_notes_from_xero",
            error_details=frappe.get_traceback()
        )


def process_xero_credit_note(xero_cn_data, settings):
    """Creates or updates an ERPNext return invoice from Xero credit note data."""
    from .xero_invoices import parse_xero_date, get_or_create_item_from_xero_code, get_erpnext_account_from_xero_code, get_erpnext_tax_from_xero_type
    
    xero_cn_id = xero_cn_data.get("CreditNoteID")
    cn_number = xero_cn_data.get("CreditNoteNumber")
    cn_type = xero_cn_data.get("Type")  # ACCRECCREDIT or ACCPAYCREDIT
    
    if not xero_cn_id or not cn_type:
        log_xero_error(message=f"Skipping Xero credit note due to missing ID or Type", status="Info")
        return
    
    # Determine ERPNext DocType
    erpnext_doctype = "Sales Invoice" if cn_type == "ACCRECCREDIT" else "Purchase Invoice"
    
    # Check if credit note already exists
    erpnext_doc_name = frappe.db.get_value(erpnext_doctype, {"xero_credit_note_id": xero_cn_id}, "name")
    
    # Get contact information
    xero_contact_id = xero_cn_data.get("Contact", {}).get("ContactID")
    if not xero_contact_id:
        log_xero_error(message=f"Skipping Xero credit note {cn_number}: No contact information", status="Info")
        return
    
    # Find corresponding ERPNext customer/supplier
    party_doctype = "Customer" if cn_type == "ACCRECCREDIT" else "Supplier"
    party_name = frappe.db.get_value(party_doctype, {"xero_contact_id": xero_contact_id}, "name")
    
    if not party_name:
        log_xero_error(
            message=f"Skipping Xero credit note {cn_number}: {party_doctype} not found for Xero Contact {xero_contact_id}",
            status="Info",
            xero_entity_id=xero_cn_id,
            xero_entity_type="CreditNote"
        )
        return
    
    try:
        # Get company
        company = frappe.defaults.get_global_default("company")
        if not company:
            company = frappe.get_all("Company", limit=1, pluck="name")[0]
        
        # Map header fields
        erpnext_data = {
            "xero_credit_note_id": xero_cn_id,
            "xero_sync_status": "Synced",
            "is_return": 1,  # Mark as return invoice
            "company": company,
            "posting_date": parse_xero_date(xero_cn_data.get("Date")),
            "currency": xero_cn_data.get("CurrencyCode", "USD"),
            "conversion_rate": frappe.utils.flt(xero_cn_data.get("CurrencyRate", 1.0)),
        }
        
        # Add party-specific fields
        if erpnext_doctype == "Sales Invoice":
            erpnext_data["customer"] = party_name
            erpnext_data["customer_name"] = xero_cn_data.get("Contact", {}).get("Name")
            erpnext_data["debit_to"] = frappe.get_cached_value("Company", company, "default_receivable_account")
        else:  # Purchase Invoice
            erpnext_data["supplier"] = party_name
            erpnext_data["supplier_name"] = xero_cn_data.get("Contact", {}).get("Name")
            erpnext_data["credit_to"] = frappe.get_cached_value("Company", company, "default_payable_account")
        
        # Store Xero credit note number in remarks
        if cn_number:
            erpnext_data["remarks"] = f"Xero Credit Note: {cn_number}"
        
        # Create or update credit note
        if erpnext_doc_name:
            # Update existing
            doc = frappe.get_doc(erpnext_doctype, erpnext_doc_name)
            doc.update(erpnext_data)
            doc.save(ignore_permissions=True)
            log_message = f"Updated {erpnext_doctype} (Return) {erpnext_doc_name} from Xero Credit Note {xero_cn_id}"
        else:
            # Create new
            doc = frappe.new_doc(erpnext_doctype)
            doc.update(erpnext_data)
            
            # Add line items
            line_items = xero_cn_data.get("LineItems", [])
            for line in line_items:
                item_code = get_or_create_item_from_xero_code(line.get("ItemCode"), line.get("Description"), settings)
                account = get_erpnext_account_from_xero_code(line.get("AccountCode"), settings)
                
                if not account:
                    log_xero_error(
                        message=f"Skipping line item in credit note {cn_number}: No account mapping for Xero AccountCode {line.get('AccountCode')}",
                        status="Warning",
                        xero_entity_id=xero_cn_id,
                        xero_entity_type="CreditNote"
                    )
                    continue
                
                # For credit notes, quantities should be negative in ERPNext
                item_dict = {
                    "description": line.get("Description", "Item from Xero"),
                    "qty": -abs(frappe.utils.flt(line.get("Quantity", 1))),  # Negative for return
                    "rate": frappe.utils.flt(line.get("UnitAmount", 0)),
                    "amount": -abs(frappe.utils.flt(line.get("LineAmount", 0))),  # Negative for return
                }
                
                if item_code:
                    item_dict["item_code"] = item_code
                    item_dict["item_name"] = line.get("Description")
                else:
                    item_dict["item_name"] = line.get("Description", "Xero Item")
                
                # Add account
                if erpnext_doctype == "Sales Invoice":
                    item_dict["income_account"] = account
                else:
                    item_dict["expense_account"] = account
                
                # Add tax template if mapped
                tax_template = get_erpnext_tax_from_xero_type(line.get("TaxType"), settings)
                if tax_template:
                    item_dict["item_tax_template"] = tax_template
                
                doc.append("items", item_dict)
            
            if not doc.items:
                log_xero_error(
                    message=f"Skipping Xero credit note {cn_number}: No valid line items",
                    status="Warning",
                    xero_entity_id=xero_cn_id,
                    xero_entity_type="CreditNote"
                )
                return
            
            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created {erpnext_doctype} (Return) {erpnext_doc_name} from Xero Credit Note {xero_cn_id} ({cn_number})"
        
        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type=erpnext_doctype,
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_cn_id,
            xero_entity_type="CreditNote",
            direction="Xero to ERPNext"
        )
    
    except Exception as e:
        sync_status = "Error"
        if erpnext_doc_name:
            frappe.db.set_value(erpnext_doctype, erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
            frappe.db.commit()
        
        log_xero_error(
            message=f"Failed to sync Xero Credit Note {xero_cn_id} ({cn_number}) to ERPNext",
            erpnext_doc_type=erpnext_doctype if 'erpnext_doctype' in locals() else None,
            erpnext_doc_name=erpnext_doc_name if 'erpnext_doc_name' in locals() else None,
            xero_entity_id=xero_cn_id,
            xero_entity_type="CreditNote",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )
