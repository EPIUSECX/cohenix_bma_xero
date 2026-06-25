# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
import time
import random
from functools import wraps
from .logging import log_xero_error

def retry_with_exponential_backoff(max_retries=3, base_delay=1, max_delay=60, backoff_factor=2):
    """
    Decorator to retry functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_factor: Multiplier for delay on each retry
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        # Final attempt failed, log and re-raise
                        log_xero_error(
                            message=f"Function {func.__name__} failed after {max_retries} retries",
                            status="Error",
                            error_details=frappe.get_traceback()
                        )
                        raise e
                    
                    # Calculate delay with jitter to avoid thundering herd
                    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                    jitter = random.uniform(0.1, 0.3) * delay
                    total_delay = delay + jitter
                    
                    log_xero_error(
                        message=f"Function {func.__name__} failed on attempt {attempt + 1}, retrying in {total_delay:.2f} seconds",
                        status="Warning",
                        error_details=str(e)
                    )
                    
                    time.sleep(total_delay)
            
            # This should never be reached, but just in case
            raise last_exception
        
        return wrapper
    return decorator

@frappe.whitelist()
def retry_failed_sync(log_name):
    from .xero_client import require_xero_manager
    require_xero_manager()
    """
    Retry a failed sync operation based on the Xero Log entry.
    
    Args:
        log_name: Name of the Xero Log document to retry
    """
    try:
        log_doc = frappe.get_doc("Xero Log", log_name)
        
        if log_doc.status != "Error":
            frappe.throw("Only failed sync operations can be retried.")
        
        # Determine the sync function to call based on the log entry
        sync_function = get_sync_function(log_doc.erpnext_doc_type, log_doc.xero_entity_type, log_doc.direction)
        
        if not sync_function:
            frappe.throw(f"No sync function found for {log_doc.erpnext_doc_type} -> {log_doc.xero_entity_type}")
        
        # Call the sync function (ME-6: match each function's real signature).
        if log_doc.direction == "ERPNext to Xero":
            if log_doc.erpnext_doc_type == "Item":
                # sync_item_to_xero(item_code, **kwargs)
                sync_function(log_doc.erpnext_doc_name)
            else:
                # All other outbound sync fns are (doc_name, doc_type, **kwargs)
                sync_function(
                    doc_name=log_doc.erpnext_doc_name,
                    doc_type=log_doc.erpnext_doc_type,
                )
        else:
            # Handle Xero to ERPNext sync if needed
            frappe.throw("Xero to ERPNext retry not implemented yet")
        
        frappe.msgprint(f"Retry initiated for {log_doc.erpnext_doc_type} {log_doc.erpnext_doc_name}")
        
    except Exception as e:
        log_xero_error(
            message=f"Failed to retry sync for log {log_name}",
            status="Error",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Retry failed: {str(e)}")

def get_sync_function(erpnext_doc_type, xero_entity_type, direction):
    """
    Get the appropriate sync function based on document types.
    
    Returns:
        Function object or None if not found
    """
    if direction != "ERPNext to Xero":
        return None
    
    sync_map = {
        ("Sales Invoice", "Invoice"): "xero.api.xero_invoices.sync_invoice_to_xero",
        ("Purchase Invoice", "Invoice"): "xero.api.xero_invoices.sync_invoice_to_xero",
        ("Customer", "Contact"): "xero.api.xero_contacts.sync_contact_to_xero",
        ("Supplier", "Contact"): "xero.api.xero_contacts.sync_contact_to_xero",
        ("Item", "Item"): "xero.api.xero_items.sync_item_to_xero",
        ("Payment Entry", "Payment"): "xero.api.xero_payments.sync_payment_to_xero",
        ("Payment Entry", "BankTransaction"): "xero.api.xero_payments.sync_payment_to_xero",
        ("Journal Entry", "Journal"): "xero.api.xero_journals.sync_journal_to_xero",
        ("Sales Invoice", "CreditNote"): "xero.api.xero_credit_notes.sync_return_to_xero",
        ("Purchase Invoice", "CreditNote"): "xero.api.xero_credit_notes.sync_return_to_xero",
    }
    
    function_path = sync_map.get((erpnext_doc_type, xero_entity_type))
    if function_path:
        try:
            module_path, function_name = function_path.rsplit('.', 1)
            module = frappe.get_module(module_path)
            return getattr(module, function_name)
        except (ImportError, AttributeError):
            return None
    
    return None

@frappe.whitelist()
def bulk_retry_failed_syncs(filters=None):
    from .xero_client import require_xero_manager
    require_xero_manager()
    """
    Retry multiple failed sync operations in bulk.
    
    Args:
        filters: Optional filters to apply when selecting failed syncs
    """
    try:
        # Get all failed sync logs
        base_filters = {"status": "Error"}
        if filters:
            base_filters.update(filters)
        
        failed_logs = frappe.get_all(
            "Xero Log",
            filters=base_filters,
            fields=["name", "erpnext_doc_type", "erpnext_doc_name", "xero_entity_type", "direction"],
            limit=50  # Limit to prevent overwhelming the system
        )
        
        if not failed_logs:
            frappe.msgprint("No failed sync operations found to retry.")
            return
        
        success_count = 0
        error_count = 0
        
        for log_entry in failed_logs:
            try:
                # Enqueue each retry as a background job to prevent timeout
                frappe.enqueue(
                    "xero.utils.retry_handler.retry_failed_sync",
                    queue="short",
                    timeout=300,
                    log_name=log_entry.name
                )
                success_count += 1
            except Exception as e:
                error_count += 1
                log_xero_error(
                    message=f"Failed to enqueue retry for log {log_entry.name}",
                    status="Error",
                    error_details=str(e)
                )
        
        frappe.msgprint(f"Bulk retry initiated: {success_count} queued, {error_count} failed to queue")
        
    except Exception as e:
        log_xero_error(
            message="Failed to initiate bulk retry",
            status="Error",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Bulk retry failed: {str(e)}")

def is_retryable_error(exception):
    """
    Determine if an error is retryable based on its type and message.
    
    Args:
        exception: The exception to check
        
    Returns:
        bool: True if the error should be retried
    """
    retryable_errors = [
        "rate limit",
        "timeout",
        "connection",
        "network",
        "temporary",
        "503",  # Service Unavailable
        "502",  # Bad Gateway
        "504",  # Gateway Timeout
        "429",  # Too Many Requests
    ]
    
    error_message = str(exception).lower()
    return any(error_type in error_message for error_type in retryable_errors)