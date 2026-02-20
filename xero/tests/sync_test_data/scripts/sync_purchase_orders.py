import frappe
from xero.api.xero_purchase_orders import sync_purchase_order_to_xero

def sync_purchase_orders():
    purchase_orders = frappe.get_all('Purchase Order',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name'])
    for po in purchase_orders:
        try:
            sync_purchase_order_to_xero(po.name, 'Purchase Order')
            print(f'✓ Synced Purchase Order: {po.name}')
        except Exception as e:
            print(f'✗ Failed Purchase Order {po.name}: {str(e)}')