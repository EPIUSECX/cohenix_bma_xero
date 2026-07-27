# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from xero.utils.xero_client import require_xero_manager
from frappe.model.document import Document
from frappe.utils import now


class XeroAccount(Document):
    def before_save(self):
        """Set last synced timestamp when saving"""
        if not self.last_synced:
            self.last_synced = now()
    
    def validate(self):
        """Validate the Xero Account data"""
        if not self.account_code:
            frappe.throw("Account Code is required")
        
        if not self.account_name:
            frappe.throw("Account Name is required")
        
        if not self.account_id:
            frappe.throw("Xero Account ID is required")
    
    def on_update(self):
        """Update last synced timestamp on update"""
        self.db_set('last_synced', now(), update_modified=False)


@frappe.whitelist()
def get_xero_account_by_code(account_code):
    """Get Xero Account by account code"""
    require_xero_manager()
    try:
        return frappe.get_doc("Xero Account", account_code)
    except frappe.DoesNotExistError:
        return None


@frappe.whitelist()
def sync_xero_accounts():
    """Sync all accounts from Xero to local DocType"""
    require_xero_manager()
    from xero.api.xero_accounts import fetch_xero_accounts
    
    try:
        # Fetch accounts from Xero
        accounts_data = fetch_xero_accounts()
        
        if not accounts_data:
            frappe.msgprint("No accounts found in Xero")
            return
        
        created_count = 0
        updated_count = 0
        
        for account_data in accounts_data:
            account_code = account_data.get('code')
            if not account_code:
                continue
            
            # Check if account already exists
            existing_account = frappe.db.exists("Xero Account", account_code)
            
            account_doc_data = {
                'doctype': 'Xero Account',
                'account_code': account_code,
                'account_name': account_data.get('name'),
                'account_id': account_data.get('account_id'),
                'account_type': account_data.get('type'),
                'status': account_data.get('status', 'ACTIVE'),
                'currency_code': account_data.get('currency_code'),
                'enable_payments': account_data.get('enable_payments', False),
                'tax_type': account_data.get('tax_type'),
                'last_synced': now(),
                'sync_status': 'Synced'
            }
            
            if existing_account:
                # Update existing account
                doc = frappe.get_doc("Xero Account", account_code)
                doc.update(account_doc_data)
                doc.save(ignore_permissions=True)
                updated_count += 1
            else:
                # Create new account
                doc = frappe.get_doc(account_doc_data)
                doc.insert(ignore_permissions=True)
                created_count += 1

        message = f"Sync completed: {created_count} accounts created, {updated_count} accounts updated"
        frappe.msgprint(message)
        
        return {
            'created': created_count,
            'updated': updated_count,
            'total': created_count + updated_count
        }
        
    except Exception as e:
        frappe.log_error(f"Error syncing Xero accounts: {str(e)}")
        frappe.throw(f"Failed to sync Xero accounts: {str(e)}")