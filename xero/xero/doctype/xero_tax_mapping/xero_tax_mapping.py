# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class XeroTaxMapping(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		applies_to: DF.Literal["Both", "Sales", "Purchases"]
		erpnext_tax_template: DF.Data
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		xero_tax_rate: DF.Float
		xero_tax_type_code: DF.Data | None
		xero_tax_type_name: DF.Data | None
	# end: auto-generated types

	pass
