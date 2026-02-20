import frappe
from xero.api.xero_payments import sync_payment_to_xero

def sync_supplier_payments():
    supplier_payments = frappe.get_all('Payment Entry',
        filters={
            'company': 'EPIUSE',
            'party_type': 'Supplier',
            'docstatus': ['in', [0, 1]]
        },
        fields=['name'])
    for sp in supplier_payments:
        try:
            sync_payment_to_xero(sp.name, 'Payment Entry')
            print(f'✓ Synced Supplier Payment: {sp.name}')
        except Exception as e:
            print(f'✗ Failed Supplier Payment {sp.name}: {str(e)}')