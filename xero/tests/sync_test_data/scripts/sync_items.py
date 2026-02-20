import frappe
from xero.api.xero_items import sync_item_to_xero

def sync_items():
    items = frappe.get_all('Item', fields=['item_code'])
    for item in items:
        try:
            sync_item_to_xero(item.item_code)
            print(f'✓ Synced Item: {item.item_code}')
        except Exception as e:
            print(f'✗ Failed Item {item.item_code}: {str(e)}')