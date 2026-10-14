# Copyright (c) 2026, EPI-USE Global Services and contributors
# For license information, please see license.txt
"""Boot data for the Frappe UI pages."""

import os

import frappe


def boot_session(bootinfo):
	if frappe.session.user == "Guest":
		return
	bootinfo.xero_pages_version = _pages_version()


def _pages_version() -> int:
	"""Change stamp of the Frappe UI page bundle, so Desk loads a new build, not a cached one.

	Assets under /assets are served without a version and cached for hours, so
	xero_pages.bundle.js appends this to the URL of the bundle.
	"""
	path = frappe.get_app_path("xero", "public", "frontend", "xero-pages.js")
	return int(os.path.getmtime(path)) if os.path.exists(path) else 0
