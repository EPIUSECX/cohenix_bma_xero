# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class XeroSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING, List

	if TYPE_CHECKING:
		from frappe.types import DF
		from .xero_account_mapping import XeroAccountMapping
		from .xero_tax_mapping import XeroTaxMapping

		access_token: DF.SmallText | None
		account_mapping: DF.Table[XeroAccountMapping]
		client_id: DF.Data | None
		client_secret: DF.Password | None
		connection_status: DF.Data | None
		create_payment_entry_on_sync: DF.Check
		default_bank_account: DF.Link | None
		enable_auto_sync: DF.Check
		enable_webhooks: DF.Check
		enable_xero_sync: DF.Check
		refresh_token: DF.SmallText | None
		sync_chart_of_accounts: DF.Check
		sync_contacts: DF.Check
		sync_frequency: DF.Literal["Hourly", "Daily", "Weekly"] | None
		sync_invoices: DF.Check
		sync_journal_entries: DF.Check
		sync_items: DF.Check
		sync_payments: DF.Check # This is for invoice payment status check
		sync_payments_standalone: DF.Check # This is for standalone PE sync
		sync_credit_notes: DF.Check
		tax_mapping: DF.Table[XeroTaxMapping]
		tenant_id: DF.Data | None
		token_expiry: DF.Datetime | None
		webhook_secret: DF.Password | None
	# end: auto-generated types

	# Add custom methods if needed, e.g., to fetch mappings easily
	def get_account_map(self):
		"""Returns a dictionary mapping ERPNext accounts to Xero codes."""
		mapping = {}
		for row in self.account_mapping:
			if row.erpnext_account and row.xero_account_code:
				mapping[row.erpnext_account] = row.xero_account_code
		return mapping

	def get_tax_map(self):
		"""Returns a dictionary mapping ERPNext tax templates to Xero tax types."""
		mapping = {}
		for row in self.tax_mapping:
			if row.erpnext_tax_template and row.xero_tax_type_code:
				mapping[row.erpnext_tax_template] = row.xero_tax_type_code
		return mapping

	@frappe.whitelist()
	def check_xero_connection(self):
		"""Attempts to connect to Xero API (e.g., fetch Organisation) to verify credentials and token."""
		if not self.enable_xero_sync or not self.access_token or not self.tenant_id:
			self.connection_status = "Disabled or Not Configured"
			self.save(ignore_permissions=True)
			return {"status": self.connection_status}

		from xero.utils.xero_client import xero_request # Avoid circular import at top
		status = "Error"
		try:
			# Make a simple API call to check connectivity, e.g., get Organisation details
			response = xero_request("GET", "Organisation")
			if response and response.get("Organisations"):
				status = "Active"
			else:
				status = "Error (Invalid Response)"
		except Exception as e:
			status = f"Error ({e})" # Include error message

		self.connection_status = status
		self.save(ignore_permissions=True)
		frappe.db.commit()
		return {"status": status}

	@frappe.whitelist()
	def disconnect_xero(self):
		"""Clears Xero tokens and tenant ID."""
		self.access_token = None
		self.refresh_token = None
		self.token_expiry = None
		self.tenant_id = None
		self.connection_status = "Disconnected"
		self.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.msgprint("Disconnected from Xero. Tokens have been cleared.")

	@frappe.whitelist()
	def fetch_and_update_account_mapping(self):
		"""Fetches accounts from Xero and ERPNext, populates mapping table."""
		if not self.enable_xero_sync or not self.tenant_id:
			frappe.throw("Xero sync must be enabled and connected.")
		
		doc = frappe.get_doc("Xero Settings", self.name) # Explicitly reload

		from xero.api.xero_accounts import sync_accounts_from_xero # Fetch Xero accounts
		from xero.utils.xero_client import xero_request

		# 1. Fetch Xero Accounts (ensure they are created/updated in ERPNext first)
		# sync_accounts_from_xero() # Optionally run full sync first? Or just fetch?
		try:
			xero_accounts_response = xero_request("GET", "Accounts")
			xero_accounts = xero_accounts_response.get("Accounts", []) if xero_accounts_response else []
		except Exception as e:
			frappe.throw(f"Failed to fetch accounts from Xero: {e}")

		# 2. Get relevant ERPNext Accounts (e.g., non-group accounts for the default company)
		# TODO: Add company filter if needed
		erpnext_accounts = frappe.get_all("Account", filters={"is_group": 0}, fields=["name", "account_number"])

		# 3. Prepare Xero data lookup (by code and ID)
		xero_lookup_by_code = {acc.get("Code"): acc for acc in xero_accounts if acc.get("Code")}
		xero_lookup_by_id = {acc.get("AccountID"): acc for acc in xero_accounts if acc.get("AccountID")}

		# 4. Update mapping table
		account_mapping_table = doc.get("account_mapping") or []
		existing_erp_accounts_in_map = {row.erpnext_account for row in account_mapping_table}
		updated = 0
		added = 0

		for erp_acc in erpnext_accounts:
			erp_acc_name = erp_acc["name"]
			erp_acc_number = erp_acc["account_number"]
			xero_match = None

			# Try matching via ERPNext Account Number == Xero Code
			if erp_acc_number and erp_acc_number in xero_lookup_by_code:
				xero_match = xero_lookup_by_code[erp_acc_number]
			# TODO: Add matching via custom field 'xero_account_id' if implemented on Account

			# Find existing row or create new one
			existing_row = next((row for row in doc.account_mapping if row.erpnext_account == erp_acc_name), None)

			if existing_row:
				# Update existing row if match found and code is missing/different
				if xero_match and existing_row.xero_account_code != xero_match.get("Code"):
					existing_row.xero_account_code = xero_match.get("Code")
					existing_row.xero_account_id = xero_match.get("AccountID")
					existing_row.xero_account_name = xero_match.get("Name")
					updated += 1
			elif erp_acc_name not in existing_erp_accounts_in_map:
				# Add new row only if a match was found in Xero
				if xero_match:
					doc.append("account_mapping", {
						"erpnext_account": erp_acc_name,
						"xero_account_code": xero_match.get("Code"),
						"xero_account_id": xero_match.get("AccountID"),
						"xero_account_name": xero_match.get("Name")
					})
					added += 1

		doc.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.msgprint(f"Account mapping updated: {added} added, {updated} updated. Please review and fill any missing Xero Account Codes manually.")


	@frappe.whitelist()
	def fetch_and_update_tax_mapping(self):
		"""Fetches tax rates/types from Xero and populates mapping table."""
		if not self.enable_xero_sync or not self.tenant_id:
			frappe.throw("Xero sync must be enabled and connected.")
		
		doc = frappe.get_doc("Xero Settings", self.name) # Explicitly reload

		from xero.api.xero_accounts import get_xero_tax_rates # Use the existing function

		# 1. Fetch Xero Tax Rates
		xero_tax_rates = get_xero_tax_rates()
		if not xero_tax_rates:
			frappe.msgprint("Could not fetch Tax Rates from Xero, or none exist.")
			return

		# 2. Get ERPNext Item Tax Templates
		erpnext_templates = frappe.get_all("Item Tax Template", fields=["name"])

		# 3. Update mapping table (simple add - requires manual code entry)
		tax_mapping_table = doc.get("tax_mapping") or []
		existing_erp_templates_in_map = {row.erpnext_tax_template for row in tax_mapping_table}
		added = 0

		if not doc.get("tax_mapping"):
			doc.set("tax_mapping", [])

		for template in erpnext_templates:
			if template.name not in existing_erp_templates_in_map:
				# Add template, user needs to fill in the Xero code
				doc.append("tax_mapping", {
					"erpnext_tax_template": template.name,
					"xero_tax_type_code": None # User must fill this
				})
				added += 1

		doc.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.msgprint(f"Tax mapping updated: {added} ERPNext templates added. Please review and enter the corresponding Xero TaxType Codes.")
