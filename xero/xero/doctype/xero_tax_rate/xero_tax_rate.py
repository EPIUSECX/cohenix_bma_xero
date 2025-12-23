# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class XeroTaxRate(Document):
    def before_save(self):
        """Set last synced timestamp when saving"""
        if not self.last_synced:
            self.last_synced = now()
    
    def validate(self):
        """Validate the Xero Tax Rate data"""
        if not self.tax_type_code:
            frappe.throw("Tax Type Code is required")
        
        if not self.tax_type_name:
            frappe.throw("Tax Type Name is required")
    
    def on_update(self):
        """Update last synced timestamp on update"""
        self.db_set('last_synced', now(), update_modified=False)


@frappe.whitelist()
def get_xero_tax_rate_by_code(tax_type_code):
    """Get Xero Tax Rate by tax type code"""
    try:
        return frappe.get_doc("Xero Tax Rate", tax_type_code)
    except frappe.DoesNotExistError:
        return None


@frappe.whitelist()
def sync_xero_tax_rates():
    """Sync all tax rates from Xero to local DocType"""
    from xero.api.xero_accounts import fetch_xero_tax_rates
    
    try:
        # Fetch tax rates from Xero
        tax_rates_data = fetch_xero_tax_rates()
        
        if not tax_rates_data:
            frappe.msgprint("No tax rates found in Xero")
            return
        
        created_count = 0
        updated_count = 0
        
        for tax_rate_data in tax_rates_data:
            tax_type_code = tax_rate_data.get('tax_type')
            if not tax_type_code:
                continue
            
            # Check if tax rate already exists
            existing_tax_rate = frappe.db.exists("Xero Tax Rate", tax_type_code)
            
            # Calculate total rate from components
            components = tax_rate_data.get('components', [])
            total_rate = sum([float(comp.get('rate', 0)) for comp in components])
            
            tax_rate_doc_data = {
                'doctype': 'Xero Tax Rate',
                'tax_type_code': tax_type_code,
                'tax_type_name': tax_rate_data.get('name'),
                'tax_rate': total_rate,
                'status': tax_rate_data.get('status', 'ACTIVE'),
                'report_tax_type': tax_rate_data.get('report_tax_type'),
                'last_synced': now(),
                'sync_status': 'Synced'
            }
            
            if existing_tax_rate:
                # Update existing tax rate
                doc = frappe.get_doc("Xero Tax Rate", tax_type_code)
                doc.update(tax_rate_doc_data)
                
                # Clear existing components
                doc.tax_components = []
                
                # Add tax components
                for component in components:
                    doc.append('tax_components', {
                        'component_name': component.get('name'),
                        'rate': float(component.get('rate', 0)),
                        'is_compound': component.get('is_compound', False)
                    })
                
                doc.save(ignore_permissions=True)
                updated_count += 1
            else:
                # Create new tax rate
                doc = frappe.get_doc(tax_rate_doc_data)
                
                # Add tax components
                for component in components:
                    doc.append('tax_components', {
                        'component_name': component.get('name'),
                        'rate': float(component.get('rate', 0)),
                        'is_compound': component.get('is_compound', False)
                    })
                
                doc.insert(ignore_permissions=True)
                created_count += 1
        
        frappe.db.commit()
        
        message = f"Sync completed: {created_count} tax rates created, {updated_count} tax rates updated"
        frappe.msgprint(message)
        
        return {
            'created': created_count,
            'updated': updated_count,
            'total': created_count + updated_count
        }
        
    except Exception as e:
        frappe.log_error(f"Error syncing Xero tax rates: {str(e)}")
        frappe.throw(f"Failed to sync Xero tax rates: {str(e)}")