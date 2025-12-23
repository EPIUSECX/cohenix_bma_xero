import frappe
from frappe.utils import today

print('=== Phase 5.1: Creating Basic Journal Entry (v2) ===\n')

# Get company and accounts
company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
print(f'Company: {company}')

# Get accounts that are NOT Receivable or Payable
accounts = frappe.get_all('Account', 
    filters={
        'is_group': 0, 
        'company': company,
        'account_type': ['not in', ['Receivable', 'Payable']]
    },
    fields=['name', 'account_type'],
    limit=10)

if len(accounts) < 2:
    print('ERROR: Not enough accounts found for testing')
else:
    # Use Cash and an expense/income account
    debit_account = None
    credit_account = None
    
    for acc in accounts:
        if 'Cash' in acc.name and not debit_account:
            debit_account = acc.name
        elif ('Expense' in acc.name or 'Cost' in acc.name) and not credit_account:
            credit_account = acc.name
    
    # Fallback to first two non-receivable/payable accounts
    if not debit_account:
        debit_account = accounts[0].name
    if not credit_account:
        credit_account = accounts[1].name if len(accounts) > 1 else accounts[0].name
    
    print(f'Debit Account: {debit_account}')
    print(f'Credit Account: {credit_account}')
    
    # Delete existing test journal entries
    existing_jes = frappe.get_all('Journal Entry', 
        filters={'user_remark': ['like', '%TEST-BASIC%']},
        limit=10)
    
    for je in existing_jes:
        try:
            frappe.delete_doc('Journal Entry', je.name, force=True)
            frappe.db.commit()
            print(f'Deleted existing JE: {je.name}')
        except:
            pass
    
    # Create basic journal entry
    print('\nCreating Journal Entry...')
    je = frappe.new_doc('Journal Entry')
    je.voucher_type = 'Journal Entry'
    je.naming_series = 'JE-'
    je.company = company
    je.posting_date = today()
    je.user_remark = 'TEST-BASIC-002: Simple transaction between Cash and Expense accounts'
    
    # Add debit entry
    je.append('accounts', {
        'account': debit_account,
        'debit_in_account_currency': 500.00,
        'credit_in_account_currency': 0.00
    })
    
    # Add credit entry
    je.append('accounts', {
        'account': credit_account,
        'debit_in_account_currency': 0.00,
        'credit_in_account_currency': 500.00
    })
    
    # Save
    je.insert()
    frappe.db.commit()
    
    print(f'\n✓ Created Journal Entry: {je.name}')
    print(f'  Posting Date: {je.posting_date}')
    print(f'  Total Debit: {je.total_debit}')
    print(f'  Total Credit: {je.total_credit}')
    print(f'  Status: Draft (docstatus={je.docstatus})')
    print(f'  Accounts:')
    for acc in je.accounts:
        print(f'    - {acc.account}: Debit={acc.debit_in_account_currency}, Credit={acc.credit_in_account_currency}')
    
    print('\n✓ SUCCESS: Basic Journal Entry created successfully!')
    print(f'Journal Entry Name: {je.name}')