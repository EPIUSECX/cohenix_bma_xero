import frappe
from frappe.utils import today, nowdate

print("=" * 80)
print("PHASE 5.3: CREATE SUPPLIER PAYMENT ENTRIES")
print("=" * 80)

company = "EPIUSE"
posting_date = nowdate()

# Account configuration
cash_account = "Cash - E"
payable_account = "Employee Advances - E"

# Payment configurations
payments_config = [
    {
        "supplier": "TEST SUPPLIER A",
        "invoice": "ACC-PINV-2025-00001",
        "amount": 1125.0,  # Full payment
        "mode": "Cash",
        "reference": "SUPP-PAY-001"
    },
    {
        "supplier": "TEST SUPPLIER B",
        "invoice": "ACC-PINV-2025-00002",
        "amount": 800.0,  # Partial payment (800 of 1500)
        "mode": "Cheque",
        "reference": "SUPP-PAY-002"
    },
    {
        "supplier": "TEST SUPPLIER C",
        "invoice": "ACC-PINV-2025-00003",
        "amount": 1875.0,  # Full payment
        "mode": "Wire Transfer",
        "reference": "SUPP-PAY-003"
    }
]

created_payments = []
errors = []

print(f"\nCompany: {company}")
print(f"Posting Date: {posting_date}")
print(f"Cash Account: {cash_account}")
print(f"Payable Account: {payable_account}")
print(f"\nCreating {len(payments_config)} supplier payment entries...\n")

for idx, config in enumerate(payments_config, 1):
    try:
        print(f"--- Payment {idx}: {config['supplier']} ---")
        
        # Get invoice details
        invoice = frappe.get_doc("Purchase Invoice", config['invoice'])
        print(f"Invoice: {invoice.name}")
        print(f"Outstanding: {invoice.outstanding_amount}")
        print(f"Payment Amount: {config['amount']}")
        
        # Validate payment amount
        if config['amount'] > invoice.outstanding_amount:
            raise Exception(f"Payment amount {config['amount']} exceeds outstanding {invoice.outstanding_amount}")
        
        # Create Payment Entry
        payment = frappe.new_doc("Payment Entry")
        payment.payment_type = "Pay"
        payment.posting_date = posting_date
        payment.company = company
        payment.mode_of_payment = config['mode']
        
        # Party details
        payment.party_type = "Supplier"
        payment.party = config['supplier']
        
        # Account details (reversed for Pay type)
        payment.paid_from = cash_account
        payment.paid_from_account_currency = "ZAR"
        payment.paid_to = payable_account
        payment.paid_to_account_currency = "ZAR"
        
        # Amount details
        payment.paid_amount = config['amount']
        payment.received_amount = config['amount']
        payment.source_exchange_rate = 1.0
        payment.target_exchange_rate = 1.0
        
        # Reference details
        payment.reference_no = config['reference']
        payment.reference_date = posting_date
        
        # Add invoice reference
        payment.append("references", {
            "reference_doctype": "Purchase Invoice",
            "reference_name": invoice.name,
            "total_amount": invoice.grand_total,
            "outstanding_amount": invoice.outstanding_amount,
            "allocated_amount": config['amount']
        })
        
        # Insert payment entry
        payment.insert()
        frappe.db.commit()
        
        created_payments.append(payment.name)
        print(f"✓ Created: {payment.name}")
        print(f"  Mode: {config['mode']}")
        print(f"  Amount: {config['amount']} ZAR")
        print(f"  Status: Draft (docstatus={payment.docstatus})")
        
        # Verify outstanding updated
        invoice.reload()
        new_outstanding = invoice.outstanding_amount
        print(f"  New Outstanding: {new_outstanding} ZAR")
        print()
        
    except Exception as e:
        error_msg = f"Failed to create payment for {config['supplier']}: {str(e)}"
        errors.append(error_msg)
        print(f"✗ ERROR: {error_msg}\n")
        continue

# Summary
print("=" * 80)
print("SUPPLIER PAYMENTS CREATION SUMMARY")
print("=" * 80)

if created_payments:
    print(f"\n✓ Successfully created {len(created_payments)} payment entries:")
    for payment_name in created_payments:
        payment = frappe.get_doc("Payment Entry", payment_name)
        print(f"  - {payment_name}: {payment.party} - {payment.paid_amount} ZAR ({payment.mode_of_payment})")

if errors:
    print(f"\n✗ Encountered {len(errors)} errors:")
    for error in errors:
        print(f"  - {error}")

# Verify invoice outstanding amounts
print("\n=== INVOICE OUTSTANDING VERIFICATION ===")
for config in payments_config:
    try:
        invoice = frappe.get_doc("Purchase Invoice", config['invoice'])
        print(f"{invoice.name}: Outstanding = {invoice.outstanding_amount} ZAR")
    except:
        print(f"{config['invoice']}: Could not verify")

print("\n" + "=" * 80)
if len(created_payments) == len(payments_config):
    print("✅ ALL SUPPLIER PAYMENTS CREATED SUCCESSFULLY")
else:
    print(f"⚠ PARTIAL SUCCESS: {len(created_payments)}/{len(payments_config)} payments created")
print("=" * 80)

# List all created payments
print(f"\nCreated Payment Entries: {created_payments}")