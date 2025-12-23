import frappe
from frappe.utils import today

print("=" * 80)
print("PHASE 5.1: VERIFY PAYMENT ENTRY PREREQUISITES")
print("=" * 80)

# Get company
company = "EPIUSE"
print(f"\n✓ Company: {company}")

# Check submitted Sales Invoices
print("\n=== SUBMITTED SALES INVOICES ===")
sales_invoices = frappe.get_all("Sales Invoice", 
    filters={"docstatus": 1, "company": company},
    fields=["name", "customer", "grand_total", "outstanding_amount", "posting_date"],
    order_by="name"
)

if not sales_invoices:
    print("✗ ERROR: No submitted sales invoices found!")
else:
    print(f"✓ Found {len(sales_invoices)} submitted sales invoices:")
    for si in sales_invoices:
        print(f"  - {si.name}: Customer={si.customer}, Total={si.grand_total}, Outstanding={si.outstanding_amount}")

# Check submitted Purchase Invoices
print("\n=== SUBMITTED PURCHASE INVOICES ===")
purchase_invoices = frappe.get_all("Purchase Invoice",
    filters={"docstatus": 1, "company": company},
    fields=["name", "supplier", "grand_total", "outstanding_amount", "posting_date"],
    order_by="name"
)

if not purchase_invoices:
    print("✗ ERROR: No submitted purchase invoices found!")
else:
    print(f"✓ Found {len(purchase_invoices)} submitted purchase invoices:")
    for pi in purchase_invoices:
        print(f"  - {pi.name}: Supplier={pi.supplier}, Total={pi.grand_total}, Outstanding={pi.outstanding_amount}")

# Check Bank/Cash accounts
print("\n=== BANK/CASH ACCOUNTS ===")
bank_cash_accounts = frappe.get_all("Account",
    filters={
        "account_type": ["in", ["Bank", "Cash"]], 
        "is_group": 0, 
        "company": company,
        "disabled": 0
    },
    fields=["name", "account_type", "account_currency"],
    order_by="name"
)

if not bank_cash_accounts:
    print("✗ ERROR: No bank/cash accounts found!")
else:
    print(f"✓ Found {len(bank_cash_accounts)} bank/cash accounts:")
    for acc in bank_cash_accounts:
        print(f"  - {acc.name} ({acc.account_type}, Currency: {acc.account_currency})")

# Check Receivable account (for customer payments)
print("\n=== RECEIVABLE ACCOUNTS ===")
receivable_accounts = frappe.get_all("Account",
    filters={
        "account_type": "Receivable",
        "is_group": 0,
        "company": company,
        "disabled": 0
    },
    fields=["name", "account_currency"],
    order_by="name"
)

if not receivable_accounts:
    print("✗ ERROR: No receivable accounts found!")
else:
    print(f"✓ Found {len(receivable_accounts)} receivable accounts:")
    for acc in receivable_accounts:
        print(f"  - {acc.name} (Currency: {acc.account_currency})")

# Check Payable account (for supplier payments)
print("\n=== PAYABLE ACCOUNTS ===")
payable_accounts = frappe.get_all("Account",
    filters={
        "account_type": "Payable",
        "is_group": 0,
        "company": company,
        "disabled": 0
    },
    fields=["name", "account_currency"],
    order_by="name"
)

if not payable_accounts:
    print("✗ ERROR: No payable accounts found!")
else:
    print(f"✓ Found {len(payable_accounts)} payable accounts:")
    for acc in payable_accounts:
        print(f"  - {acc.name} (Currency: {acc.account_currency})")

# Check Modes of Payment
print("\n=== MODES OF PAYMENT ===")
modes_of_payment = frappe.get_all("Mode of Payment", 
    filters={"enabled": 1},
    fields=["name"],
    order_by="name"
)

if not modes_of_payment:
    print("✗ ERROR: No enabled modes of payment found!")
else:
    print(f"✓ Found {len(modes_of_payment)} enabled modes of payment:")
    for mode in modes_of_payment:
        print(f"  - {mode.name}")

# Check customers with outstanding invoices
print("\n=== CUSTOMERS WITH OUTSTANDING INVOICES ===")
customers_with_outstanding = frappe.db.sql("""
    SELECT DISTINCT customer, SUM(outstanding_amount) as total_outstanding
    FROM `tabSales Invoice`
    WHERE docstatus = 1 
    AND outstanding_amount > 0
    AND company = %s
    GROUP BY customer
    ORDER BY customer
""", (company,), as_dict=True)

if customers_with_outstanding:
    print(f"✓ Found {len(customers_with_outstanding)} customers with outstanding invoices:")
    for cust in customers_with_outstanding:
        print(f"  - {cust.customer}: Outstanding={cust.total_outstanding}")
else:
    print("⚠ No customers with outstanding invoices")

# Check suppliers with outstanding invoices
print("\n=== SUPPLIERS WITH OUTSTANDING INVOICES ===")
suppliers_with_outstanding = frappe.db.sql("""
    SELECT DISTINCT supplier, SUM(outstanding_amount) as total_outstanding
    FROM `tabPurchase Invoice`
    WHERE docstatus = 1 
    AND outstanding_amount > 0
    AND company = %s
    GROUP BY supplier
    ORDER BY supplier
""", (company,), as_dict=True)

if suppliers_with_outstanding:
    print(f"✓ Found {len(suppliers_with_outstanding)} suppliers with outstanding invoices:")
    for supp in suppliers_with_outstanding:
        print(f"  - {supp.supplier}: Outstanding={supp.total_outstanding}")
else:
    print("⚠ No suppliers with outstanding invoices")

# Summary
print("\n" + "=" * 80)
print("PREREQUISITE VERIFICATION SUMMARY")
print("=" * 80)

all_checks_passed = True

if len(sales_invoices) >= 3:
    print("✓ Sales Invoices: PASS (3+ submitted invoices available)")
else:
    print(f"✗ Sales Invoices: FAIL (Need 3+, found {len(sales_invoices)})")
    all_checks_passed = False

if len(purchase_invoices) >= 3:
    print("✓ Purchase Invoices: PASS (3+ submitted invoices available)")
else:
    print(f"✗ Purchase Invoices: FAIL (Need 3+, found {len(purchase_invoices)})")
    all_checks_passed = False

if len(bank_cash_accounts) >= 1:
    print("✓ Bank/Cash Accounts: PASS (1+ accounts available)")
else:
    print("✗ Bank/Cash Accounts: FAIL (Need 1+, found 0)")
    all_checks_passed = False

if len(receivable_accounts) >= 1:
    print("✓ Receivable Accounts: PASS (1+ accounts available)")
else:
    print("✗ Receivable Accounts: FAIL (Need 1+, found 0)")
    all_checks_passed = False

if len(payable_accounts) >= 1:
    print("✓ Payable Accounts: PASS (1+ accounts available)")
else:
    print("✗ Payable Accounts: FAIL (Need 1+, found 0)")
    all_checks_passed = False

if len(modes_of_payment) >= 3:
    print("✓ Modes of Payment: PASS (3+ modes available)")
else:
    print(f"⚠ Modes of Payment: WARNING (Need 3+, found {len(modes_of_payment)})")

print("\n" + "=" * 80)
if all_checks_passed:
    print("✅ ALL PREREQUISITES VERIFIED - READY TO CREATE PAYMENT ENTRIES")
else:
    print("❌ SOME PREREQUISITES MISSING - REVIEW ERRORS ABOVE")
print("=" * 80)