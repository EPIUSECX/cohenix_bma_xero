# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline unit tests for sync-status lifecycle behaviour:

  * mark_sync_failure routes permanent Xero rejections to the terminal
    "Failed" state and everything else to the retryable "Error" state.
  * Every doc-event enqueue site defers the job until the triggering
    transaction commits (enqueue_after_commit) so workers never race a
    still-uncommitted document.
  * Inbound item-code synthesis stays within Xero's 30-char Code limit so
    auto-created Items can round-trip back out.

Run: bench run-tests --app xero --module xero.tests.test_sync_status
"""

import ast
import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from xero.utils.exceptions import XeroApiError
from xero.utils.sync_status import mark_sync_failure

API_DIR = pathlib.Path(__file__).resolve().parent.parent / "api"


def _patched_helper_env():
    """Patch mark_sync_failure's collaborators; returns the patch contexts."""
    return (
        patch("xero.utils.sync_status.log_xero_error", MagicMock()),
        patch("xero.utils.sync_status.commit_error_state", MagicMock()),
        patch.object(frappe.db, "set_value", MagicMock()),
    )


class TestMarkSyncFailure(unittest.TestCase):
    def _run(self, exception, doctype="Sales Invoice", name="SI-X", **kwargs):
        p_log, p_commit, p_set = _patched_helper_env()
        with p_log as log_mock, p_commit as commit_mock, p_set as set_mock:
            status = mark_sync_failure(
                doctype, name, exception, "ERPNext to Xero", **kwargs
            )
        return status, log_mock, commit_mock, set_mock

    def test_permanent_rejection_goes_terminal_failed(self):
        e = XeroApiError("validation exception", status_code=400)
        status, log_mock, commit_mock, set_mock = self._run(e)
        self.assertEqual(status, "Failed")
        set_mock.assert_called_once_with(
            "Sales Invoice",
            "SI-X",
            {"xero_sync_status": "Failed"},
            update_modified=False,
        )
        commit_mock.assert_called_once()
        log_mock.assert_called_once()

    def test_transient_error_stays_retryable(self):
        # 429 (rate limit) is 4xx but NOT permanent — retrying can succeed.
        e = XeroApiError("rate limited", status_code=429)
        status, _, _, set_mock = self._run(e)
        self.assertEqual(status, "Error")
        self.assertEqual(
            set_mock.call_args[0][2], {"xero_sync_status": "Error"}
        )

    def test_plain_exception_stays_retryable(self):
        status, _, _, _ = self._run(Exception("connection reset"))
        self.assertEqual(status, "Error")

    def test_no_document_writes_log_only(self):
        # Inbound failures before a document exists: no status write, no
        # commit, but the log row must still be written.
        status, log_mock, commit_mock, set_mock = self._run(
            Exception("boom"), doctype="Journal Entry", name=None
        )
        self.assertEqual(status, "Error")
        set_mock.assert_not_called()
        commit_mock.assert_not_called()
        log_mock.assert_called_once()

    def test_extra_message_reaches_the_log(self):
        _, log_mock, _, _ = self._run(
            Exception("archived contact"), extra_message="Unarchive it first."
        )
        self.assertIn(
            "Unarchive it first.", log_mock.call_args.kwargs["message"]
        )

    def test_source_entity_names_the_message(self):
        _, log_mock, _, _ = self._run(
            Exception("boom"),
            doctype="Journal Entry",
            name="JE-1",
            source_type="Xero Manual Journal",
            source_id="mj-uuid",
        )
        kwargs = log_mock.call_args.kwargs
        self.assertIn("Xero Manual Journal", kwargs["message"])
        self.assertEqual(kwargs["erpnext_doc_name"], "JE-1")


class TestEnqueueAfterCommit(unittest.TestCase):
    """Every frappe.enqueue call in xero/api must carry
    enqueue_after_commit=True: doc-event hooks fire mid-transaction, and a
    worker that starts before the commit reads a document that does not
    exist yet (or survives a rollback that dropped it)."""

    def test_every_api_enqueue_site_defers_until_commit(self):
        offenders = []
        for path in sorted(API_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "enqueue"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "frappe"
                ):
                    continue
                deferred = any(
                    kw.arg == "enqueue_after_commit"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                    for kw in node.keywords
                )
                if not deferred:
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(
            offenders,
            [],
            f"frappe.enqueue without enqueue_after_commit=True at: {offenders}",
        )

    def test_journal_hook_passes_after_commit_kwarg(self):
        # Behavioural spot-check that the kwarg actually reaches
        # frappe.enqueue (the AST test can't see runtime call plumbing).
        from xero.api.xero_journals import enqueue_sync_journal

        settings = SimpleNamespace(
            enable_xero_sync=1, get=lambda k, d=None: 1
        )
        doc = SimpleNamespace(name="JE-1", doctype="Journal Entry")
        with (
            patch("xero.api.xero_journals.get_xero_settings", return_value=settings),
            patch.object(frappe, "enqueue", MagicMock()) as enqueue_mock,
        ):
            enqueue_sync_journal(doc, "on_submit")
        self.assertTrue(enqueue_mock.called)
        self.assertTrue(
            enqueue_mock.call_args.kwargs.get("enqueue_after_commit")
        )


class TestInboundItemCodeClamp(unittest.TestCase):
    """Synthesised item codes must fit Xero's 30-char Code limit, including
    any dedup suffix, or the auto-created Item can never sync back out."""

    LIMIT = 30

    def _create(self, description, existing=()):
        from xero.api.xero_items import get_or_create_item_for_xero_line

        existing = set(existing)

        def fake_exists(doctype, name):
            return name in existing

        with (
            patch.object(frappe.db, "exists", side_effect=fake_exists),
            patch.object(frappe.db, "get_value", return_value=None),
            patch("xero.api.xero_items.frappe.new_doc") as new_doc_mock,
            patch("xero.api.xero_items.log_xero_error", MagicMock()),
        ):
            doc = MagicMock()
            new_doc_mock.return_value = doc
            code = get_or_create_item_for_xero_line(None, description)
        return code

    def test_long_description_is_clamped(self):
        code = self._create("Widget amended in Xero with an extremely long descriptive name")
        self.assertLessEqual(len(code), self.LIMIT)
        self.assertTrue(code.startswith("XERO-"))

    def test_exact_31_char_slug_is_clamped(self):
        # The historical stuck case: a 31-char synthesised code.
        code = self._create("RT3 Widget amended in Xero")
        self.assertLessEqual(len(code), self.LIMIT)

    def test_dedup_suffix_stays_within_limit(self):
        long_desc = "Widget amended in Xero with an extremely long descriptive name"
        first = self._create(long_desc)
        second = self._create(long_desc, existing={first})
        self.assertLessEqual(len(second), self.LIMIT)
        self.assertNotEqual(first, second)
        self.assertTrue(second.endswith("-1"))

    def test_short_codes_pass_through_unchanged(self):
        code = self._create("Pen")
        self.assertEqual(code, "XERO-Pen")


if __name__ == "__main__":
    unittest.main()
