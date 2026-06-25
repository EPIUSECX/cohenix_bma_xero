import frappe

print("=" * 80)
print("PHASE 8.0: SUBMIT SALES AND PURCHASE ORDERS")
print("=" * 80)

company = "EPIUSE"

# Orders to submit (first 3 of each type)
sales_orders_to_submit = [
    "SAL-ORD-2025-00002",
    "SAL-ORD-2025-00003",
    "SAL-ORD-2025-00004"
]

purchase_orders_to_submit = [
    "PUR-ORD-2025-00002",
    "PUR-ORD-2025-00003",
    "PUR-ORD-2025-00004"
]

submitted_sales_orders = []
submitted_purchase_orders = []
errors = []

print(f"\nCompany: {company}")
print(f"\nSubmitting {len(sales_orders_to_submit)} Sales Orders and {len(purchase_orders_to_submit)} Purchase Orders...\n")

# Submit Sales Orders
print("=== SUBMITTING SALES ORDERS ===\n")
for so_name in sales_orders_to_submit:
    try:
        print(f"--- {so_name} ---")
        so = frappe.get_doc("Sales Order", so_name)
        
        if so.docstatus == 1:
            print(f"⚠ Already submitted: {so_name}")
            submitted_sales_orders.append(so_name)
        elif so.docstatus == 0:
            print(f"Customer: {so.customer}")
            print(f"Items: {len(so.items)}")
            print(f"Total: {so.grand_total} ZAR")
            
            so.submit()
            frappe.db.commit()
            
            submitted_sales_orders.append(so_name)
            print(f"✓ Submitted: {so_name} (docstatus={so.docstatus})")
        else:
            print(f"✗ Cannot submit: {so_name} (docstatus={so.docstatus})")
        
        print()
        
    except Exception as e:
        error_msg = f"Failed to submit {so_name}: {str(e)}"
        errors.append(error_msg)
        print(f"✗ ERROR: {error_msg}\n")
        continue

# Submit Purchase Orders
print("=== SUBMITTING PURCHASE ORDERS ===\n")
for po_name in purchase_orders_to_submit:
    try:
        print(f"--- {po_name} ---")
        po = frappe.get_doc("Purchase Order", po_name)
        
        if po.docstatus == 1:
            print(f"⚠ Already submitted: {po_name}")
            submitted_purchase_orders.append(po_name)
        elif po.docstatus == 0:
            print(f"Supplier: {po.supplier}")
            print(f"Items: {len(po.items)}")
            print(f"Total: {po.grand_total} ZAR")
            
            po.submit()
            frappe.db.commit()
            
            submitted_purchase_orders.append(po_name)
            print(f"✓ Submitted: {po_name} (docstatus={po.docstatus})")
        else:
            print(f"✗ Cannot submit: {po_name} (docstatus={po.docstatus})")
        
        print()
        
    except Exception as e:
        error_msg = f"Failed to submit {po_name}: {str(e)}"
        errors.append(error_msg)
        print(f"✗ ERROR: {error_msg}\n")
        continue

# Summary
print("=" * 80)
print("ORDER SUBMISSION SUMMARY")
print("=" * 80)

print(f"\n✓ Sales Orders Submitted: {len(submitted_sales_orders)}")
for so_name in submitted_sales_orders:
    so = frappe.get_doc("Sales Order", so_name)
    print(f"  - {so_name}: {so.customer}, Status={so.status}")

print(f"\n✓ Purchase Orders Submitted: {len(submitted_purchase_orders)}")
for po_name in submitted_purchase_orders:
    po = frappe.get_doc("Purchase Order", po_name)
    print(f"  - {po_name}: {po.supplier}, Status={po.status}")

if errors:
    print(f"\n✗ Encountered {len(errors)} errors:")
    for error in errors:
        print(f"  - {error}")

print("\n" + "=" * 80)
total_submitted = len(submitted_sales_orders) + len(submitted_purchase_orders)
total_expected = len(sales_orders_to_submit) + len(purchase_orders_to_submit)

if total_submitted == total_expected:
    print("✅ ALL ORDERS SUBMITTED SUCCESSFULLY")
    print("=" * 80)
    print("\nReady for Delivery Notes and Purchase Receipts creation!")
else:
    print(f"⚠ PARTIAL SUCCESS: {total_submitted}/{total_expected} orders submitted")
print("=" * 80)

print(f"\nSubmitted Sales Orders: {submitted_sales_orders}")
print(f"Submitted Purchase Orders: {submitted_purchase_orders}")