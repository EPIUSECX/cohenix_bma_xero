#!/usr/bin/env python3
"""Phase 1.1: Analyze existing Chart of Accounts"""

import frappe

def analyze_accounts():
    frappe.init(site='cohenix.localhost')
    frappe.connect()
    
    # Get company information
    company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
    print(f'Company: {company}')
    
    default_income = frappe.get_cached_value('Company', company, 'default_income_account')
    default_expense = frappe.get_cached_value('Company', company, 'default_expense_account')
    default_asset = frappe.get_cached_value('Company', company, 'default_bank_account')
    
    print(f'Default Income Account: {default_income}')
    print(f'Default Expense Account: {default_expense}')
    print(f'Default Bank Account: {default_asset}')
    
    # Get all accounts with types for Journal Entry testing
    print('\n=== Available Accounts (First 20) ===')
    accounts = frappe.get_all('Account', 
        fields=['name', 'account_type', 'is_group', 'company'],
        filters={'is_group': 0, 'company': company},
        limit=20)
    
    for acc in accounts:
        print(f'{acc.name} ({acc.account_type})')
    
    frappe.db.commit()
    frappe.destroy()

if __name__ == '__main__':
    analyze_accounts()