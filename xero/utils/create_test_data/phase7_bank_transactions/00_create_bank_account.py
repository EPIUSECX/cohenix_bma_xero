import frappe

print("=" * 80)
print("PHASE 7.0: CREATE BANK AND BANK ACCOUNT")
print("=" * 80)

company = "EPIUSE"
account_name = "Cash - E"

print(f"\nCompany: {company}")
print(f"Account: {account_name}")
print("\nCreating Bank and Bank Account for Bank Transaction testing...\n")

try:
    # Step 1: Create Bank
    bank_name = "Test Bank"
    
    print(f"--- Step 1: Create Bank ---")
    if frappe.db.exists("Bank", bank_name):
        print(f"⚠ Bank already exists: {bank_name}")
    else:
        bank = frappe.new_doc("Bank")
        bank.bank_name = bank_name
        bank.insert()
        frappe.db.commit()
        print(f"✓ Created Bank: {bank_name}")
    
    # Step 2: Create Bank Account
    bank_account_name = f"{account_name} - {bank_name}"
    
    print(f"\n--- Step 2: Create Bank Account ---")
    if frappe.db.exists("Bank Account", bank_account_name):
        print(f"⚠ Bank Account already exists: {bank_account_name}")
        print(f"  Deleting existing bank account...")
        frappe.delete_doc("Bank Account", bank_account_name, force=True)
        frappe.db.commit()
    
    bank_account = frappe.new_doc("Bank Account")
    bank_account.account_name = bank_account_name
    bank_account.account = account_name
    bank_account.bank = bank_name
    bank_account.company = company
    bank_account.is_default = 1
    bank_account.insert()
    frappe.db.commit()
    
    print(f"✓ Created Bank Account: {bank_account.name}")
    print(f"  Account: {bank_account.account}")
    print(f"  Bank: {bank_account.bank}")
    print(f"  Company: {bank_account.company}")
    print(f"  Is Default: {bank_account.is_default}")
    
    # Verify creation
    print("\n--- Verification ---")
    ba = frappe.get_doc("Bank Account", bank_account.name)
    print(f"✓ Bank Account verified: {ba.name}")
    print(f"  Can be used for Bank Transactions: YES")
    
    print("\n" + "=" * 80)
    print("✅ BANK AND BANK ACCOUNT CREATED SUCCESSFULLY")
    print("=" * 80)
    print(f"\nBank Account Name: {bank_account.name}")
    print("Ready for Bank Transaction creation!")
    
except Exception as e:
    print(f"\n✗ ERROR: {str(e)}")
    import traceback
    print(traceback.format_exc())
    print("\n" + "=" * 80)
    print("❌ BANK ACCOUNT CREATION FAILED")
    print("=" * 80)