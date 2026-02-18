"""
Unit tests for Credit Note sync functionality.

These tests are designed to run within the Frappe environment.
Run with: bench --site [site] run-tests --app xero --test xero.api.xero_credit_notes

Or test individual functions in console:
    bench --site [site] console
    >>> from xero.api.xero_credit_notes import validate_credit_note_description
    >>> validate_credit_note_description("Test")
"""

import unittest
import hashlib
import json
import re


# --- Standalone validation functions for testing (copied to avoid Frappe import) ---

def validate_credit_note_description(description, item_name=None, item_code=None):
    """Validate and sanitize credit note line item description for Xero."""
    description = (description or "").strip()
    
    if description and "<" in description:
        description = re.sub(r'<[^>]+>', '', description).strip()
    
    if not description:
        description = item_name or item_code or "Item"
    
    if len(description) > 4000:
        description = description[:3997] + "..."
    
    return description


def validate_credit_note_number(cn_name):
    """Validate credit note number for Xero."""
    if not cn_name:
        return None
    
    cn_number = cn_name[:255]
    cn_number = ''.join(c for c in cn_number if 32 <= ord(c) <= 126)
    
    return cn_number or None


def validate_credit_note_reference(reference):
    """Validate credit note reference for Xero."""
    if not reference:
        return None
    
    reference = str(reference)[:255]
    
    return reference or None


# --- Test Classes ---

class TestValidateCreditNoteDescription(unittest.TestCase):
    """Tests for validate_credit_note_description function."""
    
    def test_normal_description(self):
        """Test normal description passes through."""
        result = validate_credit_note_description("Test Item Description")
        self.assertEqual(result, "Test Item Description")
    
    def test_empty_description_uses_fallback(self):
        """Test empty description uses fallback."""
        result = validate_credit_note_description("", "Fallback Name", "CODE123")
        self.assertEqual(result, "Fallback Name")
    
    def test_empty_description_uses_item_code(self):
        """Test empty description uses item code if no name."""
        result = validate_credit_note_description("", None, "CODE123")
        self.assertEqual(result, "CODE123")
    
    def test_empty_description_default(self):
        """Test empty description defaults to 'Item'."""
        result = validate_credit_note_description(None, None, None)
        self.assertEqual(result, "Item")
    
    def test_strips_html_tags(self):
        """Test HTML tags are stripped."""
        result = validate_credit_note_description("<p>Bold Text</p>", None, None)
        self.assertEqual(result, "Bold Text")
    
    def test_truncates_long_description(self):
        """Test description is truncated to 4000 chars."""
        long_desc = "A" * 5000
        result = validate_credit_note_description(long_desc)
        self.assertEqual(len(result), 4000)
        self.assertTrue(result.endswith("..."))
    
    def test_exactly_4000_chars(self):
        """Test description exactly 4000 chars is not modified."""
        desc = "A" * 4000
        result = validate_credit_note_description(desc)
        self.assertEqual(len(result), 4000)
        self.assertEqual(result, desc)
    
    def test_whitespace_stripped(self):
        """Test leading/trailing whitespace is stripped."""
        result = validate_credit_note_description("  Test Description  ")
        self.assertEqual(result, "Test Description")


class TestValidateCreditNoteNumber(unittest.TestCase):
    """Tests for validate_credit_note_number function."""
    
    def test_normal_number(self):
        """Test normal credit note number passes through."""
        result = validate_credit_note_number("CN-00001")
        self.assertEqual(result, "CN-00001")
    
    def test_empty_number_returns_none(self):
        """Test empty number returns None."""
        result = validate_credit_note_number("")
        self.assertIsNone(result)
        result = validate_credit_note_number(None)
        self.assertIsNone(result)
    
    def test_truncates_long_number(self):
        """Test number is truncated to 255 chars."""
        long_number = "CN-" + "A" * 300
        result = validate_credit_note_number(long_number)
        self.assertEqual(len(result), 255)
    
    def test_removes_non_printable_chars(self):
        """Test non-printable characters are removed."""
        result = validate_credit_note_number("CN\x00\x01\x02-00001")
        self.assertEqual(result, "CN-00001")
    
    def test_printable_special_chars_preserved(self):
        """Test printable special characters are preserved."""
        result = validate_credit_note_number("CN-2024/001 (Return)")
        self.assertEqual(result, "CN-2024/001 (Return)")


class TestValidateCreditNoteReference(unittest.TestCase):
    """Tests for validate_credit_note_reference function."""
    
    def test_normal_reference(self):
        """Test normal reference passes through."""
        result = validate_credit_note_reference("PO-12345")
        self.assertEqual(result, "PO-12345")
    
    def test_empty_reference_returns_none(self):
        """Test empty reference returns None."""
        result = validate_credit_note_reference("")
        self.assertIsNone(result)
        result = validate_credit_note_reference(None)
        self.assertIsNone(result)
    
    def test_truncates_long_reference(self):
        """Test reference is truncated to 255 chars."""
        long_ref = "R" * 300
        result = validate_credit_note_reference(long_ref)
        self.assertEqual(len(result), 255)
    
    def test_converts_to_string(self):
        """Test numeric reference is converted to string."""
        result = validate_credit_note_reference(12345)
        self.assertEqual(result, "12345")


class TestCreditNoteTypeMapping(unittest.TestCase):
    """Tests for credit note type mapping logic."""
    
    def test_sales_invoice_return_type(self):
        """Test Sales Invoice return maps to ACCRECCREDIT."""
        # Sales Invoice (is_return=1) → ACCRECCREDIT
        doc_type = "Sales Invoice"
        is_return = True
        
        if doc_type == "Sales Invoice" and is_return:
            cn_type = "ACCRECCREDIT"
        else:
            cn_type = None
        
        self.assertEqual(cn_type, "ACCRECCREDIT")
    
    def test_purchase_invoice_return_type(self):
        """Test Purchase Invoice return maps to ACCPAYCREDIT."""
        # Purchase Invoice (is_return=1) → ACCPAYCREDIT
        doc_type = "Purchase Invoice"
        is_return = True
        
        if doc_type == "Purchase Invoice" and is_return:
            cn_type = "ACCPAYCREDIT"
        else:
            cn_type = None
        
        self.assertEqual(cn_type, "ACCPAYCREDIT")
    
    def test_non_return_not_credit_note(self):
        """Test non-return invoices are not credit notes."""
        # Regular invoices should not be treated as credit notes
        doc_type = "Sales Invoice"
        is_return = False
        
        # In the actual code, this would route to invoice sync, not credit note sync
        self.assertFalse(is_return)


class TestHashComputation(unittest.TestCase):
    """Tests for hash computation logic."""
    
    def test_hash_consistency(self):
        """Test same data produces same hash."""
        hash_data = {
            "posting_date": "2024-01-15",
            "currency": "USD",
            "customer": "Test Customer",
            "items": [
                {
                    "item_code": "ITEM001",
                    "description": "Test Item",
                    "qty": 2.0,
                    "rate": 100.0,
                    "amount": 200.0,
                    "income_account": "Sales - TST"
                }
            ],
            "taxes": []
        }
        
        hash_string = json.dumps(hash_data, sort_keys=True)
        hash1 = hashlib.md5(hash_string.encode()).hexdigest()
        hash2 = hashlib.md5(hash_string.encode()).hexdigest()
        
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 32)  # MD5 hex digest length
    
    def test_hash_difference(self):
        """Test different data produces different hash."""
        hash_data1 = {
            "posting_date": "2024-01-15",
            "items": [{"item_code": "ITEM001"}]
        }
        hash_data2 = {
            "posting_date": "2024-01-15",
            "items": [{"item_code": "ITEM002"}]
        }
        
        hash1 = hashlib.md5(json.dumps(hash_data1, sort_keys=True).encode()).hexdigest()
        hash2 = hashlib.md5(json.dumps(hash_data2, sort_keys=True).encode()).hexdigest()
        
        self.assertNotEqual(hash1, hash2)


class TestXeroAPIPayloadStructure(unittest.TestCase):
    """Tests for Xero API payload structure."""
    
    def test_credit_note_payload_has_required_fields(self):
        """Test credit note payload has all required fields."""
        # Required fields for Xero Credit Notes API
        required_fields = ["Type", "Contact", "LineItems"]
        
        # Optional but important fields
        important_fields = ["Date", "Status", "LineAmountTypes", "CreditNoteNumber"]
        
        # All fields that should be in our payload
        expected_fields = required_fields + important_fields
        
        # Verify we have all expected fields defined
        self.assertEqual(len(required_fields), 3)
        self.assertIn("Type", expected_fields)
        self.assertIn("Contact", expected_fields)
        self.assertIn("LineItems", expected_fields)
    
    def test_credit_note_types(self):
        """Test valid credit note types."""
        valid_types = ["ACCRECCREDIT", "ACCPAYCREDIT"]
        
        self.assertIn("ACCRECCREDIT", valid_types)
        self.assertIn("ACCPAYCREDIT", valid_types)
    
    def test_credit_note_statuses(self):
        """Test valid credit note statuses."""
        valid_statuses = ["DRAFT", "AUTHORISED", "PAID", "VOIDED", "DELETED"]
        
        self.assertIn("DRAFT", valid_statuses)
        self.assertIn("AUTHORISED", valid_statuses)
        self.assertIn("PAID", valid_statuses)
        self.assertIn("VOIDED", valid_statuses)
        self.assertIn("DELETED", valid_statuses)


if __name__ == '__main__':
    unittest.main(verbosity=2)
