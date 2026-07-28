# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline unit tests for outbound retry coverage and Account update payloads:

  * sync_pending_documents re-queues Customers, Suppliers and Accounts stuck
    in Pending/Error (it previously only covered transactional documents, so
    a party or account that hit a transient error was never healed).
  * Account update payloads omit Status — Xero rejects any request that
    changes account details and Status together — and a mismatched Status is
    reconciled by a follow-up Status-only request.

Run: bench run-tests --app xero --module xero.tests.test_pending_retry
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from xero.api.xero_accounts import build_xero_account_payload

RETRYABLE = ["in", ["Pending", "Error"]]


def _settings(**toggles):
    return SimpleNamespace(
        enable_xero_sync=1, get=lambda k, d=None: toggles.get(k, 0)
    )


class TestPendingRetryCoverage(unittest.TestCase):
    """The hourly sweep must retry every outbound doctype, with filters that
    exclude terminal statuses (Failed, Skipped) and unsyncable accounts."""

    def _run_sweep(self, settings, rows_by_doctype=None):
        from xero.tasks import sync_pending_documents

        rows_by_doctype = rows_by_doctype or {}
        get_all_calls = {}

        def fake_get_all(doctype, filters=None, fields=None, **kwargs):
            get_all_calls[doctype] = filters
            return [
                SimpleNamespace(name=n) for n in rows_by_doctype.get(doctype, [])
            ]

        with (
            patch("xero.tasks.get_xero_settings", return_value=settings),
            patch("xero.tasks.log_xero_error", MagicMock()),
            patch.object(frappe, "get_all", side_effect=fake_get_all),
            patch.object(frappe, "enqueue", MagicMock()) as enqueue_mock,
        ):
            sync_pending_documents()
        return get_all_calls, enqueue_mock

    def test_customers_and_suppliers_are_retried(self):
        calls, enqueue_mock = self._run_sweep(
            _settings(sync_contacts_to_xero=1),
            rows_by_doctype={"Customer": ["CUST-1"], "Supplier": ["SUPP-1"]},
        )
        self.assertEqual(calls["Customer"], {"xero_sync_status": RETRYABLE})
        self.assertEqual(calls["Supplier"], {"xero_sync_status": RETRYABLE})
        queued = {
            (c.args[0], c.kwargs.get("doc_name"), c.kwargs.get("doc_type"))
            for c in enqueue_mock.call_args_list
        }
        self.assertIn(
            ("xero.api.xero_contacts.sync_contact_to_xero", "CUST-1", "Customer"),
            queued,
        )
        self.assertIn(
            ("xero.api.xero_contacts.sync_contact_to_xero", "SUPP-1", "Supplier"),
            queued,
        )

    def test_accounts_are_retried_with_safe_filters(self):
        calls, enqueue_mock = self._run_sweep(
            _settings(enable_sync_to_xero=1),
            rows_by_doctype={"Account": ["Debtors - J"]},
        )
        self.assertEqual(
            calls["Account"],
            {"is_group": 0, "disabled": 0, "xero_sync_status": RETRYABLE},
        )
        call = enqueue_mock.call_args_list[0]
        self.assertEqual(call.args[0], "xero.api.xero_accounts.sync_account_to_xero")
        self.assertEqual(call.kwargs["account_name"], "Debtors - J")

    def test_toggles_gate_the_new_blocks(self):
        calls, enqueue_mock = self._run_sweep(_settings())
        for doctype in ("Customer", "Supplier", "Account"):
            self.assertNotIn(doctype, calls)
        enqueue_mock.assert_not_called()

    def test_no_query_ever_includes_terminal_statuses(self):
        all_on = _settings(
            sync_contacts_to_xero=1,
            enable_sync_to_xero=1,
            sync_invoices_to_xero=1,
            sync_bills_to_xero=1,
            sync_items_to_xero=1,
            sync_payments_to_xero=1,
            sync_journal_entries=1,
            sync_purchase_orders=1,
            sync_quotes=1,
        )
        calls, _ = self._run_sweep(all_on)
        self.assertGreaterEqual(len(calls), 10)
        for doctype, filters in calls.items():
            self.assertEqual(
                filters.get("xero_sync_status"),
                RETRYABLE,
                f"{doctype} sweep filter must retry Pending/Error only",
            )


class TestAccountPayloadStatusSplit(unittest.TestCase):
    """Xero rejects details+Status in a single account update, so update
    payloads must omit Status; creates still declare it."""

    def _doc(self, **overrides):
        doc = frappe._dict(
            account_name="Marketing Costs",
            account_number="6100",
            name="Marketing Costs - J",
            root_type="Expense",
            account_type="",
            xero_account_type="EXPENSE",
            xero_account_id=None,
            disabled=0,
        )
        doc.update(overrides)
        return doc

    def test_create_payload_declares_status(self):
        payload = build_xero_account_payload(self._doc(), _settings())
        self.assertEqual(payload["Status"], "ACTIVE")

    def test_create_payload_maps_disabled_to_archived(self):
        payload = build_xero_account_payload(self._doc(disabled=1), _settings())
        self.assertEqual(payload["Status"], "ARCHIVED")

    def test_update_payload_omits_status(self):
        payload = build_xero_account_payload(
            self._doc(xero_account_id="acc-uuid"), _settings(), is_update=True
        )
        self.assertNotIn("Status", payload)
        self.assertEqual(payload["AccountID"], "acc-uuid")


class TestStatusFollowUp(unittest.TestCase):
    """After a successful details update, a Status mismatch (e.g. the account
    was disabled in ERPNext) is reconciled with a Status-only request."""

    def _sync(self, disabled, response_status):
        from xero.api import xero_accounts

        doc = MagicMock()
        doc.is_group = 0
        doc.name = "Marketing Costs - J"
        doc.xero_account_id = "acc-uuid"
        doc.disabled = disabled

        requests = []

        def fake_xero_request(method, endpoint, data=None, **kwargs):
            requests.append((method, endpoint, data))
            return {"Accounts": [{"AccountID": "acc-uuid", "Status": response_status}]}

        settings = SimpleNamespace(
            enable_xero_sync=1, enable_sync_to_xero=1, get=lambda k, d=None: 1
        )

        # Scope the get_doc double to Account: frappe internals (System
        # Settings cache and friends) must keep the real implementation.
        real_get_doc = frappe.get_doc

        def fake_get_doc(doctype, *args, **kwargs):
            if doctype == "Account":
                return doc
            return real_get_doc(doctype, *args, **kwargs)

        with (
            patch.object(frappe, "get_doc", side_effect=fake_get_doc),
            patch("xero.api.xero_accounts.get_xero_settings", return_value=settings),
            patch("xero.api.xero_accounts.build_xero_account_payload",
                  return_value={"AccountID": "acc-uuid", "Name": "Marketing Costs"}),
            patch("xero.api.xero_accounts.xero_request", side_effect=fake_xero_request),
            patch("xero.api.xero_accounts.compute_account_hash", return_value="h"),
            patch("xero.api.xero_accounts.log_xero_error", MagicMock()),
        ):
            xero_accounts.sync_account_to_xero(doc.name)
        return requests

    def test_mismatch_triggers_status_only_follow_up(self):
        requests = self._sync(disabled=1, response_status="ACTIVE")
        self.assertEqual(len(requests), 2)
        method, endpoint, data = requests[1]
        self.assertEqual(method, "POST")
        self.assertEqual(endpoint, "Accounts/acc-uuid")
        self.assertEqual(
            data, {"Accounts": [{"AccountID": "acc-uuid", "Status": "ARCHIVED"}]}
        )

    def test_matching_status_needs_no_follow_up(self):
        requests = self._sync(disabled=0, response_status="ACTIVE")
        self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
