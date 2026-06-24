# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline unit tests for inbound-sync behaviour:

  * ME-3 — ERPNext->Xero account-type mapping (exact, root-type fallback, generic)
  * Opt-in auto-submit (maybe_submit_inbound) is a no-op when the setting is OFF
    and never touches an already-submitted document.

Run: bench run-tests --app xero --module xero.tests.test_inbound_behavior
"""

import unittest
from types import SimpleNamespace

from xero.api.xero_accounts import (
    XERO_ACCOUNT_TYPE_MAP,
    get_xero_type_from_erpnext,
)
from xero.api.xero_invoices import maybe_submit_inbound


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
