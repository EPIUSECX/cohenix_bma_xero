# Copyright (c) 2026, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Direction-aware lookups over the Xero Settings tax mapping table.

ERPNext names a Sales and a Purchase Taxes and Charges Template the same way
("<title> - <abbr>"), and one tax account often serves both sides. Xero needs
a different tax type per side, so each mapping row says which side it applies
to. A row without a side applies to both.
"""

from frappe.utils import flt

BOTH = "Both"
SALES = "Sales"
PURCHASES = "Purchases"

PURCHASE_DOCTYPES = frozenset({"Purchase Invoice", "Purchase Order"})


def direction_of(doctype):
    """The side of the business an ERPNext doctype belongs to."""
    return PURCHASES if doctype in PURCHASE_DOCTYPES else SALES


class TaxMappingTable:
    """The tax mapping rows of Xero Settings, read for one direction."""

    def __init__(self, rows):
        self.rows = [r for r in rows or [] if r.erpnext_tax_template and r.xero_tax_type_code]

    def outbound(self, direction=None, zero_rated_only=False):
        """ERPNext tax name -> Xero tax type.

        A row for the direction wins over a row for both sides. Without a
        direction every row counts and the last one wins, as before the
        direction existed. ``zero_rated_only`` leaves out a name whose row
        records a Xero rate above 0%.
        """
        if not direction:
            winners = {r.erpnext_tax_template: r for r in self.rows}
        else:
            winners = {}
            for side in (BOTH, direction):
                for row in self._rows_for(side):
                    winners[row.erpnext_tax_template] = row
        return {
            name: row.xero_tax_type_code
            for name, row in winners.items()
            if not (zero_rated_only and flt(row.get("xero_tax_rate")))
        }

    def erpnext_names(self, xero_tax_type, direction=None):
        """ERPNext tax names mapped to a Xero tax type, most specific first."""
        sides = (direction, BOTH) if direction else (SALES, PURCHASES, BOTH)
        return [
            row.erpnext_tax_template
            for side in sides
            for row in self._rows_for(side)
            if row.xero_tax_type_code == xero_tax_type
        ]

    def _rows_for(self, side):
        return [r for r in self.rows if (r.get("applies_to") or BOTH) == side]
