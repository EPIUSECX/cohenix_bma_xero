# Invoice Sync Implementation Summary

## Overview

This document summarizes the fixes implemented for bi-directional invoice sync between ERPNext and Xero.

## Date: 2026-02-13

---

## Issues Fixed

### Critical Issues (Phase 1)

| Issue | Problem | Solution |
|-------|---------|----------|
| **Wrong HTTP Method** | Used PUT for all calls | Changed to POST for both create and update |
| **No Double-Trigger Guard** | Infinite loops when syncing from Xero | Added guard checking `xero_sync_status == "Synced"` and hash comparison |
| **Description Validation** | No length limit | Added validation: min 1 char, max 4000 chars |
| **InvoiceNumber Validation** | No length limit | Added validation: max 255 chars, printable ASCII only |
| **Reference Validation** | No length limit | Added validation: max 255 chars |

### Important Improvements (Phase 2)

| Issue | Problem | Solution |
|-------|---------|----------|
| **No Change Detection** | No way to detect data changes | Added `xero_data_hash` field and hash computation |
| **Void vs Delete** | Always used VOIDED status | Check Xero status: DRAFT/SUBMITTED → DELETED, AUTHORISED → VOIDED |
| **No ItemCode Support** | Line items missing ItemCode | Added ItemCode to line items when item is synced |
| **No Discount Support** | Discounts not synced | Added DiscountRate to line items |

---

## Files Modified

### 1. `xero/api/xero_invoices.py`

**New Functions Added:**

```python
def validate_invoice_description(description, item_name=None, item_code=None):
    """Validate and sanitize invoice line item description for Xero."""
    # Xero requires: min 1 char, max 4000 chars
    # Strips HTML tags, provides fallbacks, truncates to 4000 chars

def validate_invoice_number(invoice_name):
    """Validate invoice number for Xero."""
    # Xero requires: max 255 chars, printable ASCII only
    # Truncates to 255 chars, removes non-printable characters

def validate_invoice_reference(reference):
    """Validate invoice reference for Xero."""
    # Xero requires: max 255 chars
    # Truncates to 255 chars

def compute_invoice_hash(doc):
    """Compute MD5 hash of invoice data for change detection."""
    # Hashes: posting_date, due_date, currency, customer, items, taxes

def invoice_data_changed(doc):
    """Check if invoice data has changed since last sync."""
    # Returns True if no hash exists or hash differs
```

**Modified Functions:**

- `enqueue_sync_invoice()` - Added double-trigger guard
- `sync_invoice_to_xero()` - Changed PUT to POST, added validation, added hash storage
- `void_invoice_in_xero()` - Added status check for proper void/delete handling

### 2. `xero/setup/custom_fields.py`

**New Custom Fields:**

| DocType | Field | Type | Purpose |
|---------|-------|------|---------|
| Sales Invoice | `xero_data_hash` | Data (32) | Change detection hash |
| Purchase Invoice | `xero_data_hash` | Data (32) | Change detection hash |

---

## Test Results

### Unit Tests (26 tests, all passed)

```
TestInvoiceValidation (16 tests)
  ✓ Description validation (normal, empty, HTML, max length)
  ✓ Invoice number validation (normal, max length, non-printable)
  ✓ Reference validation (normal, max length, empty, numeric)

TestInvoiceHashComputation (5 tests)
  ✓ Consistent hash for same data
  ✓ Different hash for different data
  ✓ Hash with line items
  ✓ Hash changes when items change
  ✓ Hash with taxes

TestXeroAPIRequirements (5 tests)
  ✓ Description min/max length (Xero requirements)
  ✓ Invoice number max length (Xero requirements)
  ✓ Invoice number printable ASCII (Xero requirements)
  ✓ Reference max length (Xero requirements)
```

### Test Files Created

1. `test_invoice_standalone.py` - Standalone unit tests (no Frappe required)
2. `test_invoice_sync.py` - Frappe-dependent unit tests
3. `test_invoice_bidirectional_sync.py` - Integration tests for round-trip sync

---

## Xero API Compliance

### Invoice Fields

| Field | Xero Requirement | Implementation |
|-------|------------------|----------------|
| Type | Required | ACCREC (Sales) / ACCPAY (Purchase) |
| Contact | Required | ContactID from synced Customer/Supplier |
| LineItems | Required (min 1) | Mapped from ERPNext items |
| Date | Optional | posting_date |
| DueDate | Optional | due_date |
| InvoiceNumber | Max 255 chars | Validated and truncated |
| Reference | Max 255 chars (ACCREC only) | Validated and truncated |
| CurrencyCode | Optional | currency field |
| Status | Optional | AUTHORISED for submitted invoices |

### Line Item Fields

| Field | Xero Requirement | Implementation |
|-------|------------------|----------------|
| Description | Min 1, Max 4000 chars | Validated and sanitized |
| Quantity | Optional | qty field |
| UnitAmount | Optional | rate field |
| AccountCode | Recommended | From account mapping |
| ItemCode | Optional | From synced Item |
| TaxType | Optional | From tax mapping |
| DiscountRate | Optional (ACCREC only) | discount_percentage field |

### HTTP Methods

| Operation | Method | Endpoint |
|-----------|--------|----------|
| Create new invoice | POST | /Invoices |
| Update existing invoice | POST | /Invoices (with InvoiceID) |
| Get invoice | GET | /Invoices/{id} |
| Void invoice | POST | /Invoices (Status: VOIDED) |
| Delete invoice | POST | /Invoices (Status: DELETED) |

---

## Code Patterns Used

### Double-Trigger Guard Pattern

```python
def enqueue_sync_invoice(doc, method):
    # Guard: Skip if already synced and data unchanged
    if doc.get("xero_sync_status") == "Synced" and doc.get("xero_invoice_id"):
        if not invoice_data_changed(doc):
            log_xero_error(message="Skipping sync: already synced and data unchanged", ...)
            return
    # Proceed with sync
    frappe.enqueue(...)
```

### Change Detection Pattern

```python
def sync_invoice_to_xero(doc_name, doc_type, **kwargs):
    # ... sync logic ...
    
    # Store hash for future change detection
    data_hash = compute_invoice_hash(doc)
    frappe.db.set_value(doc_type, doc_name, {
        "xero_invoice_id": new_xero_invoice_id,
        "xero_sync_status": "Synced",
        "xero_data_hash": data_hash
    }, update_modified=False)
```

### Void vs Delete Pattern

```python
def void_invoice_in_xero(doc_name, doc_type):
    # Get current status from Xero
    xero_data = xero_request("GET", f"Invoices/{xero_invoice_id}")
    xero_status = xero_data["Invoices"][0].get("Status")
    
    # Determine appropriate action
    if xero_status in ["DRAFT", "SUBMITTED"]:
        new_status = "DELETED"
    else:  # AUTHORISED
        new_status = "VOIDED"
    
    # Apply status change
    xero_request("POST", "Invoices", data={"Invoices": [{"InvoiceID": xero_invoice_id, "Status": new_status}]})
```

---

## Migration Notes

### Custom Fields

After deploying these changes, run:

```bash
bench migrate
```

Or manually trigger custom field setup:

```python
bench execute xero.setup.custom_fields.setup_custom_fields
```

### Existing Synced Invoices

Existing invoices that are already synced will:
1. Not have `xero_data_hash` set initially
2. Will be re-synced on next update (hash will be set then)
3. No data loss or corruption will occur

---

## Known Limitations

1. **ERPNext Invoices are Immutable**: After submission, invoices cannot be modified in ERPNext. Updates to Xero invoices would need to be done through:
   - Credit notes
   - New invoices
   - Direct Xero modifications (which would then sync back)

2. **Tax Handling**: The current implementation adds taxes as separate line items. This may need review based on specific tax requirements.

3. **Tracking Categories**: Not yet implemented. Cost Center/Project mapping to Xero Tracking Categories is a future enhancement.

4. **LineItemID Tracking**: Not yet implemented. Updates will delete and recreate line items in Xero.

---

## Related Documents

- [Invoice Sync Fix Plan](plans/invoice-sync-fix-plan.md)
- [Xero Invoices API Documentation](official_api_docs/Invoices.md)
- [Item Sync Implementation Summary](ACCOUNT_SYNC_IMPLEMENTATION_SUMMARY.md)

---

## Next Steps

1. Deploy changes to test environment
2. Run integration tests with real Xero API
3. Monitor sync logs for any issues
4. Consider implementing Phase 3 enhancements:
   - LineItemID tracking
   - Tracking Category support
   - Enhanced tax handling
