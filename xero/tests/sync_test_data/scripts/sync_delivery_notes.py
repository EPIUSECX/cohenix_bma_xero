import frappe
from xero.api.xero_delivery_notes import sync_delivery_note_to_xero_invoice

def sync_delivery_notes():
    delivery_notes = frappe.get_all('Delivery Note',
        filters={'company': 'EPIUSE', 'docstatus': ['in', [0, 1]]},
        fields=['name'])
    for dn in delivery_notes:
        try:
            sync_delivery_note_to_xero_invoice(dn.name, 'Delivery Note')
            print(f'✓ Synced Delivery Note: {dn.name}')
        except Exception as e:
            print(f'✗ Failed Delivery Note {dn.name}: {str(e)}')