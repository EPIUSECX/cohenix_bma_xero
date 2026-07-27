import frappe


def execute():
	"""Remove the unused Xero chart/tax-rate cache doctypes.

	Xero Account, Xero Tax Rate and Xero Tax Component were local caches of
	the Xero chart of accounts and tax rates. Nothing reads them any more —
	mapping rows store the code/name directly and UI pickers fetch live from
	the Xero API — so the doctypes and their tables are dropped.
	"""
	for doctype in ("Xero Tax Component", "Xero Tax Rate", "Xero Account"):
		frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True)
		# delete_doc leaves the table behind; this is a deliberate schema
		# removal, so drop it too. Names are constants, not user input.
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")
