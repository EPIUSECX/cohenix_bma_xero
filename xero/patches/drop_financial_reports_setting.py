import frappe


def execute():
	"""Remove the orphaned sync_financial_reports toggle from Xero Settings.

	The financial-reports sync never worked: it wrote to four doctypes that
	were never shipped (Xero Trial Balance, Xero Profit Loss, Xero Balance
	Sheet, Xero Aged Receivables) and its scheduled entry point imported a
	function that was never defined. The feature and its checkbox are gone;
	removing the field from the doctype JSON leaves the Singles row behind,
	so drop it here.
	"""
	frappe.db.delete("Singles", {"doctype": "Xero Settings", "field": "sync_financial_reports"})
