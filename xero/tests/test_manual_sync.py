# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline tests for the desk "Sync to Xero" buttons.

Every one of these buttons was dead before this suite existed: three named a
function that did not exist, two called a function that was never whitelisted,
and two passed argument names the function did not declare. Nothing failed at
import time and no test covered them, so the breakage was invisible until a
user clicked.

The wiring tests below close that gap by resolving the JS ``method:`` strings
and the SYNC_HANDLERS table against the real functions, so a rename or a typo
fails the suite instead of a button. ``frappe.enqueue`` is patched throughout —
no job is queued and no Xero call is made.

Run: bench run-tests --app xero --module xero.tests.test_manual_sync
"""

import os
import re
import unittest
from unittest.mock import patch

import frappe

import xero.api.manual_sync as manual_sync

# .../apps/xero — the repo root, which hook paths like "xero/public/js/x.js"
# are relative to. manual_sync lives at <root>/xero/api/manual_sync.py.
APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(manual_sync.__file__))))

# method: 'xero.some.path'  /  method: "xero.some.path"
METHOD_RE = re.compile(r"""method\s*:\s*["'](xero\.[A-Za-z0-9_.]+)["']""")


def iter_js_files():
    for root, dirs, files in os.walk(os.path.join(APP_ROOT, "xero")):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "__pycache__", "dist")]
        for name in files:
            if name.endswith(".js"):
                yield os.path.join(root, name)


class TestButtonWiring(unittest.TestCase):
    """Static checks — no DB writes, no network."""

    def test_every_js_method_string_resolves_to_a_whitelisted_function(self):
        """A button may only call a function that exists AND is HTTP-reachable."""
        unresolved = []
        for path in iter_js_files():
            with open(path, encoding="utf-8") as fh:
                for dotted in METHOD_RE.findall(fh.read()):
                    try:
                        fn = frappe.get_attr(dotted)
                    except Exception:
                        unresolved.append(f"{os.path.basename(path)}: {dotted} does not exist")
                        continue
                    if fn not in frappe.whitelisted:
                        unresolved.append(f"{os.path.basename(path)}: {dotted} is not whitelisted")
        self.assertEqual(unresolved, [], "JS calls unreachable server methods: " + "; ".join(unresolved))

    def test_every_sync_handler_target_exists(self):
        for doctype, dotted in manual_sync.SYNC_HANDLERS.items():
            with self.subTest(doctype=doctype):
                self.assertTrue(callable(frappe.get_attr(dotted)), f"{dotted} is not callable")

    def test_sync_handler_doctypes_exist(self):
        for doctype in manual_sync.SYNC_HANDLERS:
            with self.subTest(doctype=doctype):
                self.assertTrue(
                    frappe.db.exists("DocType", doctype),
                    f"{doctype} is not a DocType — a doctype_js entry for it would never load",
                )

    def test_doctype_js_targets_exist(self):
        """A doctype_js entry for a missing doctype or file is silently dead."""
        problems = []
        for doctype, paths in (frappe.get_hooks(app_name="xero").get("doctype_js") or {}).items():
            if not frappe.db.exists("DocType", doctype):
                problems.append(f"{doctype}: not a DocType")
            # get_hooks aggregates values into a list, even for a single entry.
            for relpath in (paths if isinstance(paths, list) else [paths]):
                if not os.path.exists(os.path.join(APP_ROOT, relpath)):
                    problems.append(f"{doctype}: missing file {relpath}")
        self.assertEqual(problems, [], "; ".join(problems))

    def test_hook_handlers_are_not_http_exposed(self):
        """The (doc, method) handlers cannot be called from a browser."""
        for dotted in set(manual_sync.SYNC_HANDLERS.values()):
            with self.subTest(handler=dotted):
                self.assertNotIn(
                    frappe.get_attr(dotted),
                    frappe.whitelisted,
                    f"{dotted} takes a Document; whitelisting it exposes a call that can only fail",
                )


class TestSyncDocumentToXero(unittest.TestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        enqueue_patch = patch("frappe.enqueue")
        self.enqueue = enqueue_patch.start()
        self.addCleanup(enqueue_patch.stop)
        self.addCleanup(frappe.db.rollback)

    def _an_item(self):
        names = frappe.get_all("Item", limit=1, pluck="name")
        if not names:
            self.skipTest("no Item on this site")
        return names[0]

    def test_rejects_non_string_docname(self):
        """A filter dict must not select the document that gets synced.

        frappe.get_doc(doctype, {"docstatus": 1}) treats the dict as filters and
        loads whichever row matches, while has_permission() only resolves
        str/int — so without this guard the permission-checked document and the
        synced document are different documents.
        """
        with self.assertRaises(frappe.PermissionError):
            manual_sync.sync_document_to_xero("Sales Invoice", {"docstatus": 1})
        self.enqueue.assert_not_called()

    def test_rejects_non_string_doctype(self):
        with self.assertRaises(frappe.PermissionError):
            manual_sync.sync_document_to_xero(["Sales Invoice"], "anything")
        self.enqueue.assert_not_called()

    def test_rejects_unsupported_doctype(self):
        """Bank Transaction is excluded on purpose — syncing it double-counts."""
        with self.assertRaises(frappe.ValidationError):
            manual_sync.sync_document_to_xero("Bank Transaction", "whatever")
        self.enqueue.assert_not_called()

    def test_requires_a_xero_role(self):
        user = frappe.get_all(
            "User",
            filters={"enabled": 1, "name": ("not in", ["Administrator", "Guest"])},
            limit=1,
            pluck="name",
        )
        if not user:
            self.skipTest("no non-admin user on this site")
        roles = set(frappe.get_roles(user[0]))
        if roles & {"Xero Integration Manager", "System Manager"}:
            self.skipTest(f"{user[0]} already holds a Xero management role")
        frappe.set_user(user[0])
        self.addCleanup(frappe.set_user, "Administrator")
        with self.assertRaises(frappe.PermissionError):
            manual_sync.sync_document_to_xero("Item", self._an_item())
        self.enqueue.assert_not_called()

    def test_refuses_when_master_switch_is_off(self):
        item = self._an_item()
        with patch.object(manual_sync, "get_xero_settings") as settings:
            settings.return_value = frappe._dict(enable_xero_sync=0)
            with self.assertRaises(frappe.ValidationError):
                manual_sync.sync_document_to_xero("Item", item)
        self.enqueue.assert_not_called()

    def test_queues_the_sync_and_returns_a_message(self):
        item = self._an_item()
        with patch.object(manual_sync, "get_xero_settings") as settings:
            settings.return_value = frappe._dict(enable_xero_sync=1, sync_items=1)
            message = manual_sync.sync_document_to_xero("Item", item)
        self.assertIn(item, message)
        self.assertTrue(self.enqueue.called, "expected an outbound sync job to be queued")

    def test_return_invoice_routes_to_the_credit_note_sync(self):
        """Replaces the deleted credit_note.js: a return is a Xero credit note."""
        name = frappe.get_all(
            "Sales Invoice", filters={"docstatus": 1, "is_return": 1}, limit=1, pluck="name"
        )
        if not name:
            self.skipTest("no submitted Sales Invoice return on this site")
        manual_sync.sync_document_to_xero("Sales Invoice", name[0])
        queued = [c.args[0] for c in self.enqueue.call_args_list if c.args]
        self.assertIn("xero.api.xero_credit_notes.sync_return_to_xero", queued)
