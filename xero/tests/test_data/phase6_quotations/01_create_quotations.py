import frappe
from frappe.utils import today, add_days, nowdate

print("=" * 80)
print("PHASE 6.1: CREATE QUOTATIONS")
print("=" * 80)

company = "EPIUSE"
transaction_date = nowdate()
valid_till = add_days(transaction_date, 30)
price_list = "Standard Selling"

# Quotation configurations
quotations_config = [
    {
        "customer": "TEST CUSTOMER A",
        "items": [
            {"item_code": "TEST-SALES-001", "qty": 5, "rate": 100.0}
        ],
        "description": "Standard single-item quote"
    },
    {
        "customer": "TEST CUSTOMER B",
        "items": [
            {"item_code": "TEST-SALES-002", "qty": 3, "rate": 150.0},
            {"item_code": "TEST-MULTI-001", "qty": 2, "rate": 200.0}
        ],
        "description": "Multi-item quote"
    },
    {
        "customer": "TEST CUSTOMER_FT",
        "items": [
            {"item_code": "TEST-SALES_FT", "qty": 10, "rate": 250.0}
        ],
        "description": "Large value quote"
    }
]

created_quotations = []
errors = []

print(f"\nCompany: {company}")
print(f"Transaction Date: {transaction_date}")
print(f"Valid Until: {valid_till}")
print(f"Price List: {price_list}")
print(f"\nCreating {len(quotations_config)} quotations...\n")

for idx, config in enumerate(quotations_config, 1):
    try:
        print(f"--- Quotation {idx}: {config['customer']} ---")
        print(f"Description: {config['description']}")
        print(f"Items: {len(config['items'])}")
        
        # Create Quotation
        quotation = frappe.new_doc("Quotation")
        quotation.quotation_to = "Customer"
        quotation.party_name = config['customer']
        quotation.transaction_date = transaction_date
        quotation.valid_till = valid_till
        quotation.company = company
        quotation.currency = "ZAR"
        quotation.selling_price_list = price_list
        
        # Add line items
        total_amount = 0
        for item in config['items']:
            amount = item['qty'] * item['rate']
            total_amount += amount
            
            quotation.append("items", {
                "item_code": item['item_code'],
                "qty": item['qty'],
                "rate": item['rate'],
                "amount": amount
            })
            print(f"  - {item['item_code']}: Qty={item['qty']}, Rate={item['rate']}, Amount={amount}")
        
        # Insert quotation
        quotation.insert()
        frappe.db.commit()
        
        created_quotations.append(quotation.name)
        print(f"✓ Created: {quotation.name}")
        print(f"  Total Amount: {quotation.grand_total} ZAR")
        print(f"  Status: Draft (docstatus={quotation.docstatus})")
        print(f"  Valid Until: {quotation.valid_till}")
        print()
        
    except Exception as e:
        error_msg = f"Failed to create quotation for {config['customer']}: {str(e)}"
        errors.append(error_msg)
        print(f"✗ ERROR: {error_msg}\n")
        import traceback
        print(traceback.format_exc())
        continue

# Summary
print("=" * 80)
print("QUOTATIONS CREATION SUMMARY")
print("=" * 80)

if created_quotations:
    print(f"\n✓ Successfully created {len(created_quotations)} quotations:")
    total_value = 0
    for quot_name in created_quotations:
        quot = frappe.get_doc("Quotation", quot_name)
        print(f"  - {quot_name}: {quot.party_name} - {quot.grand_total} ZAR ({len(quot.items)} items)")
        total_value += quot.grand_total
    
    print(f"\nTotal Quotation Value: {total_value} ZAR")

if errors:
    print(f"\n✗ Encountered {len(errors)} errors:")
    for error in errors:
        print(f"  - {error}")

# List all quotations
print("\n=== ALL QUOTATIONS ===")
all_quotations = frappe.get_all("Quotation",
    filters={"company": company},
    fields=["name", "party_name", "grand_total", "transaction_date", "valid_till", "docstatus"],
    order_by="name"
)

for quot in all_quotations:
    status = "Draft" if quot.docstatus == 0 else "Submitted" if quot.docstatus == 1 else "Cancelled"
    print(f"{quot.name}: {quot.party_name}, Total={quot.grand_total}, Status={status}")

print("\n" + "=" * 80)
if len(created_quotations) == len(quotations_config):
    print("✅ ALL QUOTATIONS CREATED SUCCESSFULLY")
else:
    print(f"⚠ PARTIAL SUCCESS: {len(created_quotations)}/{len(quotations_config)} quotations created")
print("=" * 80)

# List created quotations
print(f"\nCreated Quotations: {created_quotations}")