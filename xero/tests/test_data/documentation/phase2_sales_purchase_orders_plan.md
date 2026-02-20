# Phase 2: Sales and Purchase Orders Creation Plan

## Objective

Create Sales Orders and Purchase Orders via terminal to test Level 2 dependencies (Master Data + Items) and prepare for Xero sync testing.

## Background

Based on [`xero_entities_ordered_by_dependency.md`](xero_entities_ordered_by_dependency.md):
- **Phase 1 Complete:** ✅ Master Data Setup (Customers, Suppliers, Items, Journal Entries)
- **Phase 2 Next:** Sales/Purchase Orders with pre-existing master data
- **Complexity:** High - Multiple master data dependencies
- **Terminal Feasibility:** ❌ Difficult without extensive setup (but we have the setup!)

## Prerequisites (Already Complete ✅)

From Phase 1, we have:
- ✅ 5 Customers (TEST CUSTOMER A, B, C, D, _FT)
- ✅ 5 Suppliers (TEST SUPPLIER A, B, C, D, _FT)
- ✅ 10 Items with pricing:
  - Sales Items: TEST-SALES-001, TEST-SALES-002, TEST-SALES_FT
  - Purchase Items: TEST-PURCHASE-001, TEST-PURCHASE-002, TEST-PURCHASE_FT
  - Stock Items: TEST-STOCK-001, TEST-STOCK-002, TEST-STOCK_FT
  - Multi-purpose: TEST-MULTI-001
- ✅ Company: EPIUSE
- ✅ Default accounts configured

## Phase 2.1: Sales Order Creation

### Dependencies Required:
1. ✅ Customer (we have 5)
2. ✅ Items with sales enabled (we have 4: TEST-SALES-001, 002, _FT, TEST-MULTI-001)
3. ⚠️ Pricing rules (may use item standard_rate)
4. ⚠️ Price List (may need to check/create)

### Sales Order Structure:
```python
sales_order = {
    'customer': 'TEST CUSTOMER A',
    'transaction_date': today(),
    'delivery_date': add_days(today(), 7),
    'items': [
        {
            'item_code': 'TEST-SALES-001',
            'qty': 10,
            'rate': 100.0,  # from item.standard_rate
            'amount': 1000.0
        }
    ],
    'company': 'EPIUSE'
}
```

### Validation Challenges:
- Price List validation
- Delivery date requirements
- Item availability checks
- Tax template requirements (optional)

### Terminal Script Strategy:
1. Check for default Price List
2. Create Sales Order with minimal required fields
3. Use item's standard_rate for pricing
4. Set delivery_date to avoid validation errors
5. Keep it simple - single item per order initially

## Phase 2.2: Purchase Order Creation

### Dependencies Required:
1. ✅ Supplier (we have 5)
2. ✅ Items with purchase enabled (we have 4: TEST-PURCHASE-001, 002, _FT, TEST-MULTI-001)
3. ⚠️ Pricing rules (may use item standard_rate)
4. ⚠️ Price List (may need to check/create)

### Purchase Order Structure:
```python
purchase_order = {
    'supplier': 'TEST SUPPLIER A',
    'transaction_date': today(),
    'schedule_date': add_days(today(), 7),
    'items': [
        {
            'item_code': 'TEST-PURCHASE-001',
            'qty': 20,
            'rate': 75.0,  # from item.standard_rate
            'amount': 1500.0
        }
    ],
    'company': 'EPIUSE'
}
```

### Validation Challenges:
- Price List validation
- Schedule date requirements
- Item availability checks
- Supplier-specific pricing

### Terminal Script Strategy:
1. Check for default Purchase Price List
2. Create Purchase Order with minimal required fields
3. Use item's standard_rate for pricing
4. Set schedule_date to avoid validation errors
5. Keep it simple - single item per order initially

## Phase 2.3: Price List Investigation

Before creating orders, we need to:

### Investigation Script:
```bash
# Check existing price lists
bench --site cohenix.localhost execute "
import frappe
price_lists = frappe.get_all('Price List', fields=['name', 'buying', 'selling', 'enabled'])
for pl in price_lists:
    print(f'{pl.name}: Buying={pl.buying}, Selling={pl.selling}, Enabled={pl.enabled}')
"
```

### Fallback Strategy:
If no price lists exist, we can:
1. Create a simple "Standard Selling" price list
2. Create a simple "Standard Buying" price list
3. Or use `ignore_pricing_rule=1` flag

## Implementation Plan

### Step 1: Price List Discovery (Phase 2.0)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase2_0_check_price_lists.py
```

**Script:** Check existing price lists and company defaults

### Step 2: Create Sales Order (Phase 2.1)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase2_1_create_sales_order.py
```

**Script:** Create test Sales Order with:
- Customer: TEST CUSTOMER_FT
- Item: TEST-SALES_FT
- Qty: 5
- Rate: 100.0 (from item)

### Step 3: Create Purchase Order (Phase 2.2)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase2_2_create_purchase_order.py
```

**Script:** Create test Purchase Order with:
- Supplier: TEST SUPPLIER_FT
- Item: TEST-PURCHASE_FT
- Qty: 10
- Rate: 75.0 (from item)

### Step 4: Validate Orders (Phase 2.3)
```bash
cd /workspace/cohenix-bench && bench --site cohenix.localhost console < phase2_3_validate_orders.py
```

**Script:** Validate both orders were created successfully

## Expected Challenges & Solutions

### Challenge 1: Price List Required
**Solution:** Check company defaults, create if needed, or use `ignore_pricing_rule=1`

### Challenge 2: Warehouse Required for Stock Items
**Solution:** Use non-stock items (TEST-SALES, TEST-PURCHASE) or specify default warehouse

### Challenge 3: Tax Template Validation
**Solution:** Leave taxes empty initially, add if required

### Challenge 4: Delivery/Schedule Date Validation
**Solution:** Set dates to future (7 days from today)

### Challenge 5: Item Price Not Found
**Solution:** Use item's standard_rate directly in order line

## Success Criteria

### ✅ Phase 2 Complete When:
- [ ] At least 1 Sales Order created successfully
- [ ] At least 1 Purchase Order created successfully
- [ ] Orders reference existing Customers/Suppliers
- [ ] Orders reference existing Items with pricing
- [ ] Orders are in Draft status (docstatus=0)
- [ ] All commands logged in `successfull_terminal_entity_creations.md`

### ✅ Ready for Phase 3 When:
- [ ] Sales Orders can be submitted (docstatus=1)
- [ ] Purchase Orders can be submitted (docstatus=1)
- [ ] Orders are ready for Invoice creation
- [ ] Xero sync can be tested on orders

## Risk Mitigation

### Low Risk Items:
- Using _FT test entities (proven to work)
- Single item per order (simplest case)
- Draft status only (no submission initially)

### Medium Risk Items:
- Price List requirements
- Warehouse requirements for stock items
- Tax calculations

### High Risk Items:
- Complex pricing rules
- Multi-currency scenarios
- Advanced tax configurations

**Mitigation:** Start simple, add complexity incrementally

## Next Steps After Phase 2

1. **Phase 3:** Create Sales/Purchase Invoices from Orders
2. **Phase 4:** Create Payment Entries for Invoices
3. **Phase 5:** Test Xero sync for all transaction types
4. **Phase 6:** Create Credit Notes and test complex scenarios

## Documentation

All successful commands will be logged in:
- `successfull_terminal_entity_creations.md` - Command log
- `phase2_sales_purchase_orders_plan.md` - This planning document

---

**Plan Created:** 2025-12-08  
**Status:** Ready for Implementation  
**Prerequisites:** ✅ All Phase 1 master data complete  
**Next Action:** Execute Phase 2.0 - Price List Discovery