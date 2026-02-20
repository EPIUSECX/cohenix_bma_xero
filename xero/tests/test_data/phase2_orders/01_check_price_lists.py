import frappe

print('=== Phase 2.0: Price List Discovery ===\n')

# Get company
company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
print(f'Company: {company}\n')

# Check existing price lists
print('1. Checking Price Lists...')
price_lists = frappe.get_all('Price List', 
    fields=['name', 'buying', 'selling', 'enabled', 'currency'],
    limit=20)

if price_lists:
    print(f'Found {len(price_lists)} price lists:')
    for pl in price_lists:
        pl_type = []
        if pl.buying: pl_type.append('Buying')
        if pl.selling: pl_type.append('Selling')
        type_str = '/'.join(pl_type) if pl_type else 'None'
        status = 'Enabled' if pl.enabled else 'Disabled'
        print(f'  - {pl.name}: {type_str}, {status}, Currency: {pl.currency}')
else:
    print('  No price lists found')

# Check company defaults
print('\n2. Checking Company Defaults...')
company_doc = frappe.get_doc('Company', company)
print(f'  Default Selling Price List: {company_doc.get("default_selling_price_list") or "Not Set"}')
print(f'  Default Buying Price List: {company_doc.get("default_buying_price_list") or "Not Set"}')
print(f'  Default Currency: {company_doc.get("default_currency")}')

# Check if we need to create price lists
print('\n3. Price List Requirements...')
if not price_lists:
    print('  ⚠️ No price lists found - may need to create or use ignore_pricing_rule')
else:
    selling_pl = [pl for pl in price_lists if pl.selling and pl.enabled]
    buying_pl = [pl for pl in price_lists if pl.buying and pl.enabled]
    
    if selling_pl:
        print(f'  ✓ Selling price lists available: {[pl.name for pl in selling_pl]}')
    else:
        print('  ⚠️ No enabled selling price lists')
    
    if buying_pl:
        print(f'  ✓ Buying price lists available: {[pl.name for pl in buying_pl]}')
    else:
        print('  ⚠️ No enabled buying price lists')

print('\n✓ Price List Discovery Complete')