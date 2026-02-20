import frappe
from frappe.utils import today, nowdate

print("=" * 80)
print("PHASE 5.4: CREATE ADVANCE PAYMENT ENTRY")
print("=" * 80)

company = "EPIUSE"
posting_date = nowdate()

# Account configuration
cash_account = "Cash - E"
receivable_account = "Debtors - E"

# Advance payment configuration (no invoice reference)
advance_config = {
    "customer": "TEST CUSTOMER_FT",
    "amount": 500.0,
    "mode": "Cash",
    "reference": "ADV-PAY-001",
    "remarks": "Advance payment for future orders"
}

print(f"\nCompany: {company}")
print(f"Posting Date: {posting_date}")
print(f"Cash Account: {cash_account}")
print(f"Receivable Account: {receivable_account}")
print(f"\nCreating advance payment entry (no invoice reference)...\n")

try:
    print(f"--- Advance Payment: {advance_config['customer']} ---")
    print(f"Amount: {advance_config['amount']} ZAR")
    print(f"Mode: {advance_config['mode']}")
    print(f"Purpose: {advance_config['remarks']}")
    
    # Create Payment Entry
    payment = frappe.new_doc("Payment Entry")
    payment.payment_type = "Receive"
    payment.posting_date = posting_date
    payment.company = company
    payment.mode_of_payment = advance_config['mode']
    
    # Party details
    payment.party_type = "Customer"
    payment.party = advance_config['customer']
    
    # Account details
    payment.paid_from = receivable_account
    payment.paid_from_account_currency = "ZAR"
    payment.paid_to = cash_account
    payment.paid_to_account_currency = "ZAR"
    
    # Amount details
    payment.paid_amount = advance_config['amount']
    payment.received_amount = advance_config['amount']
    payment.source_exchange_rate = 1.0
    payment.target_exchange_rate = 1.0
    
    # Reference details
    payment.reference_no = advance_config['reference']
    payment.reference_date = posting_date
    payment.remarks = advance_config['remarks']
    
    # NOTE: No invoice references for advance payment
    # The references table is left empty
    
    # Insert payment entry
    payment.insert()
    frappe.db.commit()
    
    print(f"\n✓ Created: {payment.name}")
    print(f"  Type: Advance Payment (no invoice reference)")
    print(f"  Customer: {advance_config['customer']}")
    print(f"  Amount: {advance_config['amount']} ZAR")
    print(f"  Mode: {advance_config['mode']}")
    print(f"  Status: Draft (docstatus={payment.docstatus})")
    print(f"  References: None (advance payment)")
    
    # Summary
    print("\n" + "=" * 80)
    print("ADVANCE PAYMENT CREATION SUMMARY")
    print("=" * 80)
    print(f"\n✓ Successfully created advance payment entry:")
    print(f"  - {payment.name}: {payment.party} - {payment.paid_amount} ZAR ({payment.mode_of_payment})")
    print(f"  - Type: Advance (no invoice allocation)")
    print(f"  - Can be allocated to future invoices")
    
    print("\n" + "=" * 80)
    print("✅ ADVANCE PAYMENT CREATED SUCCESSFULLY")
    print("=" * 80)
    
    print(f"\nCreated Payment Entry: {payment.name}")
    
except Exception as e:
    print(f"\n✗ ERROR: Failed to create advance payment: {str(e)}")
    import traceback
    print(traceback.format_exc())
    print("\n" + "=" * 80)
    print("❌ ADVANCE PAYMENT CREATION FAILED")
    print("=" * 80)