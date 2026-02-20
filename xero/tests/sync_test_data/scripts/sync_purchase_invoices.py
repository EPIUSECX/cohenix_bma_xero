import frappe
from xero.api.xero_invoices import sync_invoice_to_xero

def sync_purchase_invoices():
    purchase_invoices = frappe.get_all('Purchase Invoice',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name'])
    for pi in purchase_invoices:
        try:
            sync_invoice_to_xero(pi.name, 'Purchase Invoice')
            print(f'✓ Synced Purchase Invoice: {pi.name}')
        except Exception as e:
            print(f'✗ Failed Purchase Invoice {pi.name}: {str(e)}')