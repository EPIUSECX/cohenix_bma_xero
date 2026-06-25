import frappe
from frappe.utils import today, add_days

print('='*70)
print('PHASE 2: Creating 5 Sales Orders and 5 Purchase Orders')
print('='*70)

company = 'EPIUSE'
results = {'sales_orders': [], 'purchase_orders': []}

print('\nCREATING SALES ORDERS')
print('-'*70)

# Sales Order 1
so = frappe.new_doc('Sales Order')
so.customer = 'TEST CUSTOMER A'
so.transaction_date = today()
so.delivery_date = add_days(today(), 7)
so.company = company
so.selling_price_list = 'Standard Selling'
so.currency = 'ZAR'
so.append('items', {'item_code': 'TEST-SALES-001', 'qty': 5, 'rate': 100.0, 'delivery_date': add_days(today(), 7)})
so.insert()
frappe.db.commit()
results['sales_orders'].append(so.name)
print(f'✓ SO-1: {so.name} - Customer: TEST CUSTOMER A, Item: TEST-SALES-001, Qty: 5')

# Sales Order 2
so = frappe.new_doc('Sales Order')
so.customer = 'TEST CUSTOMER B'
so.transaction_date = today()
so.delivery_date = add_days(today(), 7)
so.company = company
so.selling_price_list = 'Standard Selling'
so.currency = 'ZAR'
so.append('items', {'item_code': 'TEST-SALES-002', 'qty': 7, 'rate': 100.0, 'delivery_date': add_days(today(), 7)})
so.insert()
frappe.db.commit()
results['sales_orders'].append(so.name)
print(f'✓ SO-2: {so.name} - Customer: TEST CUSTOMER B, Item: TEST-SALES-002, Qty: 7')

# Sales Order 3
so = frappe.new_doc('Sales Order')
so.customer = 'TEST CUSTOMER C'
so.transaction_date = today()
so.delivery_date = add_days(today(), 7)
so.company = company
so.selling_price_list = 'Standard Selling'
so.currency = 'ZAR'
so.append('items', {'item_code': 'TEST-SALES_FT', 'qty': 10, 'rate': 100.0, 'delivery_date': add_days(today(), 7)})
so.insert()
frappe.db.commit()
results['sales_orders'].append(so.name)
print(f'✓ SO-3: {so.name} - Customer: TEST CUSTOMER C, Item: TEST-SALES_FT, Qty: 10')

# Sales Order 4
so = frappe.new_doc('Sales Order')
so.customer = 'TEST CUSTOMER D'
so.transaction_date = today()
so.delivery_date = add_days(today(), 7)
so.company = company
so.selling_price_list = 'Standard Selling'
so.currency = 'ZAR'
so.append('items', {'item_code': 'TEST-MULTI-001', 'qty': 8, 'rate': 100.0, 'delivery_date': add_days(today(), 7)})
so.insert()
frappe.db.commit()
results['sales_orders'].append(so.name)
print(f'✓ SO-4: {so.name} - Customer: TEST CUSTOMER D, Item: TEST-MULTI-001, Qty: 8')

# Sales Order 5
so = frappe.new_doc('Sales Order')
so.customer = 'TEST CUSTOMER_FT'
so.transaction_date = today()
so.delivery_date = add_days(today(), 7)
so.company = company
so.selling_price_list = 'Standard Selling'
so.currency = 'ZAR'
so.append('items', {'item_code': 'TEST-SALES-001', 'qty': 12, 'rate': 100.0, 'delivery_date': add_days(today(), 7)})
so.insert()
frappe.db.commit()
results['sales_orders'].append(so.name)
print(f'✓ SO-5: {so.name} - Customer: TEST CUSTOMER_FT, Item: TEST-SALES-001, Qty: 12')

print(f'\n✓ Created {len(results["sales_orders"])} Sales Orders')

print('\nCREATING PURCHASE ORDERS')
print('-'*70)

# Purchase Order 1
po = frappe.new_doc('Purchase Order')
po.supplier = 'TEST SUPPLIER A'
po.transaction_date = today()
po.schedule_date = add_days(today(), 10)
po.company = company
po.buying_price_list = 'Standard Buying'
po.currency = 'ZAR'
po.append('items', {'item_code': 'TEST-PURCHASE-001', 'qty': 15, 'rate': 75.0, 'schedule_date': add_days(today(), 10)})
po.insert()
frappe.db.commit()
results['purchase_orders'].append(po.name)
print(f'✓ PO-1: {po.name} - Supplier: TEST SUPPLIER A, Item: TEST-PURCHASE-001, Qty: 15')

# Purchase Order 2
po = frappe.new_doc('Purchase Order')
po.supplier = 'TEST SUPPLIER B'
po.transaction_date = today()
po.schedule_date = add_days(today(), 10)
po.company = company
po.buying_price_list = 'Standard Buying'
po.currency = 'ZAR'
po.append('items', {'item_code': 'TEST-PURCHASE-002', 'qty': 20, 'rate': 75.0, 'schedule_date': add_days(today(), 10)})
po.insert()
frappe.db.commit()
results['purchase_orders'].append(po.name)
print(f'✓ PO-2: {po.name} - Supplier: TEST SUPPLIER B, Item: TEST-PURCHASE-002, Qty: 20')

# Purchase Order 3
po = frappe.new_doc('Purchase Order')
po.supplier = 'TEST SUPPLIER C'
po.transaction_date = today()
po.schedule_date = add_days(today(), 10)
po.company = company
po.buying_price_list = 'Standard Buying'
po.currency = 'ZAR'
po.append('items', {'item_code': 'TEST-PURCHASE_FT', 'qty': 25, 'rate': 75.0, 'schedule_date': add_days(today(), 10)})
po.insert()
frappe.db.commit()
results['purchase_orders'].append(po.name)
print(f'✓ PO-3: {po.name} - Supplier: TEST SUPPLIER C, Item: TEST-PURCHASE_FT, Qty: 25')

# Purchase Order 4
po = frappe.new_doc('Purchase Order')
po.supplier = 'TEST SUPPLIER D'
po.transaction_date = today()
po.schedule_date = add_days(today(), 10)
po.company = company
po.buying_price_list = 'Standard Buying'
po.currency = 'ZAR'
po.append('items', {'item_code': 'TEST-MULTI-001', 'qty': 18, 'rate': 75.0, 'schedule_date': add_days(today(), 10)})
po.insert()
frappe.db.commit()
results['purchase_orders'].append(po.name)
print(f'✓ PO-4: {po.name} - Supplier: TEST SUPPLIER D, Item: TEST-MULTI-001, Qty: 18')

# Purchase Order 5
po = frappe.new_doc('Purchase Order')
po.supplier = 'TEST SUPPLIER_FT'
po.transaction_date = today()
po.schedule_date = add_days(today(), 10)
po.company = company
po.buying_price_list = 'Standard Buying'
po.currency = 'ZAR'
po.append('items', {'item_code': 'TEST-PURCHASE-001', 'qty': 30, 'rate': 75.0, 'schedule_date': add_days(today(), 10)})
po.insert()
frappe.db.commit()
results['purchase_orders'].append(po.name)
print(f'✓ PO-5: {po.name} - Supplier: TEST SUPPLIER_FT, Item: TEST-PURCHASE-001, Qty: 30')

print(f'\n✓ Created {len(results["purchase_orders"])} Purchase Orders')

print('\n' + '='*70)
print('SUMMARY')
print('='*70)
print(f'✓ Sales Orders: {len(results["sales_orders"])}')
for so in results['sales_orders']:
    print(f'    - {so}')
print(f'\n✓ Purchase Orders: {len(results["purchase_orders"])}')
for po in results['purchase_orders']:
    print(f'    - {po}')
print(f'\n✓ TOTAL ORDERS: {len(results["sales_orders"]) + len(results["purchase_orders"])}')
print('='*70)