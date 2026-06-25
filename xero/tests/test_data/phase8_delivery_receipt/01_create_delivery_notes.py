import frappe
from frappe.utils import nowdate

print("=" * 80)
print("PHASE 8.1: CREATE DELIVERY NOTES FROM SALES ORDERS")
print("=" * 80)

company = "EPIUSE"
warehouse = "Stores - E"

# Sales Orders to create delivery notes from
sales_orders_config = [
    {
        "sales_order": "SAL-ORD-2025-00002",
        "delivery_type": "Full",
        "qty_percentage": 1.0  # 100%
    },
    {
        "sales_order": "SAL-ORD-2025-00003",
        "delivery_type": "Partial",
        "qty_percentage": 0.5  # 50%
    },
    {
        "sales_order": "SAL-ORD-2025-00004",
        "delivery_type": "Full",
        "qty_percentage": 1.0  # 100%
    }
]

created_delivery_notes = []
errors = []

print(f"\nCompany: {company}")
print(f"Warehouse: {warehouse}")
print(f"\nCreating {len(sales_orders_config)} delivery notes...\n")

for idx, config in enumerate(sales_orders_config, 1):
    try:
        print(f"--- Delivery Note {idx}: {config['delivery_type']} Delivery ---")
        
        # Get Sales Order
        so = frappe.get_doc("Sales Order", config['sales_order'])
        print(f"Sales Order: {so.name}")
        print(f"Customer: {so.customer}")
        print(f"Items: {len(so.items)}")
        
        # Create Delivery Note using make_delivery_note utility
        from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
        
        dn = make_delivery_note(so.name)
        dn.posting_date = nowdate()
        dn.set_warehouse = warehouse
        
        # Adjust quantities for partial delivery
        if config['qty_percentage'] < 1.0:
            for item in dn.items:
                item.qty = item.qty * config['qty_percentage']
                print(f"  Adjusted {item.item_code}: Qty={item.qty} ({config['qty_percentage']*100}%)")
        
        # Insert delivery note
        dn.insert()
        frappe.db.commit()
        
        created_delivery_notes.append(dn.name)
        print(f"✓ Created: {dn.name}")
        print(f"  Customer: {dn.customer}")
        print(f"  Items: {len(dn.items)}")
        print(f"  Total: {dn.grand_total} ZAR")
        print(f"  Type: {config['delivery_type']}")
        print(f"  Status: Draft (docstatus={dn.docstatus})")
        print()
        
    except Exception as e:
        error_msg = f"Failed to create delivery note for {config['sales_order']}: {str(e)}"
        errors.append(error_msg)
        print(f"✗ ERROR: {error_msg}\n")
        import traceback
        print(traceback.format_exc())
        continue

# Summary
print("=" * 80)
print("DELIVERY NOTES CREATION SUMMARY")
print("=" * 80)

if created_delivery_notes:
    print(f"\n✓ Successfully created {len(created_delivery_notes)} delivery notes:")
    total_value = 0
    for dn_name in created_delivery_notes:
        dn = frappe.get_doc("Delivery Note", dn_name)
        print(f"  - {dn_name}: {dn.customer} - {dn.grand_total} ZAR ({len(dn.items)} items)")
        total_value += dn.grand_total
    
    print(f"\nTotal Delivery Value: {total_value} ZAR")

if errors:
    print(f"\n✗ Encountered {len(errors)} errors:")
    for error in errors:
        print(f"  - {error}")

# List all delivery notes
print("\n=== ALL DELIVERY NOTES ===")
all_delivery_notes = frappe.get_all("Delivery Note",
    filters={"company": company},
    fields=["name", "customer", "grand_total", "docstatus"],
    order_by="name"
)

for dn in all_delivery_notes:
    status = "Draft" if dn.docstatus == 0 else "Submitted" if dn.docstatus == 1 else "Cancelled"
    print(f"{dn.name}: {dn.customer}, Total={dn.grand_total}, Status={status}")

print("\n" + "=" * 80)
if len(created_delivery_notes) == len(sales_orders_config):
    print("✅ ALL DELIVERY NOTES CREATED SUCCESSFULLY")
else:
    print(f"⚠ PARTIAL SUCCESS: {len(created_delivery_notes)}/{len(sales_orders_config)} delivery notes created")
print("=" * 80)

# List created delivery notes
print(f"\nCreated Delivery Notes: {created_delivery_notes}")