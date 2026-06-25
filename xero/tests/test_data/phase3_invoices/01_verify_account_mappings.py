import frappe

print('='*70)
print('PHASE 3.0: Account Mapping Verification for Invoices')
print('='*70)

company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
print(f'\nCompany: {company}\n')

# 1. Check Receivable Accounts (for Sales Invoice)
print('1. RECEIVABLE ACCOUNTS (for Sales Invoice debit_to)')
print('-'*70)
receivable_accounts = frappe.get_all('Account',
    filters={'is_group': 0, 'company': company, 'account_type': 'Receivable'},
    fields=['name', 'account_type', 'account_currency'])

if receivable_accounts:
    for acc in receivable_accounts:
        print(f'   ✓ {acc.name} (Currency: {acc.account_currency or "Not Set"})')
    default_receivable = receivable_accounts[0].name
    print(f'\n   → Will use: {default_receivable}')
else:
    print('   ✗ No Receivable accounts found!')
    default_receivable = None

# 2. Check Payable Accounts (for Purchase Invoice credit_to)
print('\n2. PAYABLE ACCOUNTS (for Purchase Invoice credit_to)')
print('-'*70)
payable_accounts = frappe.get_all('Account',
    filters={'is_group': 0, 'company': company, 'account_type': 'Payable'},
    fields=['name', 'account_type', 'account_currency'])

if payable_accounts:
    for acc in payable_accounts:
        print(f'   ✓ {acc.name} (Currency: {acc.account_currency or "Not Set"})')
    default_payable = payable_accounts[0].name
    print(f'\n   → Will use: {default_payable}')
else:
    print('   ✗ No Payable accounts found!')
    default_payable = None

# 3. Check Income Accounts (for Sales Invoice items)
print('\n3. INCOME ACCOUNTS (for Sales Invoice item income_account)')
print('-'*70)
income_accounts = frappe.get_all('Account',
    filters={'is_group': 0, 'company': company, 'account_type': 'Income Account'},
    fields=['name', 'account_type'],
    limit=5)

if income_accounts:
    for acc in income_accounts:
        print(f'   ✓ {acc.name}')
    default_income = income_accounts[0].name
else:
    # Fallback to company default
    default_income = frappe.get_cached_value('Company', company, 'default_income_account')
    print(f'   ℹ Using company default: {default_income}')

print(f'\n   → Will use: {default_income}')

# 4. Check Expense Accounts (for Purchase Invoice items)
print('\n4. EXPENSE ACCOUNTS (for Purchase Invoice item expense_account)')
print('-'*70)
expense_accounts = frappe.get_all('Account',
    filters={'is_group': 0, 'company': company, 'account_type': ['in', ['Expense Account', 'Cost of Goods Sold']]},
    fields=['name', 'account_type'],
    limit=5)

if expense_accounts:
    for acc in expense_accounts:
        print(f'   ✓ {acc.name} ({acc.account_type})')
    default_expense = expense_accounts[0].name
else:
    # Fallback to company default
    default_expense = frappe.get_cached_value('Company', company, 'default_expense_account')
    print(f'   ℹ Using company default: {default_expense}')

print(f'\n   → Will use: {default_expense}')

# 5. Check Cost Centers
print('\n5. COST CENTERS (may be required)')
print('-'*70)
cost_centers = frappe.get_all('Cost Center',
    filters={'is_group': 0, 'company': company},
    fields=['name', 'is_group'],
    limit=5)

if cost_centers:
    for cc in cost_centers:
        print(f'   ✓ {cc.name}')
    default_cost_center = cost_centers[0].name
    print(f'\n   → Will use: {default_cost_center}')
else:
    print('   ℹ No cost centers found - may not be required')
    default_cost_center = None

# 6. Verify Item Account Mappings
print('\n6. ITEM ACCOUNT MAPPINGS')
print('-'*70)
test_items = ['TEST-SALES-001', 'TEST-PURCHASE-001', 'TEST-SALES_FT', 'TEST-PURCHASE_FT']

for item_code in test_items:
    if frappe.db.exists('Item', item_code):
        item = frappe.get_doc('Item', item_code)
        print(f'\n   Item: {item_code}')
        print(f'     - Income Account: {item.get("income_account") or "Not Set"}')
        print(f'     - Expense Account: {item.get("expense_account") or "Not Set"}')
        print(f'     - Standard Rate: {item.get("standard_rate") or 0}')

# Summary
print('\n' + '='*70)
print('ACCOUNT MAPPING SUMMARY')
print('='*70)
print(f'✓ Receivable Account: {default_receivable or "NOT FOUND"}')
print(f'✓ Payable Account: {default_payable or "NOT FOUND"}')
print(f'✓ Income Account: {default_income or "NOT FOUND"}')
print(f'✓ Expense Account: {default_expense or "NOT FOUND"}')
print(f'✓ Cost Center: {default_cost_center or "Not Required"}')

if default_receivable and default_payable and default_income and default_expense:
    print('\n✅ ALL REQUIRED ACCOUNTS VERIFIED - READY FOR INVOICE CREATION')
else:
    print('\n⚠️ MISSING REQUIRED ACCOUNTS - MAY NEED CONFIGURATION')

print('='*70)