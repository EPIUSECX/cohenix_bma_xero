import frappe

print('=== Adding Customer Addresses ===')

customers = ['TEST CUSTOMER A', 'TEST CUSTOMER B', 'TEST CUSTOMER C', 'TEST CUSTOMER D']
addresses_created = 0

for customer_name in customers:
    if not frappe.db.exists('Customer', customer_name):
        print(f'✗ Customer not found: {customer_name}')
    else:
        customer = frappe.get_doc('Customer', customer_name)
        address_name = f'{customer_name} - Billing'
        
        if frappe.db.exists('Address', address_name):
            print(f'Address already exists for {customer_name}')
        else:
            address = frappe.new_doc('Address')
            address.address_title = address_name
            address.address_type = 'Billing'
            address.address_line1 = '123 Test Street'
            address.city = 'Test City'
            address.state = 'Test State'
            address.pincode = '12345'
            address.country = 'United States'
            
            address.append('links', {
                'link_doctype': 'Customer',
                'link_name': customer_name
            })
            
            address.insert()
            frappe.db.commit()
            addresses_created += 1
            
            print(f'✓ Added address for {customer_name}: {address.name}')

print(f'\n✓ SUCCESS: Created {addresses_created} new addresses for {len(customers)} customers')