# Copyright (c) 2024, EpiUse and contributors
# For license information, please see license.txt

import frappe
from frappe import _


@frappe.whitelist()
def get_dashboard_data():
    """
    Get project metrics for dashboard
    """
    return {
        "summary": get_project_summary(),
        "recent_projects": get_recent_projects(),
        "profitability": get_profitability_metrics()
    }


def get_project_summary():
    """
    Get high-level project metrics
    """
    return frappe.db.sql("""
        SELECT 
            status,
            COUNT(*) as count,
            SUM(estimate_amount) as total_estimate,
            SUM(total_cost) as total_cost,
            SUM(total_time) as total_hours
        FROM `tabXero Project`
        GROUP BY status
    """, as_dict=1)


def get_recent_projects():
    """
    Get recently updated projects
    """
    return frappe.get_all("Xero Project",
        fields=[
            "name", 
            "project_id",
            "status", 
            "deadline", 
            "estimate_amount", 
            "total_cost",
            "total_time"
        ],
        order_by="modified desc",
        limit=5
    )


def get_profitability_metrics():
    """
    Calculate profitability metrics
    """
    return frappe.db.sql("""
        SELECT 
            name,
            project_id,
            estimate_amount,
            total_cost,
            (estimate_amount - total_cost) as margin,
            CASE 
                WHEN estimate_amount > 0 
                THEN ((estimate_amount - total_cost) / estimate_amount * 100) 
                ELSE 0 
            END as margin_percent
        FROM `tabXero Project`
        WHERE status = 'INPROGRESS'
            AND estimate_amount > 0
        ORDER BY margin_percent DESC
        LIMIT 10
    """, as_dict=1)

@frappe.whitelist()
def get_project_variances():
    """
    Get budget and time variances for projects
    """
    return frappe.db.sql("""
        SELECT 
            name,
            project_id,
            status,
            estimate_amount,
            total_cost,
            (estimate_amount - total_cost) as budget_variance,
            CASE 
                WHEN estimate_amount > 0 
                THEN ((estimate_amount - total_cost) / estimate_amount * 100) 
                ELSE 0 
            END as budget_variance_percent,
            total_time,
            CASE 
                WHEN total_cost > estimate_amount THEN 'Over Budget'
                WHEN total_cost > estimate_amount * 0.9 THEN 'At Risk'
                ELSE 'On Track'
            END as budget_status
        FROM `tabXero Project`
        WHERE estimate_amount > 0
        ORDER BY budget_variance ASC
    """, as_dict=1)

@frappe.whitelist()
def get_financial_metrics():
    """
    Get comprehensive financial metrics for all projects
    """
    metrics = frappe.db.sql("""
        SELECT 
            COUNT(*) as total_projects,
            SUM(estimate_amount) as total_estimated,
            SUM(total_cost) as total_actual_cost,
            SUM(estimate_amount - total_cost) as total_margin,
            AVG(CASE 
                WHEN estimate_amount > 0 
                THEN ((estimate_amount - total_cost) / estimate_amount * 100) 
                ELSE 0 
            END) as avg_margin_percent,
            COUNT(CASE WHEN total_cost > estimate_amount THEN 1 END) as over_budget_count,
            SUM(CASE WHEN total_cost > estimate_amount THEN (total_cost - estimate_amount) ELSE 0 END) as over_budget_amount
        FROM `tabXero Project`
        WHERE estimate_amount > 0
    """, as_dict=1)
    
    # Projects by status
    by_status = frappe.db.sql("""
        SELECT 
            status,
            COUNT(*) as count,
            SUM(estimate_amount) as total_estimate,
            SUM(total_cost) as total_cost,
            AVG(CASE 
                WHEN estimate_amount > 0 
                THEN ((estimate_amount - total_cost) / estimate_amount * 100) 
                ELSE 0 
            END) as avg_margin_percent
        FROM `tabXero Project`
        GROUP BY status
    """, as_dict=1)
    
    return {
        "overall": metrics[0] if metrics else {},
        "by_status": by_status
    }

@frappe.whitelist()
def get_time_tracking_metrics():
    """
    Get time tracking metrics across projects
    """
    return frappe.db.sql("""
        SELECT 
            name,
            project_id,
            total_time,
            total_cost,
            CASE 
                WHEN total_time > 0 
                THEN total_cost / total_time 
                ELSE 0 
            END as cost_per_hour
        FROM `tabXero Project`
        WHERE total_time > 0
        ORDER BY total_time DESC
        LIMIT 10
    """, as_dict=1)

@frappe.whitelist()
def get_alerts_and_warnings():
    """
    Get project alerts and warnings
    """
    # Projects over budget
    over_budget = frappe.db.sql("""
        SELECT 
            name,
            project_id,
            estimate_amount,
            total_cost,
            (total_cost - estimate_amount) as over_amount,
            ((total_cost - estimate_amount) / estimate_amount * 100) as over_percent
        FROM `tabXero Project`
        WHERE total_cost > estimate_amount
        ORDER BY over_percent DESC
    """, as_dict=1)
    
    # Projects at risk (>90% of budget used)
    at_risk = frappe.db.sql("""
        SELECT 
            name,
            project_id,
            estimate_amount,
            total_cost,
            (total_cost / estimate_amount * 100) as budget_used_percent
        FROM `tabXero Project`
        WHERE total_cost > estimate_amount * 0.9
        AND total_cost <= estimate_amount
        AND status = 'INPROGRESS'
        ORDER BY budget_used_percent DESC
    """, as_dict=1)
    
    # Projects with low margin (<10%)
    low_margin = frappe.db.sql("""
        SELECT 
            name,
            project_id,
            estimate_amount,
            total_cost,
            (estimate_amount - total_cost) as margin,
            ((estimate_amount - total_cost) / estimate_amount * 100) as margin_percent
        FROM `tabXero Project`
        WHERE estimate_amount > 0
        AND ((estimate_amount - total_cost) / estimate_amount * 100) < 10
        AND status = 'INPROGRESS'
        ORDER BY margin_percent ASC
    """, as_dict=1)
    
    return {
        "over_budget": over_budget,
        "at_risk": at_risk,
        "low_margin": low_margin,
        "total_alerts": len(over_budget) + len(at_risk) + len(low_margin)
    }
