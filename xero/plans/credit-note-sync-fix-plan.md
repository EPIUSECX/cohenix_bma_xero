# Credit Note Sync Fix Plan

## Executive Summary

The current Credit Note sync implementation has **15 critical issues** that prevent reliable bi-directional syncing between ERPNext and Xero. This plan addresses all issues in 3 phases, following the proven patterns from the Invoice sync implementation.

---

## Current Implementation Analysis

### File: `xero/api/xero_credit_notes.py`

| Function | Purpose | Issues |
|----------|---------|--------|
| `enqueue_sync_return()` | Hook entry point for returns | No double-trigger guard |
| `sync_return_to_xero()` | Outbound sync (ERPNext → Xero) | Wrong HTTP method, no validation, no change detection |
| `sync_credit_notes_from_xero()` | Inbound sync scheduler | Missing status handling |
| `process_xero_credit_note()` | Process individual Xero CN | No hash storage, no allocations handling |

### Hook Configuration (`hooks.py`)

```python
# Current hooks (lines 142-149)
doc_events = {
    "Sales Invoice": {
        "on_submit": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
        "on_cancel": "xero.api.xero_invoices.enqueue_void_invoice"
    },
    "Purchase Invoice": {
        "on_submit": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
        "on_cancel": "xero.api.xero_invoices.enqueue_void_invoice"
    },
}
```

**Note**: The `enqueue_sync_invoice_or_return()` correctly routes returns to `enqueue_sync_return()`, but there's no `on_cancel` handling specific to credit notes.

---

## Issues Identified

### Phase 1: Critical Issues (Must Fix)

#### Issue 1: Wrong HTTP Method
- **Location**: `sync_return_to_xero()`, line 102
- **Current**: `xero_request("PUT", "CreditNotes", ...)`
- **Problem**: PUT is only for creating NEW credit notes or allocations. POST is required for both create AND update.
- **Xero API Reference**: 
  > "POST CreditNotes - Use this method to create or update a credit note"
  > "PUT CreditNotes - Creating CreditNotes via PUT uses the same request format as via POST"
- **Fix**: Change to POST for all credit note sync operations

#### Issue 2: No Double-Trigger Guard
- **Location**: `enqueue_sync_return()`, lines 11-23
- **Current**: Always enqueues sync job without checking sync status
- **Problem**: When syncing FROM Xero, the `on_submit` hook fires and creates an infinite loop
- **Fix**: Add guard checking `xero_sync_status == "Synced"` and hash comparison

#### Issue 3: No Field Validation
- **Location**: `sync_return_to_xero()`, lines 77-96
- **Current**: No validation on Description, CreditNoteNumber, Reference
- **Problem**: Xero API has strict limits:
  - Description: max 4000 chars
  - CreditNoteNumber: max 255 chars (ACCRECCREDIT must be unique)
  - Reference: max 255 chars (ACCRECCREDIT only)
- **Fix**: Add validation functions similar to invoice sync

#### Issue 4: Missing LineAmountTypes
- **Location**: `sync_return_to_xero()`, line 89-96
- **Current**: Not included in payload
- **Problem**: Xero requires this field to determine tax handling
- **Fix**: Add `"LineAmountTypes": "Exclusive"` (ERPNext default)

#### Issue 5: No on_cancel Hook for Credit Notes
- **Location**: `hooks.py`
- **Current**: `enqueue_void_invoice()` handles invoices but not credit notes
- **Problem**: Cancelling a return in ERPNext doesn't void/delete the credit note in Xero
- **Fix**: Create `enqueue_void_credit_note()` and `void_credit_note_in_xero()` functions

---

### Phase 2: Important Issues (Should Fix)

#### Issue 6: No Change Detection
- **Location**: `sync_return_to_xero()`
- **Current**: No `xero_data_hash` field usage
- **Problem**: Every sync makes an API call even if data hasn't changed
- **Fix**: Add hash computation and comparison (pattern from invoice sync)

#### Issue 7: No ItemCode Support
- **Location**: `sync_return_to_xero()`, lines 77-86
- **Current**: No ItemCode in line items
- **Problem**: Items not linked to Xero inventory
- **Fix**: Add ItemCode when item is synced to Xero

#### Issue 8: No Discount Support
- **Location**: `sync_return_to_xero()`, lines 77-86
- **Current**: No discount handling
- **Problem**: Discounts not synced to Xero
- **Fix**: Add DiscountRate to line items

#### Issue 9: No TaxType Mapping
- **Location**: `sync_return_to_xero()`, lines 77-86
- **Current**: No tax type in line items
- **Problem**: Tax not properly mapped to Xero
- **Fix**: Add TaxType mapping using existing `map_erpnext_tax_to_xero()`

#### Issue 10: Missing Reference Field
- **Location**: `sync_return_to_xero()`
- **Current**: Not included in payload
- **Problem**: ACCRECCREDIT supports Reference field (max 255 chars)
- **Fix**: Add Reference field for Sales Invoice returns

---

### Phase 3: Enhancement Issues (Nice to Have)

#### Issue 11: No Status Handling in Inbound Sync
- **Location**: `process_xero_credit_note()`, lines 199-359
- **Current**: Creates all documents as Draft
- **Problem**: Should handle DRAFT, AUTHORISED, PAID, VOIDED statuses
- **Fix**: Map Xero status to appropriate ERPNext docstatus

#### Issue 12: No Allocations Handling
- **Location**: `process_xero_credit_note()`
- **Current**: Doesn't process Allocations array
- **Problem**: Credit note allocations to invoices not tracked
- **Fix**: Store allocation info in remarks or custom field

#### Issue 13: No RemainingCredit Tracking
- **Location**: `process_xero_credit_note()`
- **Current**: Doesn't track RemainingCredit
- **Problem**: Can't determine if credit note is fully applied
- **Fix**: Store in custom field or remarks

#### Issue 14: No Discount Support in Inbound Sync
- **Location**: `process_xero_credit_note()`, lines 294-319
- **Current**: Doesn't handle DiscountRate from Xero
- **Problem**: Discounts not reflected in ERPNext
- **Fix**: Add discount_percentage to line items

#### Issue 15: No Retry Logic
- **Location**: `sync_return_to_xero()`
- **Current**: No retry decorator
- **Problem**: Transient API failures cause permanent sync failures
- **Fix**: Add `@retry_with_exponential_backoff` decorator

---

## Xero Credit Notes API Reference

### Key Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/CreditNotes` | Retrieve all credit notes |
| GET | `/CreditNotes/{id}` | Retrieve specific credit note |
| POST | `/CreditNotes` | Create OR update credit note |
| PUT | `/CreditNotes` | Create new credit note only |
| PUT | `/CreditNotes/{id}/Allocations` | Allocate credit note to invoice |
| DELETE | `/CreditNotes/{id}/Allocations/{allocId}` | Delete allocation |

### Credit Note Types

| Type | Description | ERPNext Equivalent |
|------|-------------|-------------------|
| `ACCRECCREDIT` | Accounts Receivable Credit | Sales Invoice (is_return=1) |
| `ACCPAYCREDIT` | Accounts Payable Credit | Purchase Invoice (is_return=1) |

### Credit Note Status Flow

```
DRAFT → AUTHORISED → PAID
                  ↘ VOIDED
                  ↘ DELETED (DRAFT only)
```

### Required Fields for POST/PUT

| Field | Required | Notes |
|-------|----------|-------|
| Type | Yes | ACCRECCREDIT or ACCPAYCREDIT |
| Contact | Yes | Must include ContactID |
| LineItems | Recommended | Required for AUTHORISED status |
| Date | No | Defaults to current date |
| Status | No | DRAFT if not specified |

### Field Validations

| Field | Max Length | Notes |
|-------|------------|-------|
| Description | 4000 | Line item description |
| CreditNoteNumber | 255 | ACCRECCREDIT must be unique |
| Reference | 255 | ACCRECCREDIT only |

### Allocations

Credit notes must have Status `AUTHORISED` before allocation.

```json
// PUT /CreditNotes/{CreditNoteID}/Allocations
{
  "Amount": 60.50,
  "Invoice": {
    "InvoiceID": "f5832195-5cd3-4660-ad3f-b73d9c64f263"
  }
}
```

---

## Implementation Plan

### Step 1: Add Validation Functions

Create validation functions in `xero_credit_notes.py`:

```python
def validate_credit_note_description(description, item_name=None, item_code=None):
    """Validate and sanitize credit note line item description for Xero."""
    description = (description or "").strip()
    
    # Strip HTML tags
    if description and "<" in description:
        description = re.sub(r'<[^>]+>', '', description).strip()
    
    # Fallback if empty
    if not description:
        description = item_name or item_code or "Item"
    
    # Xero max length is 4000 chars
    if len(description) > 4000:
        description = description[:3997] + "..."
    
    return description


def validate_credit_note_number(cn_name):
    """Validate credit note number for Xero. Max 255 chars."""
    if not cn_name:
        return None
    cn_number = cn_name[:255]
    cn_number = ''.join(c for c in cn_number if 32 <= ord(c) <= 126)
    return cn_number or None


def validate_credit_note_reference(reference):
    """Validate credit note reference for Xero. Max 255 chars."""
    if not reference:
        return None
    reference = str(reference)[:255]
    return reference or None
```

### Step 2: Add Hash Functions for Change Detection

```python
def compute_credit_note_hash(doc):
    """Compute MD5 hash of credit note data for change detection."""
    hash_data = {
        "posting_date": str(doc.posting_date),
        "currency": doc.currency,
        "customer": doc.get("customer") or doc.get("supplier"),
        "items": [],
        "taxes": []
    }
    
    for item in doc.items:
        hash_data["items"].append({
            "item_code": item.item_code,
            "description": item.description,
            "qty": flt(item.qty),
            "rate": flt(item.rate),
            "amount": flt(item.amount),
            "income_account": item.get("income_account") or item.get("expense_account")
        })
    
    for tax in doc.taxes:
        hash_data["taxes"].append({
            "account_head": tax.account_head,
            "tax_amount": flt(tax.tax_amount_after_discount_amount)
        })
    
    hash_string = json.dumps(hash_data, sort_keys=True)
    return hashlib.md5(hash_string.encode()).hexdigest()


def credit_note_data_changed(doc):
    """Check if credit note data has changed since last sync."""
    stored_hash = doc.get("xero_data_hash")
    if not stored_hash:
        return True
    current_hash = compute_credit_note_hash(doc)
    return current_hash != stored_hash
```

### Step 3: Fix Outbound Sync Function

Key changes to `sync_return_to_xero()`:

1. Change HTTP method from PUT to POST
2. Add double-trigger guard
3. Add field validation
4. Add LineAmountTypes
5. Add ItemCode support
6. Add DiscountRate support
7. Add TaxType mapping
8. Add Reference field
9. Add hash storage
10. Add retry decorator

### Step 4: Add Void/Delete Functionality

Create new functions:

```python
def enqueue_void_credit_note(doc, method):
    """Enqueue background job to void a cancelled credit note in Xero."""
    # Check if this is a return document
    if not doc.get("is_return"):
        return  # Let invoice void handler deal with it
    
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_credit_notes"):
        return

    frappe.enqueue(
        "xero.api.xero_credit_notes.void_credit_note_in_xero",
        queue="short",
        doc_name=doc.name,
        doc_type=doc.doctype
    )


def void_credit_note_in_xero(doc_name, doc_type):
    """Void or delete a credit note in Xero."""
    # Implementation similar to void_invoice_in_xero()
    # - DRAFT/SUBMITTED → DELETED
    # - AUTHORISED → VOIDED
```

### Step 5: Update Hooks

No changes needed to `hooks.py` since `enqueue_void_invoice()` already routes to the correct handler based on `is_return` flag. However, we need to update `enqueue_void_invoice()` to check for returns:

```python
# In xero_invoices.py
def enqueue_void_invoice(doc, method):
    """Enqueue background job to void a cancelled invoice in Xero."""
    if doc.get("is_return"):
        from .xero_credit_notes import enqueue_void_credit_note
        enqueue_void_credit_note(doc, method)
        return
    
    # ... existing invoice void logic
```

### Step 6: Fix Inbound Sync Function

Key changes to `process_xero_credit_note()`:

1. Add hash storage
2. Handle status mapping
3. Handle allocations (store in remarks)
4. Handle RemainingCredit
5. Handle DiscountRate

---

## Custom Fields Required

The following custom fields already exist on Sales Invoice and Purchase Invoice:

| Field | Type | Purpose |
|-------|------|---------|
| `xero_credit_note_id` | Data | Xero CreditNote ID |
| `xero_sync_status` | Select | Sync status |
| `xero_data_hash` | Data | MD5 hash for change detection |

**No new custom fields required.**

---

## Testing Plan

### Unit Tests

Create `test_credit_note_sync.py` with tests for:

1. `validate_credit_note_description()` - various inputs
2. `validate_credit_note_number()` - length and character limits
3. `validate_credit_note_reference()` - length limits
4. `compute_credit_note_hash()` - consistent hash generation
5. `credit_note_data_changed()` - change detection

### Round-Trip Tests

Create `test_credit_note_bidirectional_sync.py`:

| Test | Direction | DocType | Expected Result |
|------|-----------|---------|-----------------|
| 1 | Outbound | Sales Invoice Return | ACCRECCREDIT created in Xero |
| 2 | Outbound | Purchase Invoice Return | ACCPAYCREDIT created in Xero |
| 3 | Inbound | ACCRECCREDIT | Sales Invoice Return created |
| 4 | Inbound | ACCPAYCREDIT | Purchase Invoice Return created |
| 5 | Update | Sales Invoice Return | ACCRECCREDIT updated in Xero |
| 6 | Update | Purchase Invoice Return | ACCPAYCREDIT updated in Xero |
| 7 | Cancel | Sales Invoice Return | ACCRECCREDIT voided in Xero |
| 8 | Cancel | Purchase Invoice Return | ACCPAYCREDIT voided in Xero |
| 9 | No Change | Sales Invoice Return | No API call made |
| 10 | No Change | Purchase Invoice Return | No API call made |
| 11 | Long Description | Sales Invoice Return | Truncated to 4000 chars |
| 12 | Long CN Number | Purchase Invoice Return | Truncated to 255 chars |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Existing synced credit notes break | Medium | High | Test with existing data before deploy |
| Double-sync creates duplicates | Low | High | Double-trigger guard prevents this |
| Hash mismatch causes re-sync | Low | Medium | Acceptable - just extra API call |
| Void fails for allocated CN | Medium | Medium | Log warning, manual intervention |

---

## Implementation Order

1. **Phase 1 (Critical)** - Must complete before any testing
   - [ ] Add validation functions
   - [ ] Add hash functions
   - [ ] Fix HTTP method (PUT → POST)
   - [ ] Add double-trigger guard
   - [ ] Add LineAmountTypes
   - [ ] Add void/delete functionality

2. **Phase 2 (Important)** - Complete for production readiness
   - [ ] Add ItemCode support
   - [ ] Add DiscountRate support
   - [ ] Add TaxType mapping
   - [ ] Add Reference field
   - [ ] Add retry decorator

3. **Phase 3 (Enhancement)** - Complete for full feature parity
   - [ ] Handle status mapping in inbound sync
   - [ ] Handle allocations
   - [ ] Handle RemainingCredit
   - [ ] Handle DiscountRate in inbound sync

---

## Success Criteria

1. All 12 round-trip tests pass
2. No infinite loops on sync
3. Cancelled returns are properly voided/deleted in Xero
4. Long fields are properly truncated
5. Change detection prevents unnecessary API calls
6. Existing synced credit notes continue to work

---

## References

- [Xero Credit Notes API Documentation](../cohenix-bench/apps/xero/xero/official_api_docs/Credit%20Notes.md)
- [Invoice Sync Implementation](../cohenix-bench/apps/xero/xero/api/xero_invoices.py)
- [Invoice Sync Fix Plan](./invoice-sync-fix-plan.md)
