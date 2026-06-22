# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from .xero_invoices import parse_xero_date

# --- Bank Transaction Sync (ERPNext to Xero) — DISABLED BY DESIGN ---
#
# In ERPNext a Bank Transaction is a bank-statement / reconciliation artifact:
# it only acquires a counterparty and a contra (GL) account through the voucher
# it is reconciled against (a Payment Entry or Journal Entry, via the
# `payment_entries` child table). Those vouchers already sync to Xero —
# Payment Entry -> Xero Payment and Journal Entry -> Xero Manual Journal — and
# each already moves the Xero bank balance. Pushing the Bank Transaction as an
# additional Xero spend/receive would DOUBLE-COUNT every bank movement, so
# outbound Bank Transaction sync is intentionally disabled. Inbound sync
# (Xero -> ERPNext, below) is unaffected.


def enqueue_sync_bank_transaction(doc, method=None):
    """No-op: outbound Bank Transaction sync is disabled by design.

    Retained as a safe stub so legacy queued jobs (or any remaining reference)
    cannot raise. See the module note above.
    """
    return


def sync_bank_transaction_to_xero(doc_name=None, doc_type="Bank Transaction", **kwargs):
    """No-op: outbound Bank Transaction sync is disabled by design.

    Bank movements are represented in Xero via Payment Entry (-> Payment) and
    Journal Entry (-> Manual Journal) sync; syncing Bank Transactions as well
    would double-count. See the module note above.
    """
    log_xero_error(
        message=(
            f"Outbound Bank Transaction sync is disabled by design; skipping "
            f"{doc_type} {doc_name}. Bank movements sync via Payment Entry and "
            f"Journal Entry."
        ),
        status="Info",
        erpnext_doc_type=doc_type,
        erpnext_doc_name=doc_name,
        category="System Monitoring",
    )
    return


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

    # Resolve the ERPNext **Bank Account** that mirrors this Xero bank account.
    # The Xero AccountID is stored on the GL Account (Account.xero_account_id),
    # but Bank Transaction.bank_account links to the Bank Account doctype — so
    # map GL Account -> Bank Account.
    gl_account = frappe.db.get_value("Account", {"xero_account_id": xero_bank_account_id}, "name")
    if not gl_account:
        log_xero_error(message=f"Skipping Xero bank transaction {xero_transaction_id}: no ERPNext GL account linked to Xero Account {xero_bank_account_id}. Sync Chart of Accounts / link the bank account first.", status="Info")
        return
    bank_account = frappe.db.get_value("Bank Account", {"account": gl_account}, "name")
    if not bank_account:
        log_xero_error(message=f"Skipping Xero bank transaction {xero_transaction_id}: no ERPNext Bank Account is linked to GL account '{gl_account}'. Create one to mirror Xero bank transactions.", status="Info")
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
            # Xero serialises dates as /Date(ms+offset)/ — use the shared parser,
            # NOT getdate() (which raises on that format).
            "date": parse_xero_date(xero_transaction_data.get("Date")),
            # Bank Transaction's bank link field is `bank_account` (Link to Bank
            # Account), NOT `account` — the latter is not a field on the doctype.
            "bank_account": bank_account,
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
        from ..utils.logging import is_already_exists_error
        error_traceback = frappe.get_traceback()
        
        if is_already_exists_error(str(e), error_traceback):
            if erpnext_doc_name:
                frappe.db.set_value("Bank Transaction", erpnext_doc_name, "xero_sync_status", "Synced", update_modified=False)
                frappe.db.commit()
            
            log_xero_error(
                message=f"Xero Bank Transaction {xero_transaction_id} already exists in ERPNext as {erpnext_doc_name or 'existing document'}. Skipping update.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type="Bank Transaction",
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_transaction_id,
                xero_entity_type="BankTransaction",
                direction="Xero to ERPNext"
            )
        else:
            from ..utils.logging import format_sync_error_message
            sync_status = "Error"
            if erpnext_doc_name:
                frappe.db.set_value("Bank Transaction", erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
                frappe.db.commit()

            user_message = format_sync_error_message(
                "Xero Bank Transaction", xero_transaction_id, xero_transaction_id, "Xero to ERPNext", e
            )

            log_xero_error(
                message=user_message,
                erpnext_doc_type="Bank Transaction",
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_transaction_id,
                xero_entity_type="BankTransaction",
                direction="Xero to ERPNext",
                error_details=error_traceback
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

        # Get ERPNext Bank Transactions for comparison. `bank_account` here is a
        # GL Account name; Bank Transaction links to the Bank Account doctype, so
        # translate GL Account -> Bank Account(s) before filtering.
        bank_accounts = frappe.get_all("Bank Account", filters={"account": bank_account}, pluck="name")
        filters = {
            "bank_account": ["in", bank_accounts or [None]],
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