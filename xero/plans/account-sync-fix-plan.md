# Account Sync Fix Plan

## Executive Summary

The current account synchronization implementation has a **critical gap**: the outbound sync (`sync_accounts_to_xero`) is a **placeholder function** that does nothing. This means:
- Accounts created in ERPNext are **never synced to Xero**
- Account updates in ERPNext are **never reflected in Xero**
- Bidirectional sync **does not exist** for accounts

This document analyzes the current implementation against the Xero Accounts API and provides a comprehensive fix plan.

---

## Part 1: Xero Accounts API Analysis

### API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/Accounts` | Retrieve all accounts |
| GET | `/Accounts/{AccountID}` | Retrieve specific account |
| PUT | `/Accounts` | Create new account |
| POST | `/Accounts/{AccountID}` | Update existing account |
| DELETE | `/Accounts/{AccountID}` | Delete account (limited) |

### Field Specifications

#### Required Fields for PUT (Create)

| Field | Max Length | Notes |
|-------|------------|-------|
| `Code` | 10 | Customer-defined alphanumeric code |
| `Name` | 150 | Account name |
| `Type` | - | Must be valid Xero Account Type |
| `BankAccountNumber` | - | Required ONLY for Type=BANK |

#### Optional Fields for PUT/POST

| Field | Max Length | Notes |
|-------|------------|-------|
| `Status` | - | ACTIVE or ARCHIVED |
| `Description` | 4000 | Not valid for bank accounts |
| `BankAccountType` | - | Bank accounts only |
| `CurrencyCode` | - | Bank accounts only |
| `TaxType` | - | Valid Xero TaxType |
| `EnablePaymentsToAccount` | - | Boolean |
| `ShowInExpenseClaims` | - | Boolean |
| `AddToWatchlist` | - | POST only, not PUT |

#### Read-Only Fields (Returned by GET, Cannot Set)

| Field | Notes |
|-------|-------|
| `AccountID` | Xero-generated UUID |
| `Class` | Asset/Equity/Expense/Liability/Revenue |
| `SystemAccount` | DEBTORS/CREDITORS/etc. |
| `ReportingCode*` | Reporting configuration |
| `HasAttachments` | Boolean |
| `UpdatedDateUTC` | Last modified timestamp |

### Xero Account Types

```
BANK, CURRENT, CURRLIAB, DEPRECIATN, DIRECTCOSTS, EQUITY, 
EXPENSE, FIXED, INVENTORY, LIABILITY, NONCURRENT, OTHERINCOME, 
OVERHEADS, PREPAYMENT, REVENUE, SALES, TERMLIAB
```

### API Limitations

1. **One at a time**: Cannot batch create/update accounts
2. **No PayPal creation**: Cannot create PayPal accounts via API
3. **No BankAccountType update**: Cannot change bank account type after creation
4. **Archive restrictions**: Cannot update Status to ARCHIVED while updating other fields
5. **Delete restrictions**: Can only delete if:
   - Not a system account
   - Not used in any transactions
   - Not linked to other systems (Fixed Assets, Payment Services)

### Key Differences from Contacts API

| Aspect | Contacts API | Accounts API |
|--------|--------------|--------------|
| Create Method | PUT | PUT |
| Update Method | POST | POST |
| ID in URL | No | Yes (required for POST) |
| ID in Body | Optional | Required for POST |
| Unique Key | ContactName | Code |

---

## Part 2: Current Implementation Analysis

### File: [`xero_accounts.py`](cohenix-bench/apps/xero/xero/api/xero_accounts.py)

#### Inbound Sync (Xero → ERPNext)

**Function**: `sync_accounts_from_xero()` (Lines 35-99)

| Aspect | Current Implementation | Issue |
|--------|------------------------|-------|
| Trigger | Daily scheduled task | OK |
| Direction check | Checks `enable_sync_from_xero` | OK |
| Filtering | Skips system accounts, non-payment accounts | May be too restrictive |
| Matching | By `account_name` only | Should check `xero_account_id` first |
| Type mapping | `XERO_ACCOUNT_TYPE_MAP` | Missing reverse mapping |
| Fields synced | Code, Name, Type, Currency | Missing Description, Status, TaxType |

**Function**: `process_xero_account()` (Lines 102-215)

| Step | Current Code | Issue |
|------|--------------|-------|
| 1. Extract fields | Gets ID, Code, Name, Type | Missing Description, Status |
| 2. Type mapping | Looks up in `XERO_ACCOUNT_TYPE_MAP` | OK |
| 3. Name construction | `{Code} - {Name}` truncated to 140 | May cause duplicates |
| 4. Find existing | By `account_name` + `company` | Should prioritize `xero_account_id` |
| 5. Create parent | Attempts to create root account | Good, but may fail |
| 6. Save | Sets `xero_account_id` | Missing `xero_sync_status`, `xero_data_hash` |

#### Outbound Sync (ERPNext → Xero)

**Function**: `sync_accounts_to_xero()` (Lines 535-563)

```python
def sync_accounts_to_xero():
    """
    Sync ERPNext Accounts to Xero (placeholder function).
    This is a complex operation due to potential conflicts and different chart structures.
    For now, this is a placeholder that logs the operation.
    """
    # TODO: Implement actual account sync to Xero
    # This would involve:
    # 1. Getting ERPNext accounts that need to be synced
    # 2. Mapping ERPNext account types to Xero account types
    # 3. Creating/updating accounts in Xero via API
    # 4. Handling conflicts and validation errors
    
    return True
```

**Status**: ❌ **NOT IMPLEMENTED**

#### DocType Hooks

**File**: [`hooks.py`](cohenix-bench/apps/xero/xero/hooks.py)

```python
doc_events = {
    "Sales Invoice": {...},
    "Customer": {"on_update": "xero.api.xero_contacts.enqueue_sync_contact"},
    "Supplier": {"on_update": "xero.api.xero_contacts.enqueue_sync_contact"},
    # Account is NOT hooked!
}
```

**Status**: ❌ **NO HOOK FOR ACCOUNT**

#### Custom Fields

**File**: [`custom_fields.py`](cohenix-bench/apps/xero/xero/setup/custom_fields.py)

| Field | Type | Purpose |
|-------|------|---------|
| `xero_account_id` | Data | Xero UUID |
| `xero_sync_status` | Select | Pending/Synced/Error/Skipped |
| `xero_last_account_sync` | Datetime | Last sync timestamp |

**Missing**: `xero_data_hash` (used in contacts for change detection)

---

## Part 3: Gap Analysis

### Critical Gaps

| # | Gap | Impact | Severity |
|---|-----|--------|----------|
| 1 | Outbound sync not implemented | ERPNext accounts never sync to Xero | **CRITICAL** |
| 2 | No Account hook in doc_events | No automatic trigger for sync | **CRITICAL** |
| 3 | No reverse type mapping | Cannot determine Xero type from ERPNext | **HIGH** |
| 4 | No data hash tracking | Cannot detect changes, causes re-sync loops | **HIGH** |
| 5 | Match by name only | May create duplicates or miss updates | **MEDIUM** |

### Field Mapping Gaps

| Xero Field | ERPNext Field | Current | Required |
|------------|---------------|---------|----------|
| Code | account_number | ✅ Mapped | ✅ |
| Name | account_name | ✅ Mapped | ✅ |
| Type | root_type + account_type | ✅ Mapped (inbound only) | Need reverse |
| Description | - | ❌ Not mapped | Optional |
| Status | disabled | ❌ Not mapped | Should map |
| TaxType | - | ❌ Not mapped | Optional |
| EnablePaymentsToAccount | - | ❌ Not mapped | Should map |
| BankAccountNumber | bank_account_no | ❌ Not mapped | Required for BANK |
| CurrencyCode | currency | ✅ Mapped | Bank accounts |

### Type Mapping Gaps

**Current Inbound Mapping** (Xero → ERPNext):

```python
XERO_ACCOUNT_TYPE_MAP = {
    "BANK": {"root_type": "Asset", "account_type": "Bank"},
    "CURRENT": {"root_type": "Asset", "account_type": "Receivable"},
    # ... etc
}
```

**Missing Outbound Mapping** (ERPNext → Xero):

Need to create reverse mapping from ERPNext `root_type` + `account_type` to Xero `Type`.

---

## Part 4: Implementation Plan

### Phase 1: Add Missing Infrastructure

#### 1.1 Add `xero_data_hash` Custom Field

**File**: `setup/custom_fields.py`

```python
"Account": [
    # ... existing fields ...
    {
        "fieldname": "xero_data_hash",
        "fieldtype": "Data",
        "label": "Xero Data Hash",
        "length": 32,
        "no_copy": 1,
        "read_only": 1,
        "print_hide": 1,
        "report_hide": 1,
        "hidden": 1,
        "insert_after": "xero_sync_status"
    },
]
```

#### 1.2 Add Account DocType Hook

**File**: `hooks.py`

```python
doc_events = {
    # ... existing ...
    "Account": {
        "on_update": "xero.api.xero_accounts.enqueue_sync_account"
    },
}
```

### Phase 2: Implement Outbound Sync

#### 2.1 Create Reverse Type Mapping

```python
# Mapping from ERPNext to Xero Account Types
ERPNEXT_TO_XERO_TYPE_MAP = {
    # root_type, account_type -> Xero Type
    ("Asset", "Bank"): "BANK",
    ("Asset", "Receivable"): "CURRENT",
    ("Asset", "Payable"): "CURRLIAB",  # Actually Liability
    ("Asset", "Accumulated Depreciation"): "DEPRECIATN",
    ("Asset", "Fixed Asset"): "FIXED",
    ("Asset", "Stock"): "INVENTORY",
    ("Asset", "Prepaid Expense"): "PREPAYMENT",
    ("Asset", "Asset"): "NONCURRENT",  # Non-current asset
    ("Liability", "Payable"): "CURRLIAB",
    ("Liability", "Liability"): "TERMLIAB",  # Long-term
    ("Equity", "Equity"): "EQUITY",
    ("Income", "Income Account"): "REVENUE",
    ("Income", "Sales"): "SALES",
    ("Income", "Other Income"): "OTHERINCOME",
    ("Expense", "Direct Expense"): "DIRECTCOSTS",
    ("Expense", "Expense Account"): "EXPENSE",
    ("Expense", "Indirect Expense"): "OVERHEADS",
    # Default fallback
    (None, None): "EXPENSE",  # Safe default
}
```

#### 2.2 Implement `enqueue_sync_account`

```python
@frappe.whitelist()
def enqueue_sync_account(doc, method=None):
    """
    Enqueue account sync to Xero when Account is updated.
    Called via doc_events hook on Account.on_update.
    """
    if isinstance(doc, str):
        doc = frappe.get_doc("Account", doc)
    
    settings = get_xero_settings()
    if not settings or not settings.enable_xero_sync:
        return
    
    if not settings.enable_sync_to_xero:
        return
    
    # Skip group accounts (only sync ledger accounts)
    if doc.is_group:
        return
    
    # Skip if already synced and no changes
    if doc.xero_sync_status == "Synced" and not account_data_changed(doc):
        return
    
    # Enqueue the actual sync
    frappe.enqueue(
        "xero.api.xero_accounts.sync_account_to_xero",
        queue="short",
        account_name=doc.name
    )
```

#### 2.3 Implement `sync_account_to_xero`

```python
def sync_account_to_xero(account_name):
    """
    Sync a single ERPNext Account to Xero.
    Creates new account or updates existing one.
    """
    doc = frappe.get_doc("Account", account_name)
    settings = get_xero_settings()
    
    # Build Xero payload
    payload = build_xero_account_payload(doc, settings)
    
    if doc.xero_account_id:
        # Update existing - use POST with AccountID
        response = xero_request(
            "POST", 
            f"Accounts/{doc.xero_account_id}",
            data={"Accounts": [payload]}
        )
    else:
        # Create new - use PUT
        response = xero_request(
            "PUT",
            "Accounts",
            data={"Accounts": [payload]}
        )
    
    # Process response
    if response and response.get("Accounts"):
        xero_account = response["Accounts"][0]
        doc.db_set({
            "xero_account_id": xero_account.get("AccountID"),
            "xero_sync_status": "Synced",
            "xero_data_hash": compute_account_hash(doc),
            "xero_last_account_sync": now_datetime()
        })
```

#### 2.4 Implement `build_xero_account_payload`

```python
def build_xero_account_payload(doc, settings):
    """
    Build Xero API payload from ERPNext Account.
    Validates required fields and maps types.
    """
    # Get Xero Type
    xero_type = get_xero_type_from_erpnext(doc.root_type, doc.account_type)
    if not xero_type:
        raise Exception(f"Cannot map ERPNext account type ({doc.root_type}, {doc.account_type}) to Xero")
    
    payload = {
        "Code": validate_account_code(doc.account_number or doc.name),
        "Name": validate_account_name(doc.account_name),
        "Type": xero_type,
    }
    
    # Add AccountID for updates
    if doc.xero_account_id:
        payload["AccountID"] = doc.xero_account_id
    
    # Optional fields
    if doc.disabled:
        payload["Status"] = "ARCHIVED"
    
    # Bank account specific
    if xero_type == "BANK":
        if doc.bank_account_no:
            payload["BankAccountNumber"] = doc.bank_account_no
        if doc.currency:
            payload["CurrencyCode"] = doc.currency
    
    return payload
```

### Phase 3: Improve Inbound Sync

#### 3.1 Fix Matching Logic

```python
def find_matching_erpnext_account(xero_account_id, xero_code, xero_name, company):
    """
    Find matching ERPNext account using multiple strategies.
    Priority: xero_account_id > account_number > account_name
    """
    # 1. Try exact match by xero_account_id
    if xero_account_id:
        match = frappe.db.get_value("Account", 
            {"xero_account_id": xero_account_id, "company": company}, "name")
        if match:
            return match, "id"
    
    # 2. Try match by account_number (Xero Code)
    if xero_code:
        match = frappe.db.get_value("Account",
            {"account_number": xero_code, "company": company}, "name")
        if match:
            return match, "code"
    
    # 3. Try match by constructed name
    constructed_name = f"{xero_code} - {xero_name}"[:140]
    match = frappe.db.get_value("Account",
        {"account_name": constructed_name, "company": company}, "name")
    if match:
        return match, "name"
    
    return None, None
```

#### 3.2 Add Data Hash for Change Detection

```python
def compute_account_hash(doc):
    """Compute hash of account data for change detection."""
    import hashlib
    
    data = f"{doc.account_number}|{doc.account_name}|{doc.root_type}|{doc.account_type}|{doc.currency}|{doc.disabled}"
    return hashlib.md5(data.encode()).hexdigest()

def account_data_changed(doc):
    """Check if account data has changed since last sync."""
    if not doc.xero_data_hash:
        return True
    return compute_account_hash(doc) != doc.xero_data_hash
```

### Phase 4: Validation and Error Handling

#### 4.1 Account Code Validation

```python
def validate_account_code(code):
    """
    Validate and sanitize account code for Xero.
    - Max 10 characters
    - Alphanumeric only
    """
    if not code:
        raise ValueError("Account code is required")
    
    # Truncate to 10 chars
    code = str(code)[:10]
    
    # Remove invalid characters (keep alphanumeric)
    import re
    code = re.sub(r'[^a-zA-Z0-9]', '', code)
    
    if not code:
        raise ValueError("Account code must contain alphanumeric characters")
    
    return code
```

#### 4.2 Account Name Validation

```python
def validate_account_name(name):
    """
    Validate and sanitize account name for Xero.
    - Max 150 characters
    - No special restrictions mentioned
    """
    if not name:
        raise ValueError("Account name is required")
    
    # Truncate to 150 chars
    return str(name)[:150].strip()
```

### Phase 5: User Feedback

#### 5.1 Missing Field Notifications

When required fields are missing for sync:

```python
def notify_missing_account_fields(doc, missing_fields):
    """Create notification for missing required fields."""
    frappe.publish_realtime(
        "xero_sync_warning",
        {
            "message": f"Account '{doc.name}' cannot sync to Xero. Missing: {', '.join(missing_fields)}",
            "account": doc.name,
            "missing_fields": missing_fields
        },
        user=frappe.session.user
    )
```

#### 5.2 Sync Status Dashboard

Add Account sync status to the Xero Sync Dashboard.

---

## Part 5: Testing Plan

### Unit Tests

1. **Type Mapping Tests**
   - Test all ERPNext type combinations map to valid Xero types
   - Test fallback behavior

2. **Validation Tests**
   - Test code truncation at 10 chars
   - Test name truncation at 150 chars
   - Test missing required fields

3. **Hash Tests**
   - Test hash computation
   - Test change detection

### Integration Tests

1. **Outbound Sync Tests**
   - Create new account in ERPNext → verify created in Xero
   - Update account in ERPNext → verify updated in Xero
   - Archive account in ERPNext → verify archived in Xero

2. **Inbound Sync Tests**
   - Create account in Xero → verify created in ERPNext
   - Update account in Xero → verify updated in ERPNext
   - Archive account in Xero → verify disabled in ERPNext

3. **Round-Trip Tests**
   - Create in ERPNext → sync to Xero → modify in Xero → sync back
   - Create in Xero → sync to ERPNext → modify in ERPNext → sync back

---

## Part 6: Risk Assessment

### High Risk Areas

| Area | Risk | Mitigation |
|------|------|------------|
| Type mapping | Wrong type causes sync failure | Comprehensive mapping + validation |
| Code conflicts | Duplicate codes in Xero | Check before create, use unique codes |
| Bank accounts | Missing BankAccountNumber | Require for BANK type, skip otherwise |
| System accounts | Cannot modify in Xero | Skip system accounts in outbound |
| Archived accounts | Cannot update archived accounts | Check status before update |

### Breaking Changes

| Change | Impact | Migration |
|--------|--------|-----------|
| Add `xero_data_hash` field | New custom field | Run `setup_custom_fields` |
| Add Account hook | All account updates trigger sync | Check settings before enqueuing |
| Change matching logic | May find different matches | Log all matches for audit |

---

## Part 7: Implementation Checklist

### Must Have (Critical)

- [ ] Add `xero_data_hash` custom field
- [ ] Add Account `on_update` hook
- [ ] Implement `enqueue_sync_account`
- [ ] Implement `sync_account_to_xero`
- [ ] Implement `build_xero_account_payload`
- [ ] Create reverse type mapping `ERPNEXT_TO_XERO_TYPE_MAP`
- [ ] Add account code validation (max 10 chars)
- [ ] Add account name validation (max 150 chars)
- [ ] Fix inbound matching to check `xero_account_id` first

### Should Have (Important)

- [ ] Add data hash change detection
- [ ] Map `Status` ↔ `disabled`
- [ ] Handle bank account special fields
- [ ] Add sync status to dashboard
- [ ] Add missing field notifications

### Nice to Have (Enhancement)

- [ ] Map `Description` field
- [ ] Map `TaxType` field
- [ ] Map `EnablePaymentsToAccount` field
- [ ] Handle account hierarchy/parenting
- [ ] Bulk sync existing accounts

---

## Summary

The account sync implementation requires significant work to achieve bidirectional sync:

1. **Outbound sync is completely missing** - must be implemented from scratch
2. **Inbound sync has issues** - matching logic and change detection need improvement
3. **Type mapping is incomplete** - reverse mapping needed for outbound
4. **Validation is missing** - Xero has strict field limits that must be enforced

The implementation should follow the same patterns established in the contact sync fix:
- Data hash for change detection
- Proper validation before sync
- POST for updates, PUT for creates
- Comprehensive error handling and logging
