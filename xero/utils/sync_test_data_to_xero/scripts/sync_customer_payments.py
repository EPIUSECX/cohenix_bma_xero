import frappe
from xero.api.xero_payments import sync_payment_to_xero

def sync_customer_payments():
    payments = frappe.get_all('Payment Entry',
        filters={'company': 'EPIUSE', 'party_type': 'Customer', 'docstatus': ['in', [0, 1]]},
        fields=['name'])
    for pe in payments:
        try:
            sync_payment_to_xero(pe.name)
            print(f'✓ Synced Payment: {pe.name}')
        except Exception as e:
            print(f'✗ Failed Payment {pe.name}: {str(e)}')