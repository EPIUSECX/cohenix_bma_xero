import frappe
from frappe.utils import today

print('='*70)
print('PHASE 4.2: Creating Purchase Returns (Debit Notes)')
print('='*70)

company = 'EPIUSE'
results = []

print('\nCREATING DEBIT NOTES')
print('-'*70)

# Debit Note 1 - Return against ACC-PINV-2025-00001
print('\n1. Creating return against ACC-PINV-2025-00001...')
original_pi = frappe.get_doc('Purchase Invoice', 'ACC-PINV-2025-00001')
print(f'   Original: Supplier={original_pi.supplier}, Item={original_pi.items[0].item_code}, Qty={original_pi.items[0].qty}')

dn1 = frappe.new_doc('Purchase Invoice')
dn1.supplier = original_pi.supplier
dn1.is_return = 1
dn1.return_against = 'ACC-PINV-2025-00001'
dn1.posting_date = today()
dn1.credit_to = original_pi.credit_to
dn1.company = company
dn1.currency = 'ZAR'
dn1.buying_price_list = 'Standard Buying'
dn1.append('items', {
    'item_code': original_pi.items[0].item_code,
    'qty': -5,
    'rate': original_pi.items[0].rate,
    'expense_account': original_pi.items[0].expense_account,
    'cost_center': original_pi.items[0].cost_center
})
dn1.insert()
frappe.db.commit()
results.append(dn1.name)
print(f'   ✓ Created: {dn1.name} - Return Qty: 5, Amount: {dn1.grand_total}')

# Debit Note 2 - Return against ACC-PINV-2025-00002
print('\n2. Creating return against ACC-PINV-2025-00002...')
original_pi = frappe.get_doc('Purchase Invoice', 'ACC-PINV-2025-00002')
print(f'   Original: Supplier={original_pi.supplier}, Item={original_pi.items[0].item_code}, Qty={original_pi.items[0].qty}')

dn2 = frappe.new_doc('Purchase Invoice')
dn2.supplier = original_pi.supplier
dn2.is_return = 1
dn2.return_against = 'ACC-PINV-2025-00002'
dn2.posting_date = today()
dn2.credit_to = original_pi.credit_to
dn2.company = company
dn2.currency = 'ZAR'
dn2.buying_price_list = 'Standard Buying'
dn2.append('items', {
    'item_code': original_pi.items[0].item_code,
    'qty': -8,
    'rate': original_pi.items[0].rate,
    'expense_account': original_pi.items[0].expense_account,
    'cost_center': original_pi.items[0].cost_center
})
dn2.insert()
frappe.db.commit()
results.append(dn2.name)
print(f'   ✓ Created: {dn2.name} - Return Qty: 8, Amount: {dn2.grand_total}')

# Debit Note 3 - Return against ACC-PINV-2025-00003
print('\n3. Creating return against ACC-PINV-2025-00003...')
original_pi = frappe.get_doc('Purchase Invoice', 'ACC-PINV-2025-00003')
print(f'   Original: Supplier={original_pi.supplier}, Item={original_pi.items[0].item_code}, Qty={original_pi.items[0].qty}')

dn3 = frappe.new_doc('Purchase Invoice')
dn3.supplier = original_pi.supplier
dn3.is_return = 1
dn3.return_against = 'ACC-PINV-2025-00003'
dn3.posting_date = today()
dn3.credit_to = original_pi.credit_to
dn3.company = company
dn3.currency = 'ZAR'
dn3.buying_price_list = 'Standard Buying'
dn3.append('items', {
    'item_code': original_pi.items[0].item_code,
    'qty': -10,
    'rate': original_pi.items[0].rate,
    'expense_account': original_pi.items[0].expense_account,
    'cost_center': original_pi.items[0].cost_center
})
dn3.insert()
frappe.db.commit()
results.append(dn3.name)
print(f'   ✓ Created: {dn3.name} - Return Qty: 10, Amount: {dn3.grand_total}')

# Summary
print('\n' + '='*70)
print('DEBIT NOTES SUMMARY')
print('='*70)
print(f'✓ Debit Notes Created: {len(results)}')
for dn in results:
    dn_doc = frappe.get_doc('Purchase Invoice', dn)
    print(f'    - {dn} (Return against: {dn_doc.return_against}, Amount: {dn_doc.grand_total})')
print('='*70)
print('✅ SUCCESS: All Debit Notes Created!')
print('='*70)