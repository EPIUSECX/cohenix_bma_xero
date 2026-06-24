# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
import json
from datetime import datetime, timedelta
from frappe.utils import now_datetime, add_days, add_to_date, get_datetime, flt, cint
from frappe import _

@frappe.whitelist()
def get_dashboard_overview():
    """Get comprehensive dashboard overview with all key metrics"""
    try:
        # Get Xero connection status
        settings = frappe.get_single("Xero Settings")
        connection_status = {
            "connected": bool(settings.access_token and settings.tenant_id),
            "tenant_name": settings.tenant_name or "Not Connected",
            "last_sync": settings.last_sync_time,
            "sync_enabled": settings.enable_xero_sync,
            "sync_to_xero_enabled": settings.enable_sync_to_xero,
            "sync_from_xero_enabled": settings.enable_sync_from_xero
        }
        
        # Get sync statistics for last 24 hours
        yesterday = add_days(now_datetime(), -1)
        sync_stats = get_sync_statistics(yesterday)
        
        # Get entity sync status
        entity_status = get_entity_sync_status()
        
        # Get recent errors
        recent_errors = get_recent_errors(limit=5)
        
        # Get system health
        health_status = get_system_health()
        
        # Get active jobs
        active_jobs = get_active_sync_jobs()
        
        return {
            "connection": connection_status,
            "sync_stats": sync_stats,
            "entity_status": entity_status,
            "recent_errors": recent_errors,
            "health": health_status,
            "active_jobs": active_jobs
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Dashboard Overview Error")
        return {"error": str(e)}

@frappe.whitelist()
def get_sync_statistics(from_date=None, to_date=None):
    """Get detailed sync statistics for a date range"""
    if not from_date:
        from_date = add_days(now_datetime(), -7)
    if not to_date:
        to_date = now_datetime()
    
    # Current-state stats: dedupe to the LATEST log entry per entity document so
    # that an entity which failed once and later synced successfully counts only
    # as its current (latest) status. This makes the dashboard reflect the LIVE
    # state of the system — re-syncing a previously-failed entity moves it to
    # success and the rate climbs to 100% — instead of accumulating every
    # historical attempt forever.
    #
    # Rows with no entity document (erpnext_doc_name NULL/'Unknown' — e.g. system
    # monitoring logs) are excluded from the success-rate maths because they
    # don't represent the state of a synced record.
    overall_stats = frappe.db.sql("""
        SELECT
            SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN status = 'Error'   THEN 1 ELSE 0 END) as error_count,
            COUNT(*) as total_count,
            ROUND(
                SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END)
                / COUNT(*) * 100
            , 1) as success_rate
        FROM (
            SELECT status,
                   ROW_NUMBER() OVER (
                       PARTITION BY erpnext_doc_type, erpnext_doc_name
                       ORDER BY timestamp DESC, name DESC
                   ) AS rn
            FROM `tabXero Log`
            WHERE timestamp BETWEEN %s AND %s
              AND erpnext_doc_type IS NOT NULL
              AND erpnext_doc_name IS NOT NULL AND erpnext_doc_name != 'Unknown'
              AND status IN ('Success', 'Error')
        ) latest
        WHERE rn = 1
    """, (from_date, to_date), as_dict=True)

    # Entity-wise stats (latest attempt per entity document — current state)
    entity_stats = frappe.db.sql("""
        SELECT
            erpnext_doc_type,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status = 'Error' THEN 1 ELSE 0 END) as errors,
            ROUND(SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as success_rate
        FROM (
            SELECT erpnext_doc_type, erpnext_doc_name, status,
                   ROW_NUMBER() OVER (
                       PARTITION BY erpnext_doc_type, erpnext_doc_name
                       ORDER BY timestamp DESC, name DESC
                   ) AS rn
            FROM `tabXero Log`
            WHERE timestamp BETWEEN %s AND %s
              AND erpnext_doc_type IS NOT NULL
              AND erpnext_doc_name IS NOT NULL AND erpnext_doc_name != 'Unknown'
              -- only real sync outcomes determine current state; ignore trailing
              -- Info/Warning rows (e.g. create-once skips) that would otherwise
              -- mask an entity's last successful sync.
              AND status IN ('Success', 'Error')
        ) latest
        WHERE rn = 1
        GROUP BY erpnext_doc_type
        ORDER BY total DESC
    """, (from_date, to_date), as_dict=True)
    
    # Daily trend
    daily_trend = frappe.db.sql("""
        SELECT 
            DATE(timestamp) as date,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status = 'Error' THEN 1 ELSE 0 END) as errors
        FROM `tabXero Log`
        WHERE timestamp BETWEEN %s AND %s
        GROUP BY DATE(timestamp)
        ORDER BY date DESC
        LIMIT 30
    """, (from_date, to_date), as_dict=True)
    
    # Performance metrics
    performance = frappe.db.sql("""
        SELECT 
            AVG(TIMESTAMPDIFF(SECOND, creation, modified)) as avg_processing_time,
            COUNT(*) as total_operations,
            COUNT(DISTINCT erpnext_doc_type) as entity_types_synced
        FROM `tabXero Log`
        WHERE timestamp BETWEEN %s AND %s
        AND status = 'Success'
    """, (from_date, to_date), as_dict=True)
    
    return {
        "overall": overall_stats,
        "by_entity": entity_stats,
        "daily_trend": daily_trend,
        "performance": performance[0] if performance else {}
    }

@frappe.whitelist()
def get_entity_sync_status():
    """Get sync status for all entity types"""
    entities = [
        "Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry",
        "Customer", "Supplier", "Item", "Account", "Quotation", "Bank Transaction"
    ]
    
    TRANSACTIONAL = {"Sales Invoice", "Purchase Invoice", "Payment Entry",
                    "Journal Entry", "Quotation", "Bank Transaction"}
    MASTER_DISABLED = {"Item", "Account"}

    entity_status = []
    for entity in entities:
        # Only count relevant documents:
        #   transactional -> submitted (docstatus=1)
        #   masters with disabled flag -> not disabled
        #   other masters (Customer, Supplier) -> all records
        if entity in TRANSACTIONAL:
            total = frappe.db.sql(
                f"SELECT COUNT(*) FROM `tab{entity}` WHERE docstatus = 1"
            )[0][0]
        elif entity in MASTER_DISABLED:
            total = frappe.db.sql(
                f"SELECT COUNT(*) FROM `tab{entity}` WHERE disabled = 0"
            )[0][0]
        else:
            total = frappe.db.count(entity)

        # Get synced documents (those with Xero IDs)
        synced_field_map = {
            "Sales Invoice": "xero_invoice_id",
            "Purchase Invoice": "xero_invoice_id", 
            "Payment Entry": "xero_payment_id",
            "Journal Entry": "xero_manual_journal_id",
            "Customer": "xero_contact_id",
            "Supplier": "xero_contact_id",
            "Item": "xero_item_id",
            "Account": "xero_account_id",
            "Quotation": "xero_quote_id",
            "Bank Transaction": "xero_bank_transaction_id"
        }
        
        xero_field = synced_field_map.get(entity)
        synced = 0
        pending = 0
        errors = 0
        
        if xero_field:
            # Count synced documents -- exclude cancelled records
            synced = frappe.db.sql(f"""
                SELECT COUNT(*) FROM `tab{entity}`
                WHERE {xero_field} IS NOT NULL AND {xero_field} != ''
                AND docstatus != 2
            """)[0][0]
            
            # Count pending/error documents if sync status field exists
            sync_status_field = "xero_sync_status"
            try:
                if frappe.db.has_column(entity, sync_status_field):
                    pending = frappe.db.sql(f"""
                        SELECT COUNT(*) FROM `tab{entity}`
                        WHERE {sync_status_field} = 'Pending'
                        AND docstatus != 2
                    """)[0][0]

                    errors = frappe.db.sql(f"""
                        SELECT COUNT(*) FROM `tab{entity}`
                        WHERE {sync_status_field} = 'Error'
                        AND docstatus != 2
                    """)[0][0]
            except Exception:
                # Table doesn't exist or column missing, skip
                pass
        
        # Get last sync time
        last_sync = frappe.db.sql("""
            SELECT MAX(timestamp) FROM `tabXero Log`
            WHERE erpnext_doc_type = %s AND status = 'Success'
        """, (entity,))
        
        entity_status.append({
            "entity": entity,
            "total": total,
            "synced": synced,
            "pending": pending,
            "errors": errors,
            "sync_rate": round((synced / total * 100) if total > 0 else 0, 1),
            "last_sync": last_sync[0][0] if last_sync and last_sync[0][0] else None
        })

    # Contact Notes coverage (Xero contact History & Notes -> ERPNext Comments).
    # This is not a synced doctype but a per-contact background mirror, tracked
    # via the xero_notes_last_sync marker on Customer/Supplier.
    try:
        if frappe.get_single("Xero Settings").get("sync_contact_notes"):
            from xero.api.xero_contacts import get_contact_notes_progress
            cn_total, cn_synced, cn_pending = get_contact_notes_progress()
            cn_last = frappe.db.sql("""
                SELECT MAX(timestamp) FROM `tabXero Log`
                WHERE status = 'Info' AND message LIKE 'Contact notes sync:%'
            """)
            entity_status.append({
                "entity": "Contact Notes",
                "total": cn_total,
                "synced": cn_synced,
                "pending": cn_pending,
                "errors": 0,
                "sync_rate": round((cn_synced / cn_total * 100) if cn_total > 0 else 0, 1),
                "last_sync": cn_last[0][0] if cn_last and cn_last[0][0] else None,
            })
    except Exception:
        pass  # Never let the optional notes metric break the dashboard

    return entity_status

@frappe.whitelist()
def get_recent_errors(limit=10):
    """Get currently-OUTSTANDING error logs (resolved errors are excluded).

    An error is "outstanding" only if the entity's latest real sync outcome
    (Success/Error) is still Error — i.e. it has not since been re-synced
    successfully. So an entity that errored and was later fixed/re-synced drops
    off automatically, instead of lingering in the panel forever. Errors with no
    entity document (e.g. connection/token failures) are shown only if recent
    (last 24h), since there is no entity state to check them against.
    """
    limit = cint(limit) or 10
    cutoff = add_days(now_datetime(), -1)
    errors = frappe.db.sql("""
        (
            SELECT name,
                   COALESCE(message, 'No message available') AS message,
                   COALESCE(erpnext_doc_type, 'Unknown') AS erpnext_doc_type,
                   COALESCE(erpnext_doc_name, 'Unknown') AS erpnext_doc_name,
                   timestamp,
                   COALESCE(error_details, '') AS error_details,
                   COALESCE(xero_entity_id, '') AS xero_entity_id,
                   COALESCE(direction, 'Unknown') AS direction
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY erpnext_doc_type, erpnext_doc_name
                           ORDER BY timestamp DESC, name DESC
                       ) AS rn
                FROM `tabXero Log`
                WHERE status IN ('Success', 'Error')
                  AND erpnext_doc_type IS NOT NULL
                  AND erpnext_doc_name IS NOT NULL AND erpnext_doc_name != 'Unknown'
            ) latest
            WHERE rn = 1 AND status = 'Error'
        )
        UNION ALL
        (
            SELECT name,
                   COALESCE(message, 'No message available') AS message,
                   'Unknown' AS erpnext_doc_type,
                   'Unknown' AS erpnext_doc_name,
                   timestamp,
                   COALESCE(error_details, '') AS error_details,
                   COALESCE(xero_entity_id, '') AS xero_entity_id,
                   COALESCE(direction, 'Unknown') AS direction
            FROM `tabXero Log`
            WHERE status = 'Error'
              AND (erpnext_doc_type IS NULL OR erpnext_doc_name IS NULL OR erpnext_doc_name = 'Unknown')
              AND timestamp >= %s
        )
        ORDER BY timestamp DESC
        LIMIT %s
    """, (cutoff, limit), as_dict=True)
    
    # Categorize errors and clean up data
    error_categories = {}
    for error in errors:
        # Clean up null values that might still appear
        error['message'] = error.get('message') or 'No message available'
        error['erpnext_doc_type'] = error.get('erpnext_doc_type') or 'Unknown'
        error['erpnext_doc_name'] = error.get('erpnext_doc_name') or 'Unknown'
        error['error_details'] = error.get('error_details') or ''
        error['xero_entity_id'] = error.get('xero_entity_id') or ''
        error['direction'] = error.get('direction') or 'Unknown'
        
        # Simple error categorization based on message content
        message = error.get('message', '').lower()
        if 'connection' in message or 'timeout' in message:
            category = 'Connection Issues'
        elif 'validation' in message or 'required' in message:
            category = 'Validation Errors'
        elif 'authentication' in message or 'token' in message:
            category = 'Authentication Issues'
        elif 'rate limit' in message or 'throttle' in message:
            category = 'Rate Limiting'
        elif 'sync health monitoring' in message:
            category = 'System Monitoring'
        else:
            category = 'Other Errors'
        
        error['category'] = category
        error_categories[category] = error_categories.get(category, 0) + 1
    
    return {
        "errors": errors,
        "categories": error_categories
    }

@frappe.whitelist()
def get_system_health():
    """Get system health indicators"""
    # Check Xero connection
    settings = frappe.get_single("Xero Settings")
    connection_healthy = bool(settings.access_token and settings.tenant_id)
    
    # Check recent sync success rate
    yesterday = add_days(now_datetime(), -1)
    recent_logs = frappe.db.sql("""
        SELECT status FROM `tabXero Log`
        WHERE timestamp >= %s
    """, (yesterday,))
    
    # Base the success rate on real sync OUTCOMES only (Success vs Error).
    # Info/Warning rows (skips, deferrals, monitoring notes) are not failures and
    # must not deflate the health score.
    outcome_logs = [log for log in recent_logs if log[0] in ('Success', 'Error')]
    total_recent = len(outcome_logs)
    success_recent = len([log for log in outcome_logs if log[0] == 'Success'])
    success_rate = (success_recent / total_recent * 100) if total_recent > 0 else 100
    
    # Check for stuck jobs (jobs older than 1 hour)
    try:
        stuck_jobs = frappe.db.sql("""
            SELECT COUNT(*) FROM `tabRQ Job`
            WHERE status IN ('started', 'queued')
            AND creation < %s
            AND job_name LIKE '%xero%'
        """, (now_datetime() - timedelta(hours=1),))[0][0]
    except Exception:
        # RQ Job table might not exist or have different structure
        stuck_jobs = 0
    
    # Check error rate trend
    error_trend = frappe.db.sql("""
        SELECT 
            DATE(timestamp) as date,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'Error' THEN 1 ELSE 0 END) as errors
        FROM `tabXero Log`
        WHERE timestamp >= %s
        GROUP BY DATE(timestamp)
        ORDER BY date DESC
        LIMIT 7
    """, (add_days(now_datetime(), -7),), as_dict=True)
    
    # Calculate health score
    health_score = 100
    if not connection_healthy:
        health_score -= 40
    if success_rate < 90:
        health_score -= 20
    if stuck_jobs > 0:
        health_score -= 15
    if len([t for t in error_trend if t.total and (t.errors or 0) / t.total * 100 > 10]) > 2:
        health_score -= 15
    
    health_status = "Excellent" if health_score >= 90 else \
                   "Good" if health_score >= 70 else \
                   "Fair" if health_score >= 50 else "Poor"
    
    return {
        "score": max(0, health_score),
        "status": health_status,
        "connection_healthy": connection_healthy,
        "success_rate": round(success_rate, 1),
        "stuck_jobs": stuck_jobs,
        "error_trend": error_trend
    }

@frappe.whitelist()
def get_active_sync_jobs():
    """Get currently active sync jobs"""
    try:
        active_jobs = frappe.db.sql("""
            SELECT
                name, job_name, status, creation, started_at,
                TIMESTAMPDIFF(SECOND, COALESCE(started_at, creation), NOW()) as duration
            FROM `tabRQ Job`
            WHERE status IN ('started', 'queued', 'deferred')
            AND job_name LIKE '%xero%'
            ORDER BY creation DESC
            LIMIT 20
        """, as_dict=True)
        return active_jobs
    except Exception:
        # RQ Job table might not exist or have different structure
        return []

@frappe.whitelist()
def trigger_manual_sync(entity_type, filters=None, sync_type="full"):
    """Trigger manual sync for specific entity type"""
    try:
        settings = frappe.get_single("Xero Settings")
        if not settings.enable_xero_sync:
            frappe.throw(_("Xero sync is disabled in settings"))
        
        if not settings.access_token:
            frappe.throw(_("Xero is not connected. Please configure Xero settings first."))
        
        # Determine sync direction and check directional toggle
        from_xero_entities = [
            "Xero Accounts",
            "Xero Contacts",
            "Xero Items",
            "Xero Invoices",
            "Xero Credit Notes",
            "Xero Payments",
            "Xero Bank Transactions",
            "Xero Quotes",
            "Xero Purchase Orders",
            "Xero Manual Journals"
        ]
        
        if entity_type in from_xero_entities:
            # Inbound sync (Xero → ERPNext)
            if not settings.enable_sync_from_xero:
                frappe.throw(_("Sync from Xero is disabled. Cannot perform inbound sync."))
        else:
            # Outbound sync (ERPNext → Xero)
            if not settings.enable_sync_to_xero:
                frappe.throw(_("Sync to Xero is disabled. Cannot perform outbound sync."))
        
        # Parse filters
        if filters and isinstance(filters, str):
            filters = json.loads(filters)
        
        # Generate a unique batch ID for this sync operation
        sync_batch_id = frappe.generate_hash(length=12)
        
        sync_functions = {
            # ERPNext to Xero syncs
            "Sales Invoice": "xero.api.xero_invoices.sync_invoices_to_xero",
            "Purchase Invoice": "xero.api.xero_invoices.sync_invoices_to_xero",
            "Payment Entry": "xero.api.xero_payments.sync_payments_to_xero",
            "Journal Entry": "xero.api.xero_journals.sync_journals_to_xero",
            "Customer": "xero.api.xero_contacts.sync_contacts_to_xero",
            "Supplier": "xero.api.xero_contacts.sync_contacts_to_xero",
            "Item": "xero.api.xero_items.sync_items_to_xero",
            "Account": "xero.api.xero_accounts.sync_accounts_to_xero",
            "Quotation": "xero.api.xero_quotes.sync_quotes_to_xero",
            "Bank Transaction": "xero.api.xero_bank_transactions.sync_bank_transactions_to_xero",
            # Xero to ERPNext syncs - These sync FROM Xero TO ERPNext DocTypes
            "Xero Accounts": "xero.api.xero_accounts.sync_accounts_from_xero",
            "Xero Contacts": "xero.api.xero_contacts.sync_contacts_from_xero",
            "Xero Items": "xero.api.xero_items.sync_items_from_xero",
            "Xero Invoices": "xero.api.xero_invoices.sync_invoices_from_xero",
            "Xero Credit Notes": "xero.api.xero_credit_notes.sync_credit_notes_from_xero",
            "Xero Payments": "xero.api.xero_payments.sync_payments_from_xero",
            "Xero Bank Transactions": "xero.api.xero_bank_transactions.sync_bank_transactions_from_xero",
            "Xero Quotes": "xero.api.xero_quotes.sync_quotes_from_xero",
            "Xero Purchase Orders": "xero.api.xero_purchase_orders.sync_purchase_orders_from_xero",
            "Xero Manual Journals": "xero.api.xero_journals.sync_manual_journals_from_xero"
        }
        
        function_path = sync_functions.get(entity_type)
        if not function_path:
            frappe.throw(_("Sync function not found for entity type: {0}").format(entity_type))
        
        # Determine direction for logging
        is_from_xero = entity_type in from_xero_entities
        direction = "Xero to ERPNext" if is_from_xero else "ERPNext to Xero"
        
        # Map entity types to the actual ERPNext DocTypes they create/sync
        target_doctype_map = {
            "Xero Accounts": "Account",
            "Xero Contacts": "Customer",
            "Xero Items": "Item",
            "Xero Invoices": "Sales Invoice",
            "Xero Credit Notes": "Sales Invoice",
            "Xero Payments": "Payment Entry",
            "Xero Bank Transactions": "Bank Transaction",
            "Xero Quotes": "Quotation",
            "Xero Purchase Orders": "Purchase Order",
            "Xero Manual Journals": "Journal Entry"
        }
        target_doctype = target_doctype_map.get(entity_type, entity_type)
        
        if is_from_xero:
            # These are Xero to ERPNext sync functions - no filters needed
            job = frappe.enqueue(
                function_path,
                queue="long",
                timeout=3600,
                job_name=f"Manual Sync: {entity_type}"
            )
        else:
            # These are ERPNext to Xero sync functions - use filters
            job = frappe.enqueue(
                function_path,
                queue="long",
                timeout=3600,
                filters=filters,
                sync_type=sync_type,
                job_name=f"Manual Sync: {entity_type}"
            )
        
        # Log the manual sync trigger with batch ID
        frappe.get_doc({
            "doctype": "Xero Log",
            "status": "Info",
            "message": f"Manual sync started: {entity_type}",
            "erpnext_doc_type": target_doctype,
            "direction": direction,
            "sync_batch_id": sync_batch_id,
            "timestamp": now_datetime()
        }).insert(ignore_permissions=True)
        
        return {
            "success": True,
            "job_id": job.id,
            "sync_batch_id": sync_batch_id,
            "message": f"Manual sync for {entity_type} has been queued successfully"
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Manual Sync Error - {entity_type}")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def bulk_retry_failed_jobs(entity_type=None, date_range=None):
    """Retry multiple failed jobs in bulk"""
    try:
        conditions = ["status = 'Error'"]
        params = []
        
        if entity_type:
            conditions.append("erpnext_doc_type = %s")
            params.append(entity_type)
        
        if date_range:
            date_range = json.loads(date_range) if isinstance(date_range, str) else date_range
            if date_range.get('from_date'):
                conditions.append("timestamp >= %s")
                params.append(date_range['from_date'])
            if date_range.get('to_date'):
                conditions.append("timestamp <= %s")
                params.append(date_range['to_date'])
        
        # Get failed logs
        failed_logs = frappe.db.sql(f"""
            SELECT name, erpnext_doc_type, erpnext_doc_name
            FROM `tabXero Log`
            WHERE {' AND '.join(conditions)}
            ORDER BY timestamp DESC
            LIMIT 100
        """, params, as_dict=True)
        
        retry_count = 0
        for log in failed_logs:
            try:
                retry_failed_job(log.name)
                retry_count += 1
            except Exception as e:
                frappe.log_error(f"Bulk retry failed for {log.name}: {str(e)}")
                continue
        
        return {
            "success": True,
            "retried_count": retry_count,
            "total_failed": len(failed_logs)
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Bulk Retry Error")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def get_sync_configuration():
    """Get current sync configuration"""
    try:
        settings = frappe.get_single("Xero Settings")
        
        # Count account and tax mappings from child DocTypes
        account_mappings = frappe.db.count("Xero Account Mapping") if frappe.db.exists("DocType", "Xero Account Mapping") else 0
        tax_mappings = frappe.db.count("Xero Tax Mapping") if frappe.db.exists("DocType", "Xero Tax Mapping") else 0
        
        # Get sync settings with safe attribute access
        config = {
            "connection": {
                "connected": bool(getattr(settings, 'access_token', None) and getattr(settings, 'tenant_id', None)),
                "tenant_name": getattr(settings, 'tenant_name', None),
                "client_id": getattr(settings, 'client_id', None)[:10] + "..." if getattr(settings, 'client_id', None) else None,
                "last_token_refresh": getattr(settings, 'last_token_refresh', None)
            },
            "sync_settings": {
                "auto_sync_enabled": getattr(settings, 'enable_xero_sync', False),
                "sync_frequency": 30,  # Default value
                "batch_size": 50,      # Default value
                "max_retries": 3       # Default value
            },
            "mappings": {
                "accounts": account_mappings,
                "taxes": tax_mappings
            }
        }
        
        return config
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Sync Configuration Error")
        return {
            "connection": {
                "connected": False,
                "tenant_name": None,
                "client_id": None,
                "last_token_refresh": None
            },
            "sync_settings": {
                "auto_sync_enabled": False,
                "sync_frequency": 30,
                "batch_size": 50,
                "max_retries": 3
            },
            "mappings": {
                "accounts": 0,
                "taxes": 0
            },
            "error": str(e)
        }

@frappe.whitelist()
def update_sync_settings(settings_data):
    """Update sync settings"""
    try:
        if isinstance(settings_data, str):
            settings_data = json.loads(settings_data)
        
        settings = frappe.get_single("Xero Settings")
        
        # Update sync settings
        for key, value in settings_data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        
        settings.save()
        
        return {
            "success": True,
            "message": "Sync settings updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Update Sync Settings Error")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def get_logs(start=0, page_length=20, filters=None):
    """Enhanced log retrieval with advanced filtering"""
    import json
    
    # Convert parameters to integers
    start = int(start) if start else 0
    page_length = int(page_length) if page_length else 20
    
    conditions = []
    params = []
    
    if filters:
        if isinstance(filters, str):
            filters = json.loads(filters)
        
        if filters.get("status"):
            conditions.append("status = %s")
            params.append(filters.get('status'))
            
        if filters.get("erpnext_doc_type"):
            conditions.append("erpnext_doc_type = %s")
            params.append(filters.get('erpnext_doc_type'))
            
        if filters.get("erpnext_doc_name"):
            conditions.append("erpnext_doc_name LIKE %s")
            params.append(f"%{filters.get('erpnext_doc_name')}%")
            
        if filters.get("message"):
            conditions.append("message LIKE %s")
            params.append(f"%{filters.get('message')}%")
            
        if filters.get("from_date"):
            conditions.append("timestamp >= %s")
            params.append(filters.get('from_date'))
            
        if filters.get("to_date"):
            conditions.append("timestamp <= %s")
            params.append(filters.get('to_date'))
    
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
    try:
        # Get total count
        count_query = f"""
            SELECT COUNT(*) FROM `tabXero Log` {where_clause}
        """
        total_count = frappe.db.sql(count_query, params)[0][0] if frappe.db.exists("DocType", "Xero Log") else 0
        
        # Get logs using LIMIT with proper integer parameters
        logs_query = f"""
            SELECT
                name, status, message, erpnext_doc_type, erpnext_doc_name,
                timestamp, error_details, xero_entity_id, direction
            FROM `tabXero Log`
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT {page_length} OFFSET {start}
        """
        
        logs = frappe.db.sql(logs_query, params, as_dict=True) if frappe.db.exists("DocType", "Xero Log") else []
        
        return {
            "logs": logs,
            "total_count": total_count,
            "has_more": (start + page_length) < total_count
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Logs Error")
        return {
            "logs": [],
            "total_count": 0,
            "has_more": False,
            "error": str(e)
        }

@frappe.whitelist()
def retry_failed_job(log_name):
    """Enhanced retry functionality with better error handling"""
    try:
        log = frappe.get_doc("Xero Log", log_name)
        
        # Check if log has enough information for retry
        doc_type = getattr(log, 'erpnext_doc_type', None)
        doc_name = getattr(log, 'erpnext_doc_name', None)
        
        if not doc_type or not doc_name or doc_type == 'Unknown' or doc_name == 'Unknown':
            # For system errors or logs without document info, we can't retry individual documents
            # Instead, we'll trigger a general sync for the most common entity types
            if 'sync health monitoring' in (log.message or '').lower():
                return {
                    "success": False,
                    "error": "System monitoring errors cannot be retried. These are automatically resolved when the underlying issue is fixed."
                }
            else:
                return {
                    "success": False,
                    "error": "Log entry does not contain enough information to retry. This may be a system-level error that cannot be retried individually."
                }

        # Check if document still exists
        if not frappe.db.exists(doc_type, doc_name):
            return {
                "success": False,
                "error": f"Document {doc_type} {doc_name} no longer exists and cannot be retried."
            }

        doc = frappe.get_doc(doc_type, doc_name)

        # Enhanced sync function mapping with fallback to manual sync
        sync_function_map = {
            "Sales Invoice": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
            "Purchase Invoice": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
            "Payment Entry": "xero.api.xero_payments.enqueue_sync_payment",
            "Journal Entry": "xero.api.xero_journals.enqueue_sync_journal",
            "Customer": "xero.api.xero_contacts.enqueue_sync_contact",
            "Supplier": "xero.api.xero_contacts.enqueue_sync_contact",
            "Item": "xero.api.xero_items.enqueue_sync_item",
            "Quotation": "xero.api.xero_quotes.enqueue_sync_quotation",
            "Bank Transaction": "xero.api.xero_bank_transactions.enqueue_sync_bank_transaction",
            "Purchase Order": "xero.api.xero_purchase_orders.enqueue_sync_purchase_order"
        }

        function_path = sync_function_map.get(doc.doctype)
        if not function_path:
            # Fallback: trigger manual sync for the entity type
            result = trigger_manual_sync(doc.doctype, filters={"name": doc.name})
            if result.get('success'):
                return {
                    "success": True,
                    "message": f"Retry queued for {doc.doctype} {doc.name} via manual sync"
                }
            else:
                return {
                    "success": False,
                    "error": f"No retry logic defined for DocType: {doc.doctype} and manual sync failed: {result.get('error', 'Unknown error')}"
                }

        try:
            # Get the function and call it
            sync_function = frappe.get_attr(function_path)
            sync_function(doc, "retry")
        except Exception as sync_error:
            # If specific sync function fails, try manual sync as fallback
            frappe.log_error(f"Specific sync function failed for {doc.doctype} {doc.name}: {str(sync_error)}")
            result = trigger_manual_sync(doc.doctype, filters={"name": doc.name})
            if not result.get('success'):
                raise sync_error

        # Update the original log to indicate retry
        try:
            log.add_comment("Comment", f"Retry initiated at {now_datetime()}")
        except Exception:
            # If comment fails, continue anyway
            pass
        
        # Create new log entry for retry
        frappe.get_doc({
            "doctype": "Xero Log",
            "status": "Info",
            "message": f"Retry initiated for {doc.doctype} {doc.name}",
            "erpnext_doc_type": doc.doctype,
            "erpnext_doc_name": doc.name,
            "timestamp": now_datetime()
        }).insert(ignore_permissions=True)

        return {
            "success": True,
            "message": f"Retry queued for {doc.doctype} {doc.name}"
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Retry Failed Job Error - {log_name}")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def get_sync_queue_status():
    """Get current sync queue status"""
    try:
        # Get queue statistics
        queue_stats = frappe.db.sql("""
            SELECT
                status,
                COUNT(*) as count,
                MIN(creation) as oldest_job,
                MAX(creation) as newest_job
            FROM `tabRQ Job`
            WHERE job_name LIKE '%xero%'
            GROUP BY status
        """, as_dict=True)
        
        # Get recent job history
        recent_jobs = frappe.db.sql("""
            SELECT
                name, job_name, status, creation, started_at, ended_at,
                TIMESTAMPDIFF(SECOND, started_at, COALESCE(ended_at, NOW())) as duration
            FROM `tabRQ Job`
            WHERE job_name LIKE '%xero%'
            ORDER BY creation DESC
            LIMIT 10
        """, as_dict=True)
        
        return {
            "queue_stats": queue_stats,
            "recent_jobs": recent_jobs
        }
    except Exception:
        # RQ Job table might not exist or have different structure
        return {
            "queue_stats": [],
            "recent_jobs": []
        }

@frappe.whitelist()
def get_queue_status():
    """Get queue status for dashboard"""
    try:
        # Check if RQ Job table exists
        if not frappe.db.exists("DocType", "RQ Job"):
            return {
                "queues": [{
                    'name': 'default',
                    'pending': 0,
                    'running': 0,
                    'failed': 0
                }]
            }
        
        # Get queue statistics with proper error handling
        try:
            queue_stats = frappe.db.sql("""
                SELECT
                    'default' as name,
                    COUNT(CASE WHEN status = 'queued' THEN 1 END) as pending,
                    COUNT(CASE WHEN status = 'started' THEN 1 END) as running,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed
                FROM `tabRQ Job`
                WHERE job_name LIKE '%xero%'
            """, as_dict=True)
        except Exception:
            # If RQ Job table doesn't exist or query fails, return default values
            queue_stats = []
        
        if not queue_stats:
            queue_stats = [{
                'name': 'default',
                'pending': 0,
                'running': 0,
                'failed': 0
            }]
        
        return {
            "queues": queue_stats
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Queue Status Error")
        return {
            "queues": [{
                'name': 'default',
                'pending': 0,
                'running': 0,
                'failed': 0
            }]
        }

@frappe.whitelist()
def bulk_retry_failed():
    """Retry all failed sync jobs"""
    try:
        # Get failed logs from last 7 days that have document information
        failed_logs = frappe.db.sql("""
            SELECT name, erpnext_doc_type, erpnext_doc_name, message
            FROM `tabXero Log`
            WHERE status = 'Error'
            AND timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            AND erpnext_doc_type IS NOT NULL
            AND erpnext_doc_name IS NOT NULL
            AND erpnext_doc_type != 'Unknown'
            AND erpnext_doc_name != 'Unknown'
            AND message NOT LIKE '%sync health monitoring%'
            ORDER BY timestamp DESC
            LIMIT 50
        """, as_dict=True)
        
        retry_count = 0
        skipped_count = 0
        
        for log in failed_logs:
            try:
                result = retry_failed_job(log.name)
                if result.get('success'):
                    retry_count += 1
                else:
                    skipped_count += 1
                    frappe.log_error(f"Bulk retry skipped for {log.name}: {result.get('error', 'Unknown error')}")
            except Exception as e:
                skipped_count += 1
                frappe.log_error(f"Bulk retry failed for {log.name}: {str(e)}")
                continue
        
        # Also get count of system errors that can't be retried
        system_errors = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabXero Log`
            WHERE status = 'Error'
            AND timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            AND (erpnext_doc_type IS NULL
                 OR erpnext_doc_name IS NULL
                 OR erpnext_doc_type = 'Unknown'
                 OR erpnext_doc_name = 'Unknown'
                 OR message LIKE '%sync health monitoring%')
        """, as_dict=True)
        
        system_error_count = system_errors[0]['count'] if system_errors else 0
        
        message = f"Queued {retry_count} jobs for retry"
        if skipped_count > 0:
            message += f", skipped {skipped_count} jobs"
        if system_error_count > 0:
            message += f", {system_error_count} system errors cannot be retried"
        
        return {
            "success": True,
            "count": retry_count,
            "skipped": skipped_count,
            "system_errors": system_error_count,
            "message": message
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Bulk Retry Error")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def sync_all_entities():
    """Trigger sync for all configured entities"""
    try:
        settings = frappe.get_single("Xero Settings")
        if not settings.enable_xero_sync:
            return {
                "success": False,
                "error": "Xero sync is disabled in settings"
            }
        
        # Check directional sync settings once to avoid redundant error messages
        sync_to_xero_enabled = settings.enable_sync_to_xero
        sync_from_xero_enabled = settings.enable_sync_from_xero
        
        # Show single notification if a direction is disabled
        if not sync_to_xero_enabled:
            frappe.msgprint(
                _("Sync to Xero (ERPNext → Xero) is disabled. Only inbound syncs will be attempted."),
                title=_("Sync Direction Disabled"),
                indicator="orange"
            )
        
        if not sync_from_xero_enabled:
            frappe.msgprint(
                _("Sync from Xero (Xero → ERPNext) is disabled. Only outbound syncs will be attempted."),
                title=_("Sync Direction Disabled"),
                indicator="orange"
            )
        
        # All entities are ERPNext → Xero (outbound) syncs
        entities = [
            "Sales Invoice", "Purchase Invoice", "Payment Entry",
            "Customer", "Supplier", "Item"
        ]
        
        job_count = 0
        skipped_count = 0
        
        for entity in entities:
            # Skip if sync to Xero is disabled (all these entities are outbound)
            if not sync_to_xero_enabled:
                skipped_count += 1
                continue
            
            try:
                result = trigger_manual_sync(entity)
                if result.get('success'):
                    job_count += 1
            except Exception as e:
                frappe.log_error(f"Failed to trigger sync for {entity}: {str(e)}")
                continue
        
        message = f"Queued {job_count} sync jobs"
        if skipped_count > 0:
            message += f" ({skipped_count} skipped due to disabled sync direction)"
        
        return {
            "success": True,
            "jobs_queued": job_count,
            "skipped_count": skipped_count,
            "message": message
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Sync All Entities Error")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def clear_old_logs(days=30):
    """Clear old log entries"""
    try:
        days = int(days)
        cutoff_date = add_days(now_datetime(), -days)
        
        # Delete old logs
        deleted_count = frappe.db.sql("""
            DELETE FROM `tabXero Log`
            WHERE timestamp < %s
        """, (cutoff_date,))
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": f"Deleted {deleted_count} old log entries"
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Clear Old Logs Error")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def get_log_details(log_name):
    """Get detailed information for a specific log entry"""
    try:
        log = frappe.get_doc("Xero Log", log_name)
        return {
            "name": log.name,
            "status": log.status,
            "message": log.message,
            "erpnext_doc_type": log.erpnext_doc_type,
            "erpnext_doc_name": log.erpnext_doc_name,
            "timestamp": log.timestamp,
            "error_details": log.error_details,
            "xero_id": getattr(log, 'xero_entity_id', None),
            "operation": getattr(log, 'direction', None),
            "retry_count": getattr(log, 'retry_count', 0),
            "processing_time": getattr(log, 'processing_time', None),
            "category": getattr(log, 'category', 'General')
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Get Log Details Error - {log_name}")
        return {
            "error": str(e)
        }

@frappe.whitelist()
def test_xero_connection():
    """Test Xero API connection"""
    try:
        from xero.utils.xero_client import XeroClient
        
        settings = frappe.get_single("Xero Settings")
        if not settings.access_token:
            return {
                "success": False,
                "error": "No access token found. Please authenticate with Xero first."
            }
        
        client = XeroClient()
        # Test connection by getting organisation info
        response = client.get("Organisation")
        
        if response and response.get('Organisations'):
            return {
                "success": True,
                "message": "Connection test successful",
                "organisation": response['Organisations'][0].get('Name', 'Unknown')
            }
        else:
            return {
                "success": False,
                "error": "Failed to retrieve organisation information"
            }
            
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Test Xero Connection Error")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def refresh_xero_token():
    """Refresh Xero access token"""
    try:
        from xero.utils.xero_client import XeroClient
        
        client = XeroClient()
        success = client.refresh_token()
        
        if success:
            return {
                "success": True,
                "message": "Token refreshed successfully"
            }
        else:
            return {
                "success": False,
                "error": "Failed to refresh token"
            }
            
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Refresh Token Error")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def save_sync_settings(settings):
    """Save sync configuration settings"""
    try:
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        xero_settings = frappe.get_single("Xero Settings")
        
        # Map dashboard settings to DocType fields
        field_mapping = {
            "enable_auto_sync": "enable_auto_sync",
            "sync_frequency": "sync_frequency"
            # Note: batch_size and max_retries are dashboard-specific settings
            # They would need to be added to Xero Settings DocType if persistent storage is needed
        }
        
        # Update only the fields that exist in the DocType
        for dashboard_field, doctype_field in field_mapping.items():
            if dashboard_field in settings and hasattr(xero_settings, doctype_field):
                setattr(xero_settings, doctype_field, settings[dashboard_field])
        
        xero_settings.save()
        
        return {
            "success": True,
            "message": "Settings saved successfully"
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Save Sync Settings Error")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def export_logs(filters=None):
    """Export logs to CSV file"""
    try:
        import csv
        import os
        from frappe.utils.file_manager import save_file
        
        # Get logs with filters
        logs_data = get_logs(start=0, page_length=10000, filters=filters)
        logs = logs_data.get('logs', [])
        
        if not logs:
            return {
                "success": False,
                "error": "No logs found to export"
            }
        
        # Create CSV content
        csv_content = []
        headers = ['Timestamp', 'Status', 'Document Type', 'Document Name', 'Message', 'Xero ID']
        csv_content.append(headers)
        
        for log in logs:
            row = [
                str(log.get('timestamp', '')),
                log.get('status', ''),
                log.get('erpnext_doc_type', ''),
                log.get('erpnext_doc_name', ''),
                log.get('message', ''),
                log.get('xero_doc_id', '')
            ]
            csv_content.append(row)
        
        # Generate CSV file
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(csv_content)
        csv_data = output.getvalue()
        
        # Save file
        file_name = f"xero_sync_logs_{frappe.utils.now().replace(' ', '_').replace(':', '-')}.csv"
        file_doc = save_file(file_name, csv_data, "Home", is_private=0)
        
        return {
            "success": True,
            "file_url": file_doc.file_url,
            "message": "Logs exported successfully"
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Export Logs Error")
        return {
            "success": False,
            "error": str(e)
        }

@frappe.whitelist()
def get_health_monitoring_metrics():
    """Get comprehensive health monitoring metrics"""
    try:
        from datetime import datetime, timedelta
        
        now = now_datetime()
        one_hour_ago = add_to_date(now, hours=-1)
        one_day_ago = add_to_date(now, days=-1)
        seven_days_ago = add_to_date(now, days=-7)
        
        # Error rate trends
        error_trends = frappe.db.sql("""
            SELECT 
                DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:00:00') as hour,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'Error' THEN 1 ELSE 0 END) as errors,
                SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) as success
            FROM `tabXero Log`
            WHERE timestamp >= %s
            GROUP BY DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:00:00')
            ORDER BY hour DESC
            LIMIT 168
        """, (seven_days_ago,), as_dict=True)
        
        # Error by category
        error_by_category = frappe.db.sql("""
            SELECT 
                COALESCE(category, 'Uncategorized') as category,
                COUNT(*) as count,
                COUNT(*) * 100.0 / (SELECT COUNT(*) FROM `tabXero Log` WHERE status = 'Error' AND timestamp >= %s) as percentage
            FROM `tabXero Log`
            WHERE status = 'Error'
            AND timestamp >= %s
            GROUP BY category
            ORDER BY count DESC
        """, (seven_days_ago, seven_days_ago), as_dict=True)
        
        # API performance metrics
        api_performance = frappe.db.sql("""
            SELECT 
                AVG(processing_time) as avg_time,
                MAX(processing_time) as max_time,
                MIN(processing_time) as min_time,
                COUNT(*) as total_calls,
                SUM(CASE WHEN processing_time > 5 THEN 1 ELSE 0 END) as slow_calls
            FROM `tabXero Log`
            WHERE processing_time IS NOT NULL
            AND timestamp >= %s
        """, (one_day_ago,), as_dict=True)
        
        # Rate limiting metrics
        rate_limit_hits = frappe.db.sql("""
            SELECT 
                DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:00:00') as hour,
                COUNT(*) as hits
            FROM `tabXero Log`
            WHERE category = 'Rate Limiting'
            AND timestamp >= %s
            GROUP BY DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:00:00')
            ORDER BY hour DESC
        """, (seven_days_ago,), as_dict=True)
        
        # Token refresh metrics
        token_metrics = frappe.db.sql("""
            SELECT 
                COUNT(*) as total_refreshes,
                SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN status = 'Error' THEN 1 ELSE 0 END) as failed,
                MAX(timestamp) as last_refresh
            FROM `tabXero Log`
            WHERE message LIKE '%%token refresh%%'
            AND timestamp >= %s
        """, (seven_days_ago,), as_dict=True)
        
        # Stuck jobs (running > 1 hour)
        stuck_jobs = []
        try:
            stuck_jobs = frappe.db.sql("""
                SELECT
                    name, job_name, status, creation, started_at,
                    TIMESTAMPDIFF(MINUTE, COALESCE(started_at, creation), NOW()) as duration_minutes
                FROM `tabRQ Job`
                WHERE status IN ('started', 'queued')
                AND job_name LIKE '%%xero%%'
                AND TIMESTAMPDIFF(MINUTE, COALESCE(started_at, creation), NOW()) > 60
                ORDER BY duration_minutes DESC
            """, as_dict=True)
        except Exception:
            pass  # RQ Job table might not exist
        
        # Calculate uptime percentage (last 24h) -- only real sync outcomes
        # (Success / Error); Info and Warning rows are not failures and must not
        # deflate the uptime figure.
        total_operations_24h = frappe.db.count("Xero Log", filters={
            "timestamp": [">=", one_day_ago],
            "status": ["in", ["Success", "Error"]]
        })
        successful_operations_24h = frappe.db.count("Xero Log", filters={
            "timestamp": [">=", one_day_ago],
            "status": "Success"
        })
        uptime_percentage = (successful_operations_24h / total_operations_24h * 100) if total_operations_24h > 0 else 100
        
        return {
            "error_trends": error_trends,
            "error_by_category": error_by_category,
            "api_performance": api_performance[0] if api_performance else {},
            "rate_limit_hits": rate_limit_hits,
            "token_metrics": token_metrics[0] if token_metrics else {},
            "stuck_jobs": stuck_jobs,
            "uptime_percentage": round(uptime_percentage, 2),
            "total_operations_24h": total_operations_24h,
            "successful_operations_24h": successful_operations_24h
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Health Monitoring Metrics Error")
        return {"error": str(e)}

@frappe.whitelist()
def get_data_integrity_metrics():
    """Get data integrity validation results"""
    try:
        # Orphaned invoices (have Xero ID but no sync status)
        orphaned_invoices = frappe.db.sql("""
            SELECT COUNT(*) as count, 'Sales Invoice' as doctype
            FROM `tabSales Invoice`
            WHERE xero_invoice_id IS NOT NULL AND xero_invoice_id != ''
            AND (xero_sync_status IS NULL OR xero_sync_status = '')
            UNION ALL
            SELECT COUNT(*) as count, 'Purchase Invoice' as doctype
            FROM `tabPurchase Invoice`
            WHERE xero_invoice_id IS NOT NULL AND xero_invoice_id != ''
            AND (xero_sync_status IS NULL OR xero_sync_status = '')
        """, as_dict=True)
        
        # Documents marked as synced but missing Xero IDs
        missing_ids = frappe.db.sql("""
            SELECT COUNT(*) as count, 'Sales Invoice' as doctype
            FROM `tabSales Invoice`
            WHERE xero_sync_status = 'Synced'
            AND (xero_invoice_id IS NULL OR xero_invoice_id = '')
            UNION ALL
            SELECT COUNT(*) as count, 'Purchase Invoice' as doctype
            FROM `tabPurchase Invoice`
            WHERE xero_sync_status = 'Synced'
            AND (xero_invoice_id IS NULL OR xero_invoice_id = '')
        """, as_dict=True)
        
        # Pending prerequisites count
        pending_prerequisites = frappe.db.sql("""
            SELECT COUNT(*) as count, 'Sales Invoice' as doctype
            FROM `tabSales Invoice`
            WHERE xero_sync_status = 'Pending Prerequisites'
            UNION ALL
            SELECT COUNT(*) as count, 'Purchase Invoice' as doctype
            FROM `tabPurchase Invoice`
            WHERE xero_sync_status = 'Pending Prerequisites'
        """, as_dict=True)
        
        # Documents with errors
        documents_with_errors = frappe.db.sql("""
            SELECT COUNT(*) as count, 'Sales Invoice' as doctype
            FROM `tabSales Invoice`
            WHERE xero_sync_status = 'Error'
            UNION ALL
            SELECT COUNT(*) as count, 'Purchase Invoice' as doctype
            FROM `tabPurchase Invoice`
            WHERE xero_sync_status = 'Error'
        """, as_dict=True)
        
        # Recent validation errors
        validation_errors = frappe.db.sql("""
            SELECT 
                erpnext_doc_type,
                erpnext_doc_name,
                message,
                timestamp
            FROM `tabXero Log`
            WHERE category = 'Validation Errors'
            AND timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            ORDER BY timestamp DESC
            LIMIT 20
        """, as_dict=True)
        
        # Mapping errors
        mapping_errors = frappe.db.sql("""
            SELECT 
                message,
                COUNT(*) as count
            FROM `tabXero Log`
            WHERE category = 'Mapping Errors'
            AND timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            GROUP BY message
            ORDER BY count DESC
            LIMIT 10
        """, as_dict=True)
        
        return {
            "orphaned_invoices": orphaned_invoices,
            "missing_ids": missing_ids,
            "pending_prerequisites": pending_prerequisites,
            "documents_with_errors": documents_with_errors,
            "validation_errors": validation_errors,
            "mapping_errors": mapping_errors,
            "total_orphaned": sum([o.get('count', 0) for o in orphaned_invoices]),
            "total_missing_ids": sum([m.get('count', 0) for m in missing_ids]),
            "total_pending": sum([p.get('count', 0) for p in pending_prerequisites]),
            "total_errors": sum([e.get('count', 0) for e in documents_with_errors])
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Data Integrity Metrics Error")
        return {"error": str(e)}

@frappe.whitelist()
def get_sync_performance_metrics():
    """Get sync performance metrics"""
    try:
        one_day_ago = add_days(now_datetime(), -1)
        
        # Average sync latency by entity type
        latency_by_entity = frappe.db.sql("""
            SELECT 
                erpnext_doc_type,
                AVG(processing_time) as avg_latency,
                MIN(processing_time) as min_latency,
                MAX(processing_time) as max_latency,
                COUNT(*) as total_syncs
            FROM `tabXero Log`
            WHERE processing_time IS NOT NULL
            AND timestamp >= %s
            AND status = 'Success'
            GROUP BY erpnext_doc_type
            ORDER BY avg_latency DESC
        """, (one_day_ago,), as_dict=True)
        
        # Slowest sync operations
        slowest_syncs = frappe.db.sql("""
            SELECT 
                erpnext_doc_type,
                erpnext_doc_name,
                processing_time,
                timestamp,
                message
            FROM `tabXero Log`
            WHERE processing_time IS NOT NULL
            AND timestamp >= %s
            ORDER BY processing_time DESC
            LIMIT 10
        """, (one_day_ago,), as_dict=True)
        
        # Queue depth (pending documents)
        queue_depth = frappe.db.sql("""
            SELECT 
                'Sales Invoice' as doctype,
                COUNT(*) as pending_count
            FROM `tabSales Invoice`
            WHERE docstatus = 1
            AND (xero_sync_status IS NULL OR xero_sync_status IN ('Pending', 'Pending Prerequisites'))
            UNION ALL
            SELECT 
                'Purchase Invoice' as doctype,
                COUNT(*) as pending_count
            FROM `tabPurchase Invoice`
            WHERE docstatus = 1
            AND (xero_sync_status IS NULL OR xero_sync_status IN ('Pending', 'Pending Prerequisites'))
        """, as_dict=True)
        
        # Oldest pending sync
        oldest_pending = frappe.db.sql("""
            SELECT 
                'Sales Invoice' as doctype,
                name,
                posting_date,
                modified,
                DATEDIFF(NOW(), modified) as days_pending
            FROM `tabSales Invoice`
            WHERE docstatus = 1
            AND (xero_sync_status IS NULL OR xero_sync_status IN ('Pending', 'Pending Prerequisites'))
            ORDER BY modified ASC
            LIMIT 1
        """, as_dict=True)
        
        if not oldest_pending or len(oldest_pending) == 0:
            oldest_pending = frappe.db.sql("""
                SELECT 
                    'Purchase Invoice' as doctype,
                    name,
                    posting_date,
                    modified,
                    DATEDIFF(NOW(), modified) as days_pending
                FROM `tabPurchase Invoice`
                WHERE docstatus = 1
                AND (xero_sync_status IS NULL OR xero_sync_status IN ('Pending', 'Pending Prerequisites'))
                ORDER BY modified ASC
                LIMIT 1
            """, as_dict=True)
        
        # Calculate throughput (records per minute in last hour)
        one_hour_ago = add_to_date(now_datetime(), hours=-1)
        syncs_last_hour = frappe.db.count("Xero Log", filters={
            "timestamp": [">=", one_hour_ago],
            "status": "Success"
        })
        throughput = syncs_last_hour / 60  # Records per minute
        
        return {
            "latency_by_entity": latency_by_entity,
            "slowest_syncs": slowest_syncs,
            "queue_depth": queue_depth,
            "oldest_pending": oldest_pending[0] if oldest_pending else None,
            "throughput": round(throughput, 2),
            "total_pending": sum([q.get('pending_count', 0) for q in queue_depth])
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Sync Performance Metrics Error")
        return {"error": str(e)}

def get_failure_summary(sync_time, direction):
    """
    Aggregates failure reasons for a sync attempt
    Returns categorized failure counts with examples
    """
    try:
        failures = frappe.db.sql("""
            SELECT 
                CASE 
                    WHEN message LIKE '%%No account mapping%%' OR message LIKE '%%Account Code mapping not found%%' THEN 'Missing Account Mappings'
                    WHEN message LIKE '%%not found in ERPNext%%' THEN 'Missing Master Data'
                    WHEN message LIKE '%%must be synced first%%' OR message LIKE '%%Pending Prerequisites%%' THEN 'Missing Prerequisites'
                    WHEN message LIKE '%%No contact information%%' OR message LIKE '%%not found for Xero Contact%%' THEN 'Missing Contact'
                    WHEN message LIKE '%%No valid line items%%' THEN 'Invalid Line Items'
                    ELSE 'Other Issues'
                END as failure_category,
                COUNT(*) as count,
                GROUP_CONCAT(DISTINCT COALESCE(erpnext_doc_name, 'Unknown') ORDER BY erpnext_doc_name SEPARATOR ', ') as affected_docs,
                MAX(message) as example_message
            FROM `tabXero Log`
            WHERE DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:%%i:00') = %s
            AND direction = %s
            AND status IN ('Warning', 'Error')
            GROUP BY failure_category
            ORDER BY count DESC
        """, (sync_time, direction), as_dict=True)
        
        return failures
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Failure Summary Error")
        return []


def get_recommendations(sync_time, direction):
    """
    Provides actionable recommendations based on failure patterns
    """
    try:
        recommendations = []
        
        # Check for missing account mappings
        missing_accounts_data = frappe.db.sql("""
            SELECT 
                COUNT(*) as count,
                GROUP_CONCAT(DISTINCT 
                    SUBSTRING_INDEX(SUBSTRING_INDEX(message, 'AccountCode ', -1), ' ', 1)
                    SEPARATOR ', '
                ) as account_codes
            FROM `tabXero Log`
            WHERE DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:%%i:00') = %s
            AND direction = %s
            AND (message LIKE '%%No account mapping%%' OR message LIKE '%%Account Code mapping not found%%')
        """, (sync_time, direction), as_dict=True)
        
        if missing_accounts_data and missing_accounts_data[0]['count'] > 0:
            account_codes = missing_accounts_data[0]['account_codes'] or "unknown"
            recommendations.append({
                "type": "account_mapping",
                "severity": "high",
                "title": "Missing Account Mappings",
                "message": f"{missing_accounts_data[0]['count']} items skipped due to missing account mappings for Xero AccountCode(s): {account_codes}",
                "action": "Go to Xero Settings → Account Mappings and map these Xero account codes to ERPNext accounts",
                "icon": "fa-link",
                "action_button": {
                    "label": "Configure Mappings",
                    "route": "/app/xero-settings"
                },
                "secondary_button": {
                    "label": "View Logs",
                    "action": "view_logs",
                    "filter": {"message": "account mapping"}
                }
            })
        
        # Check for missing items
        missing_items_data = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabXero Log`
            WHERE DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:%%i:00') = %s
            AND direction = %s
            AND message LIKE '%%not found in ERPNext%%'
            AND message LIKE '%%Item%%'
        """, (sync_time, direction), as_dict=True)
        
        if missing_items_data and missing_items_data[0]['count'] > 0:
            recommendations.append({
                "type": "missing_items",
                "severity": "medium",
                "title": "Missing Items",
                "message": f"{missing_items_data[0]['count']} items not found in ERPNext",
                "action": "Click 'Sync Xero Items' first to import items from Xero, or line items will be created with description only",
                "icon": "fa-cube",
                "action_button": {
                    "label": "Sync Xero Items",
                    "entity": "Sync Xero Items"
                },
                "secondary_button": {
                    "label": "View Logs",
                    "action": "view_logs",
                    "filter": {"message": "not found in ERPNext"}
                }
            })
        
        # Check for missing contacts
        missing_contacts_data = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabXero Log`
            WHERE DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:%%i:00') = %s
            AND direction = %s
            AND (message LIKE '%%not found for Xero Contact%%' OR message LIKE '%%No contact information%%')
        """, (sync_time, direction), as_dict=True)
        
        if missing_contacts_data and missing_contacts_data[0]['count'] > 0:
            recommendations.append({
                "type": "missing_contacts",
                "severity": "high",
                "title": "Missing Contacts",
                "message": f"{missing_contacts_data[0]['count']} documents skipped due to missing contacts",
                "action": "Click 'Sync Xero Contacts' first to import customers and suppliers from Xero",
                "icon": "fa-users",
                "action_button": {
                    "label": "Sync Xero Contacts",
                    "entity": "Sync Xero Contacts"
                },
                "secondary_button": {
                    "label": "View Logs",
                    "action": "view_logs",
                    "filter": {"message": "not found for Xero Contact"}
                }
            })
        
        # Check for invalid line items
        invalid_lines_data = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabXero Log`
            WHERE DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:%%i:00') = %s
            AND direction = %s
            AND message LIKE '%%No valid line items%%'
        """, (sync_time, direction), as_dict=True)
        
        if invalid_lines_data and invalid_lines_data[0]['count'] > 0:
            recommendations.append({
                "type": "invalid_lines",
                "severity": "high",
                "title": "Invalid Line Items",
                "message": f"{invalid_lines_data[0]['count']} documents skipped because all line items were invalid",
                "action": "Check account mappings and ensure all Xero account codes used in line items are mapped in Xero Settings",
                "icon": "fa-exclamation-triangle",
                "action_button": {
                    "label": "Configure Mappings",
                    "route": "/app/xero-settings"
                },
                "secondary_button": {
                    "label": "View Logs",
                    "action": "view_logs",
                    "filter": {"message": "No valid line items"}
                }
            })
        
        return recommendations
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Recommendations Error")
        return []


@frappe.whitelist()
def get_last_sync_attempts():
    """Get detailed breakdown of last sync attempts with item-level status.
    
    Uses sync_batch_id to group logs from the same sync operation, preventing
    different sync operations (e.g. Contacts then Items) from merging together.
    Falls back to timestamp-based grouping for older logs without batch IDs.
    """
    try:
        from datetime import datetime, timedelta
        
        # Get sync attempts from the last 7 days
        seven_days_ago = add_days(now_datetime(), -7)
        
        sync_attempts = []
        
        # --- Part 1: Get batches that have a sync_batch_id (new-style) ---
        batched_syncs = frappe.db.sql("""
            SELECT
                sync_batch_id,
                direction,
                COUNT(*) as item_count,
                SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN status = 'Error' THEN 1 ELSE 0 END) as error_count,
                SUM(CASE WHEN status = 'Warning' THEN 1 ELSE 0 END) as warning_count,
                SUM(CASE WHEN status = 'Info' THEN 1 ELSE 0 END) as info_count,
                SUM(CASE WHEN message LIKE '%%Skipping%%' OR message LIKE '%%Cannot sync%%' THEN 1 ELSE 0 END) as skipped_count,
                GROUP_CONCAT(DISTINCT erpnext_doc_type ORDER BY erpnext_doc_type SEPARATOR ', ') as entities_synced,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                TIMESTAMPDIFF(SECOND, MIN(timestamp), MAX(timestamp)) as duration
            FROM `tabXero Log`
            WHERE timestamp >= %s
            AND sync_batch_id IS NOT NULL
            AND sync_batch_id != ''
            AND erpnext_doc_type IS NOT NULL
            AND erpnext_doc_type != 'Unknown'
            GROUP BY sync_batch_id, direction
            HAVING item_count > 0
            ORDER BY start_time DESC
            LIMIT 20
        """, (seven_days_ago,), as_dict=True)
        
        for batch in batched_syncs:
            # Get all log entries for this batch
            items = frappe.db.sql("""
                SELECT
                    name as log_name,
                    status,
                    message,
                    erpnext_doc_type,
                    erpnext_doc_name,
                    xero_entity_id,
                    timestamp,
                    error_details,
                    processing_time
                FROM `tabXero Log`
                WHERE sync_batch_id = %s
                AND erpnext_doc_type IS NOT NULL
                AND erpnext_doc_type != 'Unknown'
                AND status IN ('Success', 'Error', 'Warning')
                ORDER BY timestamp ASC
            """, (batch.sync_batch_id,), as_dict=True)
            
            # Determine overall status
            overall_status = _determine_overall_status(batch)
            
            # Parse entities synced
            entities_list = batch.entities_synced.split(', ') if batch.entities_synced else []
            
            # Get the sync operation name from the Info log
            sync_label = None
            info_log = frappe.db.get_value("Xero Log",
                {"sync_batch_id": batch.sync_batch_id, "status": "Info", "message": ["like", "Manual sync started:%"]},
                "message")
            if info_log:
                sync_label = info_log.replace("Manual sync started: ", "")
            
            # Get failure summary and recommendations using batch_id
            failure_summary = get_failure_summary_by_batch(batch.sync_batch_id)
            recommendations = get_recommendations_by_batch(batch.sync_batch_id)
            
            sync_attempts.append({
                "sync_batch_id": batch.sync_batch_id,
                "sync_time": str(batch.start_time),
                "sync_label": sync_label,
                "sync_direction": batch.direction or "Unknown",
                "overall_status": overall_status,
                "entities_synced": entities_list,
                "success_count": batch.success_count,
                "error_count": batch.error_count,
                "warning_count": batch.warning_count,
                "skipped_count": batch.skipped_count,
                "duration": batch.duration,
                "items": items,
                "failure_summary": failure_summary,
                "actionable_recommendations": recommendations
            })
        
        # --- Part 2: Get older logs without batch IDs (legacy fallback) ---
        # Only if we have fewer than 20 batched results
        if len(sync_attempts) < 20:
            remaining_limit = 20 - len(sync_attempts)
            legacy_batches = frappe.db.sql("""
                SELECT
                    DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:%%i:00') as sync_time,
                    direction,
                    COUNT(*) as item_count,
                    SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN status = 'Error' THEN 1 ELSE 0 END) as error_count,
                    SUM(CASE WHEN status = 'Warning' THEN 1 ELSE 0 END) as warning_count,
                    SUM(CASE WHEN message LIKE '%%Skipping%%' OR message LIKE '%%Cannot sync%%' THEN 1 ELSE 0 END) as skipped_count,
                    GROUP_CONCAT(DISTINCT erpnext_doc_type ORDER BY erpnext_doc_type SEPARATOR ', ') as entities_synced,
                    MIN(timestamp) as start_time,
                    MAX(timestamp) as end_time,
                    TIMESTAMPDIFF(SECOND, MIN(timestamp), MAX(timestamp)) as duration
                FROM `tabXero Log`
                WHERE timestamp >= %s
                AND (sync_batch_id IS NULL OR sync_batch_id = '')
                AND erpnext_doc_type IS NOT NULL
                AND erpnext_doc_type != 'Unknown'
                AND status IN ('Success', 'Error', 'Warning')
                AND message NOT LIKE '%%Manual sync started%%'
                AND message NOT LIKE '%%sync is disabled%%'
                GROUP BY DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:%%i:00'), COALESCE(direction, 'Unknown')
                HAVING item_count > 0
                ORDER BY sync_time DESC
                LIMIT %s
            """, (seven_days_ago, remaining_limit), as_dict=True)
            
            for batch in legacy_batches:
                items = frappe.db.sql("""
                    SELECT
                        name as log_name,
                        status,
                        message,
                        erpnext_doc_type,
                        erpnext_doc_name,
                        xero_entity_id,
                        timestamp,
                        error_details,
                        processing_time
                    FROM `tabXero Log`
                    WHERE DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:%%i:00') = %s
                    AND COALESCE(direction, 'Unknown') = %s
                    AND (sync_batch_id IS NULL OR sync_batch_id = '')
                    AND erpnext_doc_type IS NOT NULL
                    AND erpnext_doc_type != 'Unknown'
                    AND status IN ('Success', 'Error', 'Warning')
                    ORDER BY timestamp ASC
                """, (batch.sync_time, batch.direction), as_dict=True)
                
                overall_status = _determine_overall_status(batch)
                entities_list = batch.entities_synced.split(', ') if batch.entities_synced else []
                
                failure_summary = get_failure_summary(batch.sync_time, batch.direction)
                recommendations = get_recommendations(batch.sync_time, batch.direction)
                
                sync_attempts.append({
                    "sync_batch_id": None,
                    "sync_time": batch.sync_time,
                    "sync_label": None,
                    "sync_direction": batch.direction or "Unknown",
                    "overall_status": overall_status,
                    "entities_synced": entities_list,
                    "success_count": batch.success_count,
                    "error_count": batch.error_count,
                    "warning_count": batch.warning_count,
                    "skipped_count": batch.skipped_count,
                    "duration": batch.duration,
                    "items": items,
                    "failure_summary": failure_summary,
                    "actionable_recommendations": recommendations
                })
        
        # Sort all attempts by time descending
        sync_attempts.sort(key=lambda a: a['sync_time'], reverse=True)
        sync_attempts = sync_attempts[:20]
        
        # Calculate summary statistics
        total_attempts = len(sync_attempts)
        successful_attempts = len([a for a in sync_attempts if a['overall_status'] == 'Success'])
        failed_attempts = len([a for a in sync_attempts if a['overall_status'] == 'Failed'])
        partial_success_attempts = len([a for a in sync_attempts if a['overall_status'] == 'Partial Success'])
        warning_only_attempts = len([a for a in sync_attempts if a['overall_status'] == 'Warnings Only'])
        success_with_warnings_attempts = len([a for a in sync_attempts if a['overall_status'] == 'Success with Warnings'])
        
        return {
            "sync_attempts": sync_attempts,
            "total_attempts": total_attempts,
            "successful_attempts": successful_attempts,
            "failed_attempts": failed_attempts,
            "partial_success_attempts": partial_success_attempts,
            "warning_only_attempts": warning_only_attempts,
            "success_with_warnings_attempts": success_with_warnings_attempts,
            "in_progress_attempts": 0
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Last Sync Attempts Error")
        return {
            "error": str(e),
            "sync_attempts": [],
            "total_attempts": 0,
            "successful_attempts": 0,
            "failed_attempts": 0,
            "in_progress_attempts": 0
        }


def _determine_overall_status(batch):
    """Determine the overall status for a sync batch based on counts."""
    if batch.error_count > 0 and batch.success_count > 0:
        return "Partial Success"
    elif batch.error_count > 0:
        return "Failed"
    elif batch.warning_count > 0 and batch.success_count == 0:
        return "Warnings Only"
    elif batch.warning_count > 0 and batch.success_count > 0:
        return "Success with Warnings"
    else:
        return "Success"


def get_failure_summary_by_batch(sync_batch_id):
    """Aggregates failure reasons for a sync batch identified by sync_batch_id."""
    try:
        failures = frappe.db.sql("""
            SELECT
                CASE
                    WHEN message LIKE '%%No account mapping%%' OR message LIKE '%%Account Code mapping not found%%' THEN 'Missing Account Mappings'
                    WHEN message LIKE '%%not found in ERPNext%%' THEN 'Missing Master Data'
                    WHEN message LIKE '%%must be synced first%%' OR message LIKE '%%Pending Prerequisites%%' OR message LIKE '%%Please sync%%' THEN 'Missing Prerequisites'
                    WHEN message LIKE '%%No contact information%%' OR message LIKE '%%not found for Xero Contact%%' THEN 'Missing Contact'
                    WHEN message LIKE '%%No valid line items%%' THEN 'Invalid Line Items'
                    WHEN message LIKE '%%Cannot sync%%' THEN 'Sync Blocked'
                    ELSE 'Other Issues'
                END as failure_category,
                COUNT(*) as count,
                GROUP_CONCAT(DISTINCT COALESCE(erpnext_doc_name, 'Unknown') ORDER BY erpnext_doc_name SEPARATOR ', ') as affected_docs,
                MAX(message) as example_message
            FROM `tabXero Log`
            WHERE sync_batch_id = %s
            AND status IN ('Warning', 'Error')
            GROUP BY failure_category
            ORDER BY count DESC
        """, (sync_batch_id,), as_dict=True)
        
        return failures
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Failure Summary By Batch Error")
        return []


def get_recommendations_by_batch(sync_batch_id):
    """Provides actionable recommendations based on failure patterns for a specific batch."""
    try:
        recommendations = []
        
        # Check for missing account mappings
        missing_accounts_data = frappe.db.sql("""
            SELECT
                COUNT(*) as count,
                GROUP_CONCAT(DISTINCT
                    SUBSTRING_INDEX(SUBSTRING_INDEX(message, 'AccountCode ', -1), ' ', 1)
                    SEPARATOR ', '
                ) as account_codes
            FROM `tabXero Log`
            WHERE sync_batch_id = %s
            AND (message LIKE '%%No account mapping%%' OR message LIKE '%%Account Code mapping not found%%')
        """, (sync_batch_id,), as_dict=True)
        
        if missing_accounts_data and missing_accounts_data[0]['count'] > 0:
            account_codes = missing_accounts_data[0]['account_codes'] or "unknown"
            recommendations.append({
                "type": "account_mapping",
                "severity": "high",
                "title": "Missing Account Mappings",
                "message": f"{missing_accounts_data[0]['count']} items skipped due to missing account mappings for Xero AccountCode(s): {account_codes}",
                "action": "Go to Xero Settings → Account Mappings and map these Xero account codes to ERPNext accounts",
                "icon": "fa-link",
                "action_button": {
                    "label": "Configure Mappings",
                    "route": "/app/xero-settings"
                },
                "secondary_button": {
                    "label": "View Logs",
                    "action": "view_logs",
                    "filter": {"message": "account mapping"}
                }
            })
        
        # Check for missing prerequisites (invoices, contacts, accounts not synced)
        missing_prereqs_data = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabXero Log`
            WHERE sync_batch_id = %s
            AND (message LIKE '%%Please sync%%' OR message LIKE '%%has not been synced%%' OR message LIKE '%%must be synced first%%')
        """, (sync_batch_id,), as_dict=True)
        
        if missing_prereqs_data and missing_prereqs_data[0]['count'] > 0:
            recommendations.append({
                "type": "missing_prerequisites",
                "severity": "high",
                "title": "Missing Prerequisites",
                "message": f"{missing_prereqs_data[0]['count']} items could not sync because required data hasn't been synced yet",
                "action": "Sync the prerequisite data first (e.g. Contacts before Invoices, Invoices before Payments, Chart of Accounts before Payments)",
                "icon": "fa-exclamation-triangle",
                "action_button": {
                    "label": "View Xero Settings",
                    "route": "/app/xero-settings"
                }
            })
        
        # Check for missing contacts
        missing_contacts_data = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabXero Log`
            WHERE sync_batch_id = %s
            AND (message LIKE '%%not found for Xero Contact%%' OR message LIKE '%%No contact information%%')
        """, (sync_batch_id,), as_dict=True)
        
        if missing_contacts_data and missing_contacts_data[0]['count'] > 0:
            recommendations.append({
                "type": "missing_contacts",
                "severity": "high",
                "title": "Missing Contacts",
                "message": f"{missing_contacts_data[0]['count']} documents skipped due to missing contacts",
                "action": "Click 'Sync Xero Contacts' first to import customers and suppliers from Xero",
                "icon": "fa-users",
                "action_button": {
                    "label": "Sync Xero Contacts",
                    "entity": "Xero Contacts"
                }
            })
        
        return recommendations
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Recommendations By Batch Error")
        return []


@frappe.whitelist()
def get_sync_batch_status(sync_batch_id):
    """Get the current status of a sync batch by its ID.
    Used for polling after triggering a manual sync."""
    try:
        if not sync_batch_id:
            return {"total_logs": 0, "success_count": 0, "error_count": 0, "warning_count": 0}
        
        result = frappe.db.sql("""
            SELECT
                COUNT(*) as total_logs,
                SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN status = 'Error' THEN 1 ELSE 0 END) as error_count,
                SUM(CASE WHEN status = 'Warning' THEN 1 ELSE 0 END) as warning_count,
                SUM(CASE WHEN status = 'Info' THEN 1 ELSE 0 END) as info_count
            FROM `tabXero Log`
            WHERE sync_batch_id = %s
        """, (sync_batch_id,), as_dict=True)
        
        if result:
            return result[0]
        return {"total_logs": 0, "success_count": 0, "error_count": 0, "warning_count": 0}
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Sync Batch Status Error")
        return {"total_logs": 0, "success_count": 0, "error_count": 0, "warning_count": 0, "error": str(e)}


@frappe.whitelist()
def get_unmapped_accounts_from_errors(days=7):
    """
    Analyzes recent errors to find which Xero AccountCodes need mapping.
    Returns list of unmapped accounts with details and suggestions.
    """
    try:
        from datetime import timedelta
        cutoff_date = add_days(now_datetime(), -int(days))
        
        # Extract unique AccountCodes from error messages
        account_codes_data = frappe.db.sql("""
            SELECT DISTINCT
                SUBSTRING_INDEX(SUBSTRING_INDEX(message, 'AccountCode ', -1), ' ', 1) as account_code,
                COUNT(*) as error_count
            FROM `tabXero Log`
            WHERE (message LIKE %(pattern1)s
                   OR message LIKE %(pattern2)s)
            AND timestamp >= %(cutoff_date)s
            AND status IN ('Warning', 'Error')
            GROUP BY account_code
            ORDER BY error_count DESC
        """, {
            "pattern1": "%No account mapping%",
            "pattern2": "%Account Code mapping not found%",
            "cutoff_date": cutoff_date
        }, as_dict=True)
        
        unmapped_accounts = []
        settings = frappe.get_single("Xero Settings")
        existing_mappings = {row.xero_account_code for row in settings.account_mapping}
        
        for code_data in account_codes_data:
            account_code = code_data.account_code
            
            # Skip if already mapped
            if account_code in existing_mappings:
                continue
            
            # Skip if not a valid account code (sometimes error messages have extra text)
            if not account_code or len(account_code) > 10:
                continue
            
            # Fetch Xero Account details
            xero_account = frappe.db.get_value("Xero Account",
                                              {"account_code": account_code},
                                              ["account_code", "account_name", "account_type", "account_id"],
                                              as_dict=True)
            
            if xero_account:
                # Get suggestions for this account
                suggestions = get_account_suggestions(account_code)
                
                unmapped_accounts.append({
                    "xero_code": xero_account.account_code,
                    "xero_name": xero_account.account_name,
                    "xero_type": xero_account.account_type,
                    "xero_id": xero_account.account_id,
                    "error_count": code_data.error_count,
                    "suggested_accounts": suggestions
                })
        
        return {
            "success": True,
            "unmapped_accounts": unmapped_accounts,
            "total_unmapped": len(unmapped_accounts)
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Unmapped Accounts Error")
        return {
            "success": False,
            "error": str(e),
            "unmapped_accounts": []
        }


@frappe.whitelist()
def get_account_suggestions(xero_account_code):
    """
    Returns suggested ERPNext accounts for a Xero account based on type and name matching.
    """
    try:
        # Get Xero Account details
        xero_account = frappe.db.get_value("Xero Account",
                                          {"account_code": xero_account_code},
                                          ["account_code", "account_name", "account_type"],
                                          as_dict=True)
        
        if not xero_account:
            return {"success": False, "error": "Xero Account not found", "suggestions": []}
        
        # Map Xero account types to ERPNext account types
        account_type_map = {
            "REVENUE": ["Income Account"],
            "EXPENSE": ["Expense Account"],
            "ASSET": ["Asset"],
            "LIABILITY": ["Liability"],
            "EQUITY": ["Equity"],
            "BANK": ["Bank"],
            "CURRENT": ["Asset"],  # Current Asset
            "CURRLIAB": ["Liability"],  # Current Liability
            "FIXED": ["Asset"],  # Fixed Asset
            "INVENTORY": ["Asset"],  # Inventory Asset
            "PAYABLE": ["Liability"],  # Accounts Payable
            "RECEIVABLE": ["Asset"]  # Accounts Receivable
        }
        
        erpnext_types = account_type_map.get(xero_account.account_type, [])
        
        # Build filters for ERPNext accounts
        filters = {
            "is_group": 0,
            "disabled": 0
        }
        
        if erpnext_types:
            filters["account_type"] = ["in", erpnext_types]
        
        # Get matching accounts
        accounts = frappe.get_all("Account",
                                 filters=filters,
                                 fields=["name", "account_type", "account_number", "parent_account"],
                                 limit=50)
        
        # Score accounts based on matching criteria
        scored_accounts = []
        xero_name_lower = xero_account.account_name.lower()
        xero_code_lower = xero_account.account_code.lower()
        
        for acc in accounts:
            score = 0
            acc_name_lower = acc.name.lower()
            
            # Exact account number match (highest priority)
            if acc.account_number and acc.account_number == xero_account.account_code:
                score += 100
            
            # Exact name match
            if xero_name_lower == acc_name_lower:
                score += 50
            
            # Partial name match
            if xero_name_lower in acc_name_lower or acc_name_lower in xero_name_lower:
                score += 30
            
            # Keyword matching
            keywords = ["sales", "revenue", "income", "cogs", "cost", "expense",
                       "bank", "cash", "inventory", "stock", "payable", "receivable"]
            for keyword in keywords:
                if keyword in xero_name_lower and keyword in acc_name_lower:
                    score += 10
            
            # Account code in name
            if xero_code_lower in acc_name_lower:
                score += 20
            
            # Boost score for accounts with matching type
            if acc.account_type in erpnext_types:
                score += 5
            
            scored_accounts.append({
                "account_name": acc.name,
                "account_type": acc.account_type,
                "account_number": acc.account_number,
                "parent_account": acc.parent_account,
                "match_score": score
            })
        
        # Sort by score and return top 5
        scored_accounts.sort(key=lambda x: x["match_score"], reverse=True)
        top_suggestions = scored_accounts[:5]
        
        return {
            "success": True,
            "xero_account": xero_account,
            "suggestions": top_suggestions,
            "total_matches": len(scored_accounts)
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Account Suggestions Error")
        return {
            "success": False,
            "error": str(e),
            "suggestions": []
        }