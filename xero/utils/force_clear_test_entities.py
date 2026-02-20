"""Force clear all test entities from ERPNext."""

def force_clear_test_entities():
    import frappe
    
    print("Force clearing test entities from ERPNext...")
    
    frappe.db.auto_commit_on_many_writes = 1
    
    # First, delete Payment Ledger Entries for test invoices
    print("Deleting Payment Ledger Entries...")
    frappe.db.sql("""
        DELETE FROM `tabPayment Ledger Entry`
        WHERE voucher_no LIKE 'ACC-SINV-%'
        OR voucher_no LIKE 'ACC-PINV-%'
    """)
    frappe.db.sql("""
        DELETE FROM `tabGL Entry`
        WHERE voucher_no LIKE 'ACC-SINV-%'
        OR voucher_no LIKE 'ACC-PINV-%'
    """)
    frappe.db.sql("""
        DELETE FROM `tabSales Invoice Payment`
        WHERE parent LIKE 'ACC-SINV-%'
    """)
    frappe.db.commit()
    print("Deleted Payment Ledger Entries and GL Entries")
    
    # Delete test Sales Invoices
    print("Deleting Sales Invoices...")
    frappe.db.sql("""
        DELETE FROM `tabSales Invoice Item`
        WHERE parent LIKE 'ACC-SINV-%'
    """)
    frappe.db.sql("""
        DELETE FROM `tabSales Taxes and Charges`
        WHERE parent LIKE 'ACC-SINV-%'
    """)
    frappe.db.sql("""
        DELETE FROM `tabSales Invoice`
        WHERE name LIKE 'ACC-SINV-%'
    """)
    frappe.db.commit()
    print("Deleted Sales Invoices")
    
    # Delete test Purchase Invoices
    print("Deleting Purchase Invoices...")
    frappe.db.sql("""
        DELETE FROM `tabPurchase Invoice Item`
        WHERE parent LIKE 'ACC-PINV-%'
    """)
    frappe.db.sql("""
        DELETE FROM `tabPurchase Taxes and Charges`
        WHERE parent LIKE 'ACC-PINV-%'
    """)
    frappe.db.sql("""
        DELETE FROM `tabPurchase Invoice`
        WHERE name LIKE 'ACC-PINV-%'
    """)
    frappe.db.commit()
    print("Deleted Purchase Invoices")
    
    # Delete test Items
    print("Deleting Items...")
    frappe.db.sql("""
        DELETE FROM `tabItem`
        WHERE name LIKE 'Test Item%'
    """)
    frappe.db.commit()
    print("Deleted Items")
    
    # Delete test Contacts
    print("Deleting Contacts...")
    frappe.db.sql("""
        DELETE FROM `tabContact`
        WHERE name LIKE '%RT Test%'
    """)
    frappe.db.sql("""
        DELETE FROM `tabDynamic Link`
        WHERE link_name LIKE 'RT Test%'
    """)
    frappe.db.commit()
    print("Deleted Contacts")
    
    # Delete test Customers
    print("Deleting Customers...")
    frappe.db.sql("""
        DELETE FROM `tabCustomer`
        WHERE name LIKE 'RT Test%'
    """)
    frappe.db.commit()
    print("Deleted Customers")
    
    # Delete test Suppliers
    print("Deleting Suppliers...")
    frappe.db.sql("""
        DELETE FROM `tabSupplier`
        WHERE name LIKE 'RT Test%'
    """)
    frappe.db.commit()
    print("Deleted Suppliers")
    
    # Delete test Accounts
    print("Deleting Accounts...")
    frappe.db.sql("""
        DELETE FROM `tabAccount`
        WHERE name LIKE '%Test%'
    """)
    frappe.db.commit()
    print("Deleted Accounts")
    
    # Delete Xero Logs
    print("Deleting Xero Logs...")
    frappe.db.sql("""
        DELETE FROM `tabXero Log`
    """)
    frappe.db.commit()
    print("Deleted Xero Logs")
    
    print("\nForce clear complete!")
