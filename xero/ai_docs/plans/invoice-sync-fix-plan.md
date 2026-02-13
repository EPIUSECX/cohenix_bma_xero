# Invoice Sync Fix Plan

## Overview

This plan addresses issues with bi-directional invoice sync between ERPNext and Xero. The invoice sync is critical as it shares similar patterns with Quotes, Purchase Orders, and Credit Notes.

## Current State Analysis

### Files Involved
- `xero/api/xero_invoices.py` - Main invoice sync logic (964 lines)
- `xero/hooks.py` - DocType event hooks
- `xero/setup/custom_fields.py` - Custom field definitions

### Current Hooks
```python
"Sales Invoice": {
    "on_submit": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
    "on_cancel": "xero.api.xero_invoices.enqueue_void_invoice"
},
"Purchase Invoice": {
    "on_submit": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
    "on_cancel": "xero.api.xero_invoices.enqueue_void_invoice"
}
```

### Current Custom Fields
- `xero_invoice_id` - Xero's InvoiceID
- `xero_sync_status` - Sync status (Pending/Synced/Error/Skipped)
- `xero_credit_note_id` - For credit notes

---

## Issues Identified

### Issue 1: Wrong HTTP Method for Updates (CRITICAL)

**Current Code (line 233):**
```python
response = xero_request("PUT", "Invoices", data={"Invoices": [invoice_payload]})
```

**Xero API Requirements:**
- `PUT` - Creates NEW invoices only
- `POST` - Creates OR updates (if InvoiceID provided, updates; otherwise creates)

**Impact:** Updates to existing synced invoices will fail or create duplicates.

**Fix:**
```python
# Use POST for both create and update
method = "POST"  # Always use POST for invoices
response = xero_request(method, "Invoices", data={"Invoices": [invoice_payload]})
```

---

### Issue 2: No Change Detection for Updates

**Current State:** No `xero_data_hash` field for invoices.

**Impact:** Cannot detect if invoice data has changed since last sync, leading to:
- Unnecessary API calls
- Missed updates when data changes
- No way to prevent redundant syncs

**Fix:** Add `xero_data_hash` custom field and hash computation logic.

---

### Issue 3: No Double-Trigger Guard

**Current Code (line 28-42):**
```python
def enqueue_sync_invoice(doc, method):
    settings = get_xero_settings()
    if not settings.sync_invoices:
        return
    frappe.enqueue(...)
```

**Impact:** When syncing FROM Xero, the update to ERPNext triggers `on_submit` which tries to sync back TO Xero, causing infinite loops.

**Fix:**
```python
def enqueue_sync_invoice(doc, method):
    settings = get_xero_settings()
    if not settings.sync_invoices:
        return
    
    # Double-trigger guard: Only sync if not already synced
    if doc.get("xero_sync_status") == "Synced":
        log_xero_error(
            message=f"Skipping sync for {doc.doctype} {doc.name}: already synced to Xero",
            status="Info",
            category="System Monitoring"
        )
        return
    
    frappe.enqueue(...)
```

---

### Issue 4: Line Item Description Validation Missing

**Xero API Requirements:**
- Description: min 1 char, max 4000 chars

**Current Code (line 194-201):**
```python
description = (item.description or "").strip()
if description and "<" in description:
    import re
    description = re.sub(r'<[^>]+>', '', description).strip()
if not description:
    description = item.item_name or item.item_code or "Item"
```

**Impact:** Descriptions over 4000 chars will cause API errors.

**Fix:**
```python
def validate_invoice_description(description, item_name=None, item_code=None):
    """Validate and sanitize invoice line item description for Xero."""
    description = (description or "").strip()
    
    # Strip HTML tags
    if description and "<" in description:
        import re
        description = re.sub(r'<[^>]+>', '', description).strip()
    
    # Fallback if empty
    if not description:
        description = item_name or item_code or "Item"
    
    # Xero max length is 4000 chars
    if len(description) > 4000:
        description = description[:3997] + "..."
    
    return description
```

---

### Issue 5: InvoiceNumber Length Not Validated

**Xero API Requirements:**
- InvoiceNumber: max 255 chars (printable ASCII only)

**Current Code (line 172):**
```python
"InvoiceNumber": doc.name,
```

**Impact:** ERPNext invoice names over 255 chars will cause API errors.

**Fix:**
```python
def validate_invoice_number(invoice_name):
    """Validate invoice number for Xero (max 255 chars, printable ASCII)."""
    if not invoice_name:
        return None
    
    # Truncate to 255 chars
    invoice_number = invoice_name[:255]
    
    # Remove non-printable ASCII characters
    invoice_number = ''.join(c for c in invoice_number if 32 <= ord(c) <= 126)
    
    return invoice_number or None
```

---

### Issue 6: Reference Field Length Not Validated

**Xero API Requirements:**
- Reference: max 255 chars (ACCREC only)

**Current Code (line 173):**
```python
"Reference": doc.get("po_no") if doc_type == "Sales Invoice" else doc.get("bill_no"),
```

**Impact:** Long references will cause API errors.

**Fix:**
```python
reference = None
if doc_type == "Sales Invoice":
    reference = (doc.get("po_no") or "")[:255]
else:
    # ACCPAY doesn't support Reference field in the same way
    reference = None
```

---

### Issue 7: Missing LineItemID on Updates

**Xero API Requirements:**
- When updating, include LineItemID to update existing line items
- Without LineItemID, line items are deleted and recreated

**Current State:** No tracking of Xero LineItemIDs.

**Impact:** Every update deletes and recreates all line items, losing:
- Line item history
- Tracking category assignments
- Any manual edits in Xero

**Fix Options:**

**Option A (Recommended):** Store LineItemID in a custom field on Sales/Purchase Invoice Item:
```python
# Add custom field to Sales Invoice Item and Purchase Invoice Item
{
    "fieldname": "xero_line_item_id",
    "fieldtype": "Data",
    "label": "Xero Line Item ID",
    "read_only": 1,
    "hidden": 1
}
```

**Option B:** Fetch existing invoice from Xero before update and match line items by description/account.

---

### Issue 8: Tax Line Items Approach May Be Wrong

**Current Code (line 216-230):**
```python
for tax in doc.taxes:
    tax_line_item = {
        "Description": tax.description,
        "Quantity": 1,
        "UnitAmount": tax.tax_amount_after_discount_amount,
        "AccountCode": tax_account_code,
        "TaxType": "NONE"
    }
    invoice_payload["LineItems"].append(tax_line_item)
```

**Xero API Behavior:**
- Line items with proper TaxType will auto-calculate tax
- Adding tax as separate line items may cause double taxation

**Analysis Needed:**
- ERPNext tax structure vs Xero tax structure
- Whether taxes should be line items or use TaxType on existing items

**Recommendation:** Review and potentially refactor tax handling to use Xero's native tax calculation.

---

### Issue 9: No ItemCode Sync for Line Items

**Xero API Supports:**
```json
{
    "ItemCode": "2010-SWEATER-RED",
    "Description": "Red Sweater",
    "Quantity": "5"
}
```

**Current Code:** Doesn't include ItemCode.

**Impact:** Missing link to inventory items in Xero, losing:
- Inventory tracking
- Default account codes
- Default prices

**Fix:**
```python
line_item = {
    "Description": description,
    "Quantity": item.qty,
    "UnitAmount": item.rate,
    "AccountCode": xero_account_code,
}

# Add ItemCode if item has xero_item_id
if item.item_code:
    xero_item_code = frappe.db.get_value("Item", item.item_code, "xero_item_code")
    if xero_item_code:
        line_item["ItemCode"] = xero_item_code
```

---

### Issue 10: Status Flow Not Properly Handled

**Xero Invoice Status Flow:**
```
DRAFT → SUBMITTED → AUTHORISED → PAID
                  ↘ VOIDED
                  ↘ DELETED (DRAFT/SUBMITTED only)
```

**Current Code (line 175):**
```python
"Status": "AUTHORISED",
```

**Xero API Constraints:**
- AUTHORISED invoices have limited update capabilities
- Paid invoices can only update: Reference, DueDate, InvoiceNumber, BrandingThemeID, Contact, URL, LineItems (with restrictions)

**Impact:**
- Cannot update AUTHORISED invoices freely
- May need to handle status transitions

**Recommendation:**
1. Create as DRAFT initially for flexibility
2. Provide option to auto-approve (AUTHORISED) after creation
3. Handle status transitions properly

---

### Issue 11: No Tracking Category Support

**Xero API Supports:**
```json
{
    "Tracking": [
        {
            "Name": "Region",
            "Option": "North"
        }
    ]
}
```

**Current State:** No tracking category support.

**Impact:** Missing dimension tracking in Xero (equivalent to Cost Center/Project in ERPNext).

**Fix:** Map ERPNext Cost Center/Project to Xero Tracking Categories.

---

### Issue 12: Inbound Sync Creates Draft Only

**Current Code (line 844):**
```python
erpnext_data["docstatus"] = 0  # Always create as Draft
```

**Impact:** User must manually submit invoices created from Xero.

**Recommendation:** Add setting to auto-submit invoices imported from Xero if status is AUTHORISED.

---

### Issue 13: Void vs Delete Not Properly Distinguished

**Current Code (line 305-311):**
```python
invoice_payload = {
    "InvoiceID": xero_invoice_id,
    "Status": "VOIDED"
}
response = xero_request("POST", "Invoices", data={"Invoices": [invoice_payload]})
```

**Xero API Requirements:**
- DRAFT/SUBMITTED → can be DELETED
- AUTHORISED → can be VOIDED (if no payments)

**Impact:** May fail if trying to void a DRAFT invoice.

**Fix:**
```python
def void_invoice_in_xero(doc_name, doc_type):
    # First get the current status from Xero
    xero_data = xero_request("GET", f"Invoices/{xero_invoice_id}")
    xero_status = xero_data["Invoices"][0].get("Status")
    
    if xero_status in ["DRAFT", "SUBMITTED"]:
        new_status = "DELETED"
    else:  # AUTHORISED
        new_status = "VOIDED"
    
    invoice_payload = {
        "InvoiceID": xero_invoice_id,
        "Status": new_status
    }
    response = xero_request("POST", "Invoices", data={"Invoices": [invoice_payload]})
```

---

### Issue 14: No Currency Validation

**Current Code (line 174):**
```python
"CurrencyCode": doc.currency,
```

**Impact:** Invalid currency codes will cause API errors.

**Fix:**
```python
def validate_currency(currency_code):
    """Validate currency code is supported by Xero."""
    # Xero supports standard ISO 4217 codes
    # Common codes: USD, GBP, NZD, AUD, EUR, etc.
    valid_currencies = ["USD", "GBP", "NZD", "AUD", "EUR", "CAD", "ZAR", ...]
    
    if currency_code not in valid_currencies:
        log_xero_error(
            message=f"Currency {currency_code} may not be supported by Xero",
            status="Warning"
        )
        # Use base currency as fallback
    
    return currency_code
```

---

### Issue 15: Missing Discount Support

**Xero API Supports:**
```json
{
    "DiscountRate": "20",  // Percentage
    "DiscountAmount": "10.00"  // Fixed amount
}
```

**Current State:** No discount mapping.

**Impact:** Discounts from ERPNext not reflected in Xero.

**Fix:**
```python
# In line item mapping
if item.discount_percentage > 0:
    line_item["DiscountRate"] = item.discount_percentage
```

---

## Implementation Plan

### Phase 1: Critical Fixes (Must Have)

1. **Fix HTTP Method** (Issue #1)
   - Change PUT to POST for invoice sync
   - File: `xero/api/xero_invoices.py`

2. **Add Double-Trigger Guard** (Issue #3)
   - Check `xero_sync_status == "Synced"` before enqueueing
   - File: `xero/api/xero_invoices.py`

3. **Add Field Validation** (Issues #4, #5, #6)
   - Description max 4000 chars
   - InvoiceNumber max 255 chars
   - Reference max 255 chars
   - File: `xero/api/xero_invoices.py`

### Phase 2: Important Improvements (Should Have)

4. **Add Change Detection** (Issue #2)
   - Add `xero_data_hash` custom field
   - Add hash computation and comparison
   - Files: `xero/setup/custom_fields.py`, `xero/api/xero_invoices.py`

5. **Fix Void vs Delete** (Issue #13)
   - Check Xero status before voiding/deleting
   - File: `xero/api/xero_invoices.py`

6. **Add ItemCode Support** (Issue #9)
   - Include ItemCode in line items when available
   - File: `xero/api/xero_invoices.py`

### Phase 3: Enhanced Features (Nice to Have)

7. **Add LineItemID Tracking** (Issue #7)
   - Add custom field for line item IDs
   - Update line items instead of delete/recreate
   - Files: `xero/setup/custom_fields.py`, `xero/api/xero_invoices.py`

8. **Add Tracking Category Support** (Issue #11)
   - Map Cost Center/Project to Tracking Categories
   - Files: `xero/api/xero_invoices.py`, `xero/setup/custom_fields.py`

9. **Review Tax Handling** (Issue #8)
   - Analyze current approach
   - Refactor if needed

10. **Add Discount Support** (Issue #15)
    - Map ERPNext discounts to Xero
    - File: `xero/api/xero_invoices.py`

---

## Custom Fields to Add

### Sales Invoice / Purchase Invoice

```python
{
    "fieldname": "xero_data_hash",
    "fieldtype": "Data",
    "label": "Xero Data Hash",
    "length": 32,
    "read_only": 1,
    "hidden": 1,
    "insert_after": "xero_sync_status"
}
```

### Sales Invoice Item / Purchase Invoice Item

```python
{
    "fieldname": "xero_line_item_id",
    "fieldtype": "Data",
    "label": "Xero Line Item ID",
    "read_only": 1,
    "hidden": 1,
    "insert_after": "item_code"
}
```

---

## Testing Plan

### Unit Tests

1. Test HTTP method selection (POST for both create/update)
2. Test field validation functions
3. Test hash computation
4. Test double-trigger guard

### Integration Tests

1. **Outbound Sync - Create**
   - Create Sales Invoice in ERPNext
   - Submit invoice
   - Verify invoice created in Xero
   - Verify xero_invoice_id stored

2. **Outbound Sync - Update**
   - Modify existing synced invoice
   - Verify update in Xero (not duplicate)
   - Verify LineItemID preserved (if implemented)

3. **Inbound Sync - Create**
   - Create invoice in Xero
   - Run sync from Xero
   - Verify draft invoice created in ERPNext
   - Verify line items mapped correctly

4. **Inbound Sync - Update**
   - Modify invoice in Xero
   - Run sync from Xero
   - Verify ERPNext invoice updated

5. **Void/Delete**
   - Cancel invoice in ERPNext
   - Verify voided/deleted in Xero based on status

6. **Round-Trip Test**
   - Create in ERPNext → Sync to Xero → Modify in Xero → Sync back → Verify

---

## Code Changes Summary

### xero/api/xero_invoices.py

1. Add validation functions:
   - `validate_invoice_description()`
   - `validate_invoice_number()`
   - `validate_invoice_reference()`

2. Add hash functions:
   - `compute_invoice_hash()`
   - `invoice_data_changed()`

3. Update `sync_invoice_to_xero()`:
   - Use POST instead of PUT
   - Add double-trigger guard
   - Add field validation
   - Add hash computation
   - Include ItemCode in line items

4. Update `void_invoice_in_xero()`:
   - Check Xero status before void/delete

5. Update `process_xero_invoice()`:
   - Set xero_data_hash on sync
   - Handle LineItemID storage

### xero/setup/custom_fields.py

1. Add `xero_data_hash` to Sales Invoice
2. Add `xero_data_hash` to Purchase Invoice
3. Add `xero_line_item_id` to Sales Invoice Item
4. Add `xero_line_item_id` to Purchase Invoice Item

### xero/hooks.py

No changes needed - existing hooks are correct.

---

## Risk Assessment

### High Risk
- HTTP method fix could break existing synced invoices - need migration
- Double-trigger guard could prevent legitimate re-syncs - need manual override

### Medium Risk
- LineItemID tracking requires schema changes - need migration
- Tax handling changes could affect invoice totals - thorough testing needed

### Low Risk
- Field validation is backward compatible
- Hash computation is additive

---

## Dependencies

This fix depends on:
1. Contact sync working correctly (for ContactID)
2. Account sync working correctly (for AccountCode)
3. Item sync working correctly (for ItemCode)
4. Tax rate mapping configured in Xero Settings

---

## Estimated Effort

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| Phase 1 | Critical fixes | 4-6 hours |
| Phase 2 | Important improvements | 4-6 hours |
| Phase 3 | Enhanced features | 6-8 hours |
| Testing | All tests | 4-6 hours |
| **Total** | | **18-26 hours** |

---

## Next Steps

1. Review and approve this plan
2. Implement Phase 1 (Critical Fixes)
3. Test Phase 1 thoroughly
4. Implement Phase 2 (Important Improvements)
5. Test Phase 2 thoroughly
6. Consider Phase 3 based on priorities
