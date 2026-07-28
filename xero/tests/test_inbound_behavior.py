# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline unit tests for inbound-sync behaviour:

  * ERPNext->Xero account-type mapping (exact, root-type fallback, generic)
  * Opt-in auto-submit (maybe_submit_inbound) is a no-op when the setting is OFF
    and never touches an already-submitted document.

Run: bench run-tests --app xero --module xero.tests.test_inbound_behavior
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from xero.api.xero_accounts import (
    XERO_ACCOUNT_TYPE_MAP,
    get_xero_type_from_erpnext,
)
from xero.api.xero_invoices import maybe_submit_inbound
from xero.api.xero_line_builder import apply_inbound_taxes, inbound_line_rate


class TestAccountTypeMapping(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(get_xero_type_from_erpnext("Income", "Income Account"), "REVENUE")

    def test_root_type_fallback(self):
        # An account_type that isn't in the reverse map still resolves to a
        # sensible Xero type for its root_type (second tier), not None.
        result = get_xero_type_from_erpnext("Liability", "Some Unmapped Liability Type")
        self.assertIsNotNone(result)

    def test_unmapped_account_type_returns_valid_same_root_type(self):
        # An unmapped account_type must still resolve to a VALID Xero type whose
        # root_type matches (it need not be the generic "EXPENSE" — the
        # root-type-alone tier may return a more specific Expense-family type
        # such as DIRECTCOSTS, which is correct).
        result = get_xero_type_from_erpnext("Expense", "Totally Unknown")
        self.assertIn(result, XERO_ACCOUNT_TYPE_MAP)
        self.assertEqual(XERO_ACCOUNT_TYPE_MAP[result]["root_type"], "Expense")

    def test_unknown_root_type_returns_none(self):
        self.assertIsNone(get_xero_type_from_erpnext("NotARootType", "x"))


class TestMaybeSubmitInbound(unittest.TestCase):
    def test_noop_when_setting_off(self):
        settings = SimpleNamespace(get=lambda k, d=None: 0)  # auto_submit_inbound off
        doc = SimpleNamespace(docstatus=0, doctype="Sales Invoice", name="SI-X")
        self.assertFalse(maybe_submit_inbound(doc, settings, "xero-id", "Invoice"))

    def test_noop_when_already_submitted(self):
        settings = SimpleNamespace(get=lambda k, d=None: 1)  # setting ON
        doc = SimpleNamespace(docstatus=1, doctype="Sales Invoice", name="SI-X")
        # Already submitted -> must not attempt to submit again.
        self.assertFalse(maybe_submit_inbound(doc, settings, "xero-id", "Invoice"))

    def test_noop_when_no_settings(self):
        doc = SimpleNamespace(docstatus=0, doctype="Sales Invoice", name="SI-X")
        self.assertFalse(maybe_submit_inbound(doc, None, "xero-id", "Invoice"))


if __name__ == "__main__":
    unittest.main()


class TestSubmitGatedOnXeroStatus(unittest.TestCase):
    """A Xero DRAFT has no ledger effect in Xero, so auto_submit_inbound must
    never post it to the ERPNext GL — only AUTHORISED/PAID documents post."""

    def _doc(self):
        return SimpleNamespace(
            docstatus=0,
            doctype="Sales Invoice",
            name="SI-X",
            flags=SimpleNamespace(),
            submit=MagicMock(),
        )

    def _settings(self):
        return SimpleNamespace(get=lambda k, d=None: 1)  # auto_submit_inbound ON

    def test_draft_is_not_submitted(self):
        doc = self._doc()
        with patch("xero.api.xero_invoices.log_xero_error", MagicMock()):
            result = maybe_submit_inbound(
                doc, self._settings(), "xero-id", "Invoice", xero_status="DRAFT"
            )
        self.assertFalse(result)
        doc.submit.assert_not_called()

    def test_submitted_status_is_not_submitted(self):
        doc = self._doc()
        with patch("xero.api.xero_invoices.log_xero_error", MagicMock()):
            result = maybe_submit_inbound(
                doc, self._settings(), "xero-id", "Invoice", xero_status="SUBMITTED"
            )
        self.assertFalse(result)
        doc.submit.assert_not_called()

    def test_missing_status_is_not_submitted(self):
        doc = self._doc()
        with patch("xero.api.xero_invoices.log_xero_error", MagicMock()):
            result = maybe_submit_inbound(doc, self._settings(), "xero-id", "Invoice")
        self.assertFalse(result)
        doc.submit.assert_not_called()

    def test_authorised_is_submitted(self):
        doc = self._doc()
        with (
            patch("xero.api.xero_invoices.log_xero_error", MagicMock()),
            patch("xero.api.xero_invoices.commit_checkpoint", MagicMock()),
            patch.object(frappe.db, "set_value", MagicMock()),
        ):
            result = maybe_submit_inbound(
                doc, self._settings(), "xero-id", "Invoice", xero_status="AUTHORISED"
            )
        self.assertTrue(result)
        doc.submit.assert_called_once()
        self.assertTrue(doc.flags.ignore_xero_sync)

    def test_paid_is_submitted(self):
        doc = self._doc()
        with (
            patch("xero.api.xero_invoices.log_xero_error", MagicMock()),
            patch("xero.api.xero_invoices.commit_checkpoint", MagicMock()),
            patch.object(frappe.db, "set_value", MagicMock()),
        ):
            result = maybe_submit_inbound(
                doc, self._settings(), "xero-id", "Invoice", xero_status="PAID"
            )
        self.assertTrue(result)
        doc.submit.assert_called_once()


class TestInboundLineRate(unittest.TestCase):
    """Inbound rates must always be tax-exclusive: Inclusive Xero documents
    carry gross amounts, so the per-line tax is netted out."""

    def test_exclusive_uses_unit_amount(self):
        line = {"Quantity": 2, "UnitAmount": 100.0, "LineAmount": 200.0, "TaxAmount": 30.0}
        self.assertEqual(inbound_line_rate(line, inclusive=False), 100.0)

    def test_inclusive_nets_out_tax(self):
        # 2 x 115 gross with 30 tax -> net 200 -> rate 100
        line = {"Quantity": 2, "UnitAmount": 115.0, "LineAmount": 230.0, "TaxAmount": 30.0}
        self.assertEqual(inbound_line_rate(line, inclusive=True), 100.0)

    def test_inclusive_without_tax_amount(self):
        line = {"Quantity": 1, "UnitAmount": 115.0, "LineAmount": 115.0}
        self.assertEqual(inbound_line_rate(line, inclusive=True), 115.0)

    def test_zero_quantity_defaults_to_one(self):
        line = {"Quantity": 0, "UnitAmount": 50.0, "LineAmount": 50.0, "TaxAmount": 0}
        self.assertEqual(inbound_line_rate(line, inclusive=True), 50.0)


class _TaxDoc:
    """Doc double recording taxes rows appended by apply_inbound_taxes."""

    def __init__(self, items):
        self.items = items  # dicts: resolve_inbound_tax_account reads .get()
        self.taxes = []

    def append(self, table, row):
        self.taxes.append(row)


class TestApplyInboundTaxes(unittest.TestCase):
    def test_noop_without_tax(self):
        doc = _TaxDoc([{"item_tax_template": "VAT 15"}])
        apply_inbound_taxes(doc, {"TotalTax": 0}, "Quotation")
        self.assertEqual(doc.taxes, [])

    def test_noop_without_mapped_template(self):
        doc = _TaxDoc([{"item_tax_template": None}])
        apply_inbound_taxes(doc, {"TotalTax": 15.0}, "Quotation")
        self.assertEqual(doc.taxes, [])

    def test_sales_row_shape(self):
        doc = _TaxDoc([{"item_tax_template": "VAT 15"}])
        with patch.object(frappe.db, "get_value", return_value="VAT - X"):
            apply_inbound_taxes(doc, {"TotalTax": 15.0}, "Quotation")
        self.assertEqual(len(doc.taxes), 1)
        row = doc.taxes[0]
        self.assertEqual(row["charge_type"], "Actual")
        self.assertEqual(row["account_head"], "VAT - X")
        self.assertEqual(row["tax_amount"], 15.0)
        self.assertNotIn("category", row)

    def test_purchase_row_carries_category(self):
        for doctype in ("Purchase Invoice", "Purchase Order"):
            doc = _TaxDoc([{"item_tax_template": "VAT 15"}])
            with patch.object(frappe.db, "get_value", return_value="VAT - X"):
                apply_inbound_taxes(doc, {"TotalTax": 15.0}, doctype)
            self.assertEqual(doc.taxes[0]["category"], "Total")
            self.assertEqual(doc.taxes[0]["add_deduct_tax"], "Add")

    def test_credit_note_sign_is_negative(self):
        doc = _TaxDoc([{"item_tax_template": "VAT 15"}])
        with patch.object(frappe.db, "get_value", return_value="VAT - X"):
            apply_inbound_taxes(doc, {"TotalTax": 15.0}, "Sales Invoice", sign=-1)
        self.assertEqual(doc.taxes[0]["tax_amount"], -15.0)
