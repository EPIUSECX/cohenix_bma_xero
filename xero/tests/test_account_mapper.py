# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline unit tests for account-mapping guardrails:

  * XERO_SYSTEM_ACCOUNTS covers the full documented SystemAccount enum, so
    system accounts (e.g. 801 "Unpaid Expense Claims") are never candidates
    for auto-mapping or sync.
  * The type-only (Low confidence) matching fallback never picks an ERPNext
    control account (Receivable/Payable) and is disabled entirely for Xero
    system accounts.
  * run_full_auto_map persists only Medium+ matches — Low guesses are
    report-only because wrong mapping rows are sticky.
  * Journal-line code resolution prefers a linked account's own code over a
    contradicting mapping row, with a Warning naming both codes.

Run: bench run-tests --app xero --module xero.tests.test_account_mapper
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from xero.api.xero_accounts import XERO_SYSTEM_ACCOUNTS
from xero.utils.account_mapper import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    _find_best_erpnext_match,
)


def _erpnext_acc(name, root_type, account_type="", account_number=None):
    return {
        "name": name,
        "account_name": name.rsplit(" - ", 1)[0],
        "account_number": account_number,
        "root_type": root_type,
        "account_type": account_type,
        "xero_account_id": None,
    }


class TestSystemAccountList(unittest.TestCase):
    """The list must match Xero's documented SystemAccount enum — a missing
    code lets the auto-mapper map ERPNext accounts onto Xero internals."""

    def test_documented_codes_present(self):
        expected = {
            "DEBTORS", "CREDITORS", "BANKCURRENCYGAIN", "GST", "GSTONIMPORTS",
            "HISTORICAL", "REALISEDCURRENCYGAIN", "UNREALISEDCURRENCYGAIN",
            "RETAINEDEARNINGS", "ROUNDING", "TRACKINGTRANSFERS", "UNPAIDEXPCLM",
            "WAGEPAYABLES", "CISASSETS", "CISASSET", "CISLABOUR",
            "CISLABOUREXPENSE", "CISLABOURINCOME", "CISLIABILITY", "CISMATERIALS",
        }
        self.assertEqual(set(XERO_SYSTEM_ACCOUNTS), expected)

    def test_non_system_markers_excluded(self):
        # Non-system accounts carry SystemAccount == "" or None; membership
        # checks on those must be False or every account would be filtered.
        self.assertNotIn("", XERO_SYSTEM_ACCOUNTS)
        self.assertNotIn(None, XERO_SYSTEM_ACCOUNTS)


class TestTierFiveGuard(unittest.TestCase):
    """Type-only (Low) fallback must never guess control accounts or match
    for Xero system accounts; exact matches (High) are unaffected."""

    def test_type_only_never_picks_control_account(self):
        accounts = [_erpnext_acc("Creditors - J", "Liability", "Payable")]
        name, confidence = _find_best_erpnext_match(
            "uuid-801", "801", "Unpaid Expense Claims", "CURRLIAB",
            accounts, claimed=set(), company="J",
        )
        self.assertIsNone(name)
        self.assertIsNone(confidence)

    def test_type_only_disabled_for_system_accounts(self):
        accounts = [_erpnext_acc("Sundry Liability - J", "Liability")]
        name, confidence = _find_best_erpnext_match(
            "uuid-801", "801", "Unpaid Expense Claims", "CURRLIAB",
            accounts, claimed=set(), company="J",
            xero_system_account="UNPAIDEXPCLM",
        )
        self.assertIsNone(name)
        self.assertIsNone(confidence)

    def test_type_only_still_matches_plain_accounts(self):
        accounts = [_erpnext_acc("Sundry Liability - J", "Liability")]
        name, confidence = _find_best_erpnext_match(
            "uuid-9", "290", "Deferred Revenue", "CURRLIAB",
            accounts, claimed=set(), company="J",
        )
        self.assertEqual(name, "Sundry Liability - J")
        self.assertEqual(confidence, CONFIDENCE_LOW)

    def test_exact_code_match_on_control_account_still_high(self):
        accounts = [
            _erpnext_acc("Creditors - J", "Liability", "Payable", account_number="800")
        ]
        name, confidence = _find_best_erpnext_match(
            "uuid-800", "800", "Accounts Payable", "CURRLIAB",
            accounts, claimed=set(), company="J",
        )
        self.assertEqual(name, "Creditors - J")
        self.assertEqual(confidence, CONFIDENCE_HIGH)


class TestAutoMapPersistence(unittest.TestCase):
    """run_full_auto_map writes only Medium+ rows; Low stays report-only."""

    def test_low_confidence_rows_are_not_written(self):
        from xero.utils import account_mapper

        settings = SimpleNamespace(
            access_token="t", tenant_id="tid",
            account_mapping=[
                SimpleNamespace(xero_account_code="100", erpnext_account="A - Co")
            ],
        )
        matched = [
            {"erpnext_account": "A - Co", "xero_code": "100", "xero_name": "A",
             "confidence": "High"},
            {"erpnext_account": "B - Co", "xero_code": "200", "xero_name": "B",
             "confidence": "Medium"},
            {"erpnext_account": "C - Co", "xero_code": "300", "xero_name": "C",
             "confidence": "Low"},
        ]
        written = {}

        def fake_bulk_write(settings_arg, rows, codes, erpnext):
            written["rows"] = list(rows)
            return len(rows)

        with (
            patch("xero.utils.xero_client.require_xero_manager", MagicMock()),
            patch("xero.utils.account_mapper.get_xero_settings", return_value=settings),
            patch("xero.utils.account_mapper._fetch_xero_accounts", return_value=[]),
            patch("xero.utils.account_mapper._fetch_erpnext_accounts", return_value=[]),
            patch("xero.utils.account_mapper._load_existing_mappings",
                  return_value=(set(), set(), [])),
            patch("xero.utils.account_mapper._run_matching",
                  return_value=(matched, [], [], [])),
            patch("xero.utils.account_mapper._create_missing_accounts", MagicMock()),
            patch("xero.utils.account_mapper._bulk_write_mappings",
                  side_effect=fake_bulk_write),
            patch("xero.utils.account_mapper.log_xero_error", MagicMock()),
            patch.object(frappe.db, "get_default", return_value="Co"),
            patch.object(frappe.db, "set_single_value", MagicMock()),
        ):
            result = account_mapper.run_full_auto_map()

        self.assertEqual([r["xero_code"] for r in written["rows"]], ["100", "200"])
        self.assertEqual(result["summary"]["low_confidence_skipped"], 1)


class TestJournalCodeConflict(unittest.TestCase):
    """A mapping row that contradicts a linked account's own code loses, and
    the conflict is logged as a Warning naming both codes."""

    def _resolve(self, mapped_code, account_number, xero_account_id):
        from xero.api import xero_journals

        logs = []
        account_map = {"Creditors - J": mapped_code} if mapped_code else {}
        with (
            patch.object(frappe.db, "get_value",
                         return_value=(account_number, xero_account_id)),
            patch("xero.api.xero_journals.log_xero_error",
                  side_effect=lambda **kwargs: logs.append(kwargs)),
        ):
            code = xero_journals.resolve_line_account_code(
                "Creditors - J", account_map, "Journal Entry", "JE-1"
            )
        return code, logs

    def test_conflicting_mapping_row_loses_to_linked_code(self):
        code, logs = self._resolve("801", "CreditorsJ", "acc-uuid")
        self.assertEqual(code, "CreditorsJ")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["status"], "Warning")
        self.assertIn("801", logs[0]["message"])
        self.assertIn("CreditorsJ", logs[0]["message"])

    def test_mapping_row_wins_when_account_not_linked(self):
        code, logs = self._resolve("801", "CreditorsJ", None)
        self.assertEqual(code, "801")
        self.assertEqual(logs, [])

    def test_agreeing_codes_do_not_warn(self):
        code, logs = self._resolve("CreditorsJ", "CreditorsJ", "acc-uuid")
        self.assertEqual(code, "CreditorsJ")
        self.assertEqual(logs, [])

    def test_account_number_fallback_without_mapping(self):
        code, logs = self._resolve(None, "6100", None)
        self.assertEqual(code, "6100")
        self.assertEqual(logs, [])


if __name__ == "__main__":
    unittest.main()
