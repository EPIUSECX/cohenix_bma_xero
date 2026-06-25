import frappe
from xero.api.xero_contacts import sync_contact_to_xero

def sync_customers():
    customers = frappe.get_all('Customer', fields=['name'])
    for c in customers:
        try:
            sync_contact_to_xero(c.name, 'Customer')
            print(f'✓ Synced Customer: {c.name}')
        except Exception as e:
            print(f'✗ Failed Customer {c.name}: {str(e)}')

def sync_suppliers():
    suppliers = frappe.get_all('Supplier', fields=['name'])
    for s in suppliers:
        try:
            sync_contact_to_xero(s.name, 'Supplier')
            print(f'✓ Synced Supplier: {s.name}')
        except Exception as e:
            print(f'✗ Failed Supplier {s.name}: {str(e)}')