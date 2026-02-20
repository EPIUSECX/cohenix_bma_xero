# Quick Reference Card - Xero Test Data Scripts

## 🚀 Quick Start Commands

### Run Complete Setup (All 50 Entities)
```bash
cd /workspace/cohenix-bench

# Phase 1: Master Data (24 entities)
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/01_analyze_chart_of_accounts.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/02_identify_key_accounts.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/03_create_customers.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/04_add_customer_addresses.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/05_create_suppliers.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/06_create_items.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/07_create_final_test_entities.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/08_validate_master_data.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/09_create_journal_entry.py

# Phase 2: Orders (10 entities)
bench --site cohenix.localhost console < xero_test_data_scripts/phase2_orders/01_check_price_lists.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase2_orders/02_create_sales_purchase_orders.py

# Phase 3: Invoices (10 entities)
bench --site cohenix.localhost console < xero_test_data_scripts/phase3_invoices/01_verify_account_mappings.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase3_invoices/02_create_sales_invoices.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase3_invoices/03_create_purchase_invoices.py

# Phase 4: Returns (6 entities)
bench --site cohenix.localhost console < xero_test_data_scripts/phase4_returns/01_submit_invoices.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase4_returns/02_create_credit_notes.py
bench --site cohenix.localhost console < xero_test_data_scripts/phase4_returns/03_create_debit_notes.py
```

## 📋 Entity Summary

| Entity Type | Count | Phase | Script |
|-------------|-------|-------|--------|
| Customers | 5 | 1 | 03_create_customers.py |
| Suppliers | 5 | 1 | 05_create_suppliers.py |
| Items | 10 | 1 | 06_create_items.py |
| Addresses | 3 | 1 | 04_add_customer_addresses.py |
| Journal Entries | 1 | 1 | 09_create_journal_entry.py |
| Sales Orders | 5 | 2 | 02_create_sales_purchase_orders.py |
| Purchase Orders | 5 | 2 | 02_create_sales_purchase_orders.py |
| Sales Invoices | 5 | 3 | 02_create_sales_invoices.py |
| Purchase Invoices | 5 | 3 | 03_create_purchase_invoices.py |
| Credit Notes | 3 | 4 | 02_create_credit_notes.py |
| Debit Notes | 3 | 4 | 03_create_debit_notes.py |
| **TOTAL** | **50** | **1-4** | **17 scripts** |

## 🎯 Key Entities for Testing

### Customers:
- TEST CUSTOMER A, B, C, D (original set)
- TEST CUSTOMER_FT (final test)

### Suppliers:
- TEST SUPPLIER A, B, C, D (original set)
- TEST SUPPLIER_FT (final test)

### Items:
- **Sales:** TEST-SALES-001, 002, _FT
- **Purchase:** TEST-PURCHASE-001, 002, _FT
- **Stock:** TEST-STOCK-001, 002, _FT
- **Multi:** TEST-MULTI-001

### Invoices (Submitted):
- **Sales:** ACC-SINV-2025-00001, 00002, 00003
- **Purchase:** ACC-PINV-2025-00001, 00002, 00003

### Returns:
- **Credit Notes:** ACC-SINV-2025-00006, 00007, 00008
- **Debit Notes:** ACC-PINV-2025-00006, 00007, 00008

## 🔧 Account Configuration

| Account Purpose | Account Name | Type |
|----------------|--------------|------|
| Receivable (Sales) | Debtors - E | Receivable |
| Payable (Purchase) | Employee Advances - E | Payable |
| Income (Sales) | 200 - 200 - Sales - E | Income Account |
| Expense (Purchase) | Cost of Goods Sold - E | Cost of Goods Sold |
| Cost Center | Main - E | Cost Center |
| Cash | Cash - E | Cash |

## 💰 Financial Summary

| Transaction Type | Count | Total Amount (ZAR) |
|-----------------|-------|-------------------|
| Sales Invoices | 5 | 4,200.0 |
| Purchase Invoices | 5 | 8,100.0 |
| Credit Notes | 3 | -900.0 |
| Debit Notes | 3 | -1,725.0 |
| Journal Entry | 1 | 500.0 (balanced) |

## 📖 Documentation Files

- **README.md** - Complete guide (this directory)
- **QUICK_REFERENCE.md** - This quick reference card
- **documentation/comprehensive_master_data_setup_plan.md** - Phase 1 plan
- **documentation/phase2_sales_purchase_orders_plan.md** - Phase 2 plan
- **documentation/phase3_sales_purchase_invoices_plan.md** - Phase 3 plan
- **documentation/phase4_credit_notes_plan.md** - Phase 4 plan

## ⚡ One-Line Commands

### Create All Master Data:
```bash
cd /workspace/cohenix-bench && for s in xero_test_data_scripts/phase1_master_data/*.py; do bench --site cohenix.localhost console < "$s"; done
```

### Create All Orders:
```bash
cd /workspace/cohenix-bench && for s in xero_test_data_scripts/phase2_orders/*.py; do bench --site cohenix.localhost console < "$s"; done
```

### Create All Invoices:
```bash
cd /workspace/cohenix-bench && for s in xero_test_data_scripts/phase3_invoices/*.py; do bench --site cohenix.localhost console < "$s"; done
```

### Create All Returns:
```bash
cd /workspace/cohenix-bench && for s in xero_test_data_scripts/phase4_returns/*.py; do bench --site cohenix.localhost console < "$s"; done
```

## 🎓 Learning Path

1. **Start Here:** Read README.md for complete overview
2. **Understand Phases:** Review documentation/ planning files
3. **Run Phase 1:** Create master data foundation
4. **Validate:** Use 08_validate_master_data.py
5. **Progress:** Move through phases 2-4 sequentially
6. **Test Sync:** Use Xero sync commands from xero_sync_terminal_operations_guide.md

## 🔍 Verification Commands

### Check Customers:
```bash
bench --site cohenix.localhost execute "frappe.get_all('Customer', filters={'customer_name': ['like', 'TEST%']}, fields=['name', 'customer_type'])"
```

### Check Items:
```bash
bench --site cohenix.localhost execute "frappe.get_all('Item', filters={'item_code': ['like', 'TEST%']}, fields=['name', 'is_sales_item', 'is_purchase_item'])"
```

### Check Invoices:
```bash
bench --site cohenix.localhost execute "frappe.get_all('Sales Invoice', filters={'customer': ['like', 'TEST%']}, fields=['name', 'customer', 'grand_total', 'docstatus'])"
```

---

**Version:** 1.0  
**Last Updated:** 2025-12-08  
**Total Scripts:** 17  
**Total Entities:** 50  
**Status:** Production Ready ✅