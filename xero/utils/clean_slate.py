"""
Clean Slate Script - Remove all test data and stale Xero IDs
Run: bench --site cohenix.localhost execute xero.utils.clean_slate.run
"""
import frappe

def run():
    print("=" * 80)
    print("CLEAN SLATE - Removing all test data and stale Xero IDs")
    print("=" * 80)

    # 1. Cancel and delete submitted transactional docs
    for doctype in ["Payment Entry", "Journal Entry"]:
        docs = frappe.get_all(doctype, filters={"docstatus": 1}, fields=["name"])
        for d in docs:
            try:
                doc = frappe.get_doc(doctype, d.name)
                doc.cancel()
                frappe.db.commit()
                print(f"  Cancelled {doctype}: {d.name}")
            except Exception as e:
                print(f"  Could not cancel {doctype} {d.name}: {e}")

    for doctype in ["Sales Invoice", "Purchase Invoice"]:
        docs = frappe.get_all(doctype, filters={"docstatus": 1}, fields=["name"])
        for d in docs:
            try:
                doc = frappe.get_doc(doctype, d.name)
                doc.cancel()
                frappe.db.commit()
                print(f"  Cancelled {doctype}: {d.name}")
            except Exception as e:
                print(f"  Could not cancel {doctype} {d.name}: {e}")

    for doctype in ["Quotation", "Purchase Order"]:
        docs = frappe.get_all(doctype, filters={"docstatus": 1}, fields=["name"])
        for d in docs:
            try:
                doc = frappe.get_doc(doctype, d.name)
                doc.cancel()
                frappe.db.commit()
                print(f"  Cancelled {doctype}: {d.name}")
            except Exception as e:
                print(f"  Could not cancel {doctype} {d.name}: {e}")

    # Bank Transactions
    docs = frappe.get_all("Bank Transaction", filters={"docstatus": 1}, fields=["name"])
    for d in docs:
        try:
            doc = frappe.get_doc("Bank Transaction", d.name)
            doc.cancel()
            frappe.db.commit()
            print(f"  Cancelled Bank Transaction: {d.name}")
        except Exception as e:
            print(f"  Could not cancel Bank Transaction {d.name}: {e}")

    # 2. Delete all transactional docs (cancelled + draft)
    for doctype in ["Payment Entry", "Journal Entry", "Bank Transaction",
                    "Sales Invoice", "Purchase Invoice", "Quotation", "Purchase Order"]:
        docs = frappe.get_all(doctype, fields=["name"])
        for d in docs:
            try:
                frappe.delete_doc(doctype, d.name, force=True, ignore_permissions=True)
                frappe.db.commit()
                print(f"  Deleted {doctype}: {d.name}")
            except Exception as e:
                print(f"  Could not delete {doctype} {d.name}: {e}")

    # 3. Delete test items
    items = frappe.get_all("Item", fields=["name"])
    for item in items:
        try:
            frappe.delete_doc("Item", item.name, force=True, ignore_permissions=True)
            frappe.db.commit()
            print(f"  Deleted Item: {item.name}")
        except Exception as e:
            print(f"  Could not delete Item {item.name}: {e}")

    # 4. Delete all customers
    customers = frappe.get_all("Customer", fields=["name"])
    for c in customers:
        try:
            frappe.delete_doc("Customer", c.name, force=True, ignore_permissions=True)
            frappe.db.commit()
            print(f"  Deleted Customer: {c.name}")
        except Exception as e:
            print(f"  Could not delete Customer {c.name}: {e}")

    # 5. Delete all suppliers
    suppliers = frappe.get_all("Supplier", fields=["name"])
    for s in suppliers:
        try:
            frappe.delete_doc("Supplier", s.name, force=True, ignore_permissions=True)
            frappe.db.commit()
            print(f"  Deleted Supplier: {s.name}")
        except Exception as e:
            print(f"  Could not delete Supplier {s.name}: {e}")

    # 6. Clear stale xero_account_id from all accounts
    frappe.db.sql("UPDATE tabAccount SET xero_account_id = NULL, xero_sync_status = NULL, xero_last_account_sync = NULL WHERE xero_account_id IS NOT NULL")
    frappe.db.commit()
    print("  Cleared all xero_account_id from accounts")

    # 7. Clear Xero Account cache
    frappe.db.sql("DELETE FROM `tabXero Account`")
    frappe.db.commit()
    print("  Cleared Xero Account cache")

    # 8. Clear Xero logs
    frappe.db.sql("DELETE FROM `tabXero Log`")
    frappe.db.commit()
    print("  Cleared Xero logs")

    # 9. Clear account mappings
    frappe.db.sql("DELETE FROM `tabXero Account Mapping`")
    frappe.db.commit()
    print("  Cleared account mappings")

    print("\n" + "=" * 80)
    print("CLEAN SLATE COMPLETE")
    print("=" * 80)

    # Verify
    for doctype in ["Customer", "Supplier", "Item", "Sales Invoice", "Purchase Invoice",
                    "Payment Entry", "Journal Entry", "Quotation", "Purchase Order", "Bank Transaction"]:
        count = frappe.db.count(doctype)
        print(f"  {doctype}: {count} remaining")
