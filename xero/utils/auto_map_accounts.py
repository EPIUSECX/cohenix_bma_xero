"""
Auto-map ERPNext accounts to Xero accounts based on xero_account_id.
Run: bench --site cohenix.localhost execute xero.utils.auto_map_accounts.run
"""
import frappe

def run():
    print("=" * 80)
    print("AUTO-MAPPING ACCOUNTS: ERPNext ↔ Xero")
    print("=" * 80)

    settings = frappe.get_single("Xero Settings")

    # Get all ERPNext accounts that have a xero_account_id
    erpnext_accounts = frappe.db.sql("""
        SELECT a.name as erpnext_account, a.xero_account_id, xa.name as xero_account_name
        FROM tabAccount a
        LEFT JOIN `tabXero Account` xa ON xa.account_id = a.xero_account_id
        WHERE a.xero_account_id IS NOT NULL AND a.xero_account_id != ''
        AND a.is_group = 0
    """, as_dict=True)

    print(f"Found {len(erpnext_accounts)} ERPNext accounts with Xero IDs")

    # Get existing mappings
    existing_mappings = {m.erpnext_account: m for m in settings.account_mapping}
    print(f"Existing mappings: {len(existing_mappings)}")

    added = 0
    for acc in erpnext_accounts:
        if acc.erpnext_account in existing_mappings:
            continue

        if acc.xero_account_name:
            settings.append("account_mapping", {
                "erpnext_account": acc.erpnext_account,
                "xero_account": acc.xero_account_name,
            })
            added += 1

    if added > 0:
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"✅ Added {added} new account mappings")
    else:
        print("ℹ️ No new mappings to add")

    # Show total
    settings.reload()
    print(f"Total account mappings: {len(settings.account_mapping)}")

    # Show a sample
    for m in settings.account_mapping[:5]:
        print(f"  {m.erpnext_account} → {m.xero_account_code} ({m.xero_account_name})")
