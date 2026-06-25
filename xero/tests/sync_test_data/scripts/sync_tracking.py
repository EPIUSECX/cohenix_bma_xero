import frappe
from xero.api.xero_tracking_categories import sync_cost_center_to_xero
from xero.api.xero_projects import sync_project_to_xero

def sync_cost_centers():
    cost_centers = frappe.get_all('Cost Center',
        filters={'company': 'EPIUSE', 'is_group': 0},
        fields=['name'])
    for cc in cost_centers:
        try:
            sync_cost_center_to_xero(cc.name)
            print(f'✓ Synced Cost Center: {cc.name}')
        except Exception as e:
            print(f'✗ Failed Cost Center {cc.name}: {str(e)}')

def sync_projects():
    projects = frappe.get_all('Project',
        filters={'company': 'EPIUSE'},
        fields=['name'])
    for proj in projects:
        try:
            sync_project_to_xero(proj.name)
            print(f'✓ Synced Project: {proj.name}')
        except Exception as e:
            print(f'✗ Failed Project {proj.name}: {str(e)}')