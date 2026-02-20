import frappe
from xero.api.xero_journals import sync_journal_to_xero

def sync_journal_entries():
    journal_entries = frappe.get_all('Journal Entry',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name'])
    for je in journal_entries:
        try:
            sync_journal_to_xero(je.name, 'Journal Entry')
            print(f'✓ Synced Journal Entry: {je.name}')
        except Exception as e:
            print(f'✗ Failed Journal Entry {je.name}: {str(e)}')