import frappe
from frappe.utils import today, add_days

print('='*70)
print('PHASE 3.1: Creating 5 Sales Invoices')
print('='*70)

company = 'EPIUSE'
results = []

# Account mappings from Phase 3.0
debit_to = 'Debtors - E'
income_account = '200 - 200 - Sales - E'
cost_center = 'Main - E'

print(f'\nUsing Accounts:')
print(f'  Debit To: {debit_to}')
print(f'  Income Account: {income_account}')
print(f'  Cost Center: {cost_center}\n')

print('CREATING SALES INVOICES')
print('-'*70)

# Sales Invoice 1
si = frappe.new_doc('Sales Invoice')
si.customer = 'TEST CUSTOMER A'
si.posting_date = today()
si.due_date = add_days(today(), 30)
si.debit_to = debit_to
si.company = company
si.currency = 'ZAR'
si.selling_price_list = 'Standard Selling'
si.append('items', {
    'item_code': 'TEST-SALES-001',
    'qty': 5,
    'rate': 100.0,
    'income_account': income_account,
    'cost_center': cost_center
})
si.insert()
frappe.db.commit()
results.append(si.name)
print(f'✓ SI-1: {si.name} - Customer: TEST CUSTOMER A, Item: TEST-SALES-001, Amount: {si.grand_total}')

# Sales Invoice 2
si = frappe.new_doc('Sales Invoice')
si.customer = 'TEST CUSTOMER B'
si.posting_date = today()
si.due_date = add_days(today(), 30)
si.debit_to = debit_to
si.company = company
si.currency = 'ZAR'
si.selling_price_list = 'Standard Selling'
si.append('items', {
    'item_code': 'TEST-SALES-002',
    'qty': 7,
    'rate': 100.0,
    'income_account': income_account,
    'cost_center': cost_center
})
si.insert()
frappe.db.commit()
results.append(si.name)
print(f'✓ SI-2: {si.name} - Customer: TEST CUSTOMER B, Item: TEST-SALES-002, Amount: {si.grand_total}')

# Sales Invoice 3
si = frappe.new_doc('Sales Invoice')
si.customer = 'TEST CUSTOMER C'
si.posting_date = today()
si.due_date = add_days(today(), 30)
si.debit_to = debit_to
si.company = company
si.currency = 'ZAR'
si.selling_price_list = 'Standard Selling'
si.append('items', {
    'item_code': 'TEST-SALES_FT',
    'qty': 10,
    'rate': 100.0,
    'income_account': income_account,
    'cost_center': cost_center
})
si.insert()
frappe.db.commit()
results.append(si.name)
print(f'✓ SI-3: {si.name} - Customer: TEST CUSTOMER C, Item: TEST-SALES_FT, Amount: {si.grand_total}')

# Sales Invoice 4
si = frappe.new_doc('Sales Invoice')
si.customer = 'TEST CUSTOMER D'
si.posting_date = today()
si.due_date = add_days(today(), 30)
si.debit_to = debit_to
si.company = company
si.currency = 'ZAR'
si.selling_price_list = 'Standard Selling'
si.append('items', {
    'item_code': 'TEST-MULTI-001',
    'qty': 8,
    'rate': 100.0,
    'income_account': income_account,
    'cost_center': cost_center
})
si.insert()
frappe.db.commit()
results.append(si.name)
print(f'✓ SI-4: {si.name} - Customer: TEST CUSTOMER D, Item: TEST-MULTI-001, Amount: {si.grand_total}')

# Sales Invoice 5
si = frappe.new_doc('Sales Invoice')
si.customer = 'TEST CUSTOMER_FT'
si.posting_date = today()
si.due_date = add_days(today(), 30)
si.debit_to = debit_to
si.company = company
si.currency = 'ZAR'
si.selling_price_list = 'Standard Selling'
si.append('items', {
    'item_code': 'TEST-SALES-001',
    'qty': 12,
    'rate': 100.0,
    'income_account': income_account,
    'cost_center': cost_center
})
si.insert()
frappe.db.commit()
results.append(si.name)
print(f'✓ SI-5: {si.name} - Customer: TEST CUSTOMER_FT, Item: TEST-SALES-001, Amount: {si.grand_total}')

print(f'\n✓ Created {len(results)} Sales Invoices')

print('\n' + '='*70)
print('SUMMARY')
print('='*70)
print(f'✓ Sales Invoices Created: {len(results)}')
for si_name in results:
    print(f'    - {si_name}')
print('='*70)
print('✅ SUCCESS: All Sales Invoices Created!')
print('='*70)