# Xero Test Data Creation Scripts

## Overview

This directory contains all Python scripts used to create comprehensive test data for ERPNext-Xero integration testing. All scripts are designed to be run via `bench --site cohenix.localhost console` and have been successfully tested.

## Directory Structure

```
xero_test_data_scripts/
├── phase1_master_data/      # Master data entities (Customers, Suppliers, Items, etc.)
├── phase2_orders/           # Sales and Purchase Orders
├── phase3_invoices/         # Sales and Purchase Invoices
├── phase4_returns/          # Credit Notes and Debit Notes
├── documentation/           # Planning documents and guides
└── README.md               # This file
```

## Quick Start

### Running Scripts

All scripts should be run from the bench directory:

```bash
cd /workspace/cohenix-bench
bench --site cohenix.localhost console < xero_test_data_scripts/[phase]/[script_name].py
```

### Example:
```bash
cd /workspace/cohenix-bench
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/03_create_customers.py
```

## Phase 1: Master Data (Foundation)

**Directory:** `phase1_master_data/`

### Scripts (in execution order):

1. **01_analyze_chart_of_accounts.py**
   - Analyzes existing Chart of Accounts
   - Identifies default company accounts
   - Lists available accounts for testing

2. **02_identify_key_accounts.py**
   - Identifies key account types needed
   - Validates account availability
   - Maps accounts by type

3. **03_create_customers.py**
   - Creates 4 test customers (2 Company, 2 Individual)
   - Names: TEST CUSTOMER A, B, C, D

4. **04_add_customer_addresses.py**
   - Adds billing addresses to customers
   - Links addresses to customer records

5. **05_create_suppliers.py**
   - Creates 4 test suppliers (2 Company, 2 Individual)
   - Names: TEST SUPPLIER A, B, C, D

6. **06_create_items.py**
   - Creates 7 test items
   - Types: Sales (2), Purchase (2), Stock (2), Multi-purpose (1)
   - Names: TEST-SALES-001/002, TEST-PURCHASE-001/002, TEST-STOCK-001/002, TEST-MULTI-001

7. **07_create_final_test_entities.py**
   - Creates final test entities with _FT suffix
   - Entities: 1 Customer, 1 Supplier, 3 Items (Sales, Purchase, Stock)
   - Names: TEST CUSTOMER_FT, TEST SUPPLIER_FT, TEST-SALES_FT, TEST-PURCHASE_FT, TEST-STOCK_FT

8. **08_validate_master_data.py**
   - Validates all created master data entities
   - Provides comprehensive summary
   - Confirms entity counts

9. **09_create_journal_entry.py**
   - Creates basic Journal Entry for testing
   - Uses Cash and Prepaid Expenses accounts
   - Balanced debit/credit: 500.0 ZAR

**Entities Created:** 24 (5 Customers, 5 Suppliers, 10 Items, 3 Addresses, 1 Journal Entry)

## Phase 2: Orders (Level 2 Complexity)

**Directory:** `phase2_orders/`

### Scripts (in execution order):

1. **01_check_price_lists.py**
   - Discovers existing price lists
   - Identifies: Standard Selling, Standard Buying
   - Verifies currency: ZAR

2. **02_create_sales_purchase_orders.py**
   - Creates 5 Sales Orders (SAL-ORD-2025-00002 through 00006)
   - Creates 5 Purchase Orders (PUR-ORD-2025-00002 through 00006)
   - Uses Standard Selling/Buying price lists

**Entities Created:** 10 (5 Sales Orders, 5 Purchase Orders)

## Phase 3: Invoices (Very High Complexity)

**Directory:** `phase3_invoices/`

### Scripts (in execution order):

1. **01_verify_account_mappings.py**
   - Verifies Receivable account: Debtors - E
   - Verifies Payable account: Employee Advances - E
   - Verifies Income account: 200 - 200 - Sales - E
   - Verifies Expense account: Cost of Goods Sold - E
   - Identifies Cost Center: Main - E

2. **02_create_sales_invoices.py**
   - Creates 5 Sales Invoices (ACC-SINV-2025-00001 through 00005)
   - Total amount: 4,200.0 ZAR
   - Uses Debtors - E as debit_to account

3. **03_create_purchase_invoices.py**
   - Creates 5 Purchase Invoices (ACC-PINV-2025-00001 through 00005)
   - Total amount: 8,100.0 ZAR
   - Uses Employee Advances - E as credit_to account

**Entities Created:** 10 (5 Sales Invoices, 5 Purchase Invoices)

## Phase 4: Returns (Extreme Complexity)

**Directory:** `phase4_returns/`

### Scripts (in execution order):

1. **01_submit_invoices.py**
   - Submits 3 Sales Invoices (changes docstatus 0→1)
   - Submits 3 Purchase Invoices (changes docstatus 0→1)
   - Required before creating returns

2. **02_create_credit_notes.py**
   - Creates 3 Credit Notes (Sales Returns)
   - Names: ACC-SINV-2025-00006, 00007, 00008
   - Partial returns with negative amounts
   - Total credit: -900.0 ZAR

3. **03_create_debit_notes.py**
   - Creates 3 Debit Notes (Purchase Returns)
   - Names: ACC-PINV-2025-00006, 00007, 00008
   - Partial returns with negative amounts
   - Total debit: -1,725.0 ZAR

**Entities Created:** 6 (3 Credit Notes, 3 Debit Notes)

## Documentation

**Directory:** `documentation/`

### Planning Documents:

1. **comprehensive_master_data_setup_plan.md**
   - Original Phase 1 master data plan
   - Detailed account analysis strategies
   - Customer/Supplier/Item creation templates

2. **phase2_sales_purchase_orders_plan.md**
   - Sales and Purchase Order creation strategy
   - Price list requirements
   - Dependency analysis

3. **phase3_sales_purchase_invoices_plan.md**
   - Invoice creation strategy
   - Account mapping requirements
   - Validation challenge solutions

4. **phase4_credit_notes_plan.md**
   - Credit/Debit Note creation strategy
   - Return validation requirements
   - Invoice submission prerequisites

## Total Entities Created

**50 Entities Across All Phases:**
- 5 Customers
- 5 Suppliers
- 10 Items
- 3 Addresses
- 1 Journal Entry
- 5 Sales Orders
- 5 Purchase Orders
- 8 Sales Invoices (5 original + 3 credit notes)
- 8 Purchase Invoices (5 original + 3 debit notes)

## System Configuration

- **Company:** EPIUSE
- **Currency:** ZAR (South African Rand)
- **Default Income Account:** Sales - E
- **Default Expense Account:** Cost of Goods Sold - E
- **Receivable Account:** Debtors - E
- **Payable Account:** Employee Advances - E
- **Cost Center:** Main - E
- **Selling Price List:** Standard Selling
- **Buying Price List:** Standard Buying

## Usage Patterns

### Pattern 1: Run Individual Script
```bash
cd /workspace/cohenix-bench
bench --site cohenix.localhost console < xero_test_data_scripts/phase1_master_data/03_create_customers.py
```

### Pattern 2: Run All Scripts in a Phase
```bash
cd /workspace/cohenix-bench
for script in xero_test_data_scripts/phase1_master_data/*.py; do
    echo "Running $script..."
    bench --site cohenix.localhost console < "$script"
done
```

### Pattern 3: Run Complete Setup (All Phases)
```bash
cd /workspace/cohenix-bench

# Phase 1: Master Data
for script in xero_test_data_scripts/phase1_master_data/*.py; do
    bench --site cohenix.localhost console < "$script"
done

# Phase 2: Orders
for script in xero_test_data_scripts/phase2_orders/*.py; do
    bench --site cohenix.localhost console < "$script"
done

# Phase 3: Invoices
for script in xero_test_data_scripts/phase3_invoices/*.py; do
    bench --site cohenix.localhost console < "$script"
done

# Phase 4: Returns
for script in xero_test_data_scripts/phase4_returns/*.py; do
    bench --site cohenix.localhost console < "$script"
done
```

## Script Naming Convention

All scripts follow the pattern: `[number]_[descriptive_name].py`

- **Number:** Execution order within phase (01, 02, 03, etc.)
- **Descriptive Name:** Clear indication of script purpose
- **Extension:** .py for Python scripts

## Key Features

### ✅ Proven Success
- All scripts have been tested and verified
- Each script logs its success in `successfull_terminal_entity_creations.md`
- No manual intervention required

### ✅ Idempotent Design
- Scripts check for existing entities
- Delete and recreate to ensure clean state
- Safe to run multiple times

### ✅ Comprehensive Coverage
- All major ERPNext entity types
- Complete dependency chains
- Ready for Xero sync testing

### ✅ Well Documented
- Inline comments in scripts
- Detailed planning documents
- Success log with all commands

## Troubleshooting

### Common Issues:

1. **"Site not found" error**
   - Ensure you're in `/workspace/cohenix-bench` directory
   - Verify site name is `cohenix.localhost`

2. **"Permission denied" error**
   - Scripts may need execute permissions
   - Run: `chmod +x xero_test_data_scripts/[phase]/*.py`

3. **Validation errors**
   - Check that previous phase scripts completed successfully
   - Verify account mappings are correct
   - Review error messages in console output

### Getting Help:

- Review planning documents in `documentation/` folder
- Check `successfull_terminal_entity_creations.md` for working examples
- Examine script source code for inline comments

## Next Steps

After running all scripts, you can:

1. **Test Xero Sync:** Use scripts from `xero_sync_terminal_operations_guide.md`
2. **Create More Entities:** Modify scripts to create additional test data
3. **Test Workflows:** Submit orders, create invoices from orders, etc.
4. **Validate Data:** Run validation scripts to confirm entity integrity

## Maintenance

### Adding New Scripts:
1. Create script in appropriate phase directory
2. Follow naming convention: `[next_number]_[description].py`
3. Test thoroughly before committing
4. Document in `successfull_terminal_entity_creations.md`

### Updating Existing Scripts:
1. Test changes in development environment
2. Update version comments in script
3. Document changes in success log
4. Update this README if behavior changes

---

**Created:** 2025-12-08  
**Last Updated:** 2025-12-08  
**Status:** Production Ready  
**Total Scripts:** 17  
**Total Entities:** 50