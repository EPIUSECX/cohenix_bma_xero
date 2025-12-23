import frappe
from frappe.utils import nowdate

print("=" * 80)
print("PHASE 8.2: CREATE PURCHASE RECEIPTS FROM PURCHASE ORDERS")
print("=" * 80)

company = "EPIUSE"
warehouse = "Stores - E"

# Purchase Orders to create receipts from
purchase_orders_config = [
    {
        "purchase_order": "PUR-ORD-2025-00002",
        "receipt_type": "Full",
        "qty_percentage": 1.0  # 100%
    },
    {
        "purchase_order": "PUR-ORD-2025-00003",
        "receipt_type": "Partial",
        "qty_percentage": 0.6  # 60% (using whole number result)
    },
    {
        "purchase_order": "PUR-ORD-2025-00004",
        "receipt_type": "Full",
        "qty_percentage": 1.0  # 100%
    }
]

created_purchase_receipts = []
errors = []

print(f"\nCompany: {company}")
print(f"Warehouse: {warehouse}")
print(f"\nCreating {len(purchase_orders_config)} purchase receipts...\n")

for idx, config in enumerate(purchase_orders_config, 1):
    try:
        print(f"--- Purchase Receipt {idx}: {config['receipt_type']} Receipt ---")
        
        # Get Purchase Order
        po = frappe.get_doc("Purchase Order", config['purchase_order'])
        print(f"Purchase Order: {po.name}")
        print(f"Supplier: {po.supplier}")
        print(f"Items: {len(po.items)}")
        
        # Create Purchase Receipt using make_purchase_receipt utility
        from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
        
        pr = make_purchase_receipt(po.name)
        pr.posting_date = nowdate()
        pr.set_warehouse = warehouse
        
        # Adjust quantities for partial receipt (use whole numbers only)
        if config['qty_percentage'] < 1.0:
            for item in pr.items:
                original_qty = item.qty
                # Round to whole number
                item.qty = int(item.qty * config['qty_percentage'])
                if item.qty < 1:
                    item.qty = 1  # Minimum 1
                print(f"  Adjusted {item.item_code}: Qty={item.qty} (from {original_qty})")
        
        # Insert purchase receipt
        pr.insert()
        frappe.db.commit()
        
        created_purchase_receipts.append(pr.name)
        print(f"✓ Created: {pr.name}")
        print(f"  Supplier: {pr.supplier}")
        print(f"  Items: {len(pr.items)}")
        print(f"  Total: {pr.grand_total} ZAR")
        print(f"  Type: {config['receipt_type']}")
        print(f"  Status: Draft (docstatus={pr.docstatus})")
        print()
        
    except Exception as e:
        error_msg = f"Failed to create purchase receipt for {config['purchase_order']}: {str(e)}"
        errors.append(error_msg)
        print(f"✗ ERROR: {error_msg}\n")
        import traceback
        print(traceback.format_exc())
        continue

# Summary
print("=" * 80)
print("PURCHASE RECEIPTS CREATION SUMMARY")
print("=" * 80)

if created_purchase_receipts:
    print(f"\n✓ Successfully created {len(created_purchase_receipts)} purchase receipts:")
    total_value = 0
    for pr_name in created_purchase_receipts:
        pr = frappe.get_doc("Purchase Receipt", pr_name)
        print(f"  - {pr_name}: {pr.supplier} - {pr.grand_total} ZAR ({len(pr.items)} items)")
        total_value += pr.grand_total
    
    print(f"\nTotal Receipt Value: {total_value} ZAR")

if errors:
    print(f"\n✗ Encountered {len(errors)} errors:")
    for error in errors:
        print(f"  - {error}")

# List all purchase receipts
print("\n=== ALL PURCHASE RECEIPTS ===")
all_purchase_receipts = frappe.get_all("Purchase Receipt",
    filters={"company": company},
    fields=["name", "supplier", "grand_total", "docstatus"],
    order_by="name"
)

for pr in all_purchase_receipts:
    status = "Draft" if pr.docstatus == 0 else "Submitted" if pr.docstatus == 1 else "Cancelled"
    print(f"{pr.name}: {pr.supplier}, Total={pr.grand_total}, Status={status}")

print("\n" + "=" * 80)
if len(created_purchase_receipts) == len(purchase_orders_config):
    print("✅ ALL PURCHASE RECEIPTS CREATED SUCCESSFULLY")
else:
    print(f"⚠ PARTIAL SUCCESS: {len(created_purchase_receipts)}/{len(purchase_orders_config)} purchase receipts created")
print("=" * 80)

# List created purchase receipts
print(f"\nCreated Purchase Receipts: {created_purchase_receipts}")