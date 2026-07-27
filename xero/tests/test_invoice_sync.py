# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline unit tests for invoice sync building blocks:

  * outbound field validation/sanitisation (description, invoice number,
    reference — Xero length and character limits)
  * change-detection hashing (invoice_data_changed short-circuit)

Run: bench run-tests --app xero --module xero.tests.test_invoice_sync
"""

import unittest
from types import SimpleNamespace

from xero.api.xero_invoices import (
    compute_invoice_hash,
    invoice_data_changed,
    validate_invoice_number,
    validate_invoice_reference,
)
from xero.api.xero_line_builder import validate_invoice_description


def _invoice_double(**overrides):
    """A minimal document double carrying the fields compute_invoice_hash reads,
    answering both attribute access and .get() like a frappe document."""
    fields = {
        "posting_date": "2024-01-15",
        "due_date": "2024-01-30",
        "currency": "USD",
        "customer": "CUST001",
        "items": [],
        "taxes": [],
    }
    fields.update(overrides)
    doc = SimpleNamespace(**fields)
    doc.get = lambda key, default=None: fields.get(key, default)
    return doc


class TestInvoiceValidation(unittest.TestCase):
    def test_description_passes_through(self):
        self.assertEqual(
            validate_invoice_description("Test Item Description"),
            "Test Item Description",
        )

    def test_empty_description_falls_back_to_item_name(self):
        self.assertEqual(
            validate_invoice_description("", "Item Name", "ITEM001"), "Item Name"
        )

    def test_all_empty_description_falls_back_to_generic(self):
        self.assertEqual(validate_invoice_description("", "", ""), "Item")

    def test_html_is_stripped_from_description(self):
        self.assertEqual(
            validate_invoice_description("<p>Test <b>Description</b></p>"),
            "Test Description",
        )

    def test_description_truncated_to_xero_limit(self):
        result = validate_invoice_description("A" * 5000)
        self.assertEqual(len(result), 4000)
        self.assertTrue(result.endswith("..."))

    def test_invoice_number_passes_through(self):
        self.assertEqual(validate_invoice_number("SI-2024-00001"), "SI-2024-00001")

    def test_invoice_number_truncated_to_255(self):
        self.assertEqual(len(validate_invoice_number("A" * 300)), 255)

    def test_invoice_number_non_printable_removed(self):
        self.assertEqual(validate_invoice_number("SI\x00\x01\x02-2024"), "SI-2024")

    def test_empty_invoice_number_returns_none(self):
        self.assertIsNone(validate_invoice_number(""))

    def test_reference_passes_through(self):
        self.assertEqual(validate_invoice_reference("PO-12345"), "PO-12345")

    def test_reference_truncated_to_255(self):
        self.assertEqual(len(validate_invoice_reference("A" * 300)), 255)

    def test_empty_reference_returns_none(self):
        self.assertIsNone(validate_invoice_reference(""))
        self.assertIsNone(validate_invoice_reference(None))


class TestInvoiceChangeDetection(unittest.TestCase):
    def test_hash_is_deterministic(self):
        doc = _invoice_double()
        first = compute_invoice_hash(doc)
        self.assertEqual(first, compute_invoice_hash(doc))
        self.assertEqual(len(first), 32)  # md5 hexdigest

    def test_hash_changes_when_data_changes(self):
        self.assertNotEqual(
            compute_invoice_hash(_invoice_double()),
            compute_invoice_hash(_invoice_double(posting_date="2024-01-16")),
        )

    def test_no_stored_hash_means_changed(self):
        self.assertTrue(invoice_data_changed(_invoice_double()))

    def test_matching_hash_means_unchanged(self):
        current_hash = compute_invoice_hash(_invoice_double())
        self.assertFalse(
            invoice_data_changed(_invoice_double(xero_data_hash=current_hash))
        )

    def test_stale_hash_means_changed(self):
        self.assertTrue(invoice_data_changed(_invoice_double(xero_data_hash="0" * 32)))


if __name__ == "__main__":
    unittest.main()
