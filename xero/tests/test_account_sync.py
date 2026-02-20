#!/usr/bin/env python
"""
Test script for Account bidirectional sync with Xero.
Run: bench --site cohenix.localhost execute xero.test_account_sync.run_all_tests
"""

import frappe
from frappe.utils import now_datetime
import hashlib


def run_all_tests():
    """Run all account sync tests."""
    print("\n" + "="*60)
    print("ACCOUNT SYNC TESTS")
    print("="*60)
    
    # Test 1: Validation functions
    test_validation_functions()
    
    # Test 2: Type mapping
    test_type_mapping()
    
    # Test 3: Hash computation
    test_hash_computation()
    
    # Test 4: Matching logic
    test_matching_logic()
    
    # Test 5: Outbound sync (if Xero is connected)
    test_outbound_sync()
    
    # Test 6: Inbound sync (if Xero is connected)
    test_inbound_sync()
    
    print("\n" + "="*60)
    print("ALL TESTS COMPLETED")
    print("="*60)


def test_validation_functions():
    """Test account code and name validation."""
    print("\n--- Test 1: Validation Functions ---")
    
    from xero.api.xero_accounts import validate_account_code, validate_account_name
    
    # Test code validation
    try:
        code = validate_account_code("TEST123")
        assert code == "TEST123", f"Expected 'TEST123', got '{code}'"
        print("  ✓ Code validation: valid code passes")
    except Exception as e:
        print(f"  ✗ Code validation failed: {e}")
    
    # Test code truncation
    try:
        code = validate_account_code("VERYLONGCODE12345")
        assert code == "VERYLONGCO", f"Expected 'VERYLONGCO', got '{code}'"
        print("  ✓ Code validation: truncates to 10 chars")
    except Exception as e:
        print(f"  ✗ Code truncation failed: {e}")
    
    # Test code sanitization
    try:
        code = validate_account_code("TEST-123!")
        assert code == "TEST123", f"Expected 'TEST123', got '{code}'"
        print("  ✓ Code validation: removes special chars")
    except Exception as e:
        print(f"  ✗ Code sanitization failed: {e}")
    
    # Test name validation
    try:
        name = validate_account_name("Test Account Name")
        assert name == "Test Account Name", f"Expected 'Test Account Name', got '{name}'"
        print("  ✓ Name validation: valid name passes")
    except Exception as e:
        print(f"  ✗ Name validation failed: {e}")
    
    # Test name truncation
    try:
        long_name = "A" * 200
        name = validate_account_name(long_name)
        assert len(name) == 150, f"Expected 150 chars, got {len(name)}"
        print("  ✓ Name validation: truncates to 150 chars")
    except Exception as e:
        print(f"  ✗ Name truncation failed: {e}")


def test_type_mapping():
    """Test ERPNext to Xero type mapping."""
    print("\n--- Test 2: Type Mapping ---")
    
    from xero.api.xero_accounts import get_xero_type_from_erpnext, XERO_ACCOUNT_TYPE_MAP, ERPNEXT_TO_XERO_TYPE_MAP
    
    # Test known mappings
    test_cases = [
        ("Asset", "Bank", "BANK"),
        ("Asset", "Fixed Asset", "FIXED"),
        ("Liability", "Payable", "CURRLIAB"),
        ("Income", "Income Account", "REVENUE"),
        ("Expense", "Expense Account", "EXPENSE"),
        ("Equity", "Equity", "EQUITY"),
    ]
    
    for root_type, account_type, expected in test_cases:
        result = get_xero_type_from_erpnext(root_type, account_type)
        if result == expected:
            print(f"  ✓ ({root_type}, {account_type}) → {expected}")
        else:
            print(f"  ✗ ({root_type}, {account_type}) → Expected {expected}, got {result}")
    
    # Test fallback
    result = get_xero_type_from_erpnext("Asset", None)
    if result in ["CURRENT", "NONCURRENT"]:
        print(f"  ✓ Fallback for (Asset, None) → {result}")
    else:
        print(f"  ✗ Fallback failed: got {result}")


def test_hash_computation():
    """Test account data hash computation."""
    print("\n--- Test 3: Hash Computation ---")
    
    from xero.api.xero_accounts import compute_account_hash, account_data_changed
    
    # Create a mock account doc
    class MockAccount:
        def __init__(self):
            self.account_number = "TEST001"
            self.account_name = "Test Account"
            self.root_type = "Asset"
            self.account_type = "Bank"
            self.currency = "USD"
            self.disabled = 0
            self.bank_account_no = "123456789"
            self.xero_data_hash = None
    
    doc = MockAccount()
    
    # Test hash computation
    hash1 = compute_account_hash(doc)
    if len(hash1) == 32:
        print(f"  ✓ Hash computation: produces 32-char MD5 hash ({hash1[:8]}...)")
    else:
        print(f"  ✗ Hash length wrong: {len(hash1)}")
    
    # Test hash consistency
    hash2 = compute_account_hash(doc)
    if hash1 == hash2:
        print("  ✓ Hash consistency: same data produces same hash")
    else:
        print("  ✗ Hash inconsistency")
    
    # Test change detection
    doc.xero_data_hash = hash1
    if not account_data_changed(doc):
        print("  ✓ Change detection: no change detected when hash matches")
    else:
        print("  ✗ False positive change detection")
    
    # Test change detection with modified data
    doc.account_name = "Modified Account"
    if account_data_changed(doc):
        print("  ✓ Change detection: change detected when data modified")
    else:
        print("  ✗ Failed to detect data change")


def test_matching_logic():
    """Test ERPNext account matching logic."""
    print("\n--- Test 4: Matching Logic ---")
    
    from xero.api.xero_accounts import find_matching_erpnext_account
    
    company = frappe.defaults.get_user_default("company")
    
    # Test with non-existent account
    match, match_type = find_matching_erpnext_account(
        "non-existent-id-12345",
        "NONEXIST",
        "Non Existent Account",
        company
    )
    
    if match is None:
        print("  ✓ No match for non-existent account")
    else:
        print(f"  ✗ Unexpected match: {match}")
    
    # Test with existing account (if any have xero_account_id)
    existing = frappe.db.get_value("Account", {"xero_account_id": ["!=", ""]}, ["name", "xero_account_id"])
    if existing:
        name, xero_id = existing
        match, match_type = find_matching_erpnext_account(xero_id, "CODE", "Name", company)
        if match == name and match_type == "id":
            print(f"  ✓ Match by xero_account_id: found {name}")
        else:
            print(f"  ✗ Match failed: expected {name}, got {match}")


def test_outbound_sync():
    """Test outbound sync (ERPNext → Xero)."""
    print("\n--- Test 5: Outbound Sync ---")
    
    # Check if Xero is enabled
    settings = frappe.get_single("Xero Settings")
    if not settings.enable_xero_sync or not settings.enable_sync_to_xero:
        print("  ⊘ Xero sync not enabled - skipping outbound sync test")
        return
    
    from xero.api.xero_accounts import (
        build_xero_account_payload,
        get_xero_type_from_erpnext,
        validate_account_code,
        validate_account_name
    )
    
    # Find a test account
    test_account = frappe.db.get_value(
        "Account",
        {"is_group": 0, "disabled": 0},
        ["name", "account_name", "account_number", "root_type", "account_type"],
        as_dict=True
    )
    
    if not test_account:
        print("  ⊘ No test account found - skipping")
        return
    
    print(f"  Testing with account: {test_account.name}")
    
    try:
        # Build payload (without actually syncing)
        class MockDoc:
            def __init__(self, data):
                self.__dict__.update(data)
                self.xero_account_id = None
                self.disabled = 0
                self.bank_account_no = None
                self.description = None
                self.currency = None  # May not exist on all accounts
        
        doc = MockDoc(test_account)
        payload = build_xero_account_payload(doc, settings)
        
        print(f"  ✓ Payload built successfully:")
        print(f"    - Code: {payload.get('Code')}")
        print(f"    - Name: {payload.get('Name')[:30]}...")
        print(f"    - Type: {payload.get('Type')}")
        print(f"    - Status: {payload.get('Status')}")
        
    except Exception as e:
        print(f"  ✗ Payload build failed: {e}")


def test_inbound_sync():
    """Test inbound sync (Xero → ERPNext)."""
    print("\n--- Test 6: Inbound Sync ---")
    
    # Check if Xero is enabled
    settings = frappe.get_single("Xero Settings")
    if not settings.enable_xero_sync or not settings.enable_sync_from_xero:
        print("  ⊘ Xero sync not enabled - skipping inbound sync test")
        return
    
    from xero.api.xero_accounts import process_xero_account, XERO_ACCOUNT_TYPE_MAP
    
    # Create mock Xero account data
    mock_xero_account = {
        "AccountID": "test-sync-id-12345",
        "Code": "TESTSYNC",
        "Name": "Test Sync Account",
        "Type": "EXPENSE",
        "Status": "ACTIVE",
        "Description": "Test account for sync validation",
        "TaxType": "INPUT2",
        "EnablePaymentsToAccount": False,
    }
    
    company = frappe.defaults.get_user_default("company")
    
    print(f"  Testing with mock Xero account: {mock_xero_account['Code']}")
    
    try:
        # Process the mock account
        process_xero_account(mock_xero_account, company)
        
        # Check if account was created
        created = frappe.db.get_value(
            "Account",
            {"xero_account_id": mock_xero_account["AccountID"]},
            ["name", "account_name", "xero_sync_status"],
            as_dict=True
        )
        
        if created:
            print(f"  ✓ Account created/found: {created.name}")
            print(f"    - Name: {created.account_name}")
            print(f"    - Sync Status: {created.xero_sync_status}")
            
            # Clean up test account
            frappe.delete_doc("Account", created.name, ignore_permissions=True, force=True)
            frappe.db.commit()
            print("  ✓ Test account cleaned up")
        else:
            print("  ✗ Account not created")
            
    except Exception as e:
        print(f"  ✗ Inbound sync failed: {e}")
        import traceback
        traceback.print_exc()


# Run tests when executed directly
if __name__ == "__main__":
    run_all_tests()


def test_real_xero_sync():
    """
    Test real sync with Xero.
    Run: bench --site cohenix.localhost execute xero.test_account_sync.test_real_xero_sync
    """
    print("\n" + "="*60)
    print("REAL XERO SYNC TEST")
    print("="*60)
    
    # Check if Xero is enabled
    settings = frappe.get_single("Xero Settings")
    if not settings.enable_xero_sync:
        print("  ⊘ Xero sync not enabled - skipping")
        return
    
    # Test inbound sync
    if settings.enable_sync_from_xero:
        print("\n--- Testing Inbound Sync (Xero → ERPNext) ---")
        from xero.api.xero_accounts import sync_accounts_from_xero
        sync_accounts_from_xero()
        
        # Count synced accounts
        synced_count = frappe.db.count("Account", {"xero_account_id": ["!=", ""]})
        print(f"  ✓ Accounts with Xero ID: {synced_count}")
    else:
        print("  ⊘ Inbound sync disabled")
    
    # Test outbound sync
    if settings.enable_sync_to_xero:
        print("\n--- Testing Outbound Sync (ERPNext → Xero) ---")
        from xero.api.xero_accounts import sync_accounts_to_xero
        result = sync_accounts_to_xero()
        if result:
            print(f"  ✓ Synced: {result.get('synced', 0)}, Errors: {result.get('errors', 0)}")
    else:
        print("  ⊘ Outbound sync disabled")
    
    print("\n" + "="*60)
    print("REAL XERO SYNC TEST COMPLETED")
    print("="*60)
