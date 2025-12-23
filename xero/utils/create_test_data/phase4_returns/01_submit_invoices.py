import frappe

print('='*70)
print('PHASE 4.0: Submitting Invoices for Return Testing')
print('='*70)

results = {
    'sales_invoices_submitted': [],
    'purchase_invoices_submitted': [],
    'errors': []
}

print('\nSUBMITTING SALES INVOICES')
print('-'*70)

# Submit 3 Sales Invoices
sales_invoices_to_submit = [
    'ACC-SINV-2025-00001',
    'ACC-SINV-2025-00002',
    'ACC-SINV-2025-00003'
]

for si_name in sales_invoices_to_submit:
    if frappe.db.exists('Sales Invoice', si_name):
        try:
            si = frappe.get_doc('Sales Invoice', si_name)
            if si.docstatus == 0:
                si.submit()
                frappe.db.commit()
                results['sales_invoices_submitted'].append(si_name)
                print(f'  ✓ Submitted: {si_name} (docstatus: {si.docstatus})')
            else:
                print(f'  ℹ Already submitted: {si_name} (docstatus: {si.docstatus})')
                results['sales_invoices_submitted'].append(si_name)
        except Exception as e:
            error_msg = str(e)[:100]
            results['errors'].append(f'{si_name}: {error_msg}')
            print(f'  ✗ Failed to submit {si_name}: {error_msg}')
    else:
        print(f'  ✗ Not found: {si_name}')

print(f'\n✓ Sales Invoices Submitted: {len(results["sales_invoices_submitted"])}')

print('\nSUBMITTING PURCHASE INVOICES')
print('-'*70)

# Submit 3 Purchase Invoices
purchase_invoices_to_submit = [
    'ACC-PINV-2025-00001',
    'ACC-PINV-2025-00002',
    'ACC-PINV-2025-00003'
]

for pi_name in purchase_invoices_to_submit:
    if frappe.db.exists('Purchase Invoice', pi_name):
        try:
            pi = frappe.get_doc('Purchase Invoice', pi_name)
            if pi.docstatus == 0:
                pi.submit()
                frappe.db.commit()
                results['purchase_invoices_submitted'].append(pi_name)
                print(f'  ✓ Submitted: {pi_name} (docstatus: {pi.docstatus})')
            else:
                print(f'  ℹ Already submitted: {pi_name} (docstatus: {pi.docstatus})')
                results['purchase_invoices_submitted'].append(pi_name)
        except Exception as e:
            error_msg = str(e)[:100]
            results['errors'].append(f'{pi_name}: {error_msg}')
            print(f'  ✗ Failed to submit {pi_name}: {error_msg}')
    else:
        print(f'  ✗ Not found: {pi_name}')

print(f'\n✓ Purchase Invoices Submitted: {len(results["purchase_invoices_submitted"])}')

# Summary
print('\n' + '='*70)
print('SUBMISSION SUMMARY')
print('='*70)
print(f'✓ Sales Invoices Submitted: {len(results["sales_invoices_submitted"])}')
for si in results['sales_invoices_submitted']:
    print(f'    - {si}')

print(f'\n✓ Purchase Invoices Submitted: {len(results["purchase_invoices_submitted"])}')
for pi in results['purchase_invoices_submitted']:
    print(f'    - {pi}')

if results['errors']:
    print(f'\n⚠️ Errors Encountered: {len(results["errors"])}')
    for err in results['errors']:
        print(f'    - {err}')
else:
    print('\n✅ NO ERRORS - All submissions successful!')

print(f'\n✓ TOTAL SUBMITTED: {len(results["sales_invoices_submitted"]) + len(results["purchase_invoices_submitted"])}')
print('='*70)