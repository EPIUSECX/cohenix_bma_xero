import frappe
from xero.api.xero_quotes import sync_quotation_to_xero

def sync_quotations():
    quotations = frappe.get_all('Quotation',
        filters={'company': 'EPIUSE', 'docstatus': ['in', [0, 1]]},
        fields=['name'])
    for quot in quotations:
        try:
            sync_quotation_to_xero(quot.name, 'Quotation')
            print(f'✓ Synced Quotation: {quot.name}')
        except Exception as e:
            print(f'✗ Failed Quotation {quot.name}: {str(e)}')