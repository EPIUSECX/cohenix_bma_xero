import frappe
from xero.api.xero_bank_transactions import sync_bank_transaction_to_xero

def sync_bank_transactions():
    bank_transactions = frappe.get_all('Bank Transaction',
        filters={'company': 'EPIUSE', 'docstatus': ['in', [0, 1]]},
        fields=['name'])
    for bt in bank_transactions:
        try:
            sync_bank_transaction_to_xero(bt.name, 'Bank Transaction')
            print(f'✓ Synced Bank Transaction: {bt.name}')
        except Exception as e:
            print(f'✗ Failed Bank Transaction {bt.name}: {str(e)}')