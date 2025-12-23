import frappe
from frappe.utils import today, add_days, nowdate

print("=" * 80)
print("PHASE 9.2: CREATE PROJECTS")
print("=" * 80)

company = "EPIUSE"

# Project configurations
projects_config = [
    {
        "name": "TEST CUSTOMER A - Implementation",
        "customer": "TEST CUSTOMER A",
        "project_type": "External",
        "status": "Open",
        "expected_start_date": nowdate(),
        "expected_end_date": add_days(nowdate(), 90)
    },
    {
        "name": "TEST CUSTOMER B - Consulting",
        "customer": "TEST CUSTOMER B",
        "project_type": "External",
        "status": "Open",
        "expected_start_date": nowdate(),
        "expected_end_date": add_days(nowdate(), 60)
    }
]

created_projects = []
errors = []

print(f"\nCompany: {company}")
print(f"\nCreating {len(projects_config)} projects...\n")

for idx, config in enumerate(projects_config, 1):
    try:
        print(f"--- Project {idx}: {config['name']} ---")
        print(f"Customer: {config['customer']}")
        print(f"Type: {config['project_type']}")
        print(f"Status: {config['status']}")
        
        # Check if project already exists
        if frappe.db.exists("Project", config['name']):
            print(f"⚠ Project already exists: {config['name']}")
            print(f"  Deleting existing project...")
            frappe.delete_doc("Project", config['name'], force=True)
            frappe.db.commit()
        
        # Create Project
        project = frappe.new_doc("Project")
        project.project_name = config['name']
        project.customer = config['customer']
        project.company = company
        project.status = config['status']
        project.project_type = config['project_type']
        project.expected_start_date = config['expected_start_date']
        project.expected_end_date = config['expected_end_date']
        
        # Insert project
        project.insert()
        frappe.db.commit()
        
        created_projects.append(project.name)
        print(f"✓ Created: {project.name}")
        print(f"  Customer: {project.customer}")
        print(f"  Type: {project.project_type}")
        print(f"  Status: {project.status}")
        print(f"  Duration: {config['expected_start_date']} to {config['expected_end_date']}")
        print()
        
    except Exception as e:
        error_msg = f"Failed to create project {config['name']}: {str(e)}"
        errors.append(error_msg)
        print(f"✗ ERROR: {error_msg}\n")
        import traceback
        print(traceback.format_exc())
        continue

# Summary
print("=" * 80)
print("PROJECTS CREATION SUMMARY")
print("=" * 80)

if created_projects:
    print(f"\n✓ Successfully created {len(created_projects)} projects:")
    for proj_name in created_projects:
        proj = frappe.get_doc("Project", proj_name)
        print(f"  - {proj_name}: Customer={proj.customer}, Type={proj.project_type}, Status={proj.status}")

if errors:
    print(f"\n✗ Encountered {len(errors)} errors:")
    for error in errors:
        print(f"  - {error}")

# List all projects for the company
print("\n=== ALL PROJECTS FOR COMPANY ===")
all_projects = frappe.get_all("Project",
    filters={"company": company},
    fields=["name", "customer", "project_type", "status"],
    order_by="name"
)

for proj in all_projects:
    print(f"{proj.name}: Customer={proj.customer}, Type={proj.project_type}, Status={proj.status}")

print("\n" + "=" * 80)
if len(created_projects) == len(projects_config):
    print("✅ ALL PROJECTS CREATED SUCCESSFULLY")
else:
    print(f"⚠ PARTIAL SUCCESS: {len(created_projects)}/{len(projects_config)} projects created")
print("=" * 80)

# List created projects
print(f"\nCreated Projects: {created_projects}")