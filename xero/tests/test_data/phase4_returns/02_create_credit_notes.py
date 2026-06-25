import frappe
from frappe.utils import today

print('='*70)
print('PHASE 4.1: Creating Sales Returns (Credit Notes)')
print('='*70)

company = 'EPIUSE'
results = []

print('\nCREATING CREDIT NOTES')
print('-'*70)

# Credit Note 1 - Return against ACC-SINV-2025-00001
print('\n1. Creating return against ACC-SINV-2025-00001...')
original_si = frappe.get_doc('Sales Invoice', 'ACC-SINV-2025-00001')
print(f'   Original: Customer={original_si.customer}, Item={original_si.items[0].item_code}, Qty={original_si.items[0].qty}')

cn1 = frappe.new_doc('Sales Invoice')
cn1.customer = original_si.customer
cn1.is_return = 1
cn1.return_against = 'ACC-SINV-2025-00001'
cn1.posting_date = today()
cn1.debit_to = original_si.debit_to
cn1.company = company
cn1.currency = 'ZAR'
cn1.selling_price_list = 'Standard Selling'
cn1.append('items', {
    'item_code': original_si.items[0].item_code,
    'qty': -2,
    'rate': original_si.items[0].rate,
    'income_account': original_si.items[0].income_account,
    'cost_center': original_si.items[0].cost_center
})
cn1.insert()
frappe.db.commit()
results.append(cn1.name)
print(f'   ✓ Created: {cn1.name} - Return Qty: 2, Amount: {cn1.grand_total}')

# Credit Note 2 - Return against ACC-SINV-2025-00002
print('\n2. Creating return against ACC-SINV-2025-00002...')
original_si = frappe.get_doc('Sales Invoice', 'ACC-SINV-2025-00002')
print(f'   Original: Customer={original_si.customer}, Item={original_si.items[0].item_code}, Qty={original_si.items[0].qty}')

cn2 = frappe.new_doc('Sales Invoice')
cn2.customer = original_si.customer
cn2.is_return = 1
cn2.return_against = 'ACC-SINV-2025-00002'
cn2.posting_date = today()
cn2.debit_to = original_si.debit_to
cn2.company = company
cn2.currency = 'ZAR'
cn2.selling_price_list = 'Standard Selling'
cn2.append('items', {
    'item_code': original_si.items[0].item_code,
    'qty': -3,
    'rate': original_si.items[0].rate,
    'income_account': original_si.items[0].income_account,
    'cost_center': original_si.items[0].cost_center
})
cn2.insert()
frappe.db.commit()
results.append(cn2.name)
print(f'   ✓ Created: {cn2.name} - Return Qty: 3, Amount: {cn2.grand_total}')

# Credit Note 3 - Return against ACC-SINV-2025-00003
print('\n3. Creating return against ACC-SINV-2025-00003...')
original_si = frappe.get_doc('Sales Invoice', 'ACC-SINV-2025-00003')
print(f'   Original: Customer={original_si.customer}, Item={original_si.items[0].item_code}, Qty={original_si.items[0].qty}')

cn3 = frappe.new_doc('Sales Invoice')
cn3.customer = original_si.customer
cn3.is_return = 1
cn3.return_against = 'ACC-SINV-2025-00003'
cn3.posting_date = today()
cn3.debit_to = original_si.debit_to
cn3.company = company
cn3.currency = 'ZAR'
cn3.selling_price_list = 'Standard Selling'
cn3.append('items', {
    'item_code': original_si.items[0].item_code,
    'qty': -4,
    'rate': original_si.items[0].rate,
    'income_account': original_si.items[0].income_account,
    'cost_center': original_si.items[0].cost_center
})
cn3.insert()
frappe.db.commit()
results.append(cn3.name)
print(f'   ✓ Created: {cn3.name} - Return Qty: 4, Amount: {cn3.grand_total}')

# Summary
print('\n' + '='*70)
print('CREDIT NOTES SUMMARY')
print('='*70)
print(f'✓ Credit Notes Created: {len(results)}')
for cn in results:
    cn_doc = frappe.get_doc('Sales Invoice', cn)
    print(f'    - {cn} (Return against: {cn_doc.return_against}, Amount: {cn_doc.grand_total})')
print('='*70)
print('✅ SUCCESS: All Credit Notes Created!')
print('='*70)