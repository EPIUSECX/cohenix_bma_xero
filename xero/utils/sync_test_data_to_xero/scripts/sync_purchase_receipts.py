import frappe
from xero.api.xero_purchase_receipts import sync_purchase_receipt_to_xero_bill

def sync_purchase_receipts():
    purchase_receipts = frappe.get_all('Purchase Receipt',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name'])
    for pr in purchase_receipts:
        try:
            sync_purchase_receipt_to_xero_bill(pr.name, 'Purchase Receipt')
            print(f'✓ Synced Purchase Receipt: {pr.name}')
        except Exception as e:
            print(f'✗ Failed Purchase Receipt {pr.name}: {str(e)}')