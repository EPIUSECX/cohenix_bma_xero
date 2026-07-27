# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, add_days, add_to_date
from .utils.xero_client import get_xero_settings
from .utils.logging import log_xero_error


def sync_all_enabled():
    """
    Daily task to sync all enabled entities from Xero to ERPNext: contacts,
    items, invoices/bills, credit notes, chart of accounts, manual journals,
    purchase orders, quotes and financial reports.
    Each entity respects its own per-entity inbound toggle.
    """
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync:
        return

    # Account mapping safety gate: warn when auto-mapping is configured but incomplete.
    # This does not block the sync — accounts may still map via line-item lookup —
    # but an incomplete mapping means GL postings may land in the wrong account.
    setup_mode = settings.get("setup_mode") or "Manual"
    mapping_status = settings.get("mapping_status") or "Not Started"
    if setup_mode != "Manual" and mapping_status not in ("Complete",):
        log_xero_error(
            message=(
                f"Account Mapping Setup is '{setup_mode}' but mapping_status is '{mapping_status}'. "
                "Transactions may post to incorrect GL accounts until mapping is complete. "
                "Open Xero Settings → Account Mapping Setup and run Analyse / Apply."
            ),
            status="Warning",
            category="Account Mapping",
        )

    # No blanket directional gate — each entity checks its own flag

    try:
        # Sync contacts from Xero if per-entity inbound toggle is ON
        if settings.get("sync_contacts_from_xero"):
            from .api.xero_contacts import sync_contacts_from_xero

            sync_contacts_from_xero()

        # Sync items from Xero if per-entity inbound toggle is ON
        # Items before invoices: inbound invoice creation calls get_or_create_item_from_xero_code,
        # which works better when the item already exists locally.
        if settings.get("sync_items_from_xero"):
            from .api.xero_items import sync_items_from_xero

            sync_items_from_xero()

        # Sync Sales Invoices from Xero if per-entity inbound toggle is ON
        if settings.get("sync_invoices_from_xero") or settings.get(
            "sync_bills_from_xero"
        ):
            from .api.xero_invoices import sync_invoices_from_xero

            # Split into separate calls so each type respects its own toggle
            # (process_xero_invoice applies per-type gate on each record)
            if settings.get("sync_invoices_from_xero"):
                sync_invoices_from_xero(invoice_type="ACCREC")

            # Sync Bills (Purchase Invoices) from Xero
            if settings.get("sync_bills_from_xero"):
                sync_invoices_from_xero(invoice_type="ACCPAY")

        # Sync credit notes from Xero if per-entity inbound toggle is ON
        if settings.get("sync_credit_notes_from_xero"):
            from .api.xero_credit_notes import sync_credit_notes_from_xero

            sync_credit_notes_from_xero()

        # Extended inbound entities (enabled per client via settings).
        # Each function also re-checks enable_sync_from_xero + its own toggle.
        if settings.get("sync_chart_of_accounts"):
            from .api.xero_accounts import sync_accounts_from_xero
            sync_accounts_from_xero()

        # Manual Journals -> Journal Entries (inbound)
        if settings.get("sync_journal_entries"):
            from .api.xero_journals import sync_manual_journals_from_xero
            sync_manual_journals_from_xero()

        # Purchase Orders (inbound)
        if settings.get("sync_purchase_orders"):
            from .api.xero_purchase_orders import sync_purchase_orders_from_xero
            sync_purchase_orders_from_xero()

        # Quotes -> Quotations (inbound)
        if settings.get("sync_quotes"):
            from .api.xero_quotes import sync_quotes_from_xero
            sync_quotes_from_xero()

        if settings.get("sync_financial_reports"):
            from .api.xero_reports import sync_financial_reports_from_xero
            try:
                sync_financial_reports_from_xero()
            except AttributeError:
                pass  # Function may not exist in all versions

        log_xero_error(
            message="Daily sync task completed successfully.", status="Success"
        )

    except Exception as e:
        log_xero_error(
            message="Error during daily sync task",
            error_details=frappe.get_traceback(),
        )


def check_payments():
    """
    Hourly task to check for new payments in Xero and sync them to ERPNext.

    Uses sync_payments_from_xero (the /Payments endpoint) as the single
    pathway for Payment Entry creation — check_invoice_payments must not be
    called here as well, or the two pathways race and duplicate PEs.
    """
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync:
        return

    # Only run if payment inbound sync is enabled
    if not settings.get("sync_payments_from_xero"):
        return

    try:
        from .api.xero_payments import sync_payments_from_xero

        # Single canonical pathway for payment detection
        sync_payments_from_xero()

        log_xero_error(
            message="Hourly payment check completed successfully.", status="Success"
        )

    except Exception as e:
        log_xero_error(
            message="Error during hourly payment check",
            error_details=frappe.get_traceback(),
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
            category="System Monitoring",
        )
        return

    try:
        # Reconcile payments
        if settings.get("sync_payments"):
            from .api.xero_payments import reconcile_payments

            reconcile_payments()

        log_xero_error(
            message="Weekly reconciliation completed successfully.", status="Success"
        )

    except Exception as e:
        log_xero_error(
            message="Error during weekly reconciliation",
            error_details=frappe.get_traceback(),
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
        frappe.db.sql(
            """
            DELETE FROM `tabXero Log`
            WHERE creation < %s
        """,
            (cutoff_date,),
        )

        log_xero_error(
            message=f"Cleaned up Xero logs older than {retention_days} days.",
            status="Success",
        )

    except Exception as e:
        log_xero_error(
            message="Error during log cleanup",
            error_details=frappe.get_traceback(),
        )


@frappe.whitelist()
def purge_resolved_logs():
    """Delete Error/Warning Xero Log rows that have since been RESOLVED — i.e. a
    later Success exists for the same entity (erpnext_doc_type + erpnext_doc_name).

    Keeps the Success/Info history and any still-outstanding errors. Complements
    the time-based cleanup_old_logs. Idempotent and safe to run repeatedly or on
    a schedule. Returns the number of rows removed.
    """
    try:
        before = frappe.db.count("Xero Log")
        # Multi-table DELETE with a materialised "latest success per entity"
        # derived table (avoids the self-referencing-subquery restriction).
        frappe.db.sql(
            """
            DELETE l FROM `tabXero Log` l
            JOIN (
                SELECT erpnext_doc_type, erpnext_doc_name, MAX(timestamp) AS last_success
                FROM `tabXero Log`
                WHERE status = 'Success'
                  AND erpnext_doc_type IS NOT NULL
                  AND erpnext_doc_name IS NOT NULL AND erpnext_doc_name <> 'Unknown'
                GROUP BY erpnext_doc_type, erpnext_doc_name
            ) ls ON ls.erpnext_doc_type = l.erpnext_doc_type
                 AND ls.erpnext_doc_name = l.erpnext_doc_name
            WHERE l.status IN ('Error', 'Warning')
              AND l.timestamp < ls.last_success
            """
        )
        after = frappe.db.count("Xero Log")
        removed = before - after
        log_xero_error(
            message=f"Purged {removed} resolved (superseded) Xero Log error/warning row(s); {after} remain.",
            status="Info",
            category="System Monitoring",
        )
        return {"removed": removed, "remaining": after}
    except Exception:
        log_xero_error(
            message="Error during purge_resolved_logs",
            error_details=frappe.get_traceback(),
        )
        return {"error": True}


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

        failed_syncs = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabXero Log`
            WHERE status = 'Error'
            AND creation >= %s
        """,
            (one_hour_ago,),
            as_dict=True,
        )

        if (
            failed_syncs and failed_syncs[0].count > 10
        ):  # Alert if more than 10 failures in an hour
            from .utils.xero_client import get_system_manager_emails
            recipients = get_system_manager_emails()

            if recipients:
                frappe.sendmail(
                    recipients=recipients,
                    subject="Xero Integration: High Error Rate Detected",
                    message=f"There have been {failed_syncs[0].count} Xero sync errors in the last hour. Please check the Xero Log for details.",
                )

        log_xero_error(message="Sync health monitoring completed.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync health monitoring",
            error_details=frappe.get_traceback(),
        )


def sync_pending_documents():
    """
    Hourly task to re-queue outbound documents stuck in Pending or Error.
    Terminal statuses (Failed, Skipped) are never retried.
    """
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync:
        return

    try:
        # Sync pending Customers and Suppliers (outbound)
        if settings.get("sync_contacts_to_xero"):
            for party_type in ("Customer", "Supplier"):
                pending_parties = frappe.get_all(
                    party_type,
                    filters={"xero_sync_status": ["in", ["Pending", "Error"]]},
                    fields=["name"],
                )
                for party in pending_parties:
                    frappe.enqueue(
                        "xero.api.xero_contacts.sync_contact_to_xero",
                        queue="short",
                        doc_name=party.name,
                        doc_type=party_type,
                    )

        # Sync pending Accounts (outbound)
        if settings.get("enable_sync_to_xero"):
            pending_accounts = frappe.get_all(
                "Account",
                filters={
                    "is_group": 0,
                    "disabled": 0,
                    "xero_sync_status": ["in", ["Pending", "Error"]],
                },
                fields=["name"],
            )
            for account in pending_accounts:
                frappe.enqueue(
                    "xero.api.xero_accounts.sync_account_to_xero",
                    queue="short",
                    account_name=account.name,
                )

        # Sync pending Sales Invoices (outbound)
        if settings.get("sync_invoices_to_xero"):
            pending_sales_invoices = frappe.get_all(
                "Sales Invoice",
                filters={
                    "docstatus": 1,
                    "xero_sync_status": ["in", ["Pending", "Error"]],
                },
                fields=["name"],
            )

            for invoice in pending_sales_invoices:
                frappe.enqueue(
                    "xero.api.xero_invoices.sync_invoice_to_xero",
                    queue="short",
                    doc_name=invoice.name,
                    doc_type="Sales Invoice",
                )

        # Sync pending Purchase Invoices / Bills (outbound) — gated on its own toggle
        if settings.get("sync_bills_to_xero"):
            pending_purchase_invoices = frappe.get_all(
                "Purchase Invoice",
                filters={
                    "docstatus": 1,
                    "xero_sync_status": ["in", ["Pending", "Error"]],
                },
                fields=["name"],
            )

            for invoice in pending_purchase_invoices:
                frappe.enqueue(
                    "xero.api.xero_invoices.sync_invoice_to_xero",
                    queue="short",
                    doc_name=invoice.name,
                    doc_type="Purchase Invoice",
                )

        # Sync pending Items (outbound)
        if settings.get("sync_items_to_xero"):
            pending_items = frappe.get_all(
                "Item",
                filters={
                    "xero_sync_status": ["in", ["Pending", "Error"]],
                },
                fields=["name"],
            )

            for item in pending_items:
                frappe.enqueue(
                    "xero.api.xero_items.sync_item_to_xero",
                    queue="short",
                    item_code=item.name,
                )

        # Sync pending Payments (outbound)
        if settings.get("sync_payments_to_xero"):
            pending_payments = frappe.get_all(
                "Payment Entry",
                filters={
                    "docstatus": 1,
                    "xero_sync_status": ["in", ["Pending", "Error"]],
                },
                fields=["name"],
            )

            for payment in pending_payments:
                frappe.enqueue(
                    "xero.api.xero_payments.sync_payment_to_xero",
                    queue="short",
                    doc_name=payment.name,
                    doc_type="Payment Entry",
                )

        # Sync pending Journal Entries (outbound)
        if settings.get("sync_journal_entries"):
            pending_journals = frappe.get_all(
                "Journal Entry",
                filters={"docstatus": 1, "xero_sync_status": ["in", ["Pending", "Error"]]},
                fields=["name"],
            )
            for je in pending_journals:
                frappe.enqueue(
                    "xero.api.xero_journals.sync_journal_to_xero",
                    queue="short",
                    doc_name=je.name,
                    doc_type="Journal Entry",
                )

        # Bank Transactions are intentionally NOT re-queued for outbound sync —
        # outbound BT sync is disabled by design to avoid double-counting bank
        # movements that already sync via Payment Entry / Journal Entry.

        # Sync pending Purchase Orders (outbound)
        if settings.get("sync_purchase_orders"):
            pending_pos = frappe.get_all(
                "Purchase Order",
                filters={"docstatus": 1, "xero_sync_status": ["in", ["Pending", "Error"]]},
                fields=["name"],
            )
            for po in pending_pos:
                frappe.enqueue(
                    "xero.api.xero_purchase_orders.sync_purchase_order_to_xero",
                    queue="short",
                    doc_name=po.name,
                    doc_type="Purchase Order",
                )

        # Sync pending Quotations (outbound)
        if settings.get("sync_quotes"):
            pending_quotes = frappe.get_all(
                "Quotation",
                filters={"docstatus": 1, "xero_sync_status": ["in", ["Pending", "Error"]]},
                fields=["name"],
            )
            for quote in pending_quotes:
                frappe.enqueue(
                    "xero.api.xero_quotes.sync_quotation_to_xero",
                    queue="short",
                    doc_name=quote.name,
                    doc_type="Quotation",
                )

        log_xero_error(message="Pending documents sync task completed.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during pending documents sync",
            error_details=frappe.get_traceback(),
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
        orphaned_invoices = frappe.db.sql(
            """
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
        """,
            as_dict=True,
        )

        if orphaned_invoices:
            discrepancies.append(
                f"Found {len(orphaned_invoices)} invoices with Xero IDs but no sync status"
            )

        # Check for documents marked as synced but missing Xero IDs
        missing_ids = frappe.db.sql(
            """
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
        """,
            as_dict=True,
        )

        if missing_ids:
            discrepancies.append(
                f"Found {len(missing_ids)} documents marked as synced but missing Xero IDs"
            )

        if discrepancies:
            log_xero_error(
                message=f"Sync integrity issues found: {'; '.join(discrepancies)}",
                status="Warning",
            )
        else:
            log_xero_error(
                message="Sync integrity validation completed - no issues found.",
                status="Info",
            )

    except Exception as e:
        log_xero_error(
            message="Error during sync integrity validation",
            error_details=frappe.get_traceback(),
        )


def sync_contact_notes():
    """Scheduled (hourly): pull Xero contact History & Notes onto the linked
    ERPNext Customers/Suppliers as timeline Comments. Throttled — processes a
    rolling batch per run via a cache cursor. Opt-in via the sync_contact_notes
    setting."""
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync:
        return
    if not settings.get("enable_sync_from_xero") or not settings.get("sync_contact_notes"):
        return
    try:
        from .api.xero_contacts import sync_contact_notes_from_xero

        # Rate-limit safe: marker-driven (only new/stale contacts) + paced calls.
        sync_contact_notes_from_xero(batch_size=50)
    except Exception:
        log_xero_error(
            message="Error during scheduled contact notes sync",
            error_details=frappe.get_traceback(),
        )
