# Copyright (c) 2026, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline unit tests for the direction-aware tax mapping and zero-rated lines.

The fixtures mirror a South African company whose Sales and Purchase Taxes and
Charges Templates share their names and one VAT account:

  * a Sales and a Purchase template of one name resolve to different Xero types
  * a line ERPNext rates at 0% keeps its mapped Xero type with a zero amount
  * an untaxed line never borrows a standard-rate mapping

Run: bench run-tests --app xero --module xero.tests.test_tax_mapping
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xero.api.xero_invoices import get_erpnext_tax_from_xero_type, map_erpnext_tax_to_xero
from xero.api.xero_line_builder import build_xero_lines
from xero.utils.exceptions import TaxRepresentationError
from xero.utils.tax_mapping import BOTH, PURCHASES, SALES, TaxMappingTable, direction_of
from xero.xero.doctype.xero_settings.xero_settings import XeroSettings

STANDARD = "SA VAT 15% - Exclusive - TC"
EXPORT = "SA VAT 0% - Export - TC"
VAT_ACCOUNT = "VAT - TC"
INCOME_ACCOUNT = "Sales - TC"
EXPENSE_ACCOUNT = "Cost of Goods Sold - TC"


class Row(SimpleNamespace):
    """A document double: attribute access and .get(), like a frappe document."""

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getattr__(self, key):
        # Only reached for a field the double does not carry.
        return None


def mapping_row(name, code, applies_to=None, xero_tax_rate=0):
    return Row(
        erpnext_tax_template=name,
        xero_tax_type_code=code,
        applies_to=applies_to,
        xero_tax_rate=xero_tax_rate,
    )


class Settings(Row):
    # The real lookup, so the tests cover Xero Settings and not a copy of it.
    get_tax_map = XeroSettings.get_tax_map

    def get_account_map(self):
        return {INCOME_ACCOUNT: "200", EXPENSE_ACCOUNT: "310"}


def settings(*rows):
    return Settings(tax_mapping=list(rows))


def tax_row(rate, amount, name="tax-1"):
    return Row(
        name=name,
        charge_type="On Net Total",
        account_head=VAT_ACCOUNT,
        rate=rate,
        tax_amount_after_discount_amount=amount,
        included_in_print_rate=0,
    )


def item_row(amount=100.0, name="item-1", **extra):
    return Row(
        name=name,
        description="Widget",
        qty=1,
        rate=amount,
        amount=amount,
        income_account=INCOME_ACCOUNT,
        expense_account=EXPENSE_ACCOUNT,
        **extra,
    )


def document(template, taxes, items=None, tax_details=None):
    items = items or [item_row()]
    net_total = sum(item.amount for item in items)
    tax_total = sum(tax.tax_amount_after_discount_amount for tax in taxes)
    return Row(
        name="DOC-0001",
        items=items,
        taxes=taxes,
        taxes_and_charges=template,
        item_wise_tax_details=tax_details or [],
        grand_total=net_total + tax_total,
        disable_rounded_total=1,
    )


class TestDirection(unittest.TestCase):
    def test_purchase_doctypes_are_purchases(self):
        self.assertEqual(direction_of("Purchase Invoice"), PURCHASES)
        self.assertEqual(direction_of("Purchase Order"), PURCHASES)

    def test_other_doctypes_are_sales(self):
        self.assertEqual(direction_of("Sales Invoice"), SALES)
        self.assertEqual(direction_of("Quotation"), SALES)


class TestTaxMappingTable(unittest.TestCase):
    def test_one_name_maps_to_a_type_per_side(self):
        table = TaxMappingTable(
            [mapping_row(STANDARD, "OUTPUT3", SALES), mapping_row(STANDARD, "INPUT3", PURCHASES)]
        )
        self.assertEqual(table.outbound(SALES), {STANDARD: "OUTPUT3"})
        self.assertEqual(table.outbound(PURCHASES), {STANDARD: "INPUT3"})

    def test_side_row_wins_over_both_row_in_any_order(self):
        rows = [mapping_row(VAT_ACCOUNT, "INPUT3", PURCHASES), mapping_row(VAT_ACCOUNT, "OUTPUT3", BOTH)]
        for ordered in (rows, rows[::-1]):
            table = TaxMappingTable(ordered)
            self.assertEqual(table.outbound(PURCHASES), {VAT_ACCOUNT: "INPUT3"})
            self.assertEqual(table.outbound(SALES), {VAT_ACCOUNT: "OUTPUT3"})

    def test_row_without_a_side_applies_to_both(self):
        table = TaxMappingTable([mapping_row(EXPORT, "ZERORATEDOUTPUT")])
        self.assertEqual(table.outbound(SALES), {EXPORT: "ZERORATEDOUTPUT"})
        self.assertEqual(table.outbound(PURCHASES), {EXPORT: "ZERORATEDOUTPUT"})

    def test_without_direction_every_row_counts(self):
        table = TaxMappingTable(
            [mapping_row(STANDARD, "OUTPUT3", SALES), mapping_row(EXPORT, "ZERORATEDOUTPUT")]
        )
        self.assertEqual(table.outbound(), {STANDARD: "OUTPUT3", EXPORT: "ZERORATEDOUTPUT"})

    def test_zero_rated_only_leaves_out_rows_with_a_rate(self):
        table = TaxMappingTable(
            [
                mapping_row(STANDARD, "OUTPUT3", SALES, xero_tax_rate=15),
                mapping_row(EXPORT, "ZERORATEDOUTPUT"),
            ]
        )
        self.assertEqual(table.outbound(SALES, zero_rated_only=True), {EXPORT: "ZERORATEDOUTPUT"})

    def test_incomplete_rows_are_ignored(self):
        table = TaxMappingTable([mapping_row(STANDARD, None), mapping_row(None, "OUTPUT3")])
        self.assertEqual(table.outbound(SALES), {})

    def test_reverse_lookup_skips_the_other_side(self):
        table = TaxMappingTable(
            [
                mapping_row("Both Sides", "TAX001", BOTH),
                mapping_row("Purchases Only", "TAX001", PURCHASES),
                mapping_row("Sales Only", "TAX001", SALES),
            ]
        )
        self.assertEqual(table.erpnext_names("TAX001", SALES), ["Sales Only", "Both Sides"])
        self.assertEqual(table.erpnext_names("TAX001", PURCHASES), ["Purchases Only", "Both Sides"])
        self.assertEqual(len(table.erpnext_names("TAX001")), 3)


class TestLegacyLookups(unittest.TestCase):
    def test_quotation_lookup_reads_the_sales_side(self):
        config = settings(
            mapping_row("Item VAT 15%", "INPUT3", PURCHASES), mapping_row("Item VAT 15%", "OUTPUT3", SALES)
        )
        self.assertEqual(map_erpnext_tax_to_xero("Item VAT 15%", config, SALES), "OUTPUT3")

    def test_inbound_lookup_reads_the_document_side(self):
        config = settings(
            mapping_row("Item VAT Sales", "TAX001", SALES),
            mapping_row("Item VAT Purchases", "TAX001", PURCHASES),
        )
        with patch("xero.api.xero_invoices.frappe.db.exists", return_value=True, create=True):
            self.assertEqual(
                get_erpnext_tax_from_xero_type("TAX001", config, PURCHASES), "Item VAT Purchases"
            )
            self.assertEqual(get_erpnext_tax_from_xero_type("TAX001", config, SALES), "Item VAT Sales")

    def test_inbound_lookup_falls_back_to_a_both_row(self):
        config = settings(mapping_row("Item VAT Sales", "TAX001", SALES), mapping_row("Item VAT", "TAX001"))
        with patch("xero.api.xero_invoices.frappe.db.exists", return_value=True, create=True):
            self.assertEqual(get_erpnext_tax_from_xero_type("TAX001", config, PURCHASES), "Item VAT")


class TestStandardRatedLines(unittest.TestCase):
    """Sales and Purchase templates of one name, both on one VAT account."""

    def setUp(self):
        self.settings = settings(
            mapping_row(STANDARD, "OUTPUT3", SALES), mapping_row(STANDARD, "INPUT3", PURCHASES)
        )
        self.doc = document(STANDARD, [tax_row(15, 15.0)])

    def test_sales_invoice_gets_the_sales_type(self):
        line = build_xero_lines(self.doc, "Sales Invoice", self.settings).line_items[0]
        self.assertEqual((line["TaxType"], line["TaxAmount"]), ("OUTPUT3", 15.0))

    def test_purchase_invoice_gets_the_purchases_type(self):
        line = build_xero_lines(self.doc, "Purchase Invoice", self.settings).line_items[0]
        self.assertEqual((line["TaxType"], line["TaxAmount"]), ("INPUT3", 15.0))

    def test_account_row_for_one_side_does_not_serve_the_other(self):
        config = settings(mapping_row(VAT_ACCOUNT, "OUTPUT3", SALES))
        with self.assertRaises(TaxRepresentationError) as raised:
            build_xero_lines(self.doc, "Purchase Invoice", config)
        self.assertIn("Purchases or Both", str(raised.exception))


class TestZeroRatedLines(unittest.TestCase):
    def test_zero_rated_document_keeps_its_mapped_type(self):
        config = settings(mapping_row(EXPORT, "ZERORATEDOUTPUT", SALES))
        built = build_xero_lines(document(EXPORT, [tax_row(0, 0.0)]), "Sales Invoice", config)
        line = built.line_items[0]
        self.assertEqual((line["TaxType"], line["TaxAmount"]), ("ZERORATEDOUTPUT", 0.0))
        self.assertEqual((built.target_total, built.total_tax), (100.0, 0.0))

    def test_zero_rated_document_without_mapping_is_sent_without_tax(self):
        line = build_xero_lines(document(EXPORT, [tax_row(0, 0.0)]), "Sales Invoice", settings()).line_items[
            0
        ]
        self.assertEqual(line["TaxType"], "NONE")
        self.assertNotIn("TaxAmount", line)

    def test_document_without_tax_rows_is_sent_without_tax(self):
        config = settings(mapping_row(STANDARD, "OUTPUT3", SALES))
        line = build_xero_lines(document(STANDARD, []), "Sales Invoice", config).line_items[0]
        self.assertEqual(line["TaxType"], "NONE")

    def test_zero_rated_item_on_a_standard_document_uses_its_own_mapping(self):
        config = settings(
            mapping_row(STANDARD, "OUTPUT3", SALES), mapping_row("Zero Rated Item", "ZERORATED", SALES)
        )
        lines = build_xero_lines(
            self._mixed_document("Zero Rated Item", 0), "Sales Invoice", config
        ).line_items
        self.assertEqual((lines[0]["TaxType"], lines[0]["TaxAmount"]), ("OUTPUT3", 15.0))
        self.assertEqual((lines[1]["TaxType"], lines[1]["TaxAmount"]), ("ZERORATED", 0.0))

    def test_zero_rated_item_never_borrows_the_document_mapping(self):
        config = settings(mapping_row(STANDARD, "OUTPUT3", SALES))
        lines = build_xero_lines(
            self._mixed_document("Zero Rated Item", 0), "Sales Invoice", config
        ).line_items
        self.assertEqual(lines[1]["TaxType"], "NONE")
        self.assertNotIn("TaxAmount", lines[1])

    def test_untaxed_line_with_a_rated_item_template_is_sent_without_tax(self):
        config = settings(mapping_row("Item VAT 15%", "OUTPUT3", SALES))
        item = item_row(item_tax_template="Item VAT 15%", item_tax_rate=json.dumps({VAT_ACCOUNT: 15}))
        line = build_xero_lines(document(None, [], [item]), "Sales Invoice", config).line_items[0]
        self.assertEqual(line["TaxType"], "NONE")

    def _mixed_document(self, item_tax_template, rate):
        """One standard-rated line and one line with its own Item Tax Template."""
        items = [
            item_row(name="item-1"),
            item_row(
                name="item-2",
                item_tax_template=item_tax_template,
                item_tax_rate=json.dumps({VAT_ACCOUNT: rate}),
            ),
        ]
        details = [
            Row(tax_row="tax-1", item_row="item-1", amount=15.0),
            Row(tax_row="tax-1", item_row="item-2", amount=0.0),
        ]
        return document(STANDARD, [tax_row(15, 15.0)], items, details)

    def test_zero_rated_credit_note_keeps_its_mapped_type(self):
        config = settings(mapping_row(EXPORT, "ZERORATEDOUTPUT", SALES))
        doc = document(EXPORT, [tax_row(0, 0.0)], [item_row(amount=-100.0)])
        line = build_xero_lines(doc, "Sales Invoice", config, absolute=True).line_items[0]
        self.assertEqual(
            (line["TaxType"], line["TaxAmount"], line["LineAmount"]), ("ZERORATEDOUTPUT", 0.0, 100.0)
        )

    def test_zero_rated_purchase_order_keeps_its_mapped_type(self):
        config = settings(mapping_row(EXPORT, "ZERORATEDINPUT", PURCHASES))
        built = build_xero_lines(
            document(EXPORT, [tax_row(0, 0.0)]),
            "Purchase Order",
            config,
            require_account=False,
            include_rounding=False,
        )
        self.assertEqual(built.line_items[0]["TaxType"], "ZERORATEDINPUT")

    def test_item_template_without_rates_follows_the_document(self):
        config = settings(mapping_row(EXPORT, "ZERORATEDOUTPUT", SALES))
        item = item_row(item_tax_template="Zero Rated Item", item_tax_rate="{}")
        line = build_xero_lines(
            document(EXPORT, [tax_row(0, 0.0)], [item]), "Sales Invoice", config
        ).line_items[0]
        self.assertEqual(line["TaxType"], "ZERORATEDOUTPUT")


class TestZeroTaxLinesNeverBorrowARatedMapping(unittest.TestCase):
    """A tax account carries several rates, so its mapping proves no rate."""

    def setUp(self):
        self.account_only = settings(mapping_row(VAT_ACCOUNT, "OUTPUT3"))

    def test_account_mapping_is_not_used_on_a_zero_rated_sales_invoice(self):
        doc = document(EXPORT, [tax_row(0, 0.0)])
        line = build_xero_lines(doc, "Sales Invoice", self.account_only).line_items[0]
        self.assertEqual(line["TaxType"], "NONE")
        self.assertNotIn("TaxAmount", line)

    def test_account_mapping_is_not_used_on_a_zero_rated_purchase_invoice(self):
        doc = document(EXPORT, [tax_row(0, 0.0)])
        line = build_xero_lines(doc, "Purchase Invoice", self.account_only).line_items[0]
        self.assertEqual(line["TaxType"], "NONE")

    def test_account_mapping_still_serves_a_taxed_line(self):
        doc = document(STANDARD, [tax_row(15, 15.0)])
        line = build_xero_lines(doc, "Sales Invoice", self.account_only).line_items[0]
        self.assertEqual((line["TaxType"], line["TaxAmount"]), ("OUTPUT3", 15.0))

    def test_untaxed_line_beside_an_item_rated_line_is_sent_without_tax(self):
        """A 0% row taxes one line through its Item Tax Template; the other line has none."""
        config = settings(mapping_row(STANDARD, "OUTPUT3", SALES))
        items = [
            item_row(
                name="item-1",
                item_tax_template="Item VAT 15%",
                item_tax_rate=json.dumps({VAT_ACCOUNT: 15}),
            ),
            item_row(name="item-2"),
        ]
        details = [
            Row(tax_row="tax-1", item_row="item-1", amount=15.0),
            Row(tax_row="tax-1", item_row="item-2", amount=0.0),
        ]
        lines = build_xero_lines(
            document(STANDARD, [tax_row(0, 15.0)], items, details), "Sales Invoice", config
        ).line_items
        self.assertEqual((lines[0]["TaxType"], lines[0]["TaxAmount"]), ("OUTPUT3", 15.0))
        self.assertEqual(lines[1]["TaxType"], "NONE")

    def test_item_template_for_another_account_is_not_zero_rated(self):
        config = settings(
            mapping_row(STANDARD, "OUTPUT3", SALES), mapping_row("Other Tax Item", "ZERORATED", SALES)
        )
        line = self._second_line(config, "Other Tax Item", {"Other - TC": 0})
        self.assertEqual(line["TaxType"], "NONE")

    def test_item_template_that_does_not_apply_is_not_zero_rated(self):
        config = settings(
            mapping_row(STANDARD, "OUTPUT3", SALES), mapping_row("Exempt Item", "EXEMPTOUTPUT", SALES)
        )
        line = self._second_line(config, "Exempt Item", {VAT_ACCOUNT: "N/A"})
        self.assertEqual(line["TaxType"], "NONE")

    def test_template_mapped_to_a_rated_type_is_not_used_on_an_untaxed_document(self):
        """0% rows whose real rates come from item templates; this document has none."""
        config = settings(mapping_row(STANDARD, "OUTPUT3", SALES, xero_tax_rate=15))
        line = build_xero_lines(document(STANDARD, [tax_row(0, 0.0)]), "Sales Invoice", config).line_items[0]
        self.assertEqual(line["TaxType"], "NONE")

    def test_rate_and_not_applicable_account_together_are_zero_rated(self):
        config = settings(
            mapping_row(STANDARD, "OUTPUT3", SALES), mapping_row("Zero Rated Item", "ZERORATED", SALES)
        )
        line = self._second_line(config, "Zero Rated Item", {VAT_ACCOUNT: 0, "Other - TC": "N/A"})
        self.assertEqual((line["TaxType"], line["TaxAmount"]), ("ZERORATED", 0.0))

    def _second_line(self, config, item_tax_template, rates):
        """The untaxed second line of a standard-rated document."""
        items = [
            item_row(name="item-1"),
            item_row(name="item-2", item_tax_template=item_tax_template, item_tax_rate=json.dumps(rates)),
        ]
        details = [
            Row(tax_row="tax-1", item_row="item-1", amount=15.0),
            Row(tax_row="tax-1", item_row="item-2", amount=0.0),
        ]
        doc = document(STANDARD, [tax_row(15, 15.0)], items, details)
        return build_xero_lines(doc, "Sales Invoice", config).line_items[1]
