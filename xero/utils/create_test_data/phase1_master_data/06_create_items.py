import frappe

print('=== Creating Test Items ===')

company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
income_account = frappe.get_cached_value('Company', company, 'default_income_account')
expense_account = frappe.get_cached_value('Company', company, 'default_expense_account')

items_created = []

# Sales Item 1
if frappe.db.exists('Item', 'TEST-SALES-001'):
    frappe.delete_doc('Item', 'TEST-SALES-001', force=True)
    frappe.db.commit()
item = frappe.new_doc('Item')
item.item_code = 'TEST-SALES-001'
item.item_name = 'TEST-SALES-001'
item.item_group = 'All Item Groups'
item.stock_uom = 'Nos'
item.is_sales_item = 1
item.income_account = income_account
item.standard_rate = 100.0
item.insert()
frappe.db.commit()
items_created.append(item.name)
print(f'✓ Created Sales item: {item.name}')

# Sales Item 2
if frappe.db.exists('Item', 'TEST-SALES-002'):
    frappe.delete_doc('Item', 'TEST-SALES-002', force=True)
    frappe.db.commit()
item = frappe.new_doc('Item')
item.item_code = 'TEST-SALES-002'
item.item_name = 'TEST-SALES-002'
item.item_group = 'All Item Groups'
item.stock_uom = 'Nos'
item.is_sales_item = 1
item.income_account = income_account
item.standard_rate = 100.0
item.insert()
frappe.db.commit()
items_created.append(item.name)
print(f'✓ Created Sales item: {item.name}')

# Purchase Item 1
if frappe.db.exists('Item', 'TEST-PURCHASE-001'):
    frappe.delete_doc('Item', 'TEST-PURCHASE-001', force=True)
    frappe.db.commit()
item = frappe.new_doc('Item')
item.item_code = 'TEST-PURCHASE-001'
item.item_name = 'TEST-PURCHASE-001'
item.item_group = 'All Item Groups'
item.stock_uom = 'Nos'
item.is_purchase_item = 1
item.expense_account = expense_account
item.standard_rate = 75.0
item.insert()
frappe.db.commit()
items_created.append(item.name)
print(f'✓ Created Purchase item: {item.name}')

# Purchase Item 2
if frappe.db.exists('Item', 'TEST-PURCHASE-002'):
    frappe.delete_doc('Item', 'TEST-PURCHASE-002', force=True)
    frappe.db.commit()
item = frappe.new_doc('Item')
item.item_code = 'TEST-PURCHASE-002'
item.item_name = 'TEST-PURCHASE-002'
item.item_group = 'All Item Groups'
item.stock_uom = 'Nos'
item.is_purchase_item = 1
item.expense_account = expense_account
item.standard_rate = 75.0
item.insert()
frappe.db.commit()
items_created.append(item.name)
print(f'✓ Created Purchase item: {item.name}')

# Stock Item 1
if frappe.db.exists('Item', 'TEST-STOCK-001'):
    frappe.delete_doc('Item', 'TEST-STOCK-001', force=True)
    frappe.db.commit()
item = frappe.new_doc('Item')
item.item_code = 'TEST-STOCK-001'
item.item_name = 'TEST-STOCK-001'
item.item_group = 'All Item Groups'
item.stock_uom = 'Nos'
item.is_stock_item = 1
item.insert()
frappe.db.commit()
items_created.append(item.name)
print(f'✓ Created Stock item: {item.name}')

# Stock Item 2
if frappe.db.exists('Item', 'TEST-STOCK-002'):
    frappe.delete_doc('Item', 'TEST-STOCK-002', force=True)
    frappe.db.commit()
item = frappe.new_doc('Item')
item.item_code = 'TEST-STOCK-002'
item.item_name = 'TEST-STOCK-002'
item.item_group = 'All Item Groups'
item.stock_uom = 'Nos'
item.is_stock_item = 1
item.insert()
frappe.db.commit()
items_created.append(item.name)
print(f'✓ Created Stock item: {item.name}')

# Multi-purpose Item
if frappe.db.exists('Item', 'TEST-MULTI-001'):
    frappe.delete_doc('Item', 'TEST-MULTI-001', force=True)
    frappe.db.commit()
item = frappe.new_doc('Item')
item.item_code = 'TEST-MULTI-001'
item.item_name = 'TEST-MULTI-001'
item.item_group = 'All Item Groups'
item.stock_uom = 'Nos'
item.is_sales_item = 1
item.is_purchase_item = 1
item.is_stock_item = 1
item.income_account = income_account
item.expense_account = expense_account
item.standard_rate = 100.0
item.insert()
frappe.db.commit()
items_created.append(item.name)
print(f'✓ Created Multi-purpose item: {item.name}')

print(f'\n✓ SUCCESS: Created {len(items_created)} items')
print(f'Items: {items_created}')