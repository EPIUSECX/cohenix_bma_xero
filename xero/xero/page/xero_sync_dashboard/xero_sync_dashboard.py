# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
import json
from datetime import datetime, timedelta
from frappe.utils import now_datetime, add_days, get_datetime, flt
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
            "sync_enabled": settings.enable_xero_sync
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
    
    # Overall stats
    overall_stats = frappe.db.sql("""
        SELECT 
            status,
            COUNT(*) as count,
            AVG(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) * 100 as success_rate
        FROM `tabXero Log`
        WHERE timestamp BETWEEN %s AND %s
        GROUP BY status
    """, (from_date, to_date), as_dict=True)
    
    # Entity-wise stats
    entity_stats = frappe.db.sql("""
        SELECT 
            erpnext_doc_type,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status = 'Error' THEN 1 ELSE 0 END) as errors,
            AVG(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) * 100 as success_rate
        FROM `tabXero Log`
        WHERE timestamp BETWEEN %s AND %s
        AND erpnext_doc_type IS NOT NULL
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
    
    entity_status = []
    for entity in entities:
        # Get total documents
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
            # Count synced documents
            synced = frappe.db.sql(f"""
                SELECT COUNT(*) FROM `tab{entity}`
                WHERE {xero_field} IS NOT NULL AND {xero_field} != ''
            """)[0][0]
            
            # Count pending/error documents if sync status field exists
            sync_status_field = "xero_sync_status"
            try:
                if frappe.db.has_column(entity, sync_status_field):
                    pending = frappe.db.sql(f"""
                        SELECT COUNT(*) FROM `tab{entity}`
                        WHERE {sync_status_field} = 'Pending'
                    """)[0][0]
                    
                    errors = frappe.db.sql(f"""
                        SELECT COUNT(*) FROM `tab{entity}`
                        WHERE {sync_status_field} = 'Error'
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
    
    return entity_status

@frappe.whitelist()
def get_recent_errors(limit=10):
    """Get recent error logs with details"""
    errors = frappe.db.sql("""
        SELECT
            name,
            COALESCE(message, 'No message available') as message,
            COALESCE(erpnext_doc_type, 'Unknown') as erpnext_doc_type,
            COALESCE(erpnext_doc_name, 'Unknown') as erpnext_doc_name,
            timestamp,
            COALESCE(error_details, '') as error_details,
            COALESCE(xero_entity_id, '') as xero_entity_id,
            COALESCE(direction, 'Unknown') as direction
        FROM `tabXero Log`
        WHERE status = 'Error'
        ORDER BY timestamp DESC
        LIMIT %s
    """, (limit,), as_dict=True)
    
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
    
    total_recent = len(recent_logs)
    success_recent = len([log for log in recent_logs if log[0] == 'Success'])
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
    if len([t for t in error_trend if (t.errors / t.total * 100) > 10]) > 2:
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
        
        # Parse filters
        if filters and isinstance(filters, str):
            filters = json.loads(filters)
        
        sync_functions = {
            # ERPNext to Xero syncs
            "Sales Invoice": "xero.api.xero_invoices.sync_invoices_to_xero",
            "Purchase Invoice": "xero.api.xero_invoices.sync_invoices_to_xero",
            "Payment Entry": "xero.api.xero_payments.sync_payments_to_xero",
            "Journal Entry": "xero.api.xero_journals.sync_journals_to_xero",
            "Customer": "xero.api.xero_contacts.sync_contacts_to_xero",
            "Supplier": "xero.api.xero_contacts.sync_contacts_to_xero",
            "Item": "xero.api.xero_items.sync_items_to_xero",
            "Account": "xero.api.xero_accounts.sync_accounts_to_xero",  # Added Account sync to Xero
            "Quotation": "xero.api.xero_quotes.sync_quotes_to_xero",
            "Bank Transaction": "xero.api.xero_bank_transactions.sync_bank_transactions_to_xero",
            # Xero to ERPNext syncs - These sync FROM Xero TO ERPNext DocTypes
            "Sync Xero Accounts": "xero.api.xero_accounts.sync_accounts_from_xero",  # Creates Account records in ERPNext
            "Sync Xero Contacts": "xero.api.xero_contacts.sync_contacts_from_xero",  # Creates Customer/Supplier records in ERPNext
            "Sync Xero Items": "xero.api.xero_items.sync_items_from_xero",          # Creates Item records in ERPNext
            "Sync Xero Payments": "xero.api.xero_payments.sync_payments_from_xero", # Creates Payment Entry records in ERPNext
            "Sync Xero Bank Transactions": "xero.api.xero_bank_transactions.sync_bank_transactions_from_xero" # Creates Bank Transaction records in ERPNext
        }
        
        function_path = sync_functions.get(entity_type)
        if not function_path:
            frappe.throw(_("Sync function not found for entity type: {0}").format(entity_type))
        
        # For "Sync Xero" functions, we don't pass filters since they sync FROM Xero
        if entity_type.startswith("Sync Xero"):
            # These are Xero to ERPNext sync functions - no filters needed
            job = frappe.enqueue(
                function_path,
                queue="long",
                timeout=3600,
                job_name=f"Manual Sync: {entity_type}"
            )
            
            # Map Xero sync operations to the actual ERPNext DocTypes they create
            target_doctype_map = {
                "Sync Xero Accounts": "Account",
                "Sync Xero Contacts": "Customer",  # Could also be Supplier, but Customer is more common
                "Sync Xero Items": "Item",
                "Sync Xero Payments": "Payment Entry",
                "Sync Xero Bank Transactions": "Bank Transaction"
            }
            
            target_doctype = target_doctype_map.get(entity_type, "Account")  # Default to Account
            
            # Log the manual sync trigger with the target ERPNext DocType
            frappe.get_doc({
                "doctype": "Xero Log",
                "status": "Info",
                "message": f"Manual sync triggered for {entity_type}",
                "erpnext_doc_type": target_doctype,
                "timestamp": now_datetime()
            }).insert(ignore_permissions=True)
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
            
            # Log the manual sync trigger
            frappe.get_doc({
                "doctype": "Xero Log",
                "status": "Info",
                "message": f"Manual sync triggered for {entity_type}",
                "erpnext_doc_type": entity_type,
                "timestamp": now_datetime()
            }).insert(ignore_permissions=True)
        
        return {
            "success": True,
            "job_id": job.id,
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
            "Sales Order": "xero.api.xero_sales_orders.enqueue_sync_sales_order",
            "Delivery Note": "xero.api.xero_delivery_notes.enqueue_sync_delivery_note",
            "Purchase Order": "xero.api.xero_purchase_orders.enqueue_sync_purchase_order",
            "Purchase Receipt": "xero.api.xero_purchase_receipts.enqueue_sync_purchase_receipt",
            "Stock Ledger Entry": "xero.api.xero_stock.enqueue_sync_stock_ledger",
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
        
        entities = [
            "Sales Invoice", "Purchase Invoice", "Payment Entry",
            "Customer", "Supplier", "Item"
        ]
        
        job_count = 0
        for entity in entities:
            try:
                result = trigger_manual_sync(entity)
                if result.get('success'):
                    job_count += 1
            except Exception as e:
                frappe.log_error(f"Failed to trigger sync for {entity}: {str(e)}")
                continue
        
        return {
            "success": True,
            "jobs_queued": job_count,
            "message": f"Queued {job_count} sync jobs"
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
        
        # Calculate uptime percentage (last 24h)
        total_operations_24h = frappe.db.count("Xero Log", filters={
            "timestamp": [">=", one_day_ago]
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
            AND (xero_sync_status IS NULL OR xero_sync_status IN ('Pending', 'Error', 'Pending Prerequisites'))
            UNION ALL
            SELECT 
                'Purchase Invoice' as doctype,
                COUNT(*) as pending_count
            FROM `tabPurchase Invoice`
            WHERE docstatus = 1
            AND (xero_sync_status IS NULL OR xero_sync_status IN ('Pending', 'Error', 'Pending Prerequisites'))
        """, as_dict=True)
        
        # Oldest pending sync
        oldest_pending = frappe.db.sql("""
            SELECT 
                'Sales Invoice' as doctype,
                name,
                posting_date,
                DATEDIFF(NOW(), posting_date) as days_pending
            FROM `tabSales Invoice`
            WHERE docstatus = 1
            AND (xero_sync_status IS NULL OR xero_sync_status IN ('Pending', 'Error'))
            ORDER BY posting_date ASC
            LIMIT 1
        """, as_dict=True)
        
        if not oldest_pending or len(oldest_pending) == 0:
            oldest_pending = frappe.db.sql("""
                SELECT 
                    'Purchase Invoice' as doctype,
                    name,
                    posting_date,
                    DATEDIFF(NOW(), posting_date) as days_pending
                FROM `tabPurchase Invoice`
                WHERE docstatus = 1
                AND (xero_sync_status IS NULL OR xero_sync_status IN ('Pending', 'Error'))
                ORDER BY posting_date ASC
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