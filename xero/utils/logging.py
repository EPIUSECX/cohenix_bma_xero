# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime

def log_xero_error(message, status="Error", erpnext_doc_type=None, erpnext_doc_name=None, xero_entity_type=None, xero_entity_id=None, direction=None, error_details=None, category=None, retry_count=0, processing_time=None, sync_batch_id=None):
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
    :param sync_batch_id: Unique identifier to group log entries from the same sync operation.
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
        # Defensive: `category` is a Select field. A value not in its option
        # list raises ValidationError, which the except below swallows —
        # silently dropping the whole log entry. Map any unknown category to
        # "Other Errors" so a log is never lost over a label typo.
        chosen_category = category or auto_categorize_error(message, error_details)
        valid_categories = frappe.get_meta("Xero Log").get_field("category").options or ""
        valid_set = {o.strip() for o in valid_categories.split("\n") if o.strip()}
        if chosen_category and chosen_category not in valid_set:
            chosen_category = "Other Errors"
        log_doc.category = chosen_category
        log_doc.retry_count = retry_count
        log_doc.processing_time = processing_time
        log_doc.sync_batch_id = sync_batch_id

        log_doc.flags.ignore_permissions = True # Allow system to log errors
        log_doc.insert()

        # ME-1: Do NOT commit on every log entry. An unconditional commit here
        # flushes the caller's pending (possibly partial) writes mid-sync,
        # defeating per-document atomicity. The surrounding request/background
        # job commits normally on success. We only force a commit for terminal
        # Error/Warning entries, so a failure that is about to abort and roll
        # back the transaction still leaves an audit trail in the Xero Log.
        if status in ("Error", "Warning"):
            frappe.db.commit()

    except Exception as e:
        # If logging itself fails, print to stderr and Frappe error log
        print("--- XERO LOGGING FAILED ---")
        print(f"Original Message: {message}")
        print(f"Logging Error: {e}")
        print("--- END XERO LOGGING FAILED ---")
        frappe.log_error(f"Failed to create Xero Log entry: {e}", "Xero Logging Error")

def get_leaf_doctype_value(doctype, default=None):
    """
    Return a usable (is_group=0) value for a tree DocType such as Customer Group,
    Supplier Group, Territory, or Item Group.

    ERPNext validates that the assigned value must not be a Group node.
    Root defaults like "All Customer Groups" are group nodes and fail that check.

    Resolution order:
    1. If `default` is provided and is not a group node → return it as-is.
    2. Find the first non-group record ordered by name.
    3. Fall back to `default` (lets ERPNext surface the validation error clearly).
    """
    if default:
        is_group = frappe.db.get_value(doctype, default, "is_group")
        if is_group == 0:
            return default
    leaf = frappe.db.get_value(doctype, {"is_group": 0}, "name", order_by="name asc")
    return leaf or default or ""


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
    elif any(term in combined for term in ['already exists', 'already been used', 'already synced',
                                            'docstatustransitionerror', 'cannot change docstatus',
                                            'duplicate']):
        return "Duplicate Entity"
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


# --- Helper Functions for Error Message Formatting ---

def format_sync_error_message(entity_type, entity_id, entity_name, direction, exception):
    """
    Create a user-friendly error message from an exception for display on the dashboard.
    
    Instead of generic "Failed to sync X to Y", extracts the meaningful part of the error.
    
    :param entity_type: e.g. "Xero Invoice", "Sales Invoice", "Customer"
    :param entity_id: The entity ID (Xero GUID or ERPNext name)
    :param entity_name: Human-readable name/number (e.g. invoice number)
    :param direction: "ERPNext to Xero" or "Xero to ERPNext"
    :param exception: The caught Exception object
    :return: User-friendly error message string
    """
    error_str = str(exception)
    error_lower = error_str.lower()
    
    # CharacterLengthExceededError — extract the field and limit info
    if "characterlengthexceedederror" in error_lower or "will get truncated" in error_lower or "max characters allowed" in error_lower:
        # Try to extract the specific field info from the error message
        # Pattern: "DocType, Row N: 'FieldName' (value...) will get truncated, as max characters allowed is N"
        import re
        match = re.search(r"([^:]+, Row \d+): '([^']+)'.*max characters allowed is (\d+)", error_str)
        if match:
            location = match.group(1).strip()
            field_name = match.group(2).strip()
            max_chars = match.group(3).strip()
            return f"Character Length Exceeded: {location} — '{field_name}' exceeds max {max_chars} characters"
        
        # Simpler pattern without row
        match = re.search(r"'([^']+)'.*max characters allowed is (\d+)", error_str)
        if match:
            field_name = match.group(1).strip()
            max_chars = match.group(2).strip()
            return f"Character Length Exceeded: '{field_name}' exceeds max {max_chars} characters ({entity_name or entity_id})"
        
        return f"Character Length Exceeded: {entity_name or entity_id} — a field value is too long for ERPNext"
    
    # Validation errors from Xero API
    if "validationexception" in error_lower or "xero api error" in error_lower:
        # Try to extract the validation message
        import re
        match = re.search(r'"Message"\s*:\s*"([^"]+)"', error_str)
        if match:
            return f"Xero Validation Error: {match.group(1)} ({entity_name or entity_id})"
        return f"Xero Validation Error for {entity_type} {entity_name or entity_id}"
    
    # Account mapping errors
    if "account code mapping not found" in error_lower or "account code not found" in error_lower:
        import re
        match = re.search(r"Account[:\s]+([^\(]+)", error_str)
        account_info = match.group(1).strip() if match else "unknown account"
        return f"Missing Account Mapping: {account_info} ({entity_name or entity_id})"
    
    # Docstatus transition (shouldn't reach here if is_already_exists_error catches it, but just in case)
    if "docstatustransitionerror" in error_lower or "cannot change docstatus" in error_lower:
        return f"Cannot update submitted document: {entity_type} {entity_name or entity_id}"
    
    # Duplicate name
    if "duplicateentryerror" in error_lower or "duplicate entry" in error_lower:
        return f"Duplicate Entry: {entity_type} {entity_name or entity_id} already exists"
    
    # Mandatory field missing
    if "mandatoryerror" in error_lower or "is mandatory" in error_lower or "required" in error_lower:
        import re
        match = re.search(r"(\w[\w\s]+) is mandatory", error_str, re.IGNORECASE)
        if match:
            return f"Missing Required Field: '{match.group(1).strip()}' for {entity_type} {entity_name or entity_id}"
        return f"Missing Required Field for {entity_type} {entity_name or entity_id}"
    
    # Generic fallback — use the first line of the exception message (truncated)
    first_line = error_str.split('\n')[0][:200]
    if first_line:
        return f"Sync Error for {entity_type} {entity_name or entity_id}: {first_line}"
    
    return f"Failed to sync {entity_type} {entity_name or entity_id}"


# --- Helper Functions for "Already Exists" Detection ---

# Patterns that indicate an entity already exists (non-critical sync failures)
ALREADY_EXISTS_PATTERNS = [
    "already exists",
    "already been used",
    "already being used",
    "code already exists",
    "name already exists",
    "number already exists",
    "duplicate",
]

# Exception types that indicate an entity already exists in ERPNext (inbound sync)
ALREADY_EXISTS_EXCEPTIONS = [
    "docstatustransitionerror",
    "cannot change docstatus",
]


def is_already_exists_error(error_message, error_details=None):
    """
    Detect if an error indicates that an entity already exists
    (either in Xero for outbound sync, or in ERPNext for inbound sync).
    
    This covers:
    - Xero API 400 errors with "already exists" messages (outbound)
    - DocstatusTransitionError when trying to update submitted docs (inbound)
    
    :param error_message: The error message string.
    :param error_details: Full traceback or detailed error message.
    :return: True if the error is an "already exists" type error.
    """
    if not error_message and not error_details:
        return False
    
    combined = f"{str(error_message or '').lower()} {str(error_details or '').lower()}"
    
    # Check for Xero API "already exists" patterns
    for pattern in ALREADY_EXISTS_PATTERNS:
        if pattern in combined:
            return True
    
    # Check for ERPNext "already exists" exceptions (submitted doc update attempts)
    for pattern in ALREADY_EXISTS_EXCEPTIONS:
        if pattern in combined:
            return True
    
    return False
