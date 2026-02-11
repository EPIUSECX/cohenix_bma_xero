# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, add_days, add_to_date
from .utils.xero_client import get_xero_settings
from .utils.logging import log_xero_error

def sync_all_enabled():
    """
    Daily task to sync all enabled entities from Xero to ERPNext.
    This runs based on the settings in Xero Settings doctype.
    """
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync:
        return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping daily sync task.",
            status="Info",
            category="System Monitoring"
        )
        return

    try:
        # Sync contacts if enabled
        if settings.get("sync_contacts"):
            from .api.xero_contacts import sync_contacts_from_xero
            sync_contacts_from_xero()

        # Sync chart of accounts if enabled
        if settings.get("sync_chart_of_accounts"):
            from .api.xero_accounts import sync_accounts_from_xero
            sync_accounts_from_xero()

        # Sync items if enabled
        if settings.get("sync_items"):
            from .api.xero_items import sync_items_from_xero
            sync_items_from_xero()

        # Sync bank transactions if enabled
        if settings.get("sync_bank_transactions"):
            from .api.xero_bank_transactions import sync_bank_transactions_from_xero
            sync_bank_transactions_from_xero()

        # Sync quotations if enabled
        if settings.get("sync_quotes"):
            from .api.xero_quotes import sync_quotes_from_xero
            sync_quotes_from_xero()

        # Sync manual journals if enabled
        if settings.get("sync_journal_entries"):
            from .api.xero_journals import sync_manual_journals_from_xero
            sync_manual_journals_from_xero()

        # Sync financial reports if enabled
        if settings.get("sync_financial_reports"):
            from .api.xero_reports import sync_trial_balance_from_xero, sync_profit_loss_from_xero, sync_balance_sheet_from_xero
            sync_trial_balance_from_xero()
            sync_profit_loss_from_xero()
            sync_balance_sheet_from_xero()

        log_xero_error(message="Daily sync task completed successfully.", status="Success")

    except Exception as e:
        log_xero_error(
            message="Error during daily sync task",
            error_details=frappe.get_traceback()
        )


def check_payments():
    """
    Hourly task to check for new payments in Xero and sync them to ERPNext.
    """
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync or not settings.get("sync_payments"):
        return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        return

    try:
        from .api.xero_payments import sync_payments_from_xero
        from .api.xero_invoices import check_invoice_payments
        
        # Sync payments from the last 24 hours
        from_date = add_days(now_datetime(), -1)
        sync_payments_from_xero()
        
        # Check for payment updates on existing invoices
        check_invoice_payments()

        log_xero_error(message="Hourly payment check completed successfully.", status="Success")

    except Exception as e:
        log_xero_error(
            message="Error during hourly payment check",
            error_details=frappe.get_traceback()
        )


def reconcile_all_entities():
    """
    Weekly task to perform comprehensive reconciliation between ERPNext and Xero.
    """
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync:
        return
    
    # Reconciliation requires both sync directions to be enabled
    if not settings.enable_sync_to_xero or not settings.enable_sync_from_xero:
        log_xero_error(
            message="Reconciliation requires both sync directions to be enabled. Skipping.",
            status="Warning",
            category="System Monitoring"
        )
        return

    try:
        # Reconcile payments
        if settings.get("sync_payments"):
            from .api.xero_payments import reconcile_payments
            reconcile_payments()

        # Reconcile bank transactions
        if settings.get("sync_bank_transactions"):
            from .api.xero_bank_transactions import reconcile_bank_transactions
            # Get all bank accounts with Xero integration
            bank_accounts = frappe.get_all("Account", 
                filters={"account_type": "Bank", "xero_account_id": ["!=", ""]},
                fields=["name"]
            )
            for account in bank_accounts:
                reconcile_bank_transactions(account.name)

        # Reconcile manual journals
        if settings.get("sync_journal_entries"):
            from .api.xero_journals import reconcile_manual_journals
            reconcile_manual_journals()

        log_xero_error(message="Weekly reconciliation completed successfully.", status="Success")

    except Exception as e:
        log_xero_error(
            message="Error during weekly reconciliation",
            error_details=frappe.get_traceback()
        )


def cleanup_old_logs():
    """
    Weekly task to clean up old Xero Log entries.
    Keeps logs for the last 90 days by default.
    """
    try:
        settings = get_xero_settings()
        retention_days = settings.get("log_retention_days", 90) if settings else 90
        
        cutoff_date = add_days(now_datetime(), -retention_days)
        
        # Delete old log entries
        frappe.db.sql("""
            DELETE FROM `tabXero Log`
            WHERE creation < %s
        """, (cutoff_date,))
        
        frappe.db.commit()
        
        log_xero_error(
            message=f"Cleaned up Xero logs older than {retention_days} days.",
            status="Success"
        )

    except Exception as e:
        log_xero_error(
            message="Error during log cleanup",
            error_details=frappe.get_traceback()
        )


def monitor_sync_health():
    """
    Hourly task to monitor sync health and send alerts if needed.
    """
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync:
        return

    try:
        # Check for failed syncs in the last hour
        one_hour_ago = add_to_date(now_datetime(), hours=-1)
        
        failed_syncs = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabXero Log`
            WHERE status = 'Error'
            AND creation >= %s
        """, (one_hour_ago,), as_dict=True)

        if failed_syncs and failed_syncs[0].count > 10:  # Alert if more than 10 failures in an hour
            # Send notification to system managers
            system_managers = frappe.get_all("User", 
                filters={"role_profile_name": "System Manager", "enabled": 1},
                fields=["email"]
            )
            
            if system_managers:
                frappe.sendmail(
                    recipients=[user.email for user in system_managers],
                    subject="Xero Integration: High Error Rate Detected",
                    message=f"There have been {failed_syncs[0].count} Xero sync errors in the last hour. Please check the Xero Log for details."
                )

        log_xero_error(message="Sync health monitoring completed.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync health monitoring",
            error_details=frappe.get_traceback()
        )


def sync_pending_documents():
    """
    Hourly task to sync documents that are pending sync to Xero.
    """
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync:
        return
    
    # Check directional toggle for outbound sync
    if not settings.enable_sync_to_xero:
        log_xero_error(
            message="Sync to Xero is disabled. Skipping pending documents sync.",
            status="Info",
            category="System Monitoring"
        )
        return

    try:
        # Sync pending invoices
        if settings.get("sync_invoices"):
            pending_sales_invoices = frappe.get_all("Sales Invoice", 
                filters={"docstatus": 1, "xero_sync_status": ["in", ["Pending", "Error"]]},
                fields=["name"]
            )
            
            for invoice in pending_sales_invoices:
                frappe.enqueue(
                    "xero.api.xero_invoices.sync_invoice_to_xero",
                    queue="short",
                    doc_name=invoice.name,
                    doc_type="Sales Invoice"
                )

            pending_purchase_invoices = frappe.get_all("Purchase Invoice", 
                filters={"docstatus": 1, "xero_sync_status": ["in", ["Pending", "Error"]]},
                fields=["name"]
            )
            
            for invoice in pending_purchase_invoices:
                frappe.enqueue(
                    "xero.api.xero_invoices.sync_invoice_to_xero",
                    queue="short",
                    doc_name=invoice.name,
                    doc_type="Purchase Invoice"
                )

        # Sync pending payments
        if settings.get("sync_payments"):
            pending_payments = frappe.get_all("Payment Entry", 
                filters={"docstatus": 1, "xero_sync_status": ["in", ["Pending", "Error"]]},
                fields=["name"]
            )
            
            for payment in pending_payments:
                frappe.enqueue(
                    "xero.api.xero_payments.sync_payment_to_xero",
                    queue="short",
                    doc_name=payment.name,
                    doc_type="Payment Entry"
                )

        # Sync pending journal entries
        if settings.get("sync_journal_entries"):
            pending_journals = frappe.get_all("Journal Entry", 
                filters={"docstatus": 1, "xero_sync_status": ["in", ["Pending", "Error"]]},
                fields=["name"]
            )
            
            for journal in pending_journals:
                frappe.enqueue(
                    "xero.api.xero_journals.sync_journal_to_xero",
                    queue="short",
                    doc_name=journal.name,
                    doc_type="Journal Entry"
                )

        log_xero_error(message="Pending documents sync task completed.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during pending documents sync",
            error_details=frappe.get_traceback()
        )


def validate_sync_integrity():
    """
    Daily task to validate sync integrity and identify discrepancies.
    """
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync:
        return

    try:
        discrepancies = []

        # Check for documents with Xero IDs but no sync status
        orphaned_invoices = frappe.db.sql("""
            SELECT name, doctype
            FROM (
                SELECT name, 'Sales Invoice' as doctype, xero_invoice_id, xero_sync_status
                FROM `tabSales Invoice`
                WHERE xero_invoice_id IS NOT NULL AND xero_invoice_id != ''
                UNION ALL
                SELECT name, 'Purchase Invoice' as doctype, xero_invoice_id, xero_sync_status
                FROM `tabPurchase Invoice`
                WHERE xero_invoice_id IS NOT NULL AND xero_invoice_id != ''
            ) as combined
            WHERE xero_sync_status IS NULL OR xero_sync_status = ''
        """, as_dict=True)

        if orphaned_invoices:
            discrepancies.append(f"Found {len(orphaned_invoices)} invoices with Xero IDs but no sync status")

        # Check for documents marked as synced but missing Xero IDs
        missing_ids = frappe.db.sql("""
            SELECT name, doctype
            FROM (
                SELECT name, 'Sales Invoice' as doctype, xero_invoice_id, xero_sync_status
                FROM `tabSales Invoice`
                WHERE xero_sync_status = 'Synced'
                UNION ALL
                SELECT name, 'Purchase Invoice' as doctype, xero_invoice_id, xero_sync_status
                FROM `tabPurchase Invoice`
                WHERE xero_sync_status = 'Synced'
            ) as combined
            WHERE xero_invoice_id IS NULL OR xero_invoice_id = ''
        """, as_dict=True)

        if missing_ids:
            discrepancies.append(f"Found {len(missing_ids)} documents marked as synced but missing Xero IDs")

        if discrepancies:
            log_xero_error(
                message=f"Sync integrity issues found: {'; '.join(discrepancies)}",
                status="Warning"
            )
        else:
            log_xero_error(message="Sync integrity validation completed - no issues found.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync integrity validation",
            error_details=frappe.get_traceback()
        )
