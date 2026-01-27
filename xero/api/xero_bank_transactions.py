# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, flt
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff
from .xero_invoices import get_xero_account_code

# --- Bank Transaction Sync (ERPNext to Xero) ---

@frappe.whitelist()
def enqueue_sync_bank_transaction(doc, method):
    """Enqueue background job to sync a Bank Transaction to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_bank_transactions"):
        return

    frappe.enqueue(
        "xero.api.xero_bank_transactions.sync_bank_transaction_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync")


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_bank_transaction_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs an ERPNext Bank Transaction to Xero Bank Transactions.
    Uses PUT for create/update.
    Ref: https://developer.xero.com/documentation/api/accounting/banktransactions
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
    
    if not settings.get("sync_bank_transactions"):
        return # Bank transaction sync specifically disabled

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_bank_transaction_id = doc.get("xero_bank_transaction_id")

        # --- Basic Validation ---
        if doc.docstatus != 1:
            log_xero_error(f"Cannot sync non-submitted document: {doc_type} {doc_name}", status="Info")
            return

        # --- Get Xero Contact ID ---
        contact_party_type = "Customer" if doc.party_type == "Customer" else "Supplier"
        xero_contact_id = frappe.db.get_value(contact_party_type, doc.party, "xero_contact_id")
        if not xero_contact_id:
            # Attempt to sync the contact first
            frappe.logger().info(f"Xero Contact ID not found for {doc.party_type} {doc.party}. Attempting to sync contact first.", "Xero Sync")
            from .xero_contacts import sync_contact_to_xero
            try:
                sync_contact_to_xero(doc.party, contact_party_type)
                xero_contact_id = frappe.db.get_value(contact_party_type, doc.party, "xero_contact_id")
                if not xero_contact_id:
                    raise Exception(f"Failed to sync and retrieve Xero Contact ID for {doc.party_type} {doc.party}.")
            except Exception as contact_sync_e:
                raise Exception(f"Prerequisite failed: Could not sync {doc.party_type} {doc.party} to Xero. Error: {contact_sync_e}")

        # --- Get Xero Bank Account ID ---
        xero_bank_account_id = frappe.db.get_value("Account", doc.account, "xero_account_id")
        if not xero_bank_account_id:
            raise Exception(f"Xero Account ID not found for Bank Account: {doc.account}. Please sync Chart of Accounts first.")

        # --- Map ERPNext Bank Transaction Data to Xero Format ---
        transaction_payload = {
            "Type": "SPEND" if doc.withdrawal > 0 else "RECEIVE",
            "Contact": {
                "ContactID": xero_contact_id
            },
            "Date": getdate(doc.date).isoformat(),
            "LineItems": [],
            "BankAccount": {
                "AccountID": xero_bank_account_id
            },
            "Reference": doc.reference_number or doc.name,
            "IsReconciled": doc.clearance_date is not None,
        }

        # If updating, include the Xero Bank Transaction ID
        if xero_bank_transaction_id:
            transaction_payload["BankTransactionID"] = xero_bank_transaction_id

        # --- Map Line Items ---
        # For bank transactions, we typically have one line item
        amount = doc.withdrawal if doc.withdrawal > 0 else doc.deposit
        description = doc.description or f"Bank Transaction {doc.name}"
        
        # Get account code for the contra account (usually expense or income)
        contra_account = doc.against_account if doc.against_account else doc.account
        xero_account_code = get_xero_account_code(contra_account, settings)
        if not xero_account_code:
            raise Exception(f"Xero Account Code mapping not found for Account: {contra_account}")

        line_item = {
            "Description": description,
            "Quantity": 1,
            "UnitAmount": amount,
            "AccountCode": xero_account_code,
            "LineAmount": amount,
            "TaxType": "NONE"  # Bank transactions typically don't have tax
        }
        transaction_payload["LineItems"].append(line_item)

        # --- Make API Call (PUT for create/update) ---
        response = xero_request("PUT", "BankTransactions", data={"BankTransactions": [transaction_payload]})

        if response and response.get("BankTransactions"):
            updated_transaction = response["BankTransactions"][0]
            new_xero_transaction_id = updated_transaction.get("BankTransactionID")

            # --- Update ERPNext Document ---
            if new_xero_transaction_id:
                frappe.db.set_value(doc_type, doc_name, {
                    "xero_bank_transaction_id": new_xero_transaction_id,
                    "xero_sync_status": "Synced"
                }, update_modified=False)
                frappe.db.commit()

                log_xero_error(
                    message=f"Successfully synced {doc_type} {doc_name} to Xero.",
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


# --- Bank Transaction Sync (Xero to ERPNext) ---

def sync_bank_transactions_from_xero(bank_account_id=None):
    """
    Fetches bank transactions from Xero and creates corresponding entries in ERPNext.
    
    Args:
        bank_account_id: Specific Xero bank account ID to sync transactions for
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping bank transactions inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_bank_transactions"): return

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Bank Transactions page {page}", "Xero Sync")
            
            params = {"page": page}
            if bank_account_id:
                params["bankAccountID"] = bank_account_id
                
            response = xero_request("GET", "BankTransactions", params=params)

            if not response or not response.get("BankTransactions"):
                break

            transactions = response["BankTransactions"]
            if not transactions:
                break

            for transaction_data in transactions:
                try:
                    process_xero_bank_transaction(transaction_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Bank Transaction ID {transaction_data.get('BankTransactionID')}",
                        xero_entity_id=transaction_data.get('BankTransactionID'),
                        xero_entity_type="BankTransaction",
                        error_details=frappe.get_traceback()
                    )

            # Check if it was the last page
            if len(transactions) < 100:
                break
            page += 1

        log_xero_error(message="Finished syncing bank transactions from Xero.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_bank_transactions_from_xero",
            error_details=frappe.get_traceback()
        )


def process_xero_bank_transaction(xero_transaction_data, settings):
    """Creates or updates an ERPNext Bank Transaction from Xero transaction data."""
    xero_transaction_id = xero_transaction_data.get("BankTransactionID")
    
    if not xero_transaction_id:
        log_xero_error(message=f"Skipping Xero bank transaction due to missing ID: {xero_transaction_data}", status="Info")
        return

    # Check if ERPNext bank transaction already exists
    erpnext_doc_name = frappe.db.get_value("Bank Transaction", {"xero_bank_transaction_id": xero_transaction_id}, "name")

    # Get bank account information
    xero_bank_account_id = xero_transaction_data.get("BankAccount", {}).get("AccountID")
    if not xero_bank_account_id:
        log_xero_error(message=f"Skipping Xero bank transaction {xero_transaction_id}: No bank account information", status="Info")
        return

    # Find corresponding ERPNext bank account
    bank_account = frappe.db.get_value("Account", {"xero_account_id": xero_bank_account_id}, "name")
    if not bank_account:
        log_xero_error(message=f"Skipping Xero bank transaction {xero_transaction_id}: Bank account not found for Xero Account {xero_bank_account_id}", status="Info")
        return

    # Get contact information
    xero_contact_id = xero_transaction_data.get("Contact", {}).get("ContactID")
    party = None
    party_type = None
    
    if xero_contact_id:
        # Try to find customer first, then supplier
        party = frappe.db.get_value("Customer", {"xero_contact_id": xero_contact_id}, "name")
        if party:
            party_type = "Customer"
        else:
            party = frappe.db.get_value("Supplier", {"xero_contact_id": xero_contact_id}, "name")
            if party:
                party_type = "Supplier"

    try:
        # Calculate amounts
        transaction_type = xero_transaction_data.get("Type")
        total_amount = flt(xero_transaction_data.get("Total", 0))
        
        withdrawal = total_amount if transaction_type == "SPEND" else 0
        deposit = total_amount if transaction_type == "RECEIVE" else 0

        # Map Xero Data to ERPNext Fields
        erpnext_data = {
            "date": getdate(xero_transaction_data.get("Date")),
            "account": bank_account,
            "party_type": party_type,
            "party": party,
            "withdrawal": withdrawal,
            "deposit": deposit,
            "description": xero_transaction_data.get("Reference") or "Bank Transaction from Xero",
            "reference_number": xero_transaction_data.get("Reference"),
            "xero_bank_transaction_id": xero_transaction_id,
            "xero_sync_status": "Synced",
        }

        # Set clearance date if reconciled
        if xero_transaction_data.get("IsReconciled"):
            erpnext_data["clearance_date"] = erpnext_data["date"]

        if erpnext_doc_name:
            # Update existing transaction
            doc = frappe.get_doc("Bank Transaction", erpnext_doc_name)
            doc.update(erpnext_data)
            doc.save(ignore_permissions=True)
            log_message = f"Updated Bank Transaction {erpnext_doc_name} from Xero Transaction {xero_transaction_id}"
        else:
            # Create new transaction
            doc = frappe.new_doc("Bank Transaction")
            doc.update(erpnext_data)
            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created Bank Transaction {erpnext_doc_name} from Xero Transaction {xero_transaction_id}"

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type="Bank Transaction",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_transaction_id,
            xero_entity_type="BankTransaction",
            direction="Xero to ERPNext"
        )

    except Exception as e:
        sync_status = "Error"
        if erpnext_doc_name:
            frappe.db.set_value("Bank Transaction", erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
            frappe.db.commit()

        log_xero_error(
            message=f"Failed to sync Xero Bank Transaction {xero_transaction_id} to ERPNext",
            erpnext_doc_type="Bank Transaction",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_transaction_id,
            xero_entity_type="BankTransaction",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )


@frappe.whitelist()
def reconcile_bank_transactions(bank_account, from_date=None, to_date=None):
    """
    Reconcile bank transactions between ERPNext and Xero for a specific bank account.
    
    Args:
        bank_account: ERPNext bank account name
        from_date: Start date for reconciliation
        to_date: End date for reconciliation
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw("Xero sync is not enabled.")

    try:
        # Get Xero account ID for the bank account
        xero_account_id = frappe.db.get_value("Account", bank_account, "xero_account_id")
        if not xero_account_id:
            frappe.throw(f"Xero Account ID not found for bank account {bank_account}")

        # Sync bank transactions from Xero for this account
        sync_bank_transactions_from_xero(xero_account_id)

        # Get ERPNext bank transactions for comparison
        filters = {
            "account": bank_account,
            "docstatus": 1
        }
        
        if from_date:
            filters["date"] = [">=", from_date]
        if to_date:
            if "date" in filters:
                filters["date"] = ["between", [from_date, to_date]]
            else:
                filters["date"] = ["<=", to_date]

        erpnext_transactions = frappe.get_all(
            "Bank Transaction",
            filters=filters,
            fields=["name", "date", "withdrawal", "deposit", "reference_number", "xero_bank_transaction_id"]
        )

        # Create reconciliation report
        reconciliation_data = {
            "bank_account": bank_account,
            "from_date": from_date,
            "to_date": to_date,
            "total_erpnext_transactions": len(erpnext_transactions),
            "synced_transactions": len([t for t in erpnext_transactions if t.xero_bank_transaction_id]),
            "unsynced_transactions": len([t for t in erpnext_transactions if not t.xero_bank_transaction_id]),
        }

        frappe.msgprint(f"Bank reconciliation completed for {bank_account}. {reconciliation_data['synced_transactions']} transactions synced, {reconciliation_data['unsynced_transactions']} unsynced.")
        
        return reconciliation_data

    except Exception as e:
        log_xero_error(
            message=f"Error during bank reconciliation for account {bank_account}",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Bank reconciliation failed: {str(e)}")