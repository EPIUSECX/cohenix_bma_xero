import frappe

print('=== Creating Test Suppliers ===')

def create_supplier(stype, sname):
    if frappe.db.exists('Supplier', sname):
        frappe.delete_doc('Supplier', sname, force=True)
        frappe.db.commit()
        print(f'Deleted existing: {sname}')
    s = frappe.new_doc('Supplier')
    s.supplier_name = sname
    s.supplier_type = stype
    s.supplier_group = frappe.get_cached_value('Supplier Group', {'name': ('!=', '')}, 'name')
    s.company = frappe.get_cached_value('Company', {'name': ('!=', '')}, 'name')
    s.insert()
    frappe.db.commit()
    print(f'✓ Created {stype} supplier: {s.name}')
    return s.name

suppliers = []
suppliers.append(create_supplier('Company', 'TEST SUPPLIER A'))
suppliers.append(create_supplier('Company', 'TEST SUPPLIER B'))
suppliers.append(create_supplier('Individual', 'TEST SUPPLIER C'))
suppliers.append(create_supplier('Individual', 'TEST SUPPLIER D'))

print(f'\n✓ SUCCESS: Created {len(suppliers)} suppliers')
print(f'Suppliers: {suppliers}')