"""Clear all test entities from ERPNext (developer-only utility)."""

def clear_test_entities(confirm=None):
    import frappe

    # CR-4: developer mode + explicit confirmation required.
    if not frappe.conf.get("developer_mode"):
        frappe.throw(
            "clear_test_entities is blocked: developer_mode is not enabled on this site."
        )
    if confirm != "WIPE":
        frappe.throw(
            "Refusing to delete data without explicit confirmation. "
            "Pass confirm='WIPE' to proceed (developer sites only)."
        )

    print("Clearing test entities from ERPNext...")
    
    # Delete test Sales Invoices
    deleted_si = 0
    test_si = frappe.get_all("Sales Invoice", 
        filters={"name": ["like", "ACC-SINV-%"]},
        fields=["name", "docstatus"])
    
    for si in test_si:
        try:
            doc = frappe.get_doc("Sales Invoice", si.name)
            if si.docstatus == 1:
                doc.cancel()
            doc.delete(ignore_permissions=True)
            deleted_si += 1
        except Exception as e:
            print(f"Could not delete Sales Invoice {si.name}: {e}")
    
    print(f"Deleted {deleted_si} Sales Invoices")
    
    # Delete test Purchase Invoices
    deleted_pi = 0
    test_pi = frappe.get_all("Purchase Invoice",
        filters={"name": ["like", "ACC-PINV-%"]},
        fields=["name", "docstatus"])
    
    for pi in test_pi:
        try:
            doc = frappe.get_doc("Purchase Invoice", pi.name)
            if pi.docstatus == 1:
                doc.cancel()
            doc.delete(ignore_permissions=True)
            deleted_pi += 1
        except Exception as e:
            print(f"Could not delete Purchase Invoice {pi.name}: {e}")
    
    print(f"Deleted {deleted_pi} Purchase Invoices")
    
    # Delete test Items
    deleted_items = 0
    test_items = frappe.get_all("Item",
        filters={"name": ["like", "Test Item%"]},
        fields=["name"])
    
    for item in test_items:
        try:
            frappe.delete_doc("Item", item.name, ignore_permissions=True, force=True)
            deleted_items += 1
        except Exception as e:
            print(f"Could not delete Item {item.name}: {e}")
    
    print(f"Deleted {deleted_items} Items")
    
    # Delete test Customers
    deleted_customers = 0
    test_customers = frappe.get_all("Customer",
        filters={"name": ["like", "RT Test%"]},
        fields=["name"])
    
    for cust in test_customers:
        try:
            frappe.delete_doc("Customer", cust.name, ignore_permissions=True, force=True)
            deleted_customers += 1
        except Exception as e:
            print(f"Could not delete Customer {cust.name}: {e}")
    
    print(f"Deleted {deleted_customers} Customers")
    
    # Delete test Suppliers
    deleted_suppliers = 0
    test_suppliers = frappe.get_all("Supplier",
        filters={"name": ["like", "RT Test%"]},
        fields=["name"])
    
    for sup in test_suppliers:
        try:
            frappe.delete_doc("Supplier", sup.name, ignore_permissions=True, force=True)
            deleted_suppliers += 1
        except Exception as e:
            print(f"Could not delete Supplier {sup.name}: {e}")
    
    print(f"Deleted {deleted_suppliers} Suppliers")
    
    # Delete test Accounts
    deleted_accounts = 0
    test_accounts = frappe.get_all("Account",
        filters={"name": ["like", "%Test%"]},
        fields=["name"])
    
    for acc in test_accounts:
        try:
            frappe.delete_doc("Account", acc.name, ignore_permissions=True, force=True)
            deleted_accounts += 1
        except Exception as e:
            print(f"Could not delete Account {acc.name}: {e}")
    
    print(f"Deleted {deleted_accounts} Accounts")
    
    # Commit changes
    frappe.db.commit()
    
    print("\nClear complete!")
    print(f"Total deleted: {deleted_si + deleted_pi + deleted_items + deleted_customers + deleted_suppliers + deleted_accounts} entities")
