# Comprehensive Master Data Setup Plan for Journal Entry Testing

## Objective

Create a complete Customer/Supplier/Item setup via terminal to enable successful Journal Entry creation and testing with proper account mappings.

## Background

Based on dependency analysis:
- **Level 1**: Journal Entry (requires only accounts + balanced entries)
- **Level 2**: Sales/Purchase Orders (require customers/suppliers + items)
- **Level 3**: Invoices/Payments (require complex reference chains)

This plan focuses on **Phase 1: Master Data Setup** to enable reliable Journal Entry testing.

## Phase 1: Account Discovery and Analysis

### 1.1 Analyze Existing Chart of Accounts

**Terminal Commands:**
```bash
# Get company information and default accounts
bench --site cohenix.localhost execute "
company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
print(f'Company: {company}')
default_income = frappe.get_cached_value('Company', company, 'default_income_account')
default_expense = frappe.get_cached_value('Company', company, 'default_expense_account')
default_asset = frappe.get_cached_value('Company', company, 'default_bank_account')
print(f'Default Income Account: {default_income}')
print(f'Default Expense Account: {default_expense}')
print(f'Default Bank Account: {default_asset}')
"

# Get all accounts with types for Journal Entry testing
bench --site cohenix.localhost execute "
accounts = frappe.get_all('Account', 
    fields=['name', 'account_type', 'is_group', 'company'],
    filters={'is_group': 0, 'company': frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')},
    limit=20)
for acc in accounts:
    print(f'{acc.name} ({acc.account_type})')
"
```

### 1.2 Identify Key Accounts for Journal Entry Testing

**Target Account Types:**
- **Asset Accounts**: Bank accounts, Cash accounts, Accounts Receivable
- **Liability Accounts**: Accounts Payable, Credit Card accounts
- **Equity Accounts**: Owner’s Equity, Retained Earnings
- **Income Accounts**: Sales Revenue, Other Income
- **Expense Accounts**: Operating Expenses, Cost of Goods Sold

**Terminal Validation:**
```bash
# Verify account existence for common journal entry patterns
bench --site cohenix.localhost execute "
required_accounts = [
    'Cash', 'Bank', 'Accounts Receivable', 'Accounts Payable',
    'Sales', 'Sales Revenue', 'Office Expenses', 'Cost of Sales'
]

company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
missing_accounts = []

for acc_name in required_accounts:
    exists = frappe.db.exists('Account', {'name': ['like', f'%{acc_name}%'], 'company': company})
    if not exists:
        missing_accounts.append(acc_name)
    else:
        print(f'✓ Found account: {exists}')

if missing_accounts:
    print(f'Missing accounts: {missing_accounts}')
else:
    print('All required accounts found!')
"
```

## Phase 2: Customer Creation Setup

### 2.1 Create Comprehensive Customer Test Data

**Terminal Script for Customer Creation:**
```bash
# Create multiple customers with different configurations
bench --site cohenix.localhost execute "
import frappe

def create_test_customer(customer_type, customer_name, territory=None, customer_group=None):
    '''Create a test customer with specified configuration'''
    
    # Clean up existing customer
    if frappe.db.exists('Customer', customer_name):
        frappe.delete_doc('Customer', customer_name, force=True)
        frappe.db.commit()
        print(f'Deleted existing customer: {customer_name}')
    
    # Create customer
    customer = frappe.new_doc('Customer')
    customer.customer_name = customer_name
    customer.customer_type = customer_type  # 'Company' or 'Individual'
    customer.territory = territory or frappe.get_cached_value('Territory', {'name': ('!=', '')}, 'name')
    customer.customer_group = customer_group or frappe.get_cached_value('Customer Group', {'name': ('!=', '')}, 'name')
    customer.company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
    
    customer.insert()
    frappe.db.commit()
    
    print(f'✓ Created {customer_type} customer: {customer.name}')
    return customer.name

# Create diverse customer test set
customers_created = []

# Company customers
customers_created.append(create_test_customer('Company', 'TEST CUSTOMER A'))
customers_created.append(create_test_customer('Company', 'TEST CUSTOMER B'))

# Individual customers  
customers_created.append(create_test_customer('Individual', 'TEST CUSTOMER C'))
customers_created.append(create_test_customer('Individual', 'TEST CUSTOMER D'))

print(f'Created {len(customers_created)} customers: {customers_created}')
"
```

### 2.2 Add Customer Addresses and Contacts

**Terminal Commands for Enhanced Customer Data:**
```bash
# Add billing and shipping addresses to customers
bench --site cohenix.localhost execute "
customers = ['TEST CUSTOMER A', 'TEST CUSTOMER B', 'TEST CUSTOMER C', 'TEST CUSTOMER D']

for customer_name in customers:
    if frappe.db.exists('Customer', customer_name):
        customer = frappe.get_doc('Customer', customer_name)
        
        # Add address
        if not customer.customer_address:
            address = frappe.new_doc('Address')
            address.address_title = f'{customer_name} - Billing'
            address.address_type = 'Billing'
            address.address_line1 = '123 Test Street'
            address.city = 'Test City'
            address.state = 'Test State'
            address.pincode = '12345'
            address.country = 'United States'
            address.insert()
            
            customer.customer_address = address.name
            customer.save()
            print(f'✓ Added address for {customer_name}')
        
        frappe.db.commit()
"
```

## Phase 3: Supplier Creation Setup

### 3.1 Create Comprehensive Supplier Test Data

**Terminal Script for Supplier Creation:**
```bash
# Create suppliers with different configurations
bench --site cohenix.localhost execute "
import frappe

def create_test_supplier(supplier_type, supplier_name, supplier_group=None):
    '''Create a test supplier with specified configuration'''
    
    # Clean up existing supplier
    if frappe.db.exists('Supplier', supplier_name):
        frappe.delete_doc('Supplier', supplier_name, force=True)
        frappe.db.commit()
        print(f'Deleted existing supplier: {supplier_name}')
    
    # Create supplier
    supplier = frappe.new_doc('Supplier')
    supplier.supplier_name = supplier_name
    supplier.supplier_type = supplier_type  # 'Company' or 'Individual'
    supplier.supplier_group = supplier_group or frappe.get_cached', {'name':_value('Supplier Group ('!=', '')}, 'name')
    supplier.company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
    
    supplier.insert()
    frappe.db.commit()
    
    print(f'✓ Created {supplier_type} supplier: {supplier.name}')
    return supplier.name

# Create diverse supplier test set
suppliers_created = []

# Company suppliers
suppliers_created.append(create_test_supplier('Company', 'TEST SUPPLIER A'))
suppliers_created.append(create_test_supplier('Company', 'TEST SUPPLIER B'))

# Individual suppliers
suppliers_createdplier('Individual',.append(create_test_sup 'TEST SUPPLIER C'))
suppliers_created.append(create_test_supplier('Individual', 'TEST SUPPLIER D'))

print(f'Created {len(suppliers_created)} suppliers: {suppliers_created}')
"
```

### 3.2 Add Supplier Payment Terms

**Terminal Commands for Supplier Configuration:**
```bash
# Add payment terms and bank details to suppliers
bench --site cohenix.localhost execute "
suppliers = ['TEST SUPPLIER A', 'TEST SUPPLIER B', 'TEST SUPPLIER C', 'TEST SUPPLIER D']

for supplier_name in suppliers:
    if frappe.db.exists('Supplier', supplier_name):
        supplier = frappe.get_doc('Supplier', supplier_name)
        
        # Add default payment terms
        if not supplier.payment_terms:
            supplier.payment_terms = frappe.get_cached_value('Payment Terms Template', {'name': ('!=', '')}, 'name')
            supplier.save()
            print(f'✓ Added payment terms for {supplier_name}')
        
        frappe.db.commit()
"
```

## Phase 4: Item Creation Setup

### 4.1 Create Comprehensive Item Test Data

**Terminal Script for Item Creation:**
```bash
# Create items with different configurations
bench --site cohenix.localhost execute "
import frappe

def create_test_item(item_type, item_name, is_sales_item=0, is_purchase_item=0, is_stock_item=0):
    '''Create a test item with specified configuration'''
    
    # Clean up existing item
    if frappe.db.exists('Item', item_name):
        frappe.delete_doc('Item', item_name, force=True)
        frappe.db.commit()
        print(f'Deleted existing item: {item_name}')
    
    # Get required references
    company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
    income_account = frappe.get_cached_value('Company', company, 'default_income_account')
    expense_account = frappe.get_cached_value('Company', company, 'default_expense_account')
    
    # Create item
    item = frappe.new_doc('Item')
    item.item_code = item_name
    item.item_name = item_name
    item.item_group = 'All Item Groups'
    item.stock_uom = 'Nos'
    item.is_sales_item = is_sales_item
    item.is_purchase_item = is_purchase_item  
    item.is_stock_item = is_stock_item
    
    # Add account references if needed
    if is_sales_item and income_account:
        item.income_account = income_account
        item.standard_selling_rate = 100.0
    
    if is_purchase_item and expense_account:
        item.expense_account = expense_account
        item.standard_buying_rate = 75.0
    
    item.insert()
    frappe.db.commit()
    
    print(f'✓ Created {item_type} item: {item.name}')
    return item.name

# Create diverse item test set
items_created = []

# Sales items
items_created.append(create_test_item('Sales Item', 'TEST-SALES-001', is_sales_item=1))
items_created.append(create_test_item('Sales Item', 'TEST-SALES-002', is_sales_item=1))

# Purchase items
items_created.append(create_test_item('Purchase Item', 'TEST-PURCHASE-001', is_purchase_item=1))
items_created.append(create_test_item('Purchase Item', 'TEST-PURCHASE-002', is_purchase_item=1))

# Stock items
items_created.append(create_test_item('Stock Item', 'TEST-STOCK-001', is_stock_item=1))
items_created.append(create_test_item('Stock Item', 'TEST-STOCK-002', is_stock_item=1))

# Multi-purpose items
items_created.append(create_test_item('Multi-Purpose Item', 'TEST-MULTI-001', is_sales_item=1, is_purchase_item=1, is_stock_item=1))

print(f'Created {len(items_created)} items: {items_created}')
"
```

### 4.2 Validate Item Creation and Sync Status

**Terminal Validation Commands:**
```bash
# Verify all items created successfully and check Xero sync status
bench --site cohenix.localhost execute "
items = ['TEST-SALES-001', 'TEST-SALES-002', 'TEST-PURCHASE-001', 'TEST-PURCHASE-002', 'TEST-STOCK-001', 'TEST-STOCK-002', 'TEST-MULTI-001']

print('=== Item Validation ===')
for item_code in items:
    if frappe.db.exists('Item', item_code):
        item = frappe.get_doc('Item', item_code)
        sync_status = item.get('xero_item_sync_status', 'Not Set')
        print(f'✓ {item_code}: Sales={item.is_sales_item}, Purchase={item.is_purchase_item}, Stock={item.is_stock_item}, Xero Status={sync_status}')
    else:
        print(f'✗ {item_code}: Not found')
"
```

## Phase 5: Journal Entry Creation Testing

### 5.1 Basic Journal Entry Tests

**Terminal Commands for Journal Entry Creation:**
```bash
# Test 1: Simple Cash Transaction
bench --site cohenix.localhost execute "
import frappe

def create_simple_journal_entry(entry_name, debit_account, credit_account, amount, description):
    '''Create a simple journal entry with debit and credit'''
    
    # Clean up existing entry
    if frappe.db.exists('Journal Entry', entry_name):
        frappe.delete_doc('Journal Entry', entry_name, force=True)
        frappe.db.commit()
    
    # Create journal entry
    je = frappe.new_doc('Journal Entry')
    je.voucher_type = 'Journal Entry'
    je.naming_series = 'JE-'
    je.company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
    je.posting_date = frappe.utils.today()
    je.total_debit = amount
    je.total_credit = amount
    je.user_remark = description
    
    # Add debit entry
    je.append('accounts', {
        'account': debit_account,
        'debit': amount,
        'credit': 0,
        'debit_in_account_currency': amount,
        'credit_in_account_currency': 0
    })
    
    # Add credit entry  
    je.append('accounts', {
        'account': credit_account,
        'debit': 0,
        'credit': amount,
        'debit_in_account_currency': 0,
        'credit_in_account_currency': amount
    })
    
    je.insert()
    frappe.db.commit()
    
    print(f'✓ Created journal entry: {je.name} for {description}')
    return je.name

# Test different account combinations
company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
accounts = frappe.get_all('Account', filters={'is_group': 0, 'company': company}, limit=10)

if len(accounts) >= 2:
    debit_acc = accounts[0].name
    credit_acc = accounts[1].name
    
    create_simple_journal_entry('JE-TEST-001', debit_acc, credit_acc, 1000.00, 'Test cash transaction')
    print(f'Used accounts: {debit_acc} -> {credit_acc}')
else:
    print('Insufficient accounts for testing')
"
```

### 5.2 Complex Journal Entry Tests

**Multi-line Journal Entries:**
```bash
# Test 2: Multi-line Journal Entry with multiple accounts
bench --site cohenix.localhost execute "
import frappe

def create_complex_journal_entry():
    '''Create a complex journal entry with multiple debit and credit lines'''
    
    # Clean up existing entry
    if frappe.db.exists('Journal Entry', 'JE-TEST-002'):
        frappe.delete_doc('Journal Entry', 'JE-TEST-002', force=True)
        frappe.db.commit()
    
    company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
    accounts = frappe.get_all('Account', filters={'is_group': 0, 'company': company}, limit=6)
    
    if len(accounts) >= 4:
        # Create multi-line journal entry
        je = frappe.new_doc('Journal Entry')
        je.voucher_type = 'Journal Entry'
        je.naming_series = 'JE-'
        je.company = company
        je.posting_date = frappe.utils.today()
        je.user_remark = 'Complex journal entry with multiple accounts'
        
        # Multiple debits
        je.append('accounts', {
            'account': accounts[0].name,
            'debit': 500.00,
            'credit': 0
        })
        
        je.append('accounts', {
            'account': accounts[1].name,
            'debit': 300.00,
            'credit': 0
        })
        
        # Multiple credits
        je.append('accounts', {
            'account': accounts[2].name,
            'debit': 0,
            'credit': 400.00
        })
        
        je.append('accounts', {
            'account': accounts[3].name,
            'debit': 0,
            'credit': 400.00
        })
        
        # Set totals
        je.total_debit = 800.00
        je.total_credit = 800.00
        
        je.insert()
        frappe.db.commit()
        
        print(f'✓ Created complex journal entry: {je.name}')
        print(f'Total Debit: {je.total_debit}, Total Credit: {je.total_credit}')
        return je.name
    else:
        print('Insufficient accounts for complex testing')

create_complex_journal_entry()
"
```

### 5.3 Customer/Supplier Related Journal Entries

**Journal Entries with Customer/Supplier References:**
```bash
# Test 3: Journal Entry with customer/supplier references
bench --site cohenix.localhost execute "
import frappe

def create_customer_supplier_journal_entry():
    '''Create journal entries that reference customers and suppliers'''
    
    company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
    
    # Get customer and supplier
    customer = frappe.get_all('Customer', limit=1)
    supplier = frappe.get_all('Supplier', limit=1)
    accounts = frappe.get_all('Account', filters={'is_group': 0, 'company': company}, limit=4)
    
    if customer and supplier and len(accounts) >= 2:
        # Create customer-related entry
        je1 = frappe.new_doc('Journal Entry')
        je1.voucher_type = 'Journal Entry'
        je1.naming_series = 'JE-'
        je1.company = company
        je1.posting_date = frappe.utils.today()
        je1.user_remark = 'Customer advance payment'
        
        je1.append('accounts', {
            'account': accounts[0].name,
            'party_type': 'Customer',
            'party': customer[0].name,
            'debit': 1000.00,
            'credit': 0
        })
        
        je1.append('accounts', {
            'account': accounts[1].name,
            'debit': 0,
            'credit': 1000.00
        })
        
        je1.total_debit = 1000.00
        je1.total_credit = 1000.00
        je1.insert()
        
        # Create supplier-related entry
        je2 = frappe.new_doc('Journal Entry')
        je2.voucher_type = 'Journal Entry'
        je2.naming_series = 'JE-'
        je2.company = company
        je2.posting_date = frappe.utils.today()
        je2.user_remark = 'Supplier payment'
        
        je2.append('accounts', {
            'account': accounts[2].name,
            'debit': 0,
            'credit': 750.00
        })
        
        je2.append('accounts', {
            'account': accounts[3].name,
            'party_type': 'Supplier',
            'party': supplier[0].name,
            'debit': 750.00,
            'credit': 0
        })
        
        je2.total_debit = 750.00
        je2.total_credit = 750.00
        je2.insert()
        
        frappe.db.commit()
        
        print(f'✓ Created customer journal entry: {je1.name}')
        print(f'✓ Created supplier journal entry: {je2.name}')
        
        return [je1.name, je2.name]
    else:
        print('Insufficient data for customer/supplier testing')

create_customer_supplier_journal_entry()
"
```

## Phase 6: Validation and Xero Sync Testing

### 6.1 Validate All Created Entities

**Comprehensive Validation Script:**
```bash
# Validate all created entities and their relationships
bench --site cohenix.localhost execute "
print('=== COMPREHENSIVE ENTITY VALIDATION ===')

# Check customers
customers = frappe.get_all('Customer', filters={'customer_name': ['like', 'TEST%']})
print(f'Customers created: {len(customers)}')
for cust in customers:
    customer_doc = frappe.get_doc('Customer', cust.name)
    print(f'  - {customer_doc.customer_name} ({customer_doc.customer_type})')

# Check suppliers  
suppliers = frappe.get_all('Supplier', filters={'supplier_name': ['like', 'TEST%']})
print(f'Suppliers created: {len(suppliers)}')
for supp in suppliers:
    supplier_doc = frappe.get_doc('Supplier', supp.name)
    print(f'  - {supplier_doc.supplier_name} ({supplier_doc.supplier_type})')

# Check items
items = frappe.get_all('Item', filters={'item_code': ['like', 'TEST-%']})
print(f'Items created: {len(items)}')
for item in items:
    item_doc = frappe.get_doc('Item', item.name)
    print(f'  - {item_doc.item_code} (Sales: {item_doc.is_sales_item}, Purchase: {item_doc.is_purchase_item}, Stock: {item_doc.is_stock_item})')

# Check journal entries
journal_entries = frappe.get_all('Journal Entry', filters={'name': ['like', 'JE-TEST%']})
print(f'Journal entries created: {len(journal_entries)}')
for je in journal_entries:
    je_doc = frappe.get_doc('Journal Entry', je.name)
    print(f'  - {je_doc.name}: Total Debit={je_doc.total_debit}, Total Credit={je_doc.total_credit}')
"
```

### 6.2 Test Xero Sync for All Entities

**Xero Sync Testing Commands:**
```bash
# Test Xero sync for customers
bench --site cohenix.localhost execute "
customers = frappe.get_all('Customer', filters={'customer_name': ['like', 'TEST%']}, limit=2)
for cust in customers:
    try:
        from xero.api.xero_contacts import sync_contact_to_xero
        sync_contact_to_xero(cust.name)
        print(f'✓ Customer {cust.name} sync initiated')
    except Exception as e:
        print(f'✗ Customer {cust.name} sync failed: {e}')
"

# Test Xero sync for items
bench --site cohenix.localhost execute "
items = frappe.get_all('Item', filters={'item_code': ['like', 'TEST-%']}, limit=3)
for item in items:
    try:
        from xero.api.xero_items import sync_item_to_xero
        sync_item_to_xero(item.name)
        print(f'✓ Item {item.name} sync initiated')
    except Exception as e:
        print(f'✗ Item {item.name} sync failed: {e}')
"
```

## Phase 7: Master Data Summary and Usage Guide

### 7.1 Master Data Summary

**Created Entities Summary:**
```bash
# Generate summary of all created master data
bench --site cohenix.localhost execute "
summary = {
    'customers': [],
    'suppliers': [],
    'items': [],
    'accounts': [],
    'journal_entries': []
}

# Get customers
customers = frappe.get_all('Customer', filters={'customer_name': ['like', 'TEST%']})
for cust in customers:
    summary['customers'].append({
        'name': cust.name,
        'type': frappe.get_value('Customer', cust.name, 'customer_type')
    })

# Get suppliers
suppliers = frappe.get_all('Supplier', filters={'supplier_name': ['like', 'TEST%']})
for supp in suppliers:
    summary['suppliers'].append({
        'name': supp.name,
        'type': frappe.get_value('Supplier', supp.name, 'supplier_type')
    })

# Get items
items = frappe.get_all('Item', filters={'item_code': ['like', 'TEST-%']})
for item in items:
    summary['items'].append({
        'name': item.name,
        'sales': frappe.get_value('Item', item.name, 'is_sales_item'),
        'purchase': frappe.get_value('Item', item.name, 'is_purchase_item'),
        'stock': frappe.get_value('Item', item.name, 'is_stock_item')
    })

# Get accounts
company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
accounts = frappe.get_all('Account', filters={'is_group': 0, 'company': company}, limit=10)
for acc in accounts:
    summary['accounts'].append({
        'name': acc.name,
        'type': frappe.get_value('Account', acc.name, 'account_type')
    })

# Get journal entries
journal_entries = frappe.get_all('Journal Entry', filters={'name': ['like', 'JE-TEST%']})
for je in journal_entries:
    summary['journal_entries'].append({
        'name': je.name,
        'total': frappe.get_value('Journal Entry', je.name, 'total_debit')
    })

print('MASTER DATA SETUP COMPLETE')
print(f'Customers: {len(summary[\"customers\"])}')
print(f'Suppliers: {len(summary[\"suppliers\"])}')  
print(f'Items: {len(summary[\"items\"])}')
print(f'Accounts: {len(summary[\"accounts\"])}')
print(f'Journal Entries: {len(summary[\"journal_entries\"])}')
"
```

### 7.2 Journal Entry Testing Usage Guide

**Quick Reference Commands:**
```bash
# Create new test journal entry with existing accounts
bench --site cohenix.localhost execute "
# Get two different account types for testing
accounts = frappe.get_all('Account', 
    filters={'is_group': 0, 'company': frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')},
    fields=['name', 'account_type'],
    limit=4)

# Find asset and income accounts
asset_account = next((acc.name for acc in accounts if 'asset' in acc.account_type.lower()), accounts[0].name)
income_account = next((acc.name for acc in accounts if 'income' in acc.account_type.lower()), accounts[1].name)

print(f'Use these accounts for testing:')
print(f'Asset Account: {asset_account}')
print(f'Income Account: {income_account}')
"
```

## Success Criteria

### ✅ **Phase 1 Complete When:**
- [ ] At least 4 customers created (2 companies, 2 individuals)
- [ ] At least 4 suppliers created (2 companies, 2 individuals)  
- [ ] At least 7 items created (sales, purchase, stock, multi-purpose types)
- [ ] At least 10 accounts identified and accessible
- [ ] At least 3 journal entries created successfully

### ✅ **Phase 2 Complete When:**
- [ ] All customers/suppliers have addresses and contact details
- [ ] All items have proper account mappings
- [ ] Journal entries can be created without validation errors
- [ ] Xero sync can be initiated for master data entities

### ✅ **Ready for Advanced Testing When:**
- [ ] Master data entities sync successfully to Xero
- [ ] Journal entries create without "Both Debit and Credit values cannot be zero" errors
- [ ] Complex multi-line journal entries work correctly
- [ ] Customer/supplier references in journal entries function properly

## Risk Mitigation

### Common Issues and Solutions:

1. **"Both Debit and Credit values cannot be zero"**
   - **Solution**: Ensure total_debit equals total_credit before saving
   - **Command**: Set `je.total_debit = amount` and `je.total_credit = amount`

2. **Account not found errors**
   - **Solution**: Verify account existence before creating entries
   - **Command**: Use `frappe.db.exists('Account', account_name)` to check

3. **Customer/Supplier not linking**
   - **Solution**: Set party_type and party fields correctly
   - **Command**: Add `'party_type': 'Customer', 'party': customer_name` to account entry

4. **Xero sync failures**
   - **Solution**: Check Xero settings and account mappings
   - **Command**: Verify `xero_contact_sync_status` and `xero_item_sync_status` fields

## Next Steps After Master Data Setup

1. **Test Complex Journal Entries**: Use created accounts for advanced scenarios
2. **Test Xero Sync**: Verify all entities sync correctly to Xero
3. **Create Transaction Chains**: Use master data for invoices, payments, etc.
4. **Performance Testing**: Test bulk operations with complete dataset
5. **Error Handling**: Test recovery scenarios with various failure modes

---

*Plan created: 2025-12-08*
*Environment: ERPNext with Xero Integration*
*Objective: Enable reliable Journal Entry testing via terminal*