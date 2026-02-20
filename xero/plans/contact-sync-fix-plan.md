# Contact Bidirectional Sync Analysis & Fix Plan

> **Purpose**: This document analyzes the current contact sync implementation against Xero API requirements and provides a comprehensive plan for fixing bidirectional sync issues.

---

## Executive Summary

The contact sync implementation has several critical issues that prevent reliable bidirectional synchronization:

1. **CRITICAL**: Sending read-only fields (`IsCustomer`/`IsSupplier`) in outbound sync - Xero ignores or may reject these
2. **CRITICAL**: Using PUT instead of POST for updates - can cause errors when ContactName matches existing contacts
3. **CRITICAL**: Inbound sync defaults to Customer when no flags set - causes Supplier→Customer conversion on round-trip
4. **MAJOR**: Double-trigger guard prevents legitimate re-syncs when data changes
5. **MAJOR**: Missing field mappings and validation

---

## Part 1: Xero API Requirements Analysis

### 1.1 Key API Constraints from Official Documentation

| Constraint | Details | Impact on Implementation |
|------------|---------|--------------------------|
| **IsCustomer/IsSupplier are READ-ONLY** | Cannot be set via PUT or POST. Automatically set when AR/AP invoices are generated against a contact. | Current code sends these fields - they are ignored or may cause errors |
| **Name is the ONLY required field** | Max 255 chars, no angle brackets, no leading/trailing whitespace, no repeating spaces | Need validation before sync |
| **ContactID is the unique identifier** | ContactName may no longer be unique in the future | Must use ContactID for matching, not Name |
| **POST vs PUT behavior** | POST: Creates or updates. PUT: Creates only, errors if ContactName/ContactNumber matches existing | Current code uses PUT for updates - should use POST |
| **ContactPersons limit** | Max 5 contact persons per contact | Need to enforce limit |
| **Addresses array** | AddressType can be POBOX or STREET | Current implementation correct |
| **Phones array** | PhoneType can be DEFAULT, FAX, MOBILE, DDI | Current implementation correct |

### 1.2 POST vs PUT Behavior

From Xero API documentation:

> **POST Contacts**: Use this method to create or update one or more contact records. When updating, you don't need to specify every element. If you exclude an element then the existing value will be preserved.

> **PUT Contacts**: Use this method to create one or more contact records. This method works very similar to POST Contacts but if an existing contact matches your ContactName or ContactNumber then you will receive an error.

**Current Implementation Problem**: The code uses PUT for both create and update:
```python
# xero_contacts.py:214
response = xero_request("PUT", "Contacts", data={"Contacts": [contact_payload]})
```

**Correct Approach**: Use POST for updates (when ContactID is known), PUT only for creating new contacts with guaranteed unique names.

### 1.3 IsCustomer/IsSupplier Behavior

From Xero API documentation:

> **IsSupplier**: true or false – Boolean that describes if a contact that has any AP invoices entered against them. **Cannot be set via PUT or POST** – it is automatically set when an accounts payable invoice is generated against this contact.

> **IsCustomer**: true or false – Boolean that describes if a contact has any AR invoices entered against them. **Cannot be set via PUT or POST** – it is automatically set when an accounts receivable invoice is generated against this contact.

**Current Implementation Problem**: The code sends these fields:
```python
# xero_contacts.py:92-93
"IsCustomer": True if doc_type == "Customer" else False,
"IsSupplier": True if doc_type == "Supplier" else False,
```

**Correct Approach**: Remove these fields from outbound payload entirely. Xero will set them automatically when invoices are created.

---

## Part 2: Current Implementation Analysis

### 2.1 Outbound Sync Flow (ERPNext → Xero)

```
User saves Customer/Supplier
    ↓
on_update hook fires (hooks.py:150-154)
    ↓
enqueue_sync_contact() (xero_contacts.py:11-39)
    ↓
[GUARD] Check xero_sync_status == "Synced" → return if true
    ↓
frappe.enqueue() queues background job
    ↓
sync_contact_to_xero() (xero_contacts.py:42-253)
    ↓
[PROBLEM] Sends IsCustomer/IsSupplier (read-only fields)
    ↓
[PROBLEM] Uses PUT instead of POST
    ↓
xero_request() → Xero API
    ↓
Update xero_contact_id, xero_sync_status
```

### 2.2 Inbound Sync Flow (Xero → ERPNext)

```
Scheduled task fires (daily)
    ↓
sync_contacts_from_xero() (xero_contacts.py:411-469)
    ↓
Paginate through Xero API (100 per page)
    ↓
For each contact:
    ↓
process_xero_contact() (xero_contacts.py:471-501)
    ↓
[PROBLEM] Check IsCustomer/IsSupplier flags
    ↓
[PROBLEM] If neither flag set → default to Customer
    ↓
sync_xero_contact_to_erpnext() (xero_contacts.py:504-654)
    ↓
Create/update Customer and/or Supplier
    ↓
Sync ContactPersons and Addresses
```

### 2.3 Identified Issues

#### Issue 1: Sending Read-Only Fields (CRITICAL)

**Location**: [`xero_contacts.py:92-93`](cohenix-bench/apps/xero/xero/api/xero_contacts.py:92)

**Problem**: The code sends `IsCustomer` and `IsSupplier` in the payload, but these are read-only fields that Xero ignores or may reject.

**Impact**: 
- Confusing for developers who expect these to work
- May cause validation errors in future Xero API versions
- Gives false impression that contact type is being synced

**Fix**: Remove these fields from the payload entirely.

---

#### Issue 2: Using PUT Instead of POST (CRITICAL)

**Location**: [`xero_contacts.py:214`](cohenix-bench/apps/xero/xero/api/xero_contacts.py:214)

**Problem**: The code uses PUT for both create and update operations. According to Xero API:
- PUT errors if ContactName matches an existing contact
- POST creates or updates based on ContactID

**Impact**:
- If a contact with the same name exists in Xero (but different ContactID), PUT will fail
- Cannot reliably update existing contacts

**Fix**: Use POST when ContactID is provided (update), PUT only for creating new contacts.

---

#### Issue 3: Inbound Sync Defaults to Customer (CRITICAL)

**Location**: [`xero_contacts.py:493-501`](cohenix-bench/apps/xero/xero/api/xero_contacts.py:493)

**Problem**: When a Xero contact has neither `IsCustomer` nor `IsSupplier` set (which is the case for newly created contacts that haven't been used on invoices), the code defaults to creating a Customer.

**Impact**:
- A Supplier created in ERPNext, synced to Xero, then synced back becomes a Customer
- Contact type is not preserved on round-trip
- Creates duplicate entries (same contact as both Customer and Supplier)

**Fix**: 
1. Store the ERPNext DocType in a custom field on the Xero contact (using ContactNumber or a dedicated field)
2. On inbound sync, check this field first before falling back to IsCustomer/IsSupplier
3. If still unknown, skip the contact with a warning log

---

#### Issue 4: Double-Trigger Guard Too Broad (MAJOR)

**Location**: [`xero_contacts.py:26-29`](cohenix-bench/apps/xero/xero/api/xero_contacts.py:26)

**Problem**: The guard checks if `xero_sync_status == "Synced"` and returns early. This prevents:
- Re-syncing when data actually changes
- Syncing after fixing an error
- Manual re-sync requests

**Impact**:
- Once synced, contacts cannot be re-synced without manually clearing the status
- Data changes in ERPNext don't propagate to Xero

**Fix**: 
1. Track the last sync timestamp and data hash
2. Only skip if the document hasn't changed since last sync
3. Allow manual re-sync regardless of status

---

#### Issue 5: Missing ContactNumber Field (MAJOR)

**Location**: Outbound sync doesn't set `ContactNumber`

**Problem**: Xero's `ContactNumber` field is designed for external system identifiers. It's read-only in the Xero UI but can be set via API.

**Impact**:
- No reliable way to link Xero contacts back to ERPNext documents
- Name-based matching is unreliable (Xero says Name may not be unique in future)

**Fix**: Set `ContactNumber` to the ERPNext document name (e.g., "CUST-001" or "SUPP-001").

---

#### Issue 6: Missing Name Validation (MAJOR)

**Location**: [`xero_contacts.py:72-84`](cohenix-bench/apps/xero/xero/api/xero_contacts.py:72)

**Problem**: Xero has specific requirements for the Name field:
- Max 255 characters
- No angle brackets (`<`, `>`)
- No leading/trailing whitespace
- No repeating spaces

**Impact**: Invalid names cause sync failures with unclear error messages.

**Fix**: Add validation and sanitization before sync.

---

#### Issue 7: ContactPersons Limit Not Enforced (MINOR)

**Location**: [`xero_contacts.py:136-161`](cohenix-bench/apps/xero/xero/api/xero_contacts.py:136)

**Problem**: Xero allows max 5 ContactPersons per contact. The code doesn't enforce this limit.

**Impact**: Attempting to sync more than 5 contact persons may cause errors.

**Fix**: Limit to 5 contact persons in outbound payload.

---

#### Issue 8: No Incremental Sync Support (MINOR)

**Location**: [`xero_contacts.py:435`](cohenix-bench/apps/xero/xero/api/xero_contacts.py:435)

**Problem**: The inbound sync fetches all contacts every time. Xero supports `If-Modified-Since` header for incremental syncs.

**Impact**: Unnecessary API calls and processing for unchanged contacts.

**Fix**: Store last sync timestamp and use `If-Modified-Since` header.

---

## Part 3: Field Mapping Requirements

### 3.1 Outbound Field Mapping (ERPNext → Xero)

| ERPNext Field | Xero Field | Required | Notes |
|---------------|------------|----------|-------|
| `customer_name` / `supplier_name` | `Name` | **YES** | Max 255 chars, sanitize |
| `name` (doc name) | `ContactNumber` | Recommended | External system identifier |
| - | `ContactID` | For updates | Only when updating existing |
| Contact.first_name | `FirstName` | No | |
| Contact.last_name | `LastName` | No | |
| Contact.email_id | `EmailAddress` | No | Max 255 chars, no umlauts |
| `tax_id` | `TaxNumber` | No | Max 50 chars |
| `website` | `Website` | No | |
| Address.address_line1 | `Addresses[].AddressLine1` | No | |
| Address.city | `Addresses[].City` | No | |
| Address.state | `Addresses[].Region` | No | |
| Address.pincode | `Addresses[].PostalCode` | No | |
| Address.country | `Addresses[].Country` | No | |
| Contact.phone | `Phones[].PhoneNumber` (DEFAULT) | No | |
| Contact.mobile_no | `Phones[].PhoneNumber` (MOBILE) | No | |
| `disabled` | `ContactStatus` | No | ACTIVE/ARCHIVED |
| - | `IsCustomer` | **READ-ONLY** | Do NOT send |
| - | `IsSupplier` | **READ-ONLY** | Do NOT send |

### 3.2 Inbound Field Mapping (Xero → ERPNext)

| Xero Field | ERPNext Field | Notes |
|------------|---------------|-------|
| `ContactID` | `xero_contact_id` | Primary link |
| `ContactNumber` | Check for existing match | Link back to ERPNext doc |
| `Name` | `customer_name` / `supplier_name` | |
| `FirstName` | Contact.first_name | |
| `LastName` | Contact.last_name | |
| `EmailAddress` | Contact.email_id | |
| `TaxNumber` | `tax_id` | |
| `Website` | `website` | |
| `Addresses[]` | Address DocType | Create/update addresses |
| `Phones[]` | Contact.phone_nos | Create/update phone numbers |
| `ContactPersons[]` | Contact DocType | Create/update contact persons |
| `ContactStatus` | `disabled` | ACTIVE→0, ARCHIVED→1 |
| `DefaultCurrency` | `default_currency` | |
| `IsCustomer` | Decision: Create Customer? | **READ-ONLY, only set after invoice** |
| `IsSupplier` | Decision: Create Supplier? | **READ-ONLY, only set after invoice** |

---

## Part 4: Proposed Solution Architecture

### 4.1 Contact Type Preservation Strategy

The core problem is that Xero's `IsCustomer`/`IsSupplier` flags are read-only and only set after invoices are created. We need a way to preserve the contact type across sync cycles.

**Solution**: Use `ContactNumber` field to store ERPNext document type prefix.

```
ERPNext Customer "CUST-001" → Xero ContactNumber = "ERP:CUST-001"
ERPNext Supplier "SUPP-001" → Xero ContactNumber = "ERP:SUPP-001"
```

On inbound sync:
1. Check `ContactNumber` for "ERP:" prefix
2. Extract document type from prefix
3. Create correct ERPNext DocType
4. If no prefix, fall back to IsCustomer/IsSupplier
5. If still unknown, log warning and skip

### 4.2 Improved Double-Trigger Guard

Replace the current guard with a more sophisticated approach:

```python
def should_skip_sync(doc_type, doc_name, current_data_hash):
    """Check if sync should be skipped due to no changes."""
    last_sync_hash = frappe.db.get_value(doc_type, doc_name, "xero_data_hash")
    sync_status = frappe.db.get_value(doc_type, doc_name, "xero_sync_status")
    
    # Always allow re-sync if status is Error
    if sync_status == "Error":
        return False
    
    # Skip if data hasn't changed since last sync
    if last_sync_hash and last_sync_hash == current_data_hash:
        return True
    
    return False
```

### 4.3 User Feedback Mechanism

Provide clear feedback when sync is blocked due to missing/invalid data:

```python
VALIDATION_ERRORS = {
    "missing_name": {
        "message": "Contact name is required for Xero sync",
        "field": "customer_name",
        "action": "Please enter a name for this contact"
    },
    "invalid_name_chars": {
        "message": "Contact name contains invalid characters (angle brackets not allowed)",
        "field": "customer_name",
        "action": "Please remove < or > from the contact name"
    },
    "name_too_long": {
        "message": "Contact name exceeds 255 characters",
        "field": "customer_name",
        "action": "Please shorten the contact name"
    }
}
```

---

## Part 5: Implementation Plan

### Phase 1: Critical Fixes

1. **Remove IsCustomer/IsSupplier from outbound payload**
   - File: `xero_contacts.py:92-93`
   - Delete lines that set these fields

2. **Change PUT to POST for updates**
   - File: `xero_contacts.py:214`
   - Use POST when ContactID is provided

3. **Implement ContactNumber-based type preservation**
   - Set ContactNumber on outbound sync
   - Parse ContactNumber on inbound sync
   - Handle legacy contacts without ContactNumber

### Phase 2: Major Improvements

4. **Improve double-trigger guard**
   - Add data hash tracking
   - Allow re-sync on Error status
   - Add manual "Force Sync" option

5. **Add name validation and sanitization**
   - Validate length (max 255)
   - Remove angle brackets
   - Trim whitespace
   - Collapse multiple spaces

6. **Enforce ContactPersons limit**
   - Limit to 5 contact persons in payload

### Phase 3: Enhancements

7. **Add incremental sync support**
   - Store last sync timestamp
   - Use If-Modified-Since header

8. **Improve error messages and user feedback**
   - Map Xero validation errors to user-friendly messages
   - Add "Sync Issues" dashboard widget

---

## Part 6: Detailed Code Changes

### 6.1 Remove Read-Only Fields (Critical Fix #1)

**File**: `xero_contacts.py`

**Current Code** (lines 90-95):
```python
contact_payload = {
    "Name": name,
    "IsCustomer": True if doc_type == "Customer" else False,
    "IsSupplier": True if doc_type == "Supplier" else False,
    "ContactStatus": "ARCHIVED" if doc.get("disabled") else "ACTIVE",
}
```

**Proposed Code**:
```python
contact_payload = {
    "Name": name,
    "ContactStatus": "ARCHIVED" if doc.get("disabled") else "ACTIVE",
    # ContactNumber stores ERPNext doc type and name for reliable matching
    "ContactNumber": f"ERP:{doc_type[0]}:{doc_name}",  # e.g., "ERP:C:CUST-001"
}
```

### 6.2 Change PUT to POST (Critical Fix #2)

**File**: `xero_contacts.py`

**Current Code** (line 214):
```python
response = xero_request("PUT", "Contacts", data={"Contacts": [contact_payload]})
```

**Proposed Code**:
```python
# Use POST for updates (when ContactID known), PUT for new contacts
method = "POST" if xero_contact_id else "PUT"
response = xero_request(method, "Contacts", data={"Contacts": [contact_payload]})
```

### 6.3 Implement ContactNumber-Based Type Preservation (Critical Fix #3)

**File**: `xero_contacts.py`

**New function** to parse ContactNumber:
```python
def parse_erpnext_reference(contact_number):
    """Parse ERPNext reference from Xero ContactNumber.
    
    Returns: tuple (doc_type, doc_name) or (None, None) if not found
    """
    if not contact_number or not contact_number.startswith("ERP:"):
        return None, None
    
    parts = contact_number.split(":")
    if len(parts) != 3:
        return None, None
    
    type_code, doc_name = parts[1], parts[2]
    doc_type = "Customer" if type_code == "C" else "Supplier" if type_code == "S" else None
    return doc_type, doc_name
```

**Modified inbound sync** (lines 471-501):
```python
def process_xero_contact(xero_contact_data):
    """Creates or updates an ERPNext Customer/Supplier from Xero contact data."""
    xero_contact_id = xero_contact_data.get("ContactID")
    contact_name = xero_contact_data.get("Name")
    contact_number = xero_contact_data.get("ContactNumber")

    if not xero_contact_id or not contact_name:
        log_xero_error(message=f"Skipping Xero contact due to missing ID or Name", status="Info")
        return

    # Priority 1: Check ContactNumber for ERPNext reference
    doc_type, doc_name = parse_erpnext_reference(contact_number)
    if doc_type and doc_name:
        # Found ERPNext reference - sync to correct DocType
        sync_xero_contact_to_erpnext(xero_contact_data, doc_type)
        return

    # Priority 2: Check IsCustomer/IsSupplier flags
    is_customer = xero_contact_data.get("IsCustomer", False)
    is_supplier = xero_contact_data.get("IsSupplier", False)

    if is_customer:
        sync_xero_contact_to_erpnext(xero_contact_data, "Customer")
    if is_supplier:
        sync_xero_contact_to_erpnext(xero_contact_data, "Supplier")

    if not is_customer and not is_supplier:
        # No type information - log warning and skip
        log_xero_error(
            message=f"Xero Contact {contact_name} ({xero_contact_id}) has no type information. "
                    f"Cannot determine if Customer or Supplier. Skipping.",
            status="Warning",
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact"
        )
```

### 6.4 Improve Double-Trigger Guard (Major Fix #4)

**File**: `xero_contacts.py`

**New helper function**:
```python
def compute_data_hash(doc):
    """Compute hash of relevant fields to detect changes."""
    import hashlib
    data = f"{doc.get('customer_name') or doc.get('supplier_name')}|{doc.get('tax_id')}|{doc.get('website')}|{doc.get('disabled')}"
    return hashlib.md5(data.encode()).hexdigest()
```

**Modified guard** (lines 25-29):
```python
def enqueue_sync_contact(doc_name, doc_type=None):
    # ... existing argument handling ...

    # Check if sync should be skipped
    sync_status = frappe.db.get_value(doc_type, doc_name, "xero_sync_status")
    
    # Allow re-sync if status is Error or Pending
    if sync_status in ("Error", "Pending"):
        pass  # Continue to sync
    elif sync_status == "Synced":
        # Check if data has changed
        doc = frappe.get_doc(doc_type, doc_name)
        current_hash = compute_data_hash(doc)
        stored_hash = frappe.db.get_value(doc_type, doc_name, "xero_data_hash") or ""
        
        if current_hash == stored_hash:
            # No changes since last sync, skip
            return
    
    # Store current hash before sync
    frappe.db.set_value(doc_type, doc_name, "xero_data_hash", compute_data_hash(doc), update_modified=False)
    
    # ... rest of function ...
```

### 6.5 Add Name Validation (Major Fix #5)

**File**: `xero_contacts.py`

**New validation function**:
```python
def validate_and_sanitize_name(name, doc_type, doc_name):
    """Validate and sanitize contact name for Xero API.
    
    Xero requirements:
    - Max 255 characters
    - No angle brackets
    - No leading/trailing whitespace
    - No repeating spaces
    
    Returns: tuple (sanitized_name, error_message or None)
    """
    import re
    
    if not name or not str(name).strip():
        return None, f"Contact name is required for {doc_type} {doc_name}"
    
    name = str(name).strip()
    
    # Check for angle brackets
    if '<' in name or '>' in name:
        # Sanitize by removing
        name = name.replace('<', '').replace('>', '').strip()
        if not name:
            return None, f"Contact name for {doc_type} {doc_name} contains only invalid characters"
    
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name)
    
    # Check length
    if len(name) > 255:
        return None, f"Contact name for {doc_type} {doc_name} exceeds 255 characters (current: {len(name)})"
    
    return name, None
```

**Usage in sync function**:
```python
# Replace lines 72-84
raw_name = doc.get("customer_name") or doc.get("supplier_name")
name, error = validate_and_sanitize_name(raw_name, doc_type, doc_name)

if error:
    log_xero_error(
        message=error,
        status="Warning",
        erpnext_doc_type=doc_type,
        erpnext_doc_name=doc_name,
        category="Validation"
    )
    frappe.db.set_value(doc_type, doc_name, {"xero_sync_status": "Error"}, update_modified=False)
    frappe.db.commit()
    return
```

---

## Part 7: Fing Strategy

### 7.1 Unit Tests

1. **Test name validation**
   - Empty name → error
   - Name with angle brackets → sanitized
   - Name > 255 chars → error
   - Name with multiple spaces → collapsed

2. **Test ContactNumber parsing**
   - Valid format → correct doc_type/doc_name
   - Invalid format → None, None
   - Missing ContactNumber → None, None

3. **Test data hash computation**
   - Same data → same hash
   - Different data → different hash

### 7.2 Integration Tests

1. **Outbound sync**
   - Create new Customer → verify ContactNumber set
   - Update existing Customer → verify POST used
   - Create Supplier → verify ContactNumber prefix "S"
   - Sync with invalid name → verify error logged

2. **Inbound sync**
   - Contact with ContactNumber → correct DocType created
   - Contact without ContactNumber but IsCustomer=True → Customer created
   - Contact without type info → skipped with warning

3. **Round-trip sync**
   - Create Customer in ERPNext → sync to Xero → sync back → still Customer
   - Create Supplier in ERPNext → sync to Xero → sync back → still Supplier

### 7.3 Manual Testing Checklist

- [ ] Create new Customer, verify sync to Xero
- [ ] Create new Supplier, verify sync to Xero
- [ ] Update Customer name, verify re-sync
- [ ] Update Customer address, verify re-sync
- [ ] Create Customer with invalid name chars, verify error message
- [ ] Sync from Xero with existing contacts
- [ ] Verify no duplicate contacts created
- [ ] Verify ContactNumber field in Xero

---

## Part 8: Migration Considerations

### 8.1 Existing Contacts

Contacts already synced without ContactNumber will need migration:

1. **Identify contacts without ContactNumber**
   ```sql
   SELECT name, xero_contact_id FROM `tabCustomer` WHERE xero_contact_id IS NOT NULL;
   SELECT name, xero_contact_id FROM `tabSupplier` WHERE xero_contact_id IS NOT NULL;
   ```

2. **Update Xero contacts with ContactNumber**
   - Run a one-time migration script
   - For each existing contact, send POST to Xero with ContactNumber set

3. **Migration script** (to be created):
   ```python
   def migrate_contact_numbers():
       """One-time migration to add ContactNumber to existing Xero contacts."""
       for doc_type in ["Customer", "Supplier"]:
           for doc_name in frappe.get_all(doc_type, {"xero_contact_id": ["!=", ""]}, pluck="name"):
               # Re-sync to add ContactNumber
               sync_contact_to_xero(doc_name, doc_type)
   ```

### 8.2 Custom Field Addition

Add `xero_data_hash` field to Customer and Supplier DocTypes:

```python
# In setup/custom_fields.py
xero_data_hash_field = {
    "fieldname": "xero_data_hash",
    "label": "Xero Data Hash",
    "fieldtype": "Data",
    "length": 32,
    "read_only": 1,
    "hidden": 1,
}
```

---

## Part 9: Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Existing contacts lose type on inbound sync | High | High | ContactNumber migration before enabling inbound sync |
| PUT errors for contacts with same name | Medium | Medium | Use POST for updates |
| Name validation rejects valid names | Low | Low | Careful regex, log all rejections |
| ContactNumber format conflicts with user data | Low | Low | Use "ERP:" prefix to avoid conflicts |
| Double-trigger guard too permissive | Low | Medium | Test thoroughly, add logging |

---

## Appendix A: Xero API Reference

### Contacts Endpoint

- **URL**: `https://api.xero.com/api.xro/2.0/Contacts`
- **Methods**: GET, POST, PUT
- **Rate Limit**: 60 requests/minute/tenant

### Required Fields for POST/PUT

| Field | Required | Notes |
|-------|----------|-------|
| Name | **YES** | Max 255 chars |

### Read-Only Fields

| Field | Set By |
|-------|--------|
| ContactID | Xero (on create) |
| IsCustomer | Xero (when AR invoice created) |
| IsSupplier | Xero (when AP invoice created) |
| UpdatedDateUTC | Xero (on any change) |

---

## Appendix B: Current vs Proposed Field Mapping

### Outbound (ERPNext → Xero)

| Field | Current | Proposed | Change |
|-------|---------|----------|--------|
| Name | ✅ Sent | ✅ Sent | Add validation |
| ContactID | ✅ Sent (update) | ✅ Sent (update) | No change |
| ContactNumber | ❌ Not sent | ✅ Sent | **NEW** |
| FirstName | ✅ Sent | ✅ Sent | No change |
| LastName | ✅ Sent | ✅ Sent | No change |
| EmailAddress | ✅ Sent | ✅ Sent | No change |
| TaxNumber | ✅ Sent | ✅ Sent | No change |
| Website | ✅ Sent | ✅ Sent | No change |
| Addresses | ✅ Sent | ✅ Sent | No change |
| Phones | ✅ Sent | ✅ Sent | No change |
| ContactStatus | ✅ Sent | ✅ Sent | No change |
| IsCustomer | ❌ Sent (wrong) | ❌ Not sent | **REMOVE** |
| IsSupplier | ❌ Sent (wrong) | ❌ Not sent | **REMOVE** |

### Inbound (Xero → ERPNext)

| Field | Current | Proposed | Change |
|-------|---------|----------|--------|
| ContactID | ✅ Mapped | ✅ Mapped | No change |
| ContactNumber | ❌ Not used | ✅ Parsed for type | **NEW** |
| Name | ✅ Mapped | ✅ Mapped | No change |
| IsCustomer | ✅ Used for type | ✅ Fallback only | Lower priority |
| IsSupplier | ✅ Used for type | ✅ Fallback only | Lower priority |
| Default to Customer | ❌ Yes | ❌ No, skip instead | **CHANGE** |

---

*Document Version: 1.0*
*Created: 2026-02-12*
*Author: AI Assistant (Kilo Code)*
