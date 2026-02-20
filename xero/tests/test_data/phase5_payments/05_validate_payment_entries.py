import frappe

print("=" * 80)
print("PHASE 5.5: VALIDATE PAYMENT ENTRIES")
print("=" * 80)

company = "EPIUSE"

# Get all payment entries
print("\n=== ALL PAYMENT ENTRIES ===")
payments = frappe.get_all("Payment Entry",
    filters={"company": company},
    fields=["name", "party_type", "party", "payment_type", "paid_amount", "mode_of_payment", "docstatus", "posting_date"],
    order_by="name"
)

print(f"Total Payment Entries: {len(payments)}\n")

customer_payments = []
supplier_payments = []
advance_payments = []

for pe in payments:
    print(f"{pe.name}:")
    print(f"  Party: {pe.party_type} - {pe.party}")
    print(f"  Type: {pe.payment_type}")
    print(f"  Amount: {pe.paid_amount} ZAR")
    print(f"  Mode: {pe.mode_of_payment}")
    print(f"  Status: {'Draft' if pe.docstatus == 0 else 'Submitted' if pe.docstatus == 1 else 'Cancelled'}")
    print(f"  Date: {pe.posting_date}")
    
    # Check for invoice references
    payment_doc = frappe.get_doc("Payment Entry", pe.name)
    if payment_doc.references:
        print(f"  References: {len(payment_doc.references)} invoice(s)")
        for ref in payment_doc.references:
            print(f"    - {ref.reference_doctype}: {ref.reference_name} (Allocated: {ref.allocated_amount})")
        
        if pe.party_type == "Customer":
            customer_payments.append(pe.name)
        elif pe.party_type == "Supplier":
            supplier_payments.append(pe.name)
    else:
        print(f"  References: None (Advance Payment)")
        advance_payments.append(pe.name)
    
    print()

# Summary by type
print("=" * 80)
print("PAYMENT ENTRIES BY TYPE")
print("=" * 80)

print(f"\n✓ Customer Payments (with invoice references): {len(customer_payments)}")
for name in customer_payments:
    pe = frappe.get_doc("Payment Entry", name)
    print(f"  - {name}: {pe.party} - {pe.paid_amount} ZAR ({pe.mode_of_payment})")

print(f"\n✓ Supplier Payments (with invoice references): {len(supplier_payments)}")
for name in supplier_payments:
    pe = frappe.get_doc("Payment Entry", name)
    print(f"  - {name}: {pe.party} - {pe.paid_amount} ZAR ({pe.mode_of_payment})")

print(f"\n✓ Advance Payments (no invoice references): {len(advance_payments)}")
for name in advance_payments:
    pe = frappe.get_doc("Payment Entry", name)
    print(f"  - {name}: {pe.party} - {pe.paid_amount} ZAR ({pe.mode_of_payment})")

# Verify invoice outstanding amounts
print("\n" + "=" * 80)
print("INVOICE OUTSTANDING VERIFICATION")
print("=" * 80)

print("\n=== SALES INVOICES ===")
sales_invoices = frappe.get_all("Sales Invoice",
    filters={"docstatus": 1, "company": company},
    fields=["name", "customer", "grand_total", "outstanding_amount"],
    order_by="name"
)

for si in sales_invoices:
    status = "✓ Fully Paid" if si.outstanding_amount == 0 else f"⚠ Outstanding: {si.outstanding_amount}"
    print(f"{si.name}: {si.customer}, Total={si.grand_total}, {status}")

print("\n=== PURCHASE INVOICES ===")
purchase_invoices = frappe.get_all("Purchase Invoice",
    filters={"docstatus": 1, "company": company},
    fields=["name", "supplier", "grand_total", "outstanding_amount"],
    order_by="name"
)

for pi in purchase_invoices:
    status = "✓ Fully Paid" if pi.outstanding_amount == 0 else f"⚠ Outstanding: {pi.outstanding_amount}"
    print(f"{pi.name}: {pi.supplier}, Total={pi.grand_total}, {status}")

# Calculate totals
print("\n" + "=" * 80)
print("PAYMENT TOTALS")
print("=" * 80)

total_customer_payments = sum(frappe.get_value("Payment Entry", name, "paid_amount") for name in customer_payments)
total_supplier_payments = sum(frappe.get_value("Payment Entry", name, "paid_amount") for name in supplier_payments)
total_advance_payments = sum(frappe.get_value("Payment Entry", name, "paid_amount") for name in advance_payments)

print(f"\nCustomer Payments Total: {total_customer_payments} ZAR")
print(f"Supplier Payments Total: {total_supplier_payments} ZAR")
print(f"Advance Payments Total: {total_advance_payments} ZAR")
print(f"Grand Total: {total_customer_payments + total_supplier_payments + total_advance_payments} ZAR")

# Validation checks
print("\n" + "=" * 80)
print("VALIDATION SUMMARY")
print("=" * 80)

all_checks_passed = True

if len(customer_payments) >= 3:
    print("✓ Customer Payments: PASS (3+ payments created)")
else:
    print(f"✗ Customer Payments: FAIL (Expected 3+, found {len(customer_payments)})")
    all_checks_passed = False

if len(supplier_payments) >= 3:
    print("✓ Supplier Payments: PASS (3+ payments created)")
else:
    print(f"✗ Supplier Payments: FAIL (Expected 3+, found {len(supplier_payments)})")
    all_checks_passed = False

if len(advance_payments) >= 1:
    print("✓ Advance Payments: PASS (1+ advance payment created)")
else:
    print(f"✗ Advance Payments: FAIL (Expected 1+, found {len(advance_payments)})")
    all_checks_passed = False

if len(payments) >= 7:
    print(f"✓ Total Payments: PASS ({len(payments)} payments created)")
else:
    print(f"✗ Total Payments: FAIL (Expected 7+, found {len(payments)})")
    all_checks_passed = False

# Check for different payment modes
modes_used = set(pe.mode_of_payment for pe in payments)
if len(modes_used) >= 3:
    print(f"✓ Payment Modes: PASS ({len(modes_used)} different modes used: {', '.join(modes_used)})")
else:
    print(f"⚠ Payment Modes: WARNING (Expected 3+ modes, found {len(modes_used)})")

print("\n" + "=" * 80)
if all_checks_passed:
    print("✅ ALL PAYMENT ENTRIES VALIDATED SUCCESSFULLY")
    print("=" * 80)
    print("\nPhase 5 Complete:")
    print(f"  - {len(customer_payments)} Customer Payments")
    print(f"  - {len(supplier_payments)} Supplier Payments")
    print(f"  - {len(advance_payments)} Advance Payment(s)")
    print(f"  - Total: {len(payments)} Payment Entries")
    print(f"  - Total Amount: {total_customer_payments + total_supplier_payments + total_advance_payments} ZAR")
else:
    print("❌ SOME VALIDATION CHECKS FAILED")
print("=" * 80)