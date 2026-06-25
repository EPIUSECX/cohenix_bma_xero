# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class XeroAccountMapping(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		erpnext_account: DF.Link
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		xero_account_code: DF.Data | None
		xero_account_id: DF.Data | None
		xero_account_name: DF.Data | None
	# end: auto-generated types

	pass
