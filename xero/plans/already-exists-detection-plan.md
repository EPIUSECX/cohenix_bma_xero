# Plan: "Already Exists on Xero" Detection and Reporting

## Problem Statement

When an entity (Account, Contact, Invoice, etc.) fails to sync to Xero because it already exists, the current error message is generic and doesn't clearly indicate the root cause. Users need a clear "Entity already exists on Xero" message in the dashboard.

## Current State Analysis

### Xero API Error Responses

When you try to create an entity that already exists, Xero returns specific error messages:

**Accounts API:**
- Error: "Account code already exists" (when Code matches)
- Error: "Account name already exists" (when Name matches)
- HTTP Status: 400 Bad Request

**Contacts API:**
- Error: "A contact with this name already exists"
- HTTP Status: 400 Bad Request

**Invoices API:**
- Error: "Invoice number already exists"
- HTTP Status: 400 Bad Request

### Current Error Handling

The [`xero_request()`](cohenix-bench/apps/xero/xero/utils/xero_client.py:280) function catches HTTP errors and logs them, but doesn't parse the error message to detect "already exists" scenarios.

Current flow:
```
1. Try to create entity in Xero
2. Xero returns 400 error with message
3. Error is logged generically
4. User sees "Xero API request failed: Bad Request (400)"
```

### Xero Log Structure

The [`Xero Log`](cohenix-bench/apps/xero/xero/xero/doctype/xero_log/xero_log.json) DocType has:
- `status`: Success/Error/Info/Warning
- `category`: Connection Issues/Validation Errors/Authentication Issues/Rate Limiting/System Monitoring/Mapping Errors/Other Errors
- `message`: Text description
- `error_details`: Long text with full details

**Missing**: No "Already Exists" category or status.

## Proposed Solution

### 1. Add "Already Exists" Category to Xero Log

Update the `category` field options to include:
```
Connection Issues
Validation Errors
Authentication Issues
Rate Limiting
System Monitoring
Mapping Errors
Duplicate Entity    <-- NEW
Other Errors
```

### 2. Create Detection Helper Function

Create a utility function to detect "already exists" errors from Xero responses:

```python
# In xero/utils/error_detection.py

XERO_DUPLICATE_PATTERNS = {
    "Account": [
        "account code already exists",
        "account name already exists",
        "code already being used",
    ],
    "Contact": [
        "contact with this name already exists",
        "contact already exists",
    ],
    "Invoice": [
        "invoice number already exists",
        "invoice already exists",
    ],
    "Item": [
        "item already exists",
        "item code already exists",
    ],
    "Payment": [
        "payment already exists",
    ],
    "ManualJournal": [
        "manual journal already exists",
        "narration already exists",
    ],
}

def is_duplicate_error(entity_type, error_message):
    """
    Check if an error message indicates a duplicate entity in Xero.
    
    Args:
        entity_type: Type of entity (Account, Contact, Invoice, etc.)
        error_message: Error message from Xero API
    
    Returns:
        tuple: (is_duplicate: bool, matched_pattern: str or None)
    """
    if not error_message:
        return False, None
    
    error_lower = error_message.lower()
    patterns = XERO_DUPLICATE_PATTERNS.get(entity_type, [])
    
    for pattern in patterns:
        if pattern.lower() in error_lower:
            return True, pattern
    
    # Generic patterns for any entity type
    generic_patterns = [
        "already exists",
        "duplicate",
        "already been used",
    ]
    
    for pattern in generic_patterns:
        if pattern in error_lower:
            return True, pattern
    
    return False, None


def get_existing_entity_from_xero(entity_type, search_field, search_value):
    """
    Try to find an existing entity in Xero that matches the search criteria.
    
    Args:
        entity_type: Type of entity (Accounts, Contacts, Invoices, etc.)
        search_field: Field to search (Code, Name, InvoiceNumber, etc.)
        search_value: Value to search for
    
    Returns:
        dict: Entity data if found, None otherwise
    """
    from .xero_client import xero_request
    
    try:
        response = xero_request("GET", entity_type, params={
            "where": f'{search_field}=="{search_value}"'
        })
        
        if response and entity_type in response and len(response[entity_type]) > 0:
            return response[entity_type][0]
    except Exception:
        pass
    
    return None
```

### 3. Update Sync Functions to Use Detection

For each sync function, wrap the Xero API call with duplicate detection:

```python
# Example for sync_account_to_xero

def sync_account_to_xero(account_name):
    doc = frappe.get_doc("Account", account_name)
    # ... existing setup code ...
    
    try:
        payload = build_xero_account_payload(doc, settings)
        
        if doc.xero_account_id:
            response = xero_request("POST", f"Accounts/{doc.xero_account_id}", data={"Accounts": [payload]})
        else:
            response = xero_request("PUT", "Accounts", data={"Accounts": [payload]})
        
        # ... success handling ...
        
    except Exception as e:
        error_message = str(e)
        
        # Check for duplicate
        is_duplicate, pattern = is_duplicate_error("Account", error_message)
        
        if is_duplicate:
            # Try to find the existing account
            existing = get_existing_entity_from_xero(
                "Accounts", 
                "Code", 
                payload.get("Code")
            )
            
            if existing:
                # Link to existing account
                doc.db_set({
                    "xero_account_id": existing.get("AccountID"),
                    "xero_sync_status": "Synced",  # It's synced now
                    "xero_data_hash": compute_account_hash(doc),
                })
                
                log_xero_error(
                    message=f"Account already exists in Xero (Code: {payload.get('Code')}). Linked to existing account.",
                    status="Warning",
                    category="Duplicate Entity",
                    erpnext_doc_type="Account",
                    erpnext_doc_name=doc.name,
                    xero_entity_id=existing.get("AccountID"),
                    xero_entity_type="Account",
                    direction="ERPNext to Xero"
                )
            else:
                # Duplicate detected but couldn't find the entity
                doc.db_set("xero_sync_status", "Duplicate")
                
                log_xero_error(
                    message=f"Account already exists in Xero but could not locate it. Matched pattern: {pattern}",
                    status="Error",
                    category="Duplicate Entity",
                    erpnext_doc_type="Account",
                    erpnext_doc_name=doc.name,
                    xero_entity_type="Account",
                    direction="ERPNext to Xero",
                    error_details=error_message
                )
        else:
            # Regular error handling
            doc.db_set("xero_sync_status", "Error")
            log_xero_error(
                message=f"Failed to sync Account {doc.name} to Xero: {error_message}",
                status="Error",
                category="Validation Errors",
                # ...
            )
```

### 4. Add "Duplicate" Status Option

Update the `xero_sync_status` field options in custom_fields.py:

```python
"options": "\nPending\nSynced\nError\nSkipped\nDuplicate"
```

### 5. Update Dashboard Display

The dashboard should show:
- **Status**: "Duplicate" (yellow/warning color)
- **Message**: "Entity already exists on Xero"
- **Action**: "Link to existing" or "Update local data"

## Implementation Checklist

### Phase 1: Infrastructure
- [ ] Create `xero/utils/error_detection.py` with helper functions
- [ ] Add "Duplicate Entity" category to Xero Log DocType
- [ ] Add "Duplicate" status to xero_sync_status options

### Phase 2: Entity-Specific Implementation
- [ ] Update `sync_account_to_xero()` with duplicate detection
- [ ] Update `sync_contact_to_xero()` with duplicate detection
- [ ] Update `sync_invoice_to_xero()` with duplicate detection
- [ ] Update `sync_item_to_xero()` with duplicate detection
- [ ] Update `sync_payment_to_xero()` with duplicate detection
- [ ] Update `sync_journal_to_xero()` with duplicate detection

### Phase 3: Dashboard Updates
- [ ] Update dashboard to show "Duplicate" status with appropriate styling
- [ ] Add "Link to Existing" action button for duplicates
- [ ] Add filter for "Duplicate" status

### Phase 4: Testing
- [ ] Test duplicate detection for Accounts
- [ ] Test duplicate detection for Contacts
- [ ] Test duplicate detection for Invoices
- [ ] Test auto-linking to existing entities

## Entity-Specific Search Fields

| Entity Type | Xero Endpoint | Search Field | Unique Key |
|-------------|---------------|--------------|------------|
| Account | Accounts | Code | Account Code |
| Contact | Contacts | ContactNumber | Contact Number |
| Invoice | Invoices | InvoiceNumber | Invoice Number |
| Item | Items | Code | Item Code |
| Payment | Payments | Reference | Payment Reference |
| ManualJournal | ManualJournals | Narration | Journal Narration |

## Benefits

1. **Clear Error Messages**: Users immediately understand why sync failed
2. **Auto-Linking**: System can automatically link to existing entities
3. **Reduced Support**: Less confusion about sync failures
4. **Better Reporting**: Can track duplicate issues separately

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| False positives in duplicate detection | Use multiple pattern matching |
| Auto-linking to wrong entity | Verify by multiple fields before linking |
| Performance impact of searching | Cache results, use efficient queries |
