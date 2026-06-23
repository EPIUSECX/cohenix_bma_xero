"""
Phase 1: Contact Sync Test
Run: bench --site cohenix.localhost execute xero.utils.phase1_contacts.step_a_create
"""
import frappe
from xero.utils.logging import get_leaf_doctype_value

def step_a_create():
    """Step 1A: Create test contacts in ERPNext"""
    print("=" * 80)
    print("PHASE 1A: Creating Test Contacts")
    print("=" * 80)

    # Customer
    c = frappe.new_doc("Customer")
    c.customer_name = "SyncTest Customer Alpha"
    c.customer_type = "Company"
    c.customer_group = get_leaf_doctype_value("Customer Group", "Commercial")
    c.territory = get_leaf_doctype_value("Territory")
    c.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"✅ Created Customer: {c.name}")

    # Supplier
    s = frappe.new_doc("Supplier")
    s.supplier_name = "SyncTest Supplier Beta"
    s.supplier_group = get_leaf_doctype_value("Supplier Group")
    s.supplier_type = "Company"
    s.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"✅ Created Supplier: {s.name}")


def step_b_outbound():
    """Step 1B: Manually trigger outbound contact sync"""
    print("=" * 80)
    print("PHASE 1B: Outbound Contact Sync (ERPNext → Xero)")
    print("=" * 80)

    from xero.api.xero_contacts import sync_contact_to_xero

    # Sync customer
    try:
        sync_contact_to_xero("SyncTest Customer Alpha", "Customer")
        xero_id = frappe.db.get_value("Customer", "SyncTest Customer Alpha", "xero_contact_id")
        status = frappe.db.get_value("Customer", "SyncTest Customer Alpha", "xero_sync_status")
        print(f"Customer: xero_id={xero_id} | status={status}")
    except Exception as e:
        print(f"❌ Customer sync failed: {e}")

    # Sync supplier
    try:
        sync_contact_to_xero("SyncTest Supplier Beta", "Supplier")
        xero_id = frappe.db.get_value("Supplier", "SyncTest Supplier Beta", "xero_contact_id")
        status = frappe.db.get_value("Supplier", "SyncTest Supplier Beta", "xero_sync_status")
        print(f"Supplier: xero_id={xero_id} | status={status}")
    except Exception as e:
        print(f"❌ Supplier sync failed: {e}")


def step_c_verify_xero():
    """Step 1C: Verify contacts exist in Xero"""
    print("=" * 80)
    print("PHASE 1C: Verify Contacts in Xero")
    print("=" * 80)

    from xero.utils.xero_client import xero_request
    response = xero_request("GET", "Contacts")
    if response:
        contacts = response.get("Contacts", [])
        print(f"Total Xero contacts: {len(contacts)}")
        for c in contacts:
            if "SyncTest" in c.get("Name", ""):
                print(f"  ✅ Found: {c['Name']} | ID: {c['ContactID']} | IsCustomer: {c.get('IsCustomer')} | IsSupplier: {c.get('IsSupplier')}")
    else:
        print("❌ Failed to query Xero contacts")


def step_d_delete_erpnext():
    """Step 1D: Delete contacts from ERPNext"""
    print("=" * 80)
    print("PHASE 1D: Delete ERPNext Contacts (keep in Xero)")
    print("=" * 80)

    for doctype, name in [("Customer", "SyncTest Customer Alpha"), ("Supplier", "SyncTest Supplier Beta")]:
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            frappe.db.commit()
            print(f"  Deleted {doctype}: {name}")
        else:
            print(f"  {doctype} {name} not found")

    # Verify
    print(f"  Customers remaining: {frappe.db.count('Customer')}")
    print(f"  Suppliers remaining: {frappe.db.count('Supplier')}")


def step_e_inbound():
    """Step 1E: Inbound sync (Xero → ERPNext)"""
    print("=" * 80)
    print("PHASE 1E: Inbound Contact Sync (Xero → ERPNext)")
    print("=" * 80)

    from xero.api.xero_contacts import sync_contacts_from_xero
    sync_contacts_from_xero()


def step_f_verify_inbound():
    """Step 1F: Verify inbound results"""
    print("=" * 80)
    print("PHASE 1F: Verify Inbound Results")
    print("=" * 80)

    for doctype in ["Customer", "Supplier"]:
        contacts = frappe.get_all(doctype,
            filters={"xero_contact_id": ["!=", ""]},
            fields=["name", "xero_contact_id", "xero_sync_status"])
        print(f"\n{doctype}s with Xero ID: {len(contacts)}")
        for c in contacts:
            print(f"  {c.name} | xero_id: {c.xero_contact_id} | status: {c.xero_sync_status}")

    # Also check for SyncTest contacts without xero_id
    for doctype in ["Customer", "Supplier"]:
        contacts = frappe.get_all(doctype,
            filters={"name": ["like", "%SyncTest%"]},
            fields=["name", "xero_contact_id", "xero_sync_status"])
        if contacts:
            print(f"\n{doctype}s matching 'SyncTest':")
            for c in contacts:
                print(f"  {c.name} | xero_id: {c.xero_contact_id} | status: {c.xero_sync_status}")
