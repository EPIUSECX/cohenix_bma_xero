#!/usr/bin/env python3
"""Phase 1.2: Identify key accounts for Journal Entry testing"""

import frappe

def identify_key_accounts():
    frappe.init(site='cohenix.localhost')
    frappe.connect()
    
    company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
    print(f'Company: {company}\n')
    
    # Target account types for Journal Entry testing
    required_accounts = [
        'Cash', 'Bank', 'Accounts Receivable', 'Accounts Payable',
        'Sales', 'Sales Revenue', 'Office Expenses', 'Cost of Sales'
    ]
    
    print('=== Searching for Required Account Types ===')
    missing_accounts = []
    found_accounts = {}
    
    for acc_name in required_accounts:
        exists = frappe.db.exists('Account', {'name': ['like', f'%{acc_name}%'], 'company': company})
        if not exists:
            missing_accounts.append(acc_name)
            print(f'✗ Missing: {acc_name}')
        else:
            found_accounts[acc_name] = exists
            print(f'✓ Found: {exists}')
    
    if missing_accounts:
        print(f'\nMissing accounts: {missing_accounts}')
    else:
        print('\n✓ All required accounts found!')
    
    # Get accounts by type for Journal Entry patterns
    print('\n=== Accounts by Type ===')
    account_types = ['Receivable', 'Payable', 'Cash', 'Bank', 'Income', 'Expense', 'Fixed Asset']
    
    for acc_type in account_types:
        accounts = frappe.get_all('Account',
            fields=['name', 'account_type'],
            filters={'is_group': 0, 'company': company, 'account_type': acc_type},
            limit=3)
        
        if accounts:
            print(f'\n{acc_type} Accounts:')
            for acc in accounts:
                print(f'  - {acc.name}')
    
    frappe.db.commit()
    frappe.destroy()

if __name__ == '__main__':
    identify_key_accounts()