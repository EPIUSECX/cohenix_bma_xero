# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff

# --- Tracking Categories Sync (Xero to ERPNext) ---

def sync_tracking_categories_from_xero():
    """
    Fetches tracking categories from Xero and creates/updates corresponding
    Cost Centers and Projects in ERPNext.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping tracking categories inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_tracking_categories"): return

    try:
        frappe.logger().info("Starting Tracking Categories sync from Xero", "Xero Sync")
        response = xero_request("GET", "TrackingCategories")

        if not response or not response.get("TrackingCategories"):
            log_xero_error(message="No tracking categories found or error fetching from Xero.", status="Warning")
            return

        tracking_categories = response["TrackingCategories"]
        processed_count = 0
        
        for category in tracking_categories:
            try:
                if category.get("Status") == "ACTIVE":
                    process_xero_tracking_category(category)
                    processed_count += 1
            except Exception as e:
                log_xero_error(
                    message=f"Failed to process Xero Tracking Category ID {category.get('TrackingCategoryID')}",
                    xero_entity_id=category.get('TrackingCategoryID'),
                    xero_entity_type="TrackingCategory",
                    error_details=frappe.get_traceback()
                )

        log_xero_error(message=f"Finished syncing Tracking Categories from Xero. Processed {processed_count} categories.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_tracking_categories_from_xero",
            error_details=frappe.get_traceback()
        )


def process_xero_tracking_category(xero_category_data):
    """Creates or updates ERPNext Cost Centers/Projects from Xero tracking category data."""
    xero_category_id = xero_category_data.get("TrackingCategoryID")
    category_name = xero_category_data.get("Name")
    
    if not xero_category_id or not category_name:
        log_xero_error(message=f"Skipping Xero tracking category due to missing ID or Name: {xero_category_data}", status="Info")
        return

    # Determine if this should be a Cost Center or Project based on name
    # This is a business logic decision - you may want to customize this
    is_project_category = any(keyword in category_name.lower() for keyword in ['project', 'job', 'client', 'contract'])
    
    if is_project_category:
        sync_as_projects(xero_category_data)
    else:
        sync_as_cost_centers(xero_category_data)


def sync_as_cost_centers(xero_category_data):
    """Sync Xero tracking category as Cost Centers."""
    xero_category_id = xero_category_data.get("TrackingCategoryID")
    category_name = xero_category_data.get("Name")
    
    # Get default company
    company = frappe.defaults.get_user_default("company")
    if not company:
        company = frappe.get_all("Company", limit=1)[0].name
    
    try:
        # Create parent Cost Center for this tracking category if it doesn't exist
        parent_cost_center_name = f"{category_name} - {frappe.get_cached_value('Company', company, 'abbr')}"
        
        if not frappe.db.exists("Cost Center", parent_cost_center_name):
            parent_cc = frappe.new_doc("Cost Center")
            parent_cc.cost_center_name = category_name
            parent_cc.company = company
            parent_cc.is_group = 1
            parent_cc.parent_cost_center = f"{company} - {frappe.get_cached_value('Company', company, 'abbr')}"
            parent_cc.xero_tracking_category_id = xero_category_id
            parent_cc.insert(ignore_permissions=True)
            frappe.db.commit()
            
            log_xero_error(
                message=f"Created parent Cost Center {parent_cc.name} for Xero Tracking Category {category_name}",
                status="Success",
                erpnext_doc_type="Cost Center",
                erpnext_doc_name=parent_cc.name,
                xero_entity_id=xero_category_id,
                xero_entity_type="TrackingCategory",
                direction="Xero to ERPNext"
            )
        
        # Process tracking options as child cost centers
        if xero_category_data.get("Options"):
            for option in xero_category_data["Options"]:
                if option.get("Status") == "ACTIVE":
                    create_cost_center_from_option(option, parent_cost_center_name, company, xero_category_id)
                    
    except Exception as e:
        log_xero_error(
            message=f"Failed to sync Xero Tracking Category {category_name} as Cost Centers",
            xero_entity_id=xero_category_id,
            xero_entity_type="TrackingCategory",
            error_details=frappe.get_traceback()
        )


def create_cost_center_from_option(option_data, parent_cost_center, company, xero_category_id):
    """Create individual Cost Center from tracking option."""
    option_id = option_data.get("TrackingOptionID")
    option_name = option_data.get("Name")
    
    if not option_id or not option_name:
        return
    
    try:
        cost_center_name = f"{option_name} - {frappe.get_cached_value('Company', company, 'abbr')}"
        
        # Check if Cost Center already exists
        if frappe.db.exists("Cost Center", cost_center_name):
            return
        
        cc = frappe.new_doc("Cost Center")
        cc.cost_center_name = option_name
        cc.company = company
        cc.is_group = 0
        cc.parent_cost_center = parent_cost_center
        cc.xero_tracking_option_id = option_id
        cc.xero_tracking_category_id = xero_category_id
        cc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        log_xero_error(
            message=f"Created Cost Center {cc.name} from Xero Tracking Option {option_name}",
            status="Success",
            erpnext_doc_type="Cost Center",
            erpnext_doc_name=cc.name,
            xero_entity_id=option_id,
            xero_entity_type="TrackingOption",
            direction="Xero to ERPNext"
        )
        
    except Exception as e:
        log_xero_error(
            message=f"Failed to create Cost Center from Xero Tracking Option {option_name}",
            xero_entity_id=option_id,
            xero_entity_type="TrackingOption",
            error_details=frappe.get_traceback()
        )


def sync_as_projects(xero_category_data):
    """Sync Xero tracking category as Projects."""
    xero_category_id = xero_category_data.get("TrackingCategoryID")
    category_name = xero_category_data.get("Name")
    
    try:
        # Process tracking options as individual projects
        if xero_category_data.get("Options"):
            for option in xero_category_data["Options"]:
                if option.get("Status") == "ACTIVE":
                    create_project_from_option(option, xero_category_id)
                    
    except Exception as e:
        log_xero_error(
            message=f"Failed to sync Xero Tracking Category {category_name} as Projects",
            xero_entity_id=xero_category_id,
            xero_entity_type="TrackingCategory",
            error_details=frappe.get_traceback()
        )


def create_project_from_option(option_data, xero_category_id):
    """Create individual Project from tracking option."""
    option_id = option_data.get("TrackingOptionID")
    option_name = option_data.get("Name")
    
    if not option_id or not option_name:
        return
    
    try:
        # Check if Project already exists
        if frappe.db.exists("Project", {"xero_tracking_option_id": option_id}):
            return
        
        project = frappe.new_doc("Project")
        project.project_name = option_name
        project.status = "Open"
        project.xero_tracking_option_id = option_id
        project.xero_tracking_category_id = xero_category_id
        project.insert(ignore_permissions=True)
        frappe.db.commit()
        
        log_xero_error(
            message=f"Created Project {project.name} from Xero Tracking Option {option_name}",
            status="Success",
            erpnext_doc_type="Project",
            erpnext_doc_name=project.name,
            xero_entity_id=option_id,
            xero_entity_type="TrackingOption",
            direction="Xero to ERPNext"
        )
        
    except Exception as e:
        log_xero_error(
            message=f"Failed to create Project from Xero Tracking Option {option_name}",
            xero_entity_id=option_id,
            xero_entity_type="TrackingOption",
            error_details=frappe.get_traceback()
        )


# --- Tracking Categories Management (ERPNext to Xero) ---

@frappe.whitelist()
def create_xero_tracking_category(category_name):
    """Create a new tracking category in Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw("Xero sync is not enabled.")
    
    try:
        payload = {
            "Name": category_name
        }
        
        response = xero_request("PUT", "TrackingCategories", data={"TrackingCategories": [payload]})
        
        if response and response.get("TrackingCategories"):
            category = response["TrackingCategories"][0]
            frappe.msgprint(f"Successfully created tracking category '{category_name}' in Xero")
            return category
        else:
            frappe.throw("Failed to create tracking category in Xero")
            
    except Exception as e:
        log_xero_error(
            message=f"Failed to create tracking category '{category_name}' in Xero",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Error creating tracking category: {str(e)}")


@frappe.whitelist()
def create_xero_tracking_option(category_id, option_name):
    """Create a new tracking option in Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw("Xero sync is not enabled.")
    
    try:
        payload = {
            "Name": option_name
        }
        
        response = xero_request("PUT", f"TrackingCategories/{category_id}/Options", data={"Options": [payload]})
        
        if response and response.get("Options"):
            option = response["Options"][0]
            frappe.msgprint(f"Successfully created tracking option '{option_name}' in Xero")
            return option
        else:
            frappe.throw("Failed to create tracking option in Xero")
            
    except Exception as e:
        log_xero_error(
            message=f"Failed to create tracking option '{option_name}' in Xero",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Error creating tracking option: {str(e)}")


def get_tracking_categories_for_transaction(doc):
    """
    Get tracking categories for a transaction based on Cost Center and Project.
    Returns a list of tracking category assignments.
    """
    tracking = []
    
    # Map Cost Center to tracking category
    if hasattr(doc, 'cost_center') and doc.cost_center:
        cost_center_doc = frappe.get_doc("Cost Center", doc.cost_center)
        if hasattr(cost_center_doc, 'xero_tracking_category_id') and cost_center_doc.xero_tracking_category_id:
            tracking.append({
                "TrackingCategoryID": cost_center_doc.xero_tracking_category_id,
                "TrackingOptionID": getattr(cost_center_doc, 'xero_tracking_option_id', None),
                "Name": cost_center_doc.cost_center_name
            })
    
    # Map Project to tracking category
    if hasattr(doc, 'project') and doc.project:
        project_doc = frappe.get_doc("Project", doc.project)
        if hasattr(project_doc, 'xero_tracking_category_id') and project_doc.xero_tracking_category_id:
            tracking.append({
                "TrackingCategoryID": project_doc.xero_tracking_category_id,
                "TrackingOptionID": getattr(project_doc, 'xero_tracking_option_id', None),
                "Name": project_doc.project_name
            })
    
    return tracking[:2]  # Xero supports maximum 2 tracking categories per line item