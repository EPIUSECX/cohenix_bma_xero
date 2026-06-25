# Phase 4: Credit Notes Creation Plan

## Objective

Create Credit Notes (Sales Return) and Debit Notes (Purchase Return) via terminal to test Level 3 dependencies (Complex Entity Dependencies) and complete the entity creation testing before Xero sync.

## Background

Based on [`xero_entities_ordered_by_dependency.md`](xero_entities_ordered_by_dependency.md):
- **Phase 1 Complete:** ✅ Master Data Setup
- **Phase 2 Complete:** ✅ Sales/Purchase Orders
- **Phase 3 Complete:** ✅ Sales/Purchase Invoices (10 invoices)
- **Phase 4 Next:** Credit Notes with invoice dependencies
- **Complexity:** Extreme - Requires reference to existing invoices
- **Terminal Feasibility:** ❌ Extremely difficult (but we have the invoices!)

## Prerequisites (Already Complete ✅)

From Phases 1-3, we have:
- ✅ 5 Customers
- ✅ 5 Suppliers
- ✅ 10 Items
- ✅ 5 Sales Orders
- ✅ 5 Purchase Orders
- ✅ **5 Sales Invoices** (ACC-SINV-2025-00001 through 00005)
- ✅ **5 Purchase Invoices** (ACC-PINV-2025-00001 through 00005)
- ✅ Account mappings verified
- ✅ 44 entities ready

## Understanding Credit Notes in ERPNext

### Sales Return (Credit Note):
- **Purpose:** Return goods sold to customer, reduce receivables
- **DocType:** Sales Invoice with `is_return = 1`
- **Reference:** Must reference original Sales Invoice
- **Account Impact:** Reverses the original invoice entries
- **Xero Sync:** Syncs as Credit Note to Xero

### Purchase Return (Debit Note):
- **Purpose:** Return goods to supplier, reduce payables
- **DocType:** Purchase Invoice with `is_return = 1`
- **Reference:** Must reference original Purchase Invoice
- **Account Impact:** Reverses the original invoice entries
- **Xero Sync:** Syncs as Debit Note to Xero

## Critical Requirements for Credit Notes

### For Sales Return (Credit Note):
1. **Original Invoice:** Must reference existing Sales Invoice
2. **Return Against:** `return_against` field = original invoice name
3. **Is Return:** `is_return = 1`
4. **Negative Quantities:** Items with negative qty OR positive qty with is_return
5. **Same Accounts:** Use same debit_to and income accounts as original
6. **Same Customer:** Must be same customer as original invoice

### For Purchase Return (Debit Note):
1. **Original Invoice:** Must reference existing Purchase Invoice
2. **Return Against:** `return_against` field = original invoice name
3. **Is Return:** `is_return = 1`
4. **Negative Quantities:** Items with negative qty OR positive qty with is_return
5. **Same Accounts:** Use same credit_to and expense accounts as original
6. **Same Supplier:** Must be same supplier as original invoice

## Phase 4.0: Invoice Submission Requirement

**CRITICAL:** Credit Notes can only be created against **submitted** invoices (docstatus=1).

### Current State:
- All invoices are in Draft status (docstatus=0)
- Need to submit invoices before creating returns

### Submission Strategy:
```python
# Submit a Sales Invoice
invoice = frappe.get_doc('Sales Invoice', 'ACC-SINV-2025-00001')
invoice.submit()
frappe.db.commit()
```

### Risk Assessment:
- **Low Risk:** Submission is standard operation
- **Validation:** May trigger additional checks
- **Reversibility:** Can cancel if needed

## Phase 4.1: Sales Return (Credit Note) Creation

### Strategy:
1. Submit 3 Sales Invoices (keep 2 in draft for comparison)
2. Create Credit Notes for the submitted invoices
3. Use partial returns (not full amount)

### Credit Note Structure:
```python
credit_note = {
    'customer': 'TEST CUSTOMER A',  # Same as original
    'is_return': 1,
    'return_against': 'ACC-SINV-2025-00001',  # Original invoice
    'posting_date': today(),
    'debit_to': 'Debtors - E',  # Same as original
    'items': [{
        'item_code': 'TEST-SALES-001',  # Same as original
        'qty': -2,  # Negative for return (or positive with is_return)
        'rate': 100.0,  # Same rate as original
        'income_account': '200 - 200 - Sales - E'
    }],
    'company': 'EPIUSE',
    'currency': 'ZAR'
}
```

### Validation Challenges:
- Invoice must be submitted
- Return qty cannot exceed original qty
- Same customer required
- Same accounts required
- Reference validation

## Phase 4.2: Purchase Return (Debit Note) Creation

### Strategy:
1. Submit 3 Purchase Invoices (keep 2 in draft)
2. Create Debit Notes for the submitted invoices
3. Use partial returns

### Debit Note Structure:
```python
debit_note = {
    'supplier': 'TEST SUPPLIER A',  # Same as original
    'is_return': 1,
    'return_against': 'ACC-PINV-2025-00001',  # Original invoice
    'posting_date': today(),
    'credit_to': 'Employee Advances - E',  # Same as original
    'items': [{
        'item_code': 'TEST-PURCHASE-001',  # Same as original
        'qty': -5,  # Negative for return
        'rate': 75.0,  # Same rate as original
        'expense_account': 'Cost of Goods Sold - E'
    }],
    'company': 'EPIUSE',
    'currency': 'ZAR'
}
```

## Implementation Plan

### Step 1: Submit Invoices (Phase 4.0)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase4_0_submit_invoices.py
```

**Actions:**
- Submit 3 Sales Invoices (ACC-SINV-2025-00001, 00002, 00003)
- Submit 3 Purchase Invoices (ACC-PINV-2025-00001, 00002, 00003)
- Verify submission successful (docstatus=1)

### Step 2: Create Sales Returns (Phase 4.1)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase4_1_create_sales_returns.py
```

**Create 3 Credit Notes:**
1. Return against ACC-SINV-2025-00001 (partial: 2 of 5 items)
2. Return against ACC-SINV-2025-00002 (partial: 3 of 7 items)
3. Return against ACC-SINV-2025-00003 (partial: 4 of 10 items)

### Step 3: Create Purchase Returns (Phase 4.2)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase4_2_create_purchase_returns.py
```

**Create 3 Debit Notes:**
1. Return against ACC-PINV-2025-00001 (partial: 5 of 15 items)
2. Return against ACC-PINV-2025-00002 (partial: 8 of 20 items)
3. Return against ACC-PINV-2025-00003 (partial: 10 of 25 items)

### Step 4: Validate Returns (Phase 4.3)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase4_3_validate_returns.py
```

**Validation:**
- Confirm all returns created
- Verify return_against references
- Check account postings (should be reversed)
- Validate amounts

## Expected Challenges & Solutions

### Challenge 1: Invoice Must Be Submitted
**Solution:** Submit invoices first in Phase 4.0

### Challenge 2: Return Qty Validation
**Solution:** Use partial returns (less than original qty)

### Challenge 3: Reference Validation
**Solution:** Ensure return_against field correctly references original invoice

### Challenge 4: Account Matching
**Solution:** Use exact same accounts as original invoice

### Challenge 5: Negative Amounts
**Solution:** Use negative qty OR positive qty with is_return=1

## Success Criteria

### ✅ Phase 4 Complete When:
- [ ] At least 3 Sales Invoices submitted successfully
- [ ] At least 3 Purchase Invoices submitted successfully
- [ ] At least 3 Credit Notes (Sales Returns) created
- [ ] At least 3 Debit Notes (Purchase Returns) created
- [ ] All returns properly reference original invoices
- [ ] Account postings are reversed correctly
- [ ] All commands logged in `successfull_terminal_entity_creations.md`

### ✅ Ready for Xero Sync When:
- [ ] All returns in correct status
- [ ] Return references validated
- [ ] Account postings verified
- [ ] Ready for Xero Credit Note sync testing

## Risk Mitigation

### Low Risk:
- Invoice submission (standard operation)
- Partial returns (safer than full returns)

### Medium Risk:
- Return quantity validation
- Account matching requirements

### High Risk:
- Complex reference validation
- Return against unsubmitted invoices
- Account posting reversals

**Mitigation:** Submit invoices first, use partial returns, detailed error logging

## Alternative Approaches

### If Direct Return Creation Fails:
1. **Use Return Wizard:** ERPNext has built-in return creation from invoice
2. **Copy and Modify:** Clone original invoice and set is_return=1
3. **Manual GL Entries:** Create manual journal entries for returns

### If Submission Fails:
1. **Check Validation Errors:** Review what's blocking submission
2. **Fix Invoice Data:** Correct any validation issues
3. **Use Force Submit:** Last resort with `submit(ignore_permissions=True)`

## Expected Outcomes

### Optimistic Scenario:
- All 6 returns created successfully
- Clean reference validation
- Ready for Xero sync

### Realistic Scenario:
- 4-5 returns created
- Some reference validation adjustments needed
- Minor troubleshooting required

### Pessimistic Scenario:
- 1-2 returns created
- Significant validation challenges
- Need alternative approach

**Preparation:** Scripts handle all scenarios with fallback options

## Documentation

All successful commands will be logged in:
- `successfull_terminal_entity_creations.md` - Command log with results
- `phase4_credit_notes_plan.md` - This planning document

---

**Plan Created:** 2025-12-08  
**Status:** Ready for Implementation  
**Prerequisites:** ✅ Phase 1, 2, 3 complete (44 entities including 10 invoices)  
**Next Action:** Execute Phase 4.0 - Submit Invoices for Return Testing