import frappe
from frappe.utils import today, add_days

print('='*70)
print('PHASE 3.2: Creating 5 Purchase Invoices')
print('='*70)

company = 'EPIUSE'
results = []

# Account mappings from Phase 3.0
credit_to = 'Employee Advances - E'
expense_account = 'Cost of Goods Sold - E'
cost_center = 'Main - E'

print(f'\nUsing Accounts:')
print(f'  Credit To: {credit_to}')
print(f'  Expense Account: {expense_account}')
print(f'  Cost Center: {cost_center}\n')

print('CREATING PURCHASE INVOICES')
print('-'*70)

# Purchase Invoice 1
pi = frappe.new_doc('Purchase Invoice')
pi.supplier = 'TEST SUPPLIER A'
pi.posting_date = today()
pi.due_date = add_days(today(), 30)
pi.credit_to = credit_to
pi.company = company
pi.currency = 'ZAR'
pi.buying_price_list = 'Standard Buying'
pi.append('items', {
    'item_code': 'TEST-PURCHASE-001',
    'qty': 15,
    'rate': 75.0,
    'expense_account': expense_account,
    'cost_center': cost_center
})
pi.insert()
frappe.db.commit()
results.append(pi.name)
print(f'✓ PI-1: {pi.name} - Supplier: TEST SUPPLIER A, Item: TEST-PURCHASE-001, Amount: {pi.grand_total}')

# Purchase Invoice 2
pi = frappe.new_doc('Purchase Invoice')
pi.supplier = 'TEST SUPPLIER B'
pi.posting_date = today()
pi.due_date = add_days(today(), 30)
pi.credit_to = credit_to
pi.company = company
pi.currency = 'ZAR'
pi.buying_price_list = 'Standard Buying'
pi.append('items', {
    'item_code': 'TEST-PURCHASE-002',
    'qty': 20,
    'rate': 75.0,
    'expense_account': expense_account,
    'cost_center': cost_center
})
pi.insert()
frappe.db.commit()
results.append(pi.name)
print(f'✓ PI-2: {pi.name} - Supplier: TEST SUPPLIER B, Item: TEST-PURCHASE-002, Amount: {pi.grand_total}')

# Purchase Invoice 3
pi = frappe.new_doc('Purchase Invoice')
pi.supplier = 'TEST SUPPLIER C'
pi.posting_date = today()
pi.due_date = add_days(today(), 30)
pi.credit_to = credit_to
pi.company = company
pi.currency = 'ZAR'
pi.buying_price_list = 'Standard Buying'
pi.append('items', {
    'item_code': 'TEST-PURCHASE_FT',
    'qty': 25,
    'rate': 75.0,
    'expense_account': expense_account,
    'cost_center': cost_center
})
pi.insert()
frappe.db.commit()
results.append(pi.name)
print(f'✓ PI-3: {pi.name} - Supplier: TEST SUPPLIER C, Item: TEST-PURCHASE_FT, Amount: {pi.grand_total}')

# Purchase Invoice 4
pi = frappe.new_doc('Purchase Invoice')
pi.supplier = 'TEST SUPPLIER D'
pi.posting_date = today()
pi.due_date = add_days(today(), 30)
pi.credit_to = credit_to
pi.company = company
pi.currency = 'ZAR'
pi.buying_price_list = 'Standard Buying'
pi.append('items', {
    'item_code': 'TEST-MULTI-001',
    'qty': 18,
    'rate': 75.0,
    'expense_account': expense_account,
    'cost_center': cost_center
})
pi.insert()
frappe.db.commit()
results.append(pi.name)
print(f'✓ PI-4: {pi.name} - Supplier: TEST SUPPLIER D, Item: TEST-MULTI-001, Amount: {pi.grand_total}')

# Purchase Invoice 5
pi = frappe.new_doc('Purchase Invoice')
pi.supplier = 'TEST SUPPLIER_FT'
pi.posting_date = today()
pi.due_date = add_days(today(), 30)
pi.credit_to = credit_to
pi.company = company
pi.currency = 'ZAR'
pi.buying_price_list = 'Standard Buying'
pi.append('items', {
    'item_code': 'TEST-PURCHASE-001',
    'qty': 30,
    'rate': 75.0,
    'expense_account': expense_account,
    'cost_center': cost_center
})
pi.insert()
frappe.db.commit()
results.append(pi.name)
print(f'✓ PI-5: {pi.name} - Supplier: TEST SUPPLIER_FT, Item: TEST-PURCHASE-001, Amount: {pi.grand_total}')

print(f'\n✓ Created {len(results)} Purchase Invoices')

print('\n' + '='*70)
print('SUMMARY')
print('='*70)
print(f'✓ Purchase Invoices Created: {len(results)}')
for pi_name in results:
    print(f'    - {pi_name}')
print('='*70)
print('✅ SUCCESS: All Purchase Invoices Created!')
print('='*70)