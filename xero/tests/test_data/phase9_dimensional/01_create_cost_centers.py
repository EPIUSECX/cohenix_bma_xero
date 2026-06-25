import frappe

print("=" * 80)
print("PHASE 9.1: CREATE COST CENTERS")
print("=" * 80)

company = "EPIUSE"
parent_cost_center = "EPIUSE - E"  # Group cost center (root)

# Cost center configurations
cost_centers_config = [
    {
        "name": "Sales",
        "description": "Sales Department"
    },
    {
        "name": "Operations",
        "description": "Operations Department"
    },
    {
        "name": "Administration",
        "description": "Administration Department"
    }
]

created_cost_centers = []
errors = []

print(f"\nCompany: {company}")
print(f"Parent Cost Center: {parent_cost_center}")
print(f"\nCreating {len(cost_centers_config)} cost centers...\n")

# Verify parent cost center exists
if not frappe.db.exists("Cost Center", parent_cost_center):
    print(f"✗ ERROR: Parent cost center '{parent_cost_center}' does not exist!")
    print("Cannot proceed without root cost center.")
else:
    print(f"✓ Parent cost center verified: {parent_cost_center}\n")
    
    for idx, config in enumerate(cost_centers_config, 1):
        try:
            cost_center_name = f"{config['name']} - E"
            
            print(f"--- Cost Center {idx}: {cost_center_name} ---")
            print(f"Description: {config['description']}")
            
            # Check if cost center already exists
            if frappe.db.exists("Cost Center", cost_center_name):
                print(f"⚠ Cost center already exists: {cost_center_name}")
                print(f"  Deleting existing cost center...")
                frappe.delete_doc("Cost Center", cost_center_name, force=True)
                frappe.db.commit()
            
            # Create Cost Center
            cost_center = frappe.new_doc("Cost Center")
            cost_center.cost_center_name = config['name']
            cost_center.parent_cost_center = parent_cost_center
            cost_center.company = company
            cost_center.is_group = 0  # Leaf node (not a group)
            
            # Insert cost center
            cost_center.insert()
            frappe.db.commit()
            
            created_cost_centers.append(cost_center.name)
            print(f"✓ Created: {cost_center.name}")
            print(f"  Parent: {cost_center.parent_cost_center}")
            print(f"  Company: {cost_center.company}")
            print(f"  Is Group: {cost_center.is_group}")
            print()
            
        except Exception as e:
            error_msg = f"Failed to create cost center {config['name']}: {str(e)}"
            errors.append(error_msg)
            print(f"✗ ERROR: {error_msg}\n")
            import traceback
            print(traceback.format_exc())
            continue

# Summary
print("=" * 80)
print("COST CENTERS CREATION SUMMARY")
print("=" * 80)

if created_cost_centers:
    print(f"\n✓ Successfully created {len(created_cost_centers)} cost centers:")
    for cc_name in created_cost_centers:
        cc = frappe.get_doc("Cost Center", cc_name)
        print(f"  - {cc_name}: Parent={cc.parent_cost_center}, Company={cc.company}")

if errors:
    print(f"\n✗ Encountered {len(errors)} errors:")
    for error in errors:
        print(f"  - {error}")

# List all cost centers for the company
print("\n=== ALL COST CENTERS FOR COMPANY ===")
all_cost_centers = frappe.get_all("Cost Center",
    filters={"company": company, "is_group": 0},
    fields=["name", "parent_cost_center", "company"],
    order_by="name"
)

for cc in all_cost_centers:
    print(f"{cc.name}: Parent={cc.parent_cost_center}")

print("\n" + "=" * 80)
if len(created_cost_centers) == len(cost_centers_config):
    print("✅ ALL COST CENTERS CREATED SUCCESSFULLY")
else:
    print(f"⚠ PARTIAL SUCCESS: {len(created_cost_centers)}/{len(cost_centers_config)} cost centers created")
print("=" * 80)

# List created cost centers
print(f"\nCreated Cost Centers: {created_cost_centers}")