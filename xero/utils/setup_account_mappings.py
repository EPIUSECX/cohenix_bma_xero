"""
Setup Account Mappings: Fetch Xero accounts, populate cache, create mappings.
Run: bench --site cohenix.localhost execute xero.utils.setup_account_mappings.run
"""
import frappe
from xero.utils.xero_client import xero_request

def run():
    print("=" * 80)
    print("SETUP ACCOUNT MAPPINGS")
    print("=" * 80)

    # Step 1: Fetch Xero accounts and populate cache
    print("\nStep 1: Fetching Xero accounts...")
    response = xero_request("GET", "Accounts")
    if not response or not response.get("Accounts"):
        print("❌ Failed to fetch Xero accounts")
        return

    xero_accounts = response["Accounts"]
    print(f"  Fetched {len(xero_accounts)} Xero accounts")

    # Step 2: Populate Xero Account cache
    print("\nStep 2: Populating Xero Account cache...")
    created = 0
    for acc in xero_accounts:
        if acc.get("SystemAccount") in ["DEBTORS", "CREDITORS", "BANKCURRENCYGAIN"]:
            continue
        if acc.get("Status") != "ACTIVE":
            continue

        account_id = acc.get("AccountID")
        account_code = acc.get("Code")
        account_name = acc.get("Name")

        if not account_id or not account_code:
            continue

        # Check if already exists
        existing = frappe.db.exists("Xero Account", {"account_id": account_id})
        if existing:
            continue

        try:
            xa = frappe.new_doc("Xero Account")
            xa.account_code = account_code
            xa.account_name = account_name
            xa.account_id = account_id
            xa.account_type = acc.get("Type")
            xa.status = acc.get("Status", "ACTIVE")
            xa.currency_code = acc.get("CurrencyCode")
            xa.enable_payments = 1 if acc.get("EnablePaymentsToAccount") else 0
            xa.tax_type = acc.get("TaxType")
            xa.insert(ignore_permissions=True)
            created += 1
        except Exception as e:
            print(f"  ⚠️ Could not create Xero Account {account_code}: {e}")

    frappe.db.commit()
    print(f"  Created {created} Xero Account cache records")

    # Step 3: Create account mappings
    print("\nStep 3: Creating account mappings...")
    settings = frappe.get_single("Xero Settings")

    # Get all ERPNext accounts with xero_account_id
    erpnext_accounts = frappe.db.sql("""
        SELECT a.name as erpnext_account, a.xero_account_id
        FROM tabAccount a
        WHERE a.xero_account_id IS NOT NULL AND a.xero_account_id != ''
        AND a.is_group = 0
    """, as_dict=True)

    existing_mappings = {m.erpnext_account for m in settings.account_mapping}
    added = 0

    for acc in erpnext_accounts:
        if acc.erpnext_account in existing_mappings:
            continue

        # Find matching Xero Account by account_id
        xero_account_name = frappe.db.get_value("Xero Account",
            {"account_id": acc.xero_account_id}, "name")

        if xero_account_name:
            settings.append("account_mapping", {
                "erpnext_account": acc.erpnext_account,
                "xero_account": xero_account_name,
            })
            added += 1

    if added > 0:
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"  ✅ Added {added} account mappings")
    else:
        print("  ℹ️ No new mappings to add")

    # Summary
    settings.reload()
    print(f"\n{'=' * 80}")
    print(f"SUMMARY")
    print(f"{'=' * 80}")
    print(f"Xero Account cache: {frappe.db.count('Xero Account')} records")
    print(f"Account mappings: {len(settings.account_mapping)}")
    print(f"\nSample mappings:")
    for m in settings.account_mapping[:5]:
        print(f"  {m.erpnext_account} → {m.xero_account_code} ({m.xero_account_name})")
