import frappe

print('=== Creating Test Customers ===')

def create_customer(ctype, cname):
    if frappe.db.exists('Customer', cname):
        frappe.delete_doc('Customer', cname, force=True)
        frappe.db.commit()
        print(f'Deleted existing: {cname}')
    c = frappe.new_doc('Customer')
    c.customer_name = cname
    c.customer_type = ctype
    c.territory = frappe.get_cached_value('Territory', {'name': ('!=', '')}, 'name')
    c.customer_group = frappe.get_cached_value('Customer Group', {'name': ('!=', '')}, 'name')
    c.company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
    c.insert()
    frappe.db.commit()
    print(f'✓ Created {ctype} customer: {c.name}')
    return c.name

customers = []
customers.append(create_customer('Company', 'TEST CUSTOMER A'))
customers.append(create_customer('Company', 'TEST CUSTOMER B'))
customers.append(create_customer('Individual', 'TEST CUSTOMER C'))
customers.append(create_customer('Individual', 'TEST CUSTOMER D'))

print(f'\n✓ SUCCESS: Created {len(customers)} customers')
print(f'Customers: {customers}')