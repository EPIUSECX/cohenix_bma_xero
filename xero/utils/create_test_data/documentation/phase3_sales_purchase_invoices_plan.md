# Phase 3: Sales and Purchase Invoices Creation Plan

## Objective

Create Sales Invoices and Purchase Invoices via terminal to test Level 2+ dependencies (Master Data + Items + Account Mappings) and prepare for Xero sync testing.

## Background

Based on [`xero_entities_ordered_by_dependency.md`](xero_entities_ordered_by_dependency.md):
- **Phase 1 Complete:** ✅ Master Data Setup (Customers, Suppliers, Items, Journal Entries)
- **Phase 2 Complete:** ✅ Sales/Purchase Orders (10 orders created)
- **Phase 3 Next:** Sales/Purchase Invoices with full dependency chain
- **Complexity:** Very High - Multiple master data + account dependencies
- **Terminal Feasibility:** ❌ Very difficult, validation errors encountered (but we're prepared!)

## Prerequisites (Already Complete ✅)

From Phases 1 & 2, we have:
- ✅ 5 Customers with addresses
- ✅ 5 Suppliers
- ✅ 10 Items with pricing configured
- ✅ 5 Sales Orders (can create invoices from these)
- ✅ 5 Purchase Orders (can create bills from these)
- ✅ Company: EPIUSE
- ✅ Default accounts: Sales - E, Cost of Goods Sold - E
- ✅ Price Lists: Standard Selling, Standard Buying
- ✅ Currency: ZAR

## Critical Account Mappings Required

### For Sales Invoice:
1. **Income Account:** Sales - E (already default)
2. **Debit To Account:** Debtors - E (Receivable account)
3. **Cost Center:** May be required
4. **Tax Accounts:** Optional initially

### For Purchase Invoice:
1. **Expense Account:** Cost of Goods Sold - E (already default)
2. **Credit To Account:** Accounts Payable - E or Employee Advances - E
3. **Cost Center:** May be required
4. **Tax Accounts:** Optional initially

## Phase 3.0: Account Mapping Verification

### Investigation Script:
```python
# Check account mappings and cost centers
- Verify Debtors - E exists (Receivable)
- Verify Accounts Payable - E exists
- Check for Cost Centers
- Verify item account mappings
```

## Phase 3.1: Sales Invoice Creation Strategy

### Approach 1: Direct Invoice Creation (Standalone)
Create invoices directly without referencing Sales Orders.

**Advantages:**
- Simpler, fewer dependencies
- Direct control over all fields
- Easier to troubleshoot

**Structure:**
```python
sales_invoice = {
    'customer': 'TEST CUSTOMER A',
    'posting_date': today(),
    'due_date': add_days(today(), 30),
    'debit_to': 'Debtors - E',  # Receivable account
    'items': [{
        'item_code': 'TEST-SALES-001',
        'qty': 5,
        'rate': 100.0,
        'income_account': 'Sales - E'
    }],
    'company': 'EPIUSE',
    'currency': 'ZAR'
}
```

### Approach 2: Invoice from Sales Order
Create invoices by referencing existing Sales Orders.

**Advantages:**
- Leverages existing order data
- More realistic business flow
- Tests order-to-invoice workflow

**Challenges:**
- More complex validation
- Requires order submission first
- Additional reference validations

**Decision:** Start with Approach 1 (Direct Creation) for simplicity

## Phase 3.2: Purchase Invoice Creation Strategy

### Direct Purchase Invoice Creation

**Structure:**
```python
purchase_invoice = {
    'supplier': 'TEST SUPPLIER A',
    'posting_date': today(),
    'due_date': add_days(today(), 30),
    'credit_to': 'Accounts Payable - E',  # Payable account
    'items': [{
        'item_code': 'TEST-PURCHASE-001',
        'qty': 15,
        'rate': 75.0,
        'expense_account': 'Cost of Goods Sold - E'
    }],
    'company': 'EPIUSE',
    'currency': 'ZAR'
}
```

## Expected Validation Challenges

### Challenge 1: Account Mapping Validation
**Issue:** Items must have proper income/expense account mappings
**Solution:** Use default company accounts (Sales - E, Cost of Goods Sold - E)

### Challenge 2: Debit To / Credit To Account
**Issue:** Must be Receivable/Payable type accounts
**Solution:** Use Debtors - E and Accounts Payable - E (or Employee Advances - E)

### Challenge 3: Cost Center Requirement
**Issue:** Some companies require cost centers
**Solution:** Check if required, create/use default if needed

### Challenge 4: Tax Template Validation
**Issue:** Tax calculations may be required
**Solution:** Start without taxes, add if validation requires

### Challenge 5: Item Price Validation
**Issue:** Item prices must exist in price list
**Solution:** Use item's standard_rate directly in invoice line

### Challenge 6: Warehouse for Stock Items
**Issue:** Stock items may require warehouse
**Solution:** Use non-stock items (TEST-SALES, TEST-PURCHASE) or specify default warehouse

## Implementation Plan

### Step 1: Account Mapping Verification (Phase 3.0)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase3_0_verify_account_mappings.py
```

**Actions:**
- Verify Debtors - E (Receivable)
- Verify Accounts Payable - E or Employee Advances - E
- Check Cost Center requirements
- Validate item account mappings

### Step 2: Create Sales Invoices (Phase 3.1)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase3_1_create_sales_invoices.py
```

**Create 5 Sales Invoices:**
1. Customer: TEST CUSTOMER A, Item: TEST-SALES-001
2. Customer: TEST CUSTOMER B, Item: TEST-SALES-002
3. Customer: TEST CUSTOMER C, Item: TEST-SALES_FT
4. Customer: TEST CUSTOMER D, Item: TEST-MULTI-001
5. Customer: TEST CUSTOMER_FT, Item: TEST-SALES-001

### Step 3: Create Purchase Invoices (Phase 3.2)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase3_2_create_purchase_invoices.py
```

**Create 5 Purchase Invoices:**
1. Supplier: TEST SUPPLIER A, Item: TEST-PURCHASE-001
2. Supplier: TEST SUPPLIER B, Item: TEST-PURCHASE-002
3. Supplier: TEST SUPPLIER C, Item: TEST-PURCHASE_FT
4. Supplier: TEST SUPPLIER D, Item: TEST-MULTI-001
5. Supplier: TEST SUPPLIER_FT, Item: TEST-PURCHASE-001

### Step 4: Validate Invoices (Phase 3.3)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase3_3_validate_invoices.py
```

**Validation:**
- Confirm all invoices created
- Check account postings
- Verify amounts and calculations
- Confirm draft status

## Success Criteria

### ✅ Phase 3 Complete When:
- [ ] At least 5 Sales Invoices created successfully
- [ ] At least 5 Purchase Invoices created successfully
- [ ] All invoices reference existing Customers/Suppliers
- [ ] All invoices reference existing Items
- [ ] Account mappings validated (Debtors, Accounts Payable, Income, Expense)
- [ ] All invoices in Draft status (docstatus=0)
- [ ] All commands logged in `successfull_terminal_entity_creations.md`

### ✅ Ready for Phase 4 When:
- [ ] Invoices can be submitted (docstatus=1)
- [ ] Account postings are correct
- [ ] Ready for Payment Entry creation
- [ ] Xero sync can be tested on invoices

## Risk Mitigation Strategies

### Strategy 1: Use Non-Stock Items
**Risk:** Stock items require warehouse and inventory management
**Mitigation:** Use TEST-SALES and TEST-PURCHASE items (non-stock)

### Strategy 2: Minimal Account Mappings
**Risk:** Complex account mapping requirements
**Mitigation:** Use company default accounts only

### Strategy 3: No Tax Initially
**Risk:** Tax template validation complexity
**Mitigation:** Create invoices without taxes first

### Strategy 4: Draft Status Only
**Risk:** Submission triggers additional validations
**Mitigation:** Keep all invoices in draft initially

### Strategy 5: Single Item Per Invoice
**Risk:** Multi-item invoices add complexity
**Mitigation:** One item per invoice for simplicity

## Fallback Plans

### If Direct Creation Fails:
1. **Try from Sales Order:** Create invoice from existing Sales Order
2. **Simplify Further:** Remove optional fields
3. **Check Xero Settings:** Verify Xero account mappings don't interfere
4. **Manual Intervention:** Document what fields are absolutely required

### If Account Mapping Fails:
1. **Create Missing Accounts:** If required accounts don't exist
2. **Update Item Defaults:** Set income/expense accounts on items
3. **Company Defaults:** Update company default accounts

## Expected Outcomes

### Optimistic Scenario:
- All 10 invoices created successfully
- Minimal validation errors
- Ready for submission and Xero sync

### Realistic Scenario:
- 5-8 invoices created successfully
- Some validation errors requiring fixes
- Need to adjust account mappings

### Pessimistic Scenario:
- 1-3 invoices created
- Multiple validation errors
- Require significant troubleshooting

**Preparation:** Scripts designed to handle all scenarios with detailed error reporting

## Next Steps After Phase 3

1. **Submit Invoices:** Change docstatus from 0 to 1
2. **Test Xero Sync:** Sync invoices to Xero
3. **Phase 4:** Create Payment Entries for invoices
4. **Phase 5:** Test Credit Notes

## Documentation

All successful commands will be logged in:
- `successfull_terminal_entity_creations.md` - Command log with results
- `phase3_sales_purchase_invoices_plan.md` - This planning document

---

**Plan Created:** 2025-12-08  
**Status:** Ready for Implementation  
**Prerequisites:** ✅ Phase 1 & 2 complete (34 entities ready)  
**Next Action:** Execute Phase 3.0 - Account Mapping Verification