# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime

def log_xero_error(message, status="Error", erpnext_doc_type=None, erpnext_doc_name=None, xero_entity_type=None, xero_entity_id=None, direction=None, error_details=None, category=None, retry_count=0, processing_time=None):
    """
    Creates a Xero Log document.

    :param message: The main log message.
    :param status: 'Success', 'Error', 'Info', or 'Warning'.
    :param erpnext_doc_type: Linked ERPNext DocType.
    :param erpnext_doc_name: Linked ERPNext document name.
    :param xero_entity_type: Type of Xero entity (e.g., Contact, Invoice).
    :param xero_entity_id: ID of the Xero entity.
    :param direction: 'ERPNext to Xero' or 'Xero to ERPNext'.
    :param error_details: Full traceback or detailed error message.
    :param category: Classification of the log entry (e.g., 'Connection Issues', 'Validation Errors').
    :param retry_count: Number of retry attempts for this operation.
    :param processing_time: Time taken to process this operation in seconds.
    """
    try:
        log_doc = frappe.new_doc("Xero Log")
        log_doc.timestamp = now_datetime()
        log_doc.status = status
        log_doc.message = message  # Now Text field, no truncation needed
        log_doc.erpnext_doc_type = erpnext_doc_type
        log_doc.erpnext_doc_name = erpnext_doc_name
        log_doc.xero_entity_type = xero_entity_type
        log_doc.xero_entity_id = xero_entity_id
        log_doc.direction = direction
        log_doc.error_details = error_details
        log_doc.category = category or auto_categorize_error(message, error_details)
        log_doc.retry_count = retry_count
        log_doc.processing_time = processing_time

        log_doc.flags.ignore_permissions = True # Allow system to log errors
        log_doc.insert()
        frappe.db.commit() # Commit log entry immediately

    except Exception as e:
        # If logging itself fails, print to stderr and Frappe error log
        print("--- XERO LOGGING FAILED ---")
        print(f"Original Message: {message}")
        print(f"Logging Error: {e}")
        print("--- END XERO LOGGING FAILED ---")
        frappe.log_error(f"Failed to create Xero Log entry: {e}", "Xero Logging Error")

def auto_categorize_error(message, error_details=None):
    """
    Automatically categorize errors based on message content.
    
    :param message: The error message.
    :param error_details: Additional error details.
    :return: Category string.
    """
    if not message:
        return "Other Errors"
    
    message_lower = str(message).lower()
    details_lower = str(error_details).lower() if error_details else ""
    combined = f"{message_lower} {details_lower}"
    
    if any(term in combined for term in ['connection', 'timeout', 'network', 'refused']):
        return "Connection Issues"
    elif any(term in combined for term in ['validation', 'required', 'invalid', 'must be']):
        return "Validation Errors"
    elif any(term in combined for term in ['authentication', 'token', 'unauthorized', '401', '403']):
        return "Authentication Issues"
    elif any(term in combined for term in ['rate limit', 'throttle', '429', 'too many requests']):
        return "Rate Limiting"
    elif any(term in combined for term in ['sync health monitoring', 'health check']):
        return "System Monitoring"
    elif any(term in combined for term in ['mapping', 'account code', 'tax', 'not found in settings']):
        return "Mapping Errors"
    else:
        return "Other Errors"
