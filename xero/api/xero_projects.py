# Copyright (c) 2024, EpiUse and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import now_datetime
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error


@frappe.whitelist()
def enqueue_sync_projects():
    """
    Enqueue the project sync task to run in the background
    """
    frappe.enqueue(
        'xero.api.xero_projects.sync_projects',
        queue='long',
        timeout=1500,
        now=True
    )


def sync_projects():
    """
    Sync projects from Xero to ERPNext
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return

    try:
        response = xero_request("GET", "/projects.xro/2.0/projects")
        if not response:
            log_xero_error("Projects Sync", "No response from Xero API")
            return

        projects = response.json()
        for project in projects:
            update_or_create_project(project)
            
    except Exception as e:
        log_xero_error("Projects Sync", str(e))


def update_or_create_project(xero_project):
    """
    Create or update project in ERPNext from Xero data
    """
    project_id = xero_project.get("projectId")
    if not project_id:
        return

    try:
        existing = frappe.db.get_value("Xero Project", 
            {"project_id": project_id}, "name")
            
        project_doc = frappe.get_doc("Xero Project", existing) if existing else \
            frappe.new_doc("Xero Project")
            
        project_doc.update({
            "project_id": project_id,
            "name": xero_project.get("name"),
            "status": xero_project.get("status"),
            "deadline": xero_project.get("deadlineUtc"),
            "estimate_amount": xero_project.get("estimate", {}).get("amount"),
            "total_cost": calculate_total_cost(project_id),
            "total_time": calculate_total_time(project_id)
        })
        
        project_doc.flags.ignore_validate = True
        project_doc.save()

    except Exception as e:
        log_xero_error("Project Update", f"Project ID: {project_id} - {str(e)}")


def calculate_total_cost(project_id):
    """
    Get total costs from Xero Project API
    """
    try:
        response = xero_request("GET", 
            f"/projects.xro/2.0/projects/{project_id}/costs")
        costs = response.json()
        return sum(cost["amount"] for cost in costs)
    except Exception:
        return 0


def calculate_total_time(project_id):
    """
    Get total time from Xero Project API
    """
    try:
        response = xero_request("GET", 
            f"/projects.xro/2.0/projects/{project_id}/time")
        time_entries = response.json()
        return sum(entry["hours"] for entry in time_entries)
    except Exception:
        return 0
