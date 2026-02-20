import frappe
from xero.api.xero_invoices import sync_invoice_to_xero

def sync_sales_invoices():
    sales_invoices = frappe.get_all('Sales Invoice',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name', 'is_return'])
    for si in sales_invoices:
        try:
            sync_invoice_to_xero(si.name, 'Sales Invoice')
            doc_type = 'Credit Note' if si.is_return else 'Invoice'
            print(f'✓ Synced {doc_type}: {si.name}')
        except Exception as e:
            print(f'✗ Failed Sales Invoice {si.name}: {str(e)}')