"""Verify ERPNext is clean of test entities."""

def verify_clean():
    import frappe
    
    print("Verifying ERPNext is clean...")
    
    # Check Sales Invoices
    si_count = frappe.db.sql("SELECT COUNT(*) FROM `tabSales Invoice` WHERE name LIKE 'ACC-SINV-%'")[0][0]
    print(f"Sales Invoices (ACC-SINV-%): {si_count}")
    
    # Check Purchase Invoices
    pi_count = frappe.db.sql("SELECT COUNT(*) FROM `tabPurchase Invoice` WHERE name LIKE 'ACC-PINV-%'")[0][0]
    print(f"Purchase Invoices (ACC-PINV-%): {pi_count}")
    
    # Check Items
    item_count = frappe.db.sql("SELECT COUNT(*) FROM `tabItem` WHERE name LIKE 'Test Item%'")[0][0]
    print(f"Test Items: {item_count}")
    
    # Check Customers
    cust_count = frappe.db.sql("SELECT COUNT(*) FROM `tabCustomer` WHERE name LIKE 'RT Test%'")[0][0]
    print(f"Test Customers: {cust_count}")
    
    # Check Suppliers
    sup_count = frappe.db.sql("SELECT COUNT(*) FROM `tabSupplier` WHERE name LIKE 'RT Test%'")[0][0]
    print(f"Test Suppliers: {sup_count}")
    
    # Check Xero Logs
    log_count = frappe.db.sql("SELECT COUNT(*) FROM `tabXero Log` WHERE creation > DATE_SUB(NOW(), INTERVAL 1 DAY)")[0][0]
    print(f"Recent Xero Logs: {log_count}")
    
    # Check Payment Ledger Entries
    ple_count = frappe.db.sql("SELECT COUNT(*) FROM `tabPayment Ledger Entry` WHERE voucher_no LIKE 'ACC-%'")[0][0]
    print(f"Test Payment Ledger Entries: {ple_count}")
    
    # Check GL Entries
    gle_count = frappe.db.sql("SELECT COUNT(*) FROM `tabGL Entry` WHERE voucher_no LIKE 'ACC-%'")[0][0]
    print(f"Test GL Entries: {gle_count}")
    
    total = si_count + pi_count + item_count + cust_count + sup_count + log_count + ple_count + gle_count
    
    if total == 0:
        print("\n✅ ERPNext is CLEAN - ready for demo!")
    else:
        print(f"\n⚠️ Found {total} test entities remaining")
    
    return total == 0
