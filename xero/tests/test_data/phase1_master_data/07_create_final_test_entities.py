import frappe

print('=== Creating Final Test Entities with _FT Suffix ===\n')

# Get company and account info
company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
income_account = frappe.get_cached_value('Company', company, 'default_income_account')
expense_account = frappe.get_cached_value('Company', company, 'default_expense_account')

results = {
    'customers': [],
    'suppliers': [],
    'items': [],
    'addresses': []
}

# 1. Create Customer
print('1. Creating Customer...')
if frappe.db.exists('Customer', 'TEST CUSTOMER_FT'):
    frappe.delete_doc('Customer', 'TEST CUSTOMER_FT', force=True)
    frappe.db.commit()
c = frappe.new_doc('Customer')
c.customer_name = 'TEST CUSTOMER_FT'
c.customer_type = 'Company'
c.territory = frappe.get_cached_value('Territory', {'name': ('!=', '')}, 'name')
c.customer_group = frappe.get_cached_value('Customer Group', {'name': ('!=', '')}, 'name')
c.company = company
c.insert()
frappe.db.commit()
results['customers'].append(c.name)
print(f'   ✓ Created Customer: {c.name}')

# 2. Add Address to Customer
print('2. Creating Customer Address...')
address_name = 'TEST CUSTOMER_FT - Billing'
if not frappe.db.exists('Address', address_name):
    addr = frappe.new_doc('Address')
    addr.address_title = address_name
    addr.address_type = 'Billing'
    addr.address_line1 = '123 Final Test Street'
    addr.city = 'Test City'
    addr.state = 'Test State'
    addr.pincode = '12345'
    addr.country = 'United States'
    addr.append('links', {
        'link_doctype': 'Customer',
        'link_name': 'TEST CUSTOMER_FT'
    })
    addr.insert()
    frappe.db.commit()
    results['addresses'].append(addr.name)
    print(f'   ✓ Created Address: {addr.name}')
else:
    print(f'   ℹ Address already exists')

# 3. Create Supplier
print('3. Creating Supplier...')
if frappe.db.exists('Supplier', 'TEST SUPPLIER_FT'):
    frappe.delete_doc('Supplier', 'TEST SUPPLIER_FT', force=True)
    frappe.db.commit()
s = frappe.new_doc('Supplier')
s.supplier_name = 'TEST SUPPLIER_FT'
s.supplier_type = 'Company'
s.supplier_group = frappe.get_cached_value('Supplier Group', {'name': ('!=', '')}, 'name')
s.company = company
s.insert()
frappe.db.commit()
results['suppliers'].append(s.name)
print(f'   ✓ Created Supplier: {s.name}')

# 4. Create Sales Item
print('4. Creating Sales Item...')
if frappe.db.exists('Item', 'TEST-SALES_FT'):
    frappe.delete_doc('Item', 'TEST-SALES_FT', force=True)
    frappe.db.commit()
item = frappe.new_doc('Item')
item.item_code = 'TEST-SALES_FT'
item.item_name = 'TEST-SALES_FT'
item.item_group = 'All Item Groups'
item.stock_uom = 'Nos'
item.is_sales_item = 1
item.income_account = income_account
item.standard_rate = 100.0
item.insert()
frappe.db.commit()
results['items'].append(item.name)
print(f'   ✓ Created Sales Item: {item.name}')

# 5. Create Purchase Item
print('5. Creating Purchase Item...')
if frappe.db.exists('Item', 'TEST-PURCHASE_FT'):
    frappe.delete_doc('Item', 'TEST-PURCHASE_FT', force=True)
    frappe.db.commit()
item = frappe.new_doc('Item')
item.item_code = 'TEST-PURCHASE_FT'
item.item_name = 'TEST-PURCHASE_FT'
item.item_group = 'All Item Groups'
item.stock_uom = 'Nos'
item.is_purchase_item = 1
item.expense_account = expense_account
item.standard_rate = 75.0
item.insert()
frappe.db.commit()
results['items'].append(item.name)
print(f'   ✓ Created Purchase Item: {item.name}')

# 6. Create Stock Item
print('6. Creating Stock Item...')
if frappe.db.exists('Item', 'TEST-STOCK_FT'):
    frappe.delete_doc('Item', 'TEST-STOCK_FT', force=True)
    frappe.db.commit()
item = frappe.new_doc('Item')
item.item_code = 'TEST-STOCK_FT'
item.item_name = 'TEST-STOCK_FT'
item.item_group = 'All Item Groups'
item.stock_uom = 'Nos'
item.is_stock_item = 1
item.insert()
frappe.db.commit()
results['items'].append(item.name)
print(f'   ✓ Created Stock Item: {item.name}')

# Summary
print('\n' + '='*60)
print('FINAL TEST ENTITIES CREATION SUMMARY')
print('='*60)
print(f'✓ Customers Created: {len(results["customers"])} - {results["customers"]}')
print(f'✓ Addresses Created: {len(results["addresses"])} - {results["addresses"]}')
print(f'✓ Suppliers Created: {len(results["suppliers"])} - {results["suppliers"]}')
print(f'✓ Items Created: {len(results["items"])} - {results["items"]}')
print('='*60)
print('✓ ALL FINAL TEST ENTITIES CREATED SUCCESSFULLY!')
print('='*60)