"""
Standalone unit tests for Invoice sync validation functions.
These tests can run without Frappe environment.

Run with: python test_invoice_standalone.py
"""

import unittest
import hashlib
import json
import re


# --- Validation Functions (copied from xero_invoices.py for standalone testing) ---

def validate_invoice_description(description, item_name=None, item_code=None):
    """
    Validate and sanitize invoice line item description for Xero.
    Xero requires: min 1 char, max 4000 chars
    """
    description = (description or "").strip()
    
    # Strip HTML tags if description contains them
    if description and "<" in description:
        description = re.sub(r'<[^>]+>', '', description).strip()
    
    # Fallback if empty
    if not description:
        description = item_name or item_code or "Item"
    
    # Xero max length is 4000 chars
    if len(description) > 4000:
        description = description[:3997] + "..."
    
    return description


def validate_invoice_number(invoice_name):
    """
    Validate invoice number for Xero.
    Xero requires: max 255 chars, printable ASCII only
    """
    if not invoice_name:
        return None
    
    # Truncate to 255 chars
    invoice_number = invoice_name[:255]
    
    # Remove non-printable ASCII characters (keep 32-126)
    invoice_number = ''.join(c for c in invoice_number if 32 <= ord(c) <= 126)
    
    return invoice_number or None


def validate_invoice_reference(reference):
    """
    Validate invoice reference for Xero.
    Xero requires: max 255 chars
    """
    if not reference:
        return None
    
    # Truncate to 255 chars
    reference = str(reference)[:255]
    
    return reference or None


def compute_invoice_hash(doc_data):
    """
    Compute MD5 hash of invoice data for change detection.
    """
    hash_data = {
        "posting_date": str(doc_data.get("posting_date")),
        "due_date": str(doc_data.get("due_date")),
        "currency": doc_data.get("currency"),
        "customer": doc_data.get("customer"),
        "items": [],
        "taxes": []
    }
    
    # Add line items
    for item in doc_data.get("items", []):
        hash_data["items"].append({
            "item_code": item.get("item_code"),
            "description": item.get("description"),
            "qty": float(item.get("qty", 0)),
            "rate": float(item.get("rate", 0)),
            "amount": float(item.get("amount", 0)),
            "income_account": item.get("income_account")
        })
    
    # Add taxes
    for tax in doc_data.get("taxes", []):
        hash_data["taxes"].append({
            "account_head": tax.get("account_head"),
            "tax_amount": float(tax.get("tax_amount", 0))
        })
    
    # Compute hash
    hash_string = json.dumps(hash_data, sort_keys=True)
    return hashlib.md5(hash_string.encode()).hexdigest()


# --- Test Classes ---

class TestInvoiceValidation(unittest.TestCase):
    """Test invoice validation functions."""
    
    def test_validate_invoice_description_normal(self):
        """Test normal description validation."""
        result = validate_invoice_description("Test Item Description")
        self.assertEqual(result, "Test Item Description")
    
    def test_validate_invoice_description_empty(self):
        """Test empty description falls back to item name."""
        result = validate_invoice_description("", "Item Name", "ITEM001")
        self.assertEqual(result, "Item Name")
    
    def test_validate_invoice_description_all_empty(self):
        """Test all empty falls back to 'Item'."""
        result = validate_invoice_description("", "", "")
        self.assertEqual(result, "Item")
    
    def test_validate_invoice_description_html_stripped(self):
        """Test HTML tags are stripped from description."""
        result = validate_invoice_description("<p>Test <b>Description</b></p>")
        self.assertEqual(result, "Test Description")
    
    def test_validate_invoice_description_max_length(self):
        """Test description is truncated to 4000 chars."""
        long_desc = "A" * 5000
        result = validate_invoice_description(long_desc)
        self.assertEqual(len(result), 4000)
        self.assertTrue(result.endswith("..."))
    
    def test_validate_invoice_description_html_long(self):
        """Test HTML is stripped before truncation."""
        long_html = "<p>" + "A" * 5000 + "</p>"
        result = validate_invoice_description(long_html)
        self.assertEqual(len(result), 4000)
        self.assertNotIn("<p>", result)
    
    def test_validate_invoice_number_normal(self):
        """Test normal invoice number validation."""
        result = validate_invoice_number("SI-2024-00001")
        self.assertEqual(result, "SI-2024-00001")
    
    def test_validate_invoice_number_max_length(self):
        """Test invoice number is truncated to 255 chars."""
        long_number = "A" * 300
        result = validate_invoice_number(long_number)
        self.assertEqual(len(result), 255)
    
    def test_validate_invoice_number_non_printable_removed(self):
        """Test non-printable ASCII characters are removed."""
        result = validate_invoice_number("SI\x00\x01\x02-2024")
        self.assertEqual(result, "SI-2024")
    
    def test_validate_invoice_number_empty(self):
        """Test empty invoice number returns None."""
        result = validate_invoice_number("")
        self.assertIsNone(result)
    
    def test_validate_invoice_number_none(self):
        """Test None invoice number returns None."""
        result = validate_invoice_number(None)
        self.assertIsNone(result)
    
    def test_validate_invoice_reference_normal(self):
        """Test normal reference validation."""
        result = validate_invoice_reference("PO-12345")
        self.assertEqual(result, "PO-12345")
    
    def test_validate_invoice_reference_max_length(self):
        """Test reference is truncated to 255 chars."""
        long_ref = "A" * 300
        result = validate_invoice_reference(long_ref)
        self.assertEqual(len(result), 255)
    
    def test_validate_invoice_reference_empty(self):
        """Test empty reference returns None."""
        result = validate_invoice_reference("")
        self.assertIsNone(result)
    
    def test_validate_invoice_reference_none(self):
        """Test None reference returns None."""
        result = validate_invoice_reference(None)
        self.assertIsNone(result)
    
    def test_validate_invoice_reference_numeric(self):
        """Test numeric reference is converted to string."""
        result = validate_invoice_reference(12345)
        self.assertEqual(result, "12345")


class TestInvoiceHashComputation(unittest.TestCase):
    """Test invoice hash computation for change detection."""
    
    def test_compute_invoice_hash_consistent(self):
        """Test that same data produces same hash."""
        doc_data = {
            "posting_date": "2024-01-15",
            "due_date": "2024-01-30",
            "currency": "USD",
            "customer": "CUST001",
            "items": [],
            "taxes": []
        }
        
        hash1 = compute_invoice_hash(doc_data)
        hash2 = compute_invoice_hash(doc_data)
        
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 32)  # MD5 hash length
    
    def test_compute_invoice_hash_different_data(self):
        """Test that different data produces different hash."""
        doc_data1 = {
            "posting_date": "2024-01-15",
            "due_date": "2024-01-30",
            "currency": "USD",
            "customer": "CUST001",
            "items": [],
            "taxes": []
        }
        
        doc_data2 = {
            "posting_date": "2024-01-16",  # Different date
            "due_date": "2024-01-30",
            "currency": "USD",
            "customer": "CUST001",
            "items": [],
            "taxes": []
        }
        
        hash1 = compute_invoice_hash(doc_data1)
        hash2 = compute_invoice_hash(doc_data2)
        
        self.assertNotEqual(hash1, hash2)
    
    def test_compute_invoice_hash_with_items(self):
        """Test hash computation with line items."""
        doc_data = {
            "posting_date": "2024-01-15",
            "due_date": "2024-01-30",
            "currency": "USD",
            "customer": "CUST001",
            "items": [
                {
                    "item_code": "ITEM001",
                    "description": "Test Item",
                    "qty": 1,
                    "rate": 100,
                    "amount": 100,
                    "income_account": "Sales - TC"
                }
            ],
            "taxes": []
        }
        
        hash1 = compute_invoice_hash(doc_data)
        hash2 = compute_invoice_hash(doc_data)
        
        self.assertEqual(hash1, hash2)
    
    def test_compute_invoice_hash_item_change(self):
        """Test that item changes produce different hash."""
        doc_data1 = {
            "posting_date": "2024-01-15",
            "due_date": "2024-01-30",
            "currency": "USD",
            "customer": "CUST001",
            "items": [
                {
                    "item_code": "ITEM001",
                    "description": "Test Item",
                    "qty": 1,
                    "rate": 100,
                    "amount": 100,
                    "income_account": "Sales - TC"
                }
            ],
            "taxes": []
        }
        
        doc_data2 = {
            "posting_date": "2024-01-15",
            "due_date": "2024-01-30",
            "currency": "USD",
            "customer": "CUST001",
            "items": [
                {
                    "item_code": "ITEM001",
                    "description": "Test Item",
                    "qty": 2,  # Different quantity
                    "rate": 100,
                    "amount": 200,
                    "income_account": "Sales - TC"
                }
            ],
            "taxes": []
        }
        
        hash1 = compute_invoice_hash(doc_data1)
        hash2 = compute_invoice_hash(doc_data2)
        
        self.assertNotEqual(hash1, hash2)
    
    def test_compute_invoice_hash_with_taxes(self):
        """Test hash computation with taxes."""
        doc_data = {
            "posting_date": "2024-01-15",
            "due_date": "2024-01-30",
            "currency": "USD",
            "customer": "CUST001",
            "items": [],
            "taxes": [
                {
                    "account_head": "VAT - TC",
                    "tax_amount": 10.00
                }
            ]
        }
        
        hash1 = compute_invoice_hash(doc_data)
        hash2 = compute_invoice_hash(doc_data)
        
        self.assertEqual(hash1, hash2)


class TestXeroAPIRequirements(unittest.TestCase):
    """Test Xero API requirements are met."""
    
    def test_description_min_length(self):
        """Test that description is at least 1 char (Xero requirement)."""
        result = validate_invoice_description("")
        self.assertGreaterEqual(len(result), 1)
    
    def test_description_max_length(self):
        """Test that description is at most 4000 chars (Xero requirement)."""
        result = validate_invoice_description("A" * 10000)
        self.assertLessEqual(len(result), 4000)
    
    def test_invoice_number_max_length(self):
        """Test that invoice number is at most 255 chars (Xero requirement)."""
        result = validate_invoice_number("A" * 1000)
        self.assertLessEqual(len(result), 255)
    
    def test_reference_max_length(self):
        """Test that reference is at most 255 chars (Xero requirement)."""
        result = validate_invoice_reference("A" * 1000)
        self.assertLessEqual(len(result), 255)
    
    def test_invoice_number_printable_ascii(self):
        """Test that invoice number contains only printable ASCII (Xero requirement)."""
        result = validate_invoice_number("SI\x00-\x1F-2024")
        for char in result:
            self.assertTrue(32 <= ord(char) <= 126)


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestInvoiceValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestInvoiceHashComputation))
    suite.addTests(loader.loadTestsFromTestCase(TestXeroAPIRequirements))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result


if __name__ == "__main__":
    print("="*60)
    print("INVOICE SYNC UNIT TESTS")
    print("="*60 + "\n")
    
    result = run_tests()
    
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")
    print("="*60)
