import frappe
from xero.api.xero_sales_orders import sync_sales_order_to_xero

def sync_sales_orders():
    sales_orders = frappe.get_all('Sales Order',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name'])
    for so in sales_orders:
        try:
            sync_sales_order_to_xero(so.name, 'Sales Order')
            print(f'✓ Synced Sales Order: {so.name}')
        except Exception as e:
            print(f'✗ Failed Sales Order {so.name}: {str(e)}')