# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class XeroLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		direction: DF.Literal["ERPNext_to_Xero", "Xero_to_ERPNext"] | None
		erpnext_doc_name: DF.DynamicLink | None
		erpnext_doc_type: DF.Link | None
		error_details: DF.Text | None
		message: DF.SmallText | None
		status: DF.Literal["Success", "Error", "Info"]
		timestamp: DF.Datetime
		xero_entity_id: DF.Data | None
		xero_entity_type: DF.Data | None
	# end: auto-generated types

	pass
