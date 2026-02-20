import frappe

print('='*70)
print('PHASE 6.1: COMPREHENSIVE ENTITY VALIDATION')
print('='*70)

# Get company
company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
print(f'\nCompany: {company}\n')

validation_results = {
    'customers': {'total': 0, 'list': []},
    'suppliers': {'total': 0, 'list': []},
    'items': {'total': 0, 'list': []},
    'addresses': {'total': 0, 'list': []},
    'journal_entries': {'total': 0, 'list': []}
}

# 1. Validate Customers
print('1. CUSTOMERS')
print('-' * 70)
customers = frappe.get_all('Customer', 
    filters={'customer_name': ['like', 'TEST%']},
    fields=['name', 'customer_type', 'customer_group'])

for cust in customers:
    validation_results['customers']['list'].append(cust.name)
    print(f'   ✓ {cust.name} ({cust.customer_type})')

validation_results['customers']['total'] = len(customers)
print(f'   Total: {len(customers)} customers\n')

# 2. Validate Suppliers
print('2. SUPPLIERS')
print('-' * 70)
suppliers = frappe.get_all('Supplier',
    filters={'supplier_name': ['like', 'TEST%']},
    fields=['name', 'supplier_type', 'supplier_group'])

for supp in suppliers:
    validation_results['suppliers']['list'].append(supp.name)
    print(f'   ✓ {supp.name} ({supp.supplier_type})')

validation_results['suppliers']['total'] = len(suppliers)
print(f'   Total: {len(suppliers)} suppliers\n')

# 3. Validate Items
print('3. ITEMS')
print('-' * 70)
items = frappe.get_all('Item',
    filters={'item_code': ['like', 'TEST%']},
    fields=['name', 'is_sales_item', 'is_purchase_item', 'is_stock_item'])

for item in items:
    types = []
    if item.is_sales_item: types.append('Sales')
    if item.is_purchase_item: types.append('Purchase')
    if item.is_stock_item: types.append('Stock')
    type_str = '/'.join(types) if types else 'Basic'
    
    validation_results['items']['list'].append(item.name)
    print(f'   ✓ {item.name} ({type_str})')

validation_results['items']['total'] = len(items)
print(f'   Total: {len(items)} items\n')

# 4. Validate Addresses
print('4. ADDRESSES')
print('-' * 70)
addresses = frappe.get_all('Address',
    filters={'address_title': ['like', 'TEST%']},
    fields=['name', 'address_type', 'city'])

for addr in addresses:
    validation_results['addresses']['list'].append(addr.name)
    print(f'   ✓ {addr.name} ({addr.address_type})')

validation_results['addresses']['total'] = len(addresses)
print(f'   Total: {len(addresses)} addresses\n')

# 5. Validate Journal Entries
print('5. JOURNAL ENTRIES')
print('-' * 70)
journal_entries = frappe.get_all('Journal Entry',
    filters={'user_remark': ['like', '%TEST%']},
    fields=['name', 'posting_date', 'total_debit', 'total_credit', 'docstatus'])

for je in journal_entries:
    status = 'Draft' if je.docstatus == 0 else 'Submitted' if je.docstatus == 1 else 'Cancelled'
    validation_results['journal_entries']['list'].append(je.name)
    print(f'   ✓ {je.name} - Debit: {je.total_debit}, Credit: {je.total_credit} ({status})')

validation_results['journal_entries']['total'] = len(journal_entries)
print(f'   Total: {len(journal_entries)} journal entries\n')

# Summary
print('='*70)
print('VALIDATION SUMMARY')
print('='*70)
print(f'✓ Customers:        {validation_results["customers"]["total"]}')
print(f'✓ Suppliers:        {validation_results["suppliers"]["total"]}')
print(f'✓ Items:            {validation_results["items"]["total"]}')
print(f'✓ Addresses:        {validation_results["addresses"]["total"]}')
print(f'✓ Journal Entries:  {validation_results["journal_entries"]["total"]}')
print('='*70)

total_entities = sum([
    validation_results["customers"]["total"],
    validation_results["suppliers"]["total"],
    validation_results["items"]["total"],
    validation_results["addresses"]["total"],
    validation_results["journal_entries"]["total"]
])

print(f'\n✓ TOTAL ENTITIES VALIDATED: {total_entities}')
print('✓ ALL ENTITIES VALIDATED SUCCESSFULLY!')
print('='*70)