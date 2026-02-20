import frappe
from frappe.utils import today, nowdate

print("=" * 80)
print("PHASE 7.1: CREATE BANK TRANSACTIONS")
print("=" * 80)

company = "EPIUSE"
bank_account = "Cash - E - Test Bank - Test Bank"  # Bank Account name
transaction_date = nowdate()

# Bank transaction configurations
transactions_config = [
    # Deposits (Receipts)
    {
        "type": "Deposit",
        "amount": 500.0,
        "description": "Customer payment received",
        "party_type": "Customer",
        "party": "TEST CUSTOMER A",
        "reference": "CUST-RCPT-001"
    },
    {
        "type": "Deposit",
        "amount": 750.0,
        "description": "Direct sales receipt",
        "party_type": None,
        "party": None,
        "reference": "SALES-RCPT-001"
    },
    {
        "type": "Deposit",
        "amount": 1000.0,
        "description": "Unallocated bank receipt for reconciliation",
        "party_type": None,
        "party": None,
        "reference": "UNALLOC-001"
    },
    # Withdrawals (Payments)
    {
        "type": "Withdrawal",
        "amount": 600.0,
        "description": "Supplier payment made",
        "party_type": "Supplier",
        "party": "TEST SUPPLIER A",
        "reference": "SUPP-PAY-001"
    },
    {
        "type": "Withdrawal",
        "amount": 350.0,
        "description": "Office expense payment",
        "party_type": None,
        "party": None,
        "reference": "EXP-PAY-001"
    }
]

created_transactions = []
errors = []

print(f"\nCompany: {company}")
print(f"Bank Account: {bank_account}")
print(f"Transaction Date: {transaction_date}")
print(f"\nCreating {len(transactions_config)} bank transactions...\n")

for idx, config in enumerate(transactions_config, 1):
    try:
        print(f"--- Transaction {idx}: {config['type']} ---")
        print(f"Amount: {config['amount']} ZAR")
        print(f"Description: {config['description']}")
        if config['party']:
            print(f"Party: {config['party_type']} - {config['party']}")
        
        # Create Bank Transaction
        bank_txn = frappe.new_doc("Bank Transaction")
        bank_txn.date = transaction_date
        bank_txn.bank_account = bank_account
        bank_txn.company = company
        bank_txn.currency = "ZAR"
        bank_txn.description = config['description']
        bank_txn.reference_number = config['reference']
        
        # Set deposit or withdrawal
        if config['type'] == "Deposit":
            bank_txn.deposit = config['amount']
            bank_txn.withdrawal = 0
        else:  # Withdrawal
            bank_txn.deposit = 0
            bank_txn.withdrawal = config['amount']
        
        # Add party reference if provided
        if config['party']:
            bank_txn.party_type = config['party_type']
            bank_txn.party = config['party']
        
        # Insert bank transaction
        bank_txn.insert()
        frappe.db.commit()
        
        created_transactions.append(bank_txn.name)
        print(f"✓ Created: {bank_txn.name}")
        print(f"  Type: {config['type']}")
        print(f"  Deposit: {bank_txn.deposit} ZAR")
        print(f"  Withdrawal: {bank_txn.withdrawal} ZAR")
        print(f"  Status: Draft (docstatus={bank_txn.docstatus})")
        print()
        
    except Exception as e:
        error_msg = f"Failed to create {config['type']} transaction: {str(e)}"
        errors.append(error_msg)
        print(f"✗ ERROR: {error_msg}\n")
        import traceback
        print(traceback.format_exc())
        continue

# Summary
print("=" * 80)
print("BANK TRANSACTIONS CREATION SUMMARY")
print("=" * 80)

if created_transactions:
    print(f"\n✓ Successfully created {len(created_transactions)} bank transactions:")
    
    total_deposits = 0
    total_withdrawals = 0
    
    for txn_name in created_transactions:
        txn = frappe.get_doc("Bank Transaction", txn_name)
        txn_type = "Deposit" if txn.deposit > 0 else "Withdrawal"
        amount = txn.deposit if txn.deposit > 0 else txn.withdrawal
        party_info = f", Party: {txn.party}" if txn.party else ""
        print(f"  - {txn_name}: {txn_type} - {amount} ZAR{party_info}")
        
        total_deposits += txn.deposit
        total_withdrawals += txn.withdrawal
    
    print(f"\nTotal Deposits: {total_deposits} ZAR")
    print(f"Total Withdrawals: {total_withdrawals} ZAR")
    print(f"Net Cash Flow: {total_deposits - total_withdrawals} ZAR")

if errors:
    print(f"\n✗ Encountered {len(errors)} errors:")
    for error in errors:
        print(f"  - {error}")

# List all bank transactions
print("\n=== ALL BANK TRANSACTIONS ===")
all_transactions = frappe.get_all("Bank Transaction",
    filters={"company": company},
    fields=["name", "date", "deposit", "withdrawal", "description", "docstatus"],
    order_by="name"
)

for txn in all_transactions:
    txn_type = "Deposit" if txn.deposit > 0 else "Withdrawal"
    amount = txn.deposit if txn.deposit > 0 else txn.withdrawal
    status = "Draft" if txn.docstatus == 0 else "Submitted" if txn.docstatus == 1 else "Cancelled"
    print(f"{txn.name}: {txn_type} - {amount} ZAR, Status={status}")

print("\n" + "=" * 80)
if len(created_transactions) == len(transactions_config):
    print("✅ ALL BANK TRANSACTIONS CREATED SUCCESSFULLY")
else:
    print(f"⚠ PARTIAL SUCCESS: {len(created_transactions)}/{len(transactions_config)} transactions created")
print("=" * 80)

# List created transactions
print(f"\nCreated Bank Transactions: {created_transactions}")