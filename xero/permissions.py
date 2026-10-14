# Copyright (c) 2026, EPI-USE Global Services and contributors
# For license information, please see license.txt
"""Who sees the Xero tile on the Apps screen, and with it the app's rail."""

import frappe


def has_app_permission() -> bool:
	if frappe.session.user == "Administrator":
		return True
	if frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User":
		return False
	return any(frappe.has_permission(dt, "read") for dt in ("Xero Settings", "Xero Log"))
