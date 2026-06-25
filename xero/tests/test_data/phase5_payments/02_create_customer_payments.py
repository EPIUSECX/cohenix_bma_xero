import frappe
from frappe.utils import today, nowdate

print("=" * 80)
print("PHASE 5.2: CREATE CUSTOMER PAYMENT ENTRIES")
print("=" * 80)

company = "EPIUSE"
posting_date = nowdate()

# Account configuration
cash_account = "Cash - E"
receivable_account = "Debtors - E"

# Payment configurations
payments_config = [
    {
        "customer": "TEST CUSTOMER A",
        "invoice": "ACC-SINV-2025-00001",
        "amount": 500.0,  # Full payment
        "mode": "Cash",
        "reference": "CUST-PAY-001"
    },
    {
        "customer": "TEST CUSTOMER B",
        "invoice": "ACC-SINV-2025-00002",
        "amount": 400.0,  # Partial payment (400 of 700)
        "mode": "Cheque",
        "reference": "CUST-PAY-002"
    },
    {
        "customer": "TEST CUSTOMER C",
        "invoice": "ACC-SINV-2025-00003",
        "amount": 1000.0,  # Full payment
        "mode": "Wire Transfer",
        "reference": "CUST-PAY-003"
    }
]

created_payments = []
errors = []

print(f"\nCompany: {company}")
print(f"Posting Date: {posting_date}")
print(f"Cash Account: {cash_account}")
print(f"Receivable Account: {receivable_account}")
print(f"\nCreating {len(payments_config)} customer payment entries...\n")

for idx, config in enumerate(payments_config, 1):
    try:
        print(f"--- Payment {idx}: {config['customer']} ---")
        
        # Get invoice details
        invoice = frappe.get_doc("Sales Invoice", config['invoice'])
        print(f"Invoice: {invoice.name}")
        print(f"Outstanding: {invoice.outstanding_amount}")
        print(f"Payment Amount: {config['amount']}")
        
        # Validate payment amount
        if config['amount'] > invoice.outstanding_amount:
            raise Exception(f"Payment amount {config['amount']} exceeds outstanding {invoice.outstanding_amount}")
        
        # Create Payment Entry
        payment = frappe.new_doc("Payment Entry")
        payment.payment_type = "Receive"
        payment.posting_date = posting_date
        payment.company = company
        payment.mode_of_payment = config['mode']
        
        # Party details
        payment.party_type = "Customer"
        payment.party = config['customer']
        
        # Account details
        payment.paid_from = receivable_account
        payment.paid_from_account_currency = "ZAR"
        payment.paid_to = cash_account
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
            "reference_doctype": "Sales Invoice",
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
        error_msg = f"Failed to create payment for {config['customer']}: {str(e)}"
        errors.append(error_msg)
        print(f"✗ ERROR: {error_msg}\n")
        continue

# Summary
print("=" * 80)
print("CUSTOMER PAYMENTS CREATION SUMMARY")
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
        invoice = frappe.get_doc("Sales Invoice", config['invoice'])
        print(f"{invoice.name}: Outstanding = {invoice.outstanding_amount} ZAR")
    except:
        print(f"{config['invoice']}: Could not verify")

print("\n" + "=" * 80)
if len(created_payments) == len(payments_config):
    print("✅ ALL CUSTOMER PAYMENTS CREATED SUCCESSFULLY")
else:
    print(f"⚠ PARTIAL SUCCESS: {len(created_payments)}/{len(payments_config)} payments created")
print("=" * 80)

# List all created payments
print(f"\nCreated Payment Entries: {created_payments}")