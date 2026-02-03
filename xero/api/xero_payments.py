# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, flt, now
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff

# --- Payment Sync (ERPNext to Xero) ---

@frappe.whitelist()
def enqueue_sync_payment(doc, method):
    """Enqueue background job to sync a Payment Entry to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_payments"):
        return

    frappe.enqueue(
        "xero.api.xero_payments.sync_payment_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync")


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_payment_to_xero(doc_name, doc_type="Payment Entry", **kwargs):
    """
    Enhanced payment sync that handles multiple invoice payments and reconciliation.
    Syncs a submitted ERPNext Payment Entry to Xero as Payment or Bank Transaction.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return # Master switch disabled
    
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
    
    if not settings.get("sync_payments"):
        return # Payment sync specifically disabled

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_payment_id = doc.get("xero_payment_id")

        # --- Basic Validation ---
        if doc.docstatus != 1:
            log_xero_error(f"Cannot sync non-submitted document: {doc_type} {doc_name}", status="Info")
            return

        # --- Get Xero Contact ID ---
        xero_contact_id = frappe.db.get_value(doc.party_type, doc.party, "xero_contact_id")
        if not xero_contact_id:
            # Attempt to sync the contact first
            frappe.logger().info(f"Xero Contact ID not found for {doc.party_type} {doc.party}. Attempting to sync contact first.", "Xero Sync")
            from .xero_contacts import sync_contact_to_xero
            try:
                sync_contact_to_xero(doc.party, doc.party_type)
                xero_contact_id = frappe.db.get_value(doc.party_type, doc.party, "xero_contact_id")
                if not xero_contact_id:
                    raise Exception(f"Failed to sync and retrieve Xero Contact ID for {doc.party_type} {doc.party}.")
            except Exception as contact_sync_e:
                raise Exception(f"Prerequisite failed: Could not sync {doc.party_type} {doc.party} to Xero. Error: {contact_sync_e}")

        # --- Get Xero Bank Account ID ---
        bank_account = doc.paid_from if doc.payment_type == "Pay" else doc.paid_to
        xero_bank_account_id = frappe.db.get_value("Account", bank_account, "xero_account_id")
        if not xero_bank_account_id:
            raise Exception(f"Xero Account ID not found for Bank Account: {bank_account}. Please sync Chart of Accounts first.")

        # --- Determine Payment Type and Process ---
        if doc.references and len(doc.references) > 0:
            # This is a payment against invoice(s)
            sync_invoice_payments(doc, xero_bank_account_id, doc_type, doc_name)
        else:
            # This is a standalone payment (advance payment, etc.)
            sync_standalone_payment(doc, xero_contact_id, xero_bank_account_id, doc_type, doc_name)

    except Exception as e:
        # Ensure status is updated even if doc object wasn't fetched initially
        if doc_name and doc_type:
            frappe.db.set_value(doc_type, doc_name, {"xero_sync_status": "Error"}, update_modified=False)
            frappe.db.commit()

        log_xero_error(
            message=f"Failed to sync {doc_type} {doc_name} to Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )


def sync_invoice_payments(doc, xero_bank_account_id, doc_type, doc_name):
    """Handle payments against specific invoices."""
    synced_payments = []
    
    for reference in doc.references:
        if reference.allocated_amount <= 0:
            continue
            
        invoice_doctype = reference.reference_doctype
        invoice_name = reference.reference_name

        # Get Xero Invoice ID
        if invoice_doctype == "Sales Invoice":
            xero_invoice_id = frappe.db.get_value("Sales Invoice", invoice_name, "xero_invoice_id")
        elif invoice_doctype == "Purchase Invoice":
            xero_invoice_id = frappe.db.get_value("Purchase Invoice", invoice_name, "xero_invoice_id")
        else:
            log_xero_error(f"Unsupported invoice type for payment sync: {invoice_doctype}", status="Info")
            continue

        if not xero_invoice_id:
            log_xero_error(f"Xero Invoice ID not found for {invoice_doctype} {invoice_name}. Skipping this reference.", status="Info")
            continue

        # Create payment payload
        payment_payload = {
            "Invoice": {
                "InvoiceID": xero_invoice_id
            },
            "Account": {
                "AccountID": xero_bank_account_id
            },
            "Date": getdate(doc.posting_date).isoformat(),
            "Amount": flt(reference.allocated_amount),
            "Reference": f"{doc.reference_no or doc.name} - {invoice_name}",
        }

        # Make API call
        response = xero_request("PUT", "Payments", data={"Payments": [payment_payload]})

        if response and response.get("Payments"):
            updated_payment = response["Payments"][0]
            new_xero_payment_id = updated_payment.get("PaymentID")
            
            if new_xero_payment_id:
                synced_payments.append({
                    "payment_id": new_xero_payment_id,
                    "invoice_id": xero_invoice_id,
                    "amount": flt(reference.allocated_amount)
                })
                
                log_xero_error(
                    message=f"Successfully synced payment for invoice {invoice_name} from {doc_type} {doc_name}",
                    status="Success",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=new_xero_payment_id,
                    xero_entity_type="Payment",
                    direction="ERPNext to Xero"
                )
            else:
                raise Exception(f"Xero API response did not contain a PaymentID for invoice {invoice_name}")
        else:
            raise Exception(f"Invalid response received from Xero Payments API for invoice {invoice_name}")

    # Update ERPNext document with sync results
    if synced_payments:
        primary_payment_id = synced_payments[0]["payment_id"]
        all_payment_data = frappe.as_json(synced_payments) if len(synced_payments) > 1 else primary_payment_id
        
        frappe.db.set_value(doc_type, doc_name, {
            "xero_payment_id": primary_payment_id,
            "xero_payment_data": all_payment_data,
            "xero_sync_status": "Synced",
            "xero_last_sync": now()
        }, update_modified=False)
        frappe.db.commit()

        log_xero_error(
            message=f"Successfully synced {doc_type} {doc_name} to Xero. Created {len(synced_payments)} payment(s).",
            status="Success",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            xero_entity_id=primary_payment_id,
            xero_entity_type="Payment",
            direction="ERPNext to Xero"
        )
    else:
        raise Exception("No payments were successfully created in Xero.")


def sync_standalone_payment(doc, xero_contact_id, xero_bank_account_id, doc_type, doc_name):
    """Handle standalone payments (advances, etc.) as Bank Transactions."""
    from .xero_invoices import get_xero_account_code
    
    settings = get_xero_settings()
    
    # Get account code for the party account
    party_account = doc.party_account
    xero_account_code = get_xero_account_code(party_account, settings)
    if not xero_account_code:
        raise Exception(f"Xero Account Code mapping not found for Account: {party_account}")

    # Create bank transaction payload
    transaction_payload = {
        "Type": "SPEND" if doc.payment_type == "Pay" else "RECEIVE",
        "Contact": {
            "ContactID": xero_contact_id
        },
        "Date": getdate(doc.posting_date).isoformat(),
        "LineItems": [{
            "Description": doc.remarks or f"Payment {doc.name}",
            "Quantity": 1,
            "UnitAmount": flt(doc.paid_amount),
            "AccountCode": xero_account_code,
            "LineAmount": flt(doc.paid_amount),
            "TaxType": "NONE"  # Payments typically don't have tax
        }],
        "BankAccount": {
            "AccountID": xero_bank_account_id
        },
        "Reference": doc.reference_no or doc.name,
    }

    # If updating, include the Xero Bank Transaction ID
    xero_bank_transaction_id = doc.get("xero_bank_transaction_id")
    if xero_bank_transaction_id:
        transaction_payload["BankTransactionID"] = xero_bank_transaction_id

    # Make API call
    response = xero_request("PUT", "BankTransactions", data={"BankTransactions": [transaction_payload]})

    if response and response.get("BankTransactions"):
        updated_transaction = response["BankTransactions"][0]
        new_xero_transaction_id = updated_transaction.get("BankTransactionID")

        if new_xero_transaction_id:
            frappe.db.set_value(doc_type, doc_name, {
                "xero_bank_transaction_id": new_xero_transaction_id,
                "xero_sync_status": "Synced",
                "xero_last_sync": now()
            }, update_modified=False)
            frappe.db.commit()

            log_xero_error(
                message=f"Successfully synced standalone payment {doc_type} {doc_name} to Xero as Bank Transaction.",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=new_xero_transaction_id,
                xero_entity_type="BankTransaction",
                direction="ERPNext to Xero"
            )
        else:
            raise Exception("Xero API response did not contain a BankTransactionID.")
    else:
        raise Exception("Invalid response received from Xero BankTransactions API.")


# --- Payment Sync (Xero to ERPNext) ---

def sync_payments_from_xero(invoice_id=None):
    """
    Fetches payments from Xero and creates corresponding entries in ERPNext.
    
    Args:
        invoice_id: Specific Xero invoice ID to sync payments for
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping payments inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_payments"): return

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Payments page {page}", "Xero Sync")
            
            params = {"page": page}
            if invoice_id:
                params["InvoiceID"] = invoice_id
                
            response = xero_request("GET", "Payments", params=params)

            if not response or not response.get("Payments"):
                break

            payments = response["Payments"]
            if not payments:
                break

            for payment_data in payments:
                try:
                    process_xero_payment(payment_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Payment ID {payment_data.get('PaymentID')}",
                        xero_entity_id=payment_data.get('PaymentID'),
                        xero_entity_type="Payment",
                        error_details=frappe.get_traceback()
                    )

            # Check if it was the last page
            if len(payments) < 100:
                break
            page += 1

        log_xero_error(message="Finished syncing payments from Xero.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_payments_from_xero",
            error_details=frappe.get_traceback()
        )


def process_xero_payment(xero_payment_data, settings):
    """Creates or updates an ERPNext Payment Entry from Xero payment data."""
    from .xero_invoices import parse_xero_date
    
    xero_payment_id = xero_payment_data.get("PaymentID")
    
    if not xero_payment_id:
        log_xero_error(message=f"Skipping Xero payment due to missing ID: {xero_payment_data}", status="Info")
        return

    # Check if ERPNext payment already exists
    erpnext_doc_name = frappe.db.get_value("Payment Entry", {"xero_payment_id": xero_payment_id}, "name")

    # Get invoice information
    xero_invoice_id = xero_payment_data.get("Invoice", {}).get("InvoiceID")
    if not xero_invoice_id:
        log_xero_error(message=f"Skipping Xero payment {xero_payment_id}: No invoice information", status="Info")
        return

    # Find corresponding ERPNext invoice
    invoice_doc = None
    invoice_doctype = None
    
    # Try Sales Invoice first
    invoice_name = frappe.db.get_value("Sales Invoice", {"xero_invoice_id": xero_invoice_id}, "name")
    if invoice_name:
        invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
        invoice_doctype = "Sales Invoice"
    else:
        # Try Purchase Invoice
        invoice_name = frappe.db.get_value("Purchase Invoice", {"xero_invoice_id": xero_invoice_id}, "name")
        if invoice_name:
            invoice_doc = frappe.get_doc("Purchase Invoice", invoice_name)
            invoice_doctype = "Purchase Invoice"

    if not invoice_doc:
        log_xero_error(message=f"Skipping Xero payment {xero_payment_id}: Invoice not found for Xero Invoice {xero_invoice_id}", status="Info")
        return

    # Get account information
    xero_account_id = xero_payment_data.get("Account", {}).get("AccountID")
    if not xero_account_id:
        log_xero_error(message=f"Skipping Xero payment {xero_payment_id}: No account information", status="Info")
        return

    # Find corresponding ERPNext account
    account = frappe.db.get_value("Account", {"xero_account_id": xero_account_id}, "name")
    if not account:
        log_xero_error(message=f"Skipping Xero payment {xero_payment_id}: Account not found for Xero Account {xero_account_id}", status="Info")
        return

    try:
        # Determine payment type based on invoice type
        payment_type = "Receive" if invoice_doctype == "Sales Invoice" else "Pay"
        party_type = "Customer" if invoice_doctype == "Sales Invoice" else "Supplier"
        
        # Calculate amounts
        payment_amount = flt(xero_payment_data.get("Amount", 0))

        # Map Xero Data to ERPNext Fields
        erpnext_data = {
            "payment_type": payment_type,
            "party_type": party_type,
            "party": invoice_doc.customer if invoice_doctype == "Sales Invoice" else invoice_doc.supplier,
            "posting_date": parse_xero_date(xero_payment_data.get("Date")),
            "paid_amount": payment_amount,
            "received_amount": payment_amount,
            "paid_from": account if payment_type == "Pay" else invoice_doc.debit_to if invoice_doctype == "Sales Invoice" else invoice_doc.credit_to,
            "paid_to": invoice_doc.debit_to if invoice_doctype == "Sales Invoice" else account if payment_type == "Pay" else invoice_doc.credit_to,
            "reference_no": xero_payment_data.get("Reference"),
            "remarks": f"Payment from Xero for {invoice_doctype} {invoice_name}",
            "xero_payment_id": xero_payment_id,
            "xero_sync_status": "Synced",
            "references": [{
                "reference_doctype": invoice_doctype,
                "reference_name": invoice_name,
                "allocated_amount": payment_amount
            }]
        }

        if erpnext_doc_name:
            # Update existing payment
            doc = frappe.get_doc("Payment Entry", erpnext_doc_name)
            doc.update(erpnext_data)
            doc.save(ignore_permissions=True)
            log_message = f"Updated Payment Entry {erpnext_doc_name} from Xero Payment {xero_payment_id}"
        else:
            # Create new payment
            doc = frappe.new_doc("Payment Entry")
            doc.update(erpnext_data)
            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created Payment Entry {erpnext_doc_name} from Xero Payment {xero_payment_id}"

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type="Payment Entry",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_payment_id,
            xero_entity_type="Payment",
            direction="Xero to ERPNext"
        )

    except Exception as e:
        sync_status = "Error"
        if erpnext_doc_name:
            frappe.db.set_value("Payment Entry", erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
            frappe.db.commit()

        log_xero_error(
            message=f"Failed to sync Xero Payment {xero_payment_id} to ERPNext",
            erpnext_doc_type="Payment Entry",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_payment_id,
            xero_entity_type="Payment",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )


@frappe.whitelist()
def reconcile_payments(party=None, party_type=None, from_date=None, to_date=None):
    """
    Reconcile payments between ERPNext and Xero for a specific party or date range.
    
    Args:
        party: ERPNext party name (Customer/Supplier)
        party_type: "Customer" or "Supplier"
        from_date: Start date for reconciliation
        to_date: End date for reconciliation
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw("Xero sync is not enabled.")

    try:
        # Sync payments from Xero
        sync_payments_from_xero()

        # Get ERPNext payments for comparison
        filters = {
            "docstatus": 1
        }
        
        if party and party_type:
            filters["party"] = party
            filters["party_type"] = party_type
            
        if from_date:
            filters["posting_date"] = [">=", from_date]
        if to_date:
            if "posting_date" in filters:
                filters["posting_date"] = ["between", [from_date, to_date]]
            else:
                filters["posting_date"] = ["<=", to_date]

        erpnext_payments = frappe.get_all(
            "Payment Entry",
            filters=filters,
            fields=["name", "posting_date", "paid_amount", "party", "party_type", "reference_no", "xero_payment_id"]
        )

        # Create reconciliation report
        reconciliation_data = {
            "party": party,
            "party_type": party_type,
            "from_date": from_date,
            "to_date": to_date,
            "total_erpnext_payments": len(erpnext_payments),
            "synced_payments": len([p for p in erpnext_payments if p.xero_payment_id]),
            "unsynced_payments": len([p for p in erpnext_payments if not p.xero_payment_id]),
        }

        frappe.msgprint(f"Payment reconciliation completed. {reconciliation_data['synced_payments']} payments synced, {reconciliation_data['unsynced_payments']} unsynced.")
        
        return reconciliation_data

    except Exception as e:
        log_xero_error(
            message=f"Error during payment reconciliation",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Payment reconciliation failed: {str(e)}")
