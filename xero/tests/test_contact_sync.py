# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline round-trip tests for one full entity sync: Customer <-> Xero Contact.

The Xero HTTP layer (xero_request) and the commit helpers are mocked, and every
document written is rolled back, so these tests run on any site without a Xero
connection and leave no trace. Covered:

  * outbound create — PUT with a clean payload (no fabricated FirstName for
    company-only parties), idempotency key, and Synced/id/hash stored on success
  * outbound update — POST with ContactID once the contact is linked
  * master switch and per-direction toggle short-circuits
  * enqueue guards — hash short-circuit when nothing changed, re-queue when
    data changed, and the inbound-write suppression flag (loop prevention)
  * inbound create — Customer materialised from a Xero contact with the id,
    status, hash, and disabled mapping set, without re-firing outbound sync

Run: bench run-tests --app xero --module xero.tests.test_contact_sync
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from xero.api.xero_contacts import (
    build_contact_number,
    compute_data_hash,
    enqueue_sync_contact,
    parse_erpnext_reference,
    sync_contact_to_xero,
    sync_xero_contact_to_erpnext,
)
from xero.utils.logging import get_leaf_doctype_value

OUTBOUND_CUSTOMER = "_Test Xero Outbound Customer"
INBOUND_CUSTOMER = "_Test Xero Inbound Customer"
CONTACT_ID = "11111111-2222-3333-4444-555555555555"
SYNC_JOB = "xero.api.xero_contacts.sync_contact_to_xero"


def _settings(**overrides):
    """Xero Settings double: attribute access plus .get(), both toggles on."""
    values = {"enable_xero_sync": 1, "sync_contacts_to_xero": 1}
    values.update(overrides)
    settings = SimpleNamespace(**values)
    settings.get = lambda key, default=None: values.get(key, default)
    return settings


def _delete_if_exists(customer_name):
    existing = frappe.db.get_value("Customer", {"customer_name": customer_name})
    if existing:
        frappe.delete_doc("Customer", existing, force=1, ignore_permissions=True)


def _xero_sync_enqueued(enqueue_mock):
    """True if any frappe.enqueue call targeted the outbound contact sync job."""
    return any(
        (call.args and call.args[0] == SYNC_JOB) or call.kwargs.get("method") == SYNC_JOB
        for call in enqueue_mock.call_args_list
    )


class ContactSyncCase(unittest.TestCase):
    """Shared fixture: a real, uncommitted Customer with the outbound hook
    suppressed during setup; everything is rolled back after each test."""

    def setUp(self):
        self.addCleanup(frappe.db.rollback)
        _delete_if_exists(OUTBOUND_CUSTOMER)
        doc = frappe.new_doc("Customer")
        doc.customer_name = OUTBOUND_CUSTOMER
        doc.customer_type = "Company"
        doc.customer_group = get_leaf_doctype_value(
            "Customer Group", frappe.db.get_default("customer_group")
        )
        doc.territory = get_leaf_doctype_value(
            "Territory", frappe.db.get_default("territory")
        )
        doc.flags.ignore_xero_sync = True
        doc.insert(ignore_permissions=True)
        self.customer = doc


class TestOutboundContactSync(ContactSyncCase):
    def _sync(self, settings=None, response=None):
        if response is None:
            response = {"Contacts": [{"ContactID": CONTACT_ID, "Name": OUTBOUND_CUSTOMER}]}
        with patch("xero.api.xero_contacts.get_xero_settings",
                   return_value=settings or _settings()), \
             patch("xero.api.xero_contacts.xero_request",
                   return_value=response) as request, \
             patch("xero.api.xero_contacts.commit_external_outcome") as commit, \
             patch("xero.api.xero_contacts.commit_error_state"), \
             patch("xero.api.xero_contacts.log_xero_error") as log:
            sync_contact_to_xero(self.customer.name, "Customer")
        return SimpleNamespace(request=request, commit=commit, log=log)

    def test_create_sends_put_with_clean_payload_and_links_contact(self):
        mocks = self._sync()

        mocks.request.assert_called_once()
        method, endpoint = mocks.request.call_args.args
        self.assertEqual(method, "PUT")  # create; POST is reserved for updates
        self.assertEqual(endpoint, "Contacts")
        self.assertEqual(
            mocks.request.call_args.kwargs["idempotency_key"],
            f"Customer:{self.customer.name}:create",
        )

        payload = mocks.request.call_args.kwargs["data"]["Contacts"][0]
        self.assertEqual(payload["Name"], OUTBOUND_CUSTOMER)
        self.assertEqual(payload["ContactNumber"], f"ERP:C:{self.customer.name}")
        self.assertEqual(payload["ContactStatus"], "ACTIVE")
        # Company-only party: no person fields may be invented from the org
        # name — a fabricated FirstName round-trips into a bogus ERP Contact.
        self.assertNotIn("FirstName", payload)
        self.assertNotIn("LastName", payload)

        stored = frappe.db.get_value(
            "Customer", self.customer.name,
            ["xero_contact_id", "xero_sync_status", "xero_data_hash"], as_dict=True,
        )
        self.assertEqual(stored.xero_contact_id, CONTACT_ID)
        self.assertEqual(stored.xero_sync_status, "Synced")
        self.assertEqual(
            stored.xero_data_hash,
            compute_data_hash(frappe.get_doc("Customer", self.customer.name)),
        )
        # The successful external write must be persisted via the commit helper.
        mocks.commit.assert_called_once()

    def test_update_sends_post_with_contact_id(self):
        frappe.db.set_value(
            "Customer", self.customer.name,
            {"xero_contact_id": CONTACT_ID, "xero_sync_status": "Synced"},
            update_modified=False,
        )
        mocks = self._sync()

        method, _ = mocks.request.call_args.args
        self.assertEqual(method, "POST")  # update; PUT would reject a name match
        payload = mocks.request.call_args.kwargs["data"]["Contacts"][0]
        self.assertEqual(payload["ContactID"], CONTACT_ID)
        self.assertIsNone(mocks.request.call_args.kwargs["idempotency_key"])

    def test_master_switch_off_sends_nothing(self):
        mocks = self._sync(settings=_settings(enable_xero_sync=0))
        mocks.request.assert_not_called()
        mocks.commit.assert_not_called()

    def test_direction_toggle_off_skips_with_info_log(self):
        mocks = self._sync(settings=_settings(sync_contacts_to_xero=0))
        mocks.request.assert_not_called()
        self.assertEqual(mocks.log.call_args.kwargs.get("status"), "Info")


class TestEnqueueGuards(ContactSyncCase):
    def test_synced_and_unchanged_is_not_requeued(self):
        frappe.db.set_value(
            "Customer", self.customer.name,
            {
                "xero_sync_status": "Synced",
                "xero_data_hash": compute_data_hash(
                    frappe.get_doc("Customer", self.customer.name)
                ),
            },
            update_modified=False,
        )
        with patch("xero.api.xero_contacts.frappe.enqueue") as enqueue, \
             patch("xero.api.xero_contacts.frappe.publish_realtime"):
            enqueue_sync_contact(self.customer.name, "Customer")
        self.assertFalse(_xero_sync_enqueued(enqueue))

    def test_synced_but_changed_is_requeued(self):
        frappe.db.set_value(
            "Customer", self.customer.name,
            {"xero_sync_status": "Synced", "xero_data_hash": "stale"},
            update_modified=False,
        )
        with patch("xero.api.xero_contacts.frappe.enqueue") as enqueue, \
             patch("xero.api.xero_contacts.frappe.publish_realtime"):
            enqueue_sync_contact(self.customer.name, "Customer")
        self.assertTrue(_xero_sync_enqueued(enqueue))

    def test_inbound_write_flag_suppresses_hook(self):
        # The inbound sync sets this flag before saving so the on_update hook
        # does not bounce the same data straight back to Xero (loop prevention).
        doc = frappe.get_doc("Customer", self.customer.name)
        doc.flags.ignore_xero_sync = True
        with patch("xero.api.xero_contacts.frappe.enqueue") as enqueue, \
             patch("xero.api.xero_contacts.frappe.publish_realtime"):
            enqueue_sync_contact(doc, "on_update")
        self.assertFalse(_xero_sync_enqueued(enqueue))


class TestInboundContactSync(unittest.TestCase):
    def setUp(self):
        self.addCleanup(frappe.db.rollback)
        _delete_if_exists(INBOUND_CUSTOMER)

    def _process(self, **payload_overrides):
        payload = {
            "ContactID": CONTACT_ID,
            "Name": INBOUND_CUSTOMER,
            "ContactStatus": "ACTIVE",
            "TaxNumber": "4111111111",
        }
        payload.update(payload_overrides)
        with patch("xero.api.xero_contacts.commit_checkpoint") as checkpoint, \
             patch("xero.api.xero_contacts.log_xero_error"), \
             patch("xero.api.xero_contacts.frappe.enqueue") as enqueue:
            sync_xero_contact_to_erpnext(payload, "Customer")
        return SimpleNamespace(checkpoint=checkpoint, enqueue=enqueue)

    def test_creates_customer_without_refiring_outbound(self):
        mocks = self._process()

        name = frappe.db.get_value("Customer", {"xero_contact_id": CONTACT_ID})
        self.assertTrue(name, "inbound sync did not create the Customer")
        stored = frappe.db.get_value(
            "Customer", name,
            ["customer_name", "tax_id", "disabled", "xero_sync_status", "xero_data_hash"],
            as_dict=True,
        )
        self.assertEqual(stored.customer_name, INBOUND_CUSTOMER)
        self.assertEqual(stored.tax_id, "4111111111")
        self.assertEqual(stored.disabled, 0)
        self.assertEqual(stored.xero_sync_status, "Synced")
        # The hash must be stored on the inbound path so a later genuine
        # ERPNext edit is detected instead of short-circuited.
        self.assertTrue(stored.xero_data_hash)
        # Per-document checkpoint persisted through the helper.
        mocks.checkpoint.assert_called_once()
        # The insert fires the Customer on_update hook; the suppression flag
        # must stop it from enqueueing an outbound echo of the same data.
        self.assertFalse(_xero_sync_enqueued(mocks.enqueue))

    def test_archived_contact_maps_to_disabled(self):
        self._process(ContactStatus="ARCHIVED")
        name = frappe.db.get_value("Customer", {"xero_contact_id": CONTACT_ID})
        self.assertEqual(frappe.db.get_value("Customer", name, "disabled"), 1)


class TestContactNumberReference(unittest.TestCase):
    def test_customer_reference_round_trips(self):
        number = build_contact_number("Customer", "CUST-001")
        self.assertEqual(number, "ERP:C:CUST-001")
        self.assertEqual(parse_erpnext_reference(number), ("Customer", "CUST-001"))

    def test_supplier_reference_round_trips(self):
        self.assertEqual(
            parse_erpnext_reference(build_contact_number("Supplier", "SUP-001")),
            ("Supplier", "SUP-001"),
        )

    def test_foreign_contact_numbers_are_ignored(self):
        self.assertEqual(parse_erpnext_reference("12345"), (None, None))
        self.assertEqual(parse_erpnext_reference(None), (None, None))
        self.assertEqual(parse_erpnext_reference("ERP:C:a:b"), (None, None))


if __name__ == "__main__":
    unittest.main()
