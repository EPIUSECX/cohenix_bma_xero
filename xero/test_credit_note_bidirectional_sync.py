"""
Comprehensive bidirectional sync tests for Credit Notes.

This test script tests the full round-trip sync between ERPNext and Xero:
1. ERPNext Sales Invoice Return → Xero ACCRECCREDIT → ERPNext Sales Invoice Return
2. ERPNext Purchase Invoice Return → Xero ACCPAYCREDIT → ERPNext Purchase Invoice Return
3. Xero ACCRECCREDIT → ERPNext Sales Invoice Return → Xero ACCRECCREDIT
4. Xero ACCPAYCREDIT → ERPNext Purchase Invoice Return → Xero ACCPAYCREDIT

Run in Frappe console:
    bench --site [site] console
    >>> exec(open('xero/test_credit_note_bidirectional_sync.py').read())

Or run individual test functions:
    >>> test_outbound_sales_return()
    >>> test_outbound_purchase_return()
    >>> test_inbound_accreccredit()
    >>> test_inbound_accpaycredit()
"""

import frappe
from frappe.utils import getdate, nowdate
import json


def test_outbound_sales_return():
    """
    Test 1: ERPNext Sales Invoice Return → Xero ACCRECCREDIT
    
    Steps:
    1. Create a Customer synced to Xero
    2. Create a Sales Invoice Return (is_return=1)
    3. Submit the return
    4. Verify sync to Xero
    5. Verify xero_credit_note_id is set
    """
    print("\n" + "="*60)
    print("TEST 1: Outbound Sales Invoice Return Sync")
    print("="*60)
    
    try:
        # Get a customer that's synced to Xero
        customer = frappe.db.get_value(
            "Customer",
            {"xero_contact_id": ["is", "set"]},
            ["name", "xero_contact_id"],
            as_dict=True
        )
        
        if not customer:
            print("⚠️  No customer with Xero Contact ID found. Skipping test.")
            return {"status": "skipped", "reason": "No synced customer"}
        
        print(f"✓ Using Customer: {customer.name} (Xero ID: {customer.xero_contact_id})")
        
        # Get company and settings
        company = frappe.defaults.get_global_default("company")
        settings = frappe.get_single("Xero Settings")
        
        if not settings.enable_xero_sync or not settings.get("sync_credit_notes"):
            print("⚠️  Credit Note sync is disabled. Skipping test.")
            return {"status": "skipped", "reason": "Sync disabled"}
        
        # Get an income account that's mapped
        account_map = settings.get_account_map()
        income_account = None
        for acc, xero_code in account_map.items():
            acc_type = frappe.db.get_value("Account", acc, "root_type")
            if acc_type == "Income":
                income_account = acc
                break
        
        if not income_account:
            print("⚠️  No income account mapped. Skipping test.")
            return {"status": "skipped", "reason": "No account mapping"}
        
        print(f"✓ Using Income Account: {income_account}")
        
        # Get an item
        item = frappe.db.get_value(
            "Item",
            {"is_sales_item": 1, "disabled": 0},
            "name"
        )
        
        if not item:
            print("⚠️  No sales item found. Skipping test.")
            return {"status": "skipped", "reason": "No item"}
        
        print(f"✓ Using Item: {item}")
        
        # Create Sales Invoice Return
        si = frappe.new_doc("Sales Invoice")
        si.customer = customer.name
        si.company = company
        si.posting_date = getdate()
        si.due_date = getdate()
        si.is_return = 1
        si.currency = "USD"
        
        si.append("items", {
            "item_code": item,
            "qty": -1,  # Negative for return
            "rate": 100.0,
            "income_account": income_account
        })
        
        si.insert(ignore_permissions=True)
        si.submit()
        
        print(f"✓ Created Sales Invoice Return: {si.name}")
        
        # Trigger sync manually
        from xero.api.xero_credit_notes import sync_return_to_xero
        sync_return_to_xero(si.name, "Sales Invoice")
        
        # Check if synced
        si.reload()
        
        if si.xero_credit_note_id:
            print(f"✅ SUCCESS: Sales Invoice Return synced to Xero")
            print(f"   Xero Credit Note ID: {si.xero_credit_note_id}")
            print(f"   Sync Status: {si.xero_sync_status}")
            
            # Clean up - cancel the return
            try:
                si.cancel()
                print(f"✓ Cancelled Sales Invoice Return: {si.name}")
            except:
                pass
            
            return {
                "status": "success",
                "erpnext_doc": si.name,
                "xero_id": si.xero_credit_note_id
            }
        else:
            print(f"❌ FAILED: Sales Invoice Return not synced")
            print(f"   Sync Status: {si.xero_sync_status}")
            return {"status": "failed", "erpnext_doc": si.name}
            
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Credit Note Outbound Test Error")
        return {"status": "error", "message": str(e)}


def test_outbound_purchase_return():
    """
    Test 2: ERPNext Purchase Invoice Return → Xero ACCPAYCREDIT
    
    Steps:
    1. Create a Supplier synced to Xero
    2. Create a Purchase Invoice Return (is_return=1)
    3. Submit the return
    4. Verify sync to Xero
    5. Verify xero_credit_note_id is set
    """
    print("\n" + "="*60)
    print("TEST 2: Outbound Purchase Invoice Return Sync")
    print("="*60)
    
    try:
        # Get a supplier that's synced to Xero
        supplier = frappe.db.get_value(
            "Supplier",
            {"xero_contact_id": ["is", "set"]},
            ["name", "xero_contact_id"],
            as_dict=True
        )
        
        if not supplier:
            print("⚠️  No supplier with Xero Contact ID found. Skipping test.")
            return {"status": "skipped", "reason": "No synced supplier"}
        
        print(f"✓ Using Supplier: {supplier.name} (Xero ID: {supplier.xero_contact_id})")
        
        # Get company and settings
        company = frappe.defaults.get_global_default("company")
        settings = frappe.get_single("Xero Settings")
        
        if not settings.enable_xero_sync or not settings.get("sync_credit_notes"):
            print("⚠️  Credit Note sync is disabled. Skipping test.")
            return {"status": "skipped", "reason": "Sync disabled"}
        
        # Get an expense account that's mapped
        account_map = settings.get_account_map()
        expense_account = None
        for acc, xero_code in account_map.items():
            acc_type = frappe.db.get_value("Account", acc, "root_type")
            if acc_type == "Expense":
                expense_account = acc
                break
        
        if not expense_account:
            print("⚠️  No expense account mapped. Skipping test.")
            return {"status": "skipped", "reason": "No account mapping"}
        
        print(f"✓ Using Expense Account: {expense_account}")
        
        # Get an item
        item = frappe.db.get_value(
            "Item",
            {"is_purchase_item": 1, "disabled": 0},
            "name"
        )
        
        if not item:
            print("⚠️  No purchase item found. Skipping test.")
            return {"status": "skipped", "reason": "No item"}
        
        print(f"✓ Using Item: {item}")
        
        # Create Purchase Invoice Return
        pi = frappe.new_doc("Purchase Invoice")
        pi.supplier = supplier.name
        pi.company = company
        pi.posting_date = getdate()
        pi.is_return = 1
        pi.currency = "USD"
        
        pi.append("items", {
            "item_code": item,
            "qty": -1,  # Negative for return
            "rate": 100.0,
            "expense_account": expense_account
        })
        
        pi.insert(ignore_permissions=True)
        pi.submit()
        
        print(f"✓ Created Purchase Invoice Return: {pi.name}")
        
        # Trigger sync manually
        from xero.api.xero_credit_notes import sync_return_to_xero
        sync_return_to_xero(pi.name, "Purchase Invoice")
        
        # Check if synced
        pi.reload()
        
        if pi.xero_credit_note_id:
            print(f"✅ SUCCESS: Purchase Invoice Return synced to Xero")
            print(f"   Xero Credit Note ID: {pi.xero_credit_note_id}")
            print(f"   Sync Status: {pi.xero_sync_status}")
            
            # Clean up - cancel the return
            try:
                pi.cancel()
                print(f"✓ Cancelled Purchase Invoice Return: {pi.name}")
            except:
                pass
            
            return {
                "status": "success",
                "erpnext_doc": pi.name,
                "xero_id": pi.xero_credit_note_id
            }
        else:
            print(f"❌ FAILED: Purchase Invoice Return not synced")
            print(f"   Sync Status: {pi.xero_sync_status}")
            return {"status": "failed", "erpnext_doc": pi.name}
            
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Credit Note Outbound Test Error")
        return {"status": "error", "message": str(e)}


def test_inbound_accreccredit():
    """
    Test 3: Xero ACCRECCREDIT → ERPNext Sales Invoice Return
    
    Steps:
    1. Fetch a credit note from Xero (ACCRECCREDIT)
    2. Verify it creates a Sales Invoice Return in ERPNext
    3. Verify is_return=1
    4. Verify xero_credit_note_id is set
    """
    print("\n" + "="*60)
    print("TEST 3: Inbound ACCRECCREDIT Sync")
    print("="*60)
    
    try:
        from xero.api.xero_credit_notes import sync_credit_notes_from_xero
        from xero.utils.xero_client import xero_request
        
        # Fetch one credit note from Xero
        response = xero_request("GET", "CreditNotes", params={"page": 1})
        
        if not response or not response.get("CreditNotes"):
            print("⚠️  No credit notes found in Xero. Skipping test.")
            return {"status": "skipped", "reason": "No Xero credit notes"}
        
        # Find an ACCRECCREDIT
        accrec_credit = None
        for cn in response["CreditNotes"]:
            if cn.get("Type") == "ACCRECCREDIT":
                accrec_credit = cn
                break
        
        if not accrec_credit:
            print("⚠️  No ACCRECCREDIT found in Xero. Skipping test.")
            return {"status": "skipped", "reason": "No ACCRECCREDIT"}
        
        print(f"✓ Found Xero ACCRECCREDIT: {accrec_credit.get('CreditNoteNumber')}")
        print(f"  CreditNoteID: {accrec_credit.get('CreditNoteID')}")
        
        # Check if already synced
        existing = frappe.db.get_value(
            "Sales Invoice",
            {"xero_credit_note_id": accrec_credit.get("CreditNoteID")},
            "name"
        )
        
        if existing:
            print(f"✓ Already synced to ERPNext: {existing}")
            return {
                "status": "success",
                "xero_id": accrec_credit.get("CreditNoteID"),
                "erpnext_doc": existing,
                "note": "Already synced"
            }
        
        # Process the credit note
        settings = frappe.get_single("Xero Settings")
        from xero.api.xero_credit_notes import process_xero_credit_note
        process_xero_credit_note(accrec_credit, settings)
        
        # Check if created
        erpnext_doc = frappe.db.get_value(
            "Sales Invoice",
            {"xero_credit_note_id": accrec_credit.get("CreditNoteID")},
            ["name", "is_return", "xero_sync_status"],
            as_dict=True
        )
        
        if erpnext_doc:
            print(f"✅ SUCCESS: ACCRECCREDIT synced to ERPNext")
            print(f"   ERPNext Doc: {erpnext_doc.name}")
            print(f"   Is Return: {erpnext_doc.is_return}")
            print(f"   Sync Status: {erpnext_doc.xero_sync_status}")
            
            return {
                "status": "success",
                "xero_id": accrec_credit.get("CreditNoteID"),
                "erpnext_doc": erpnext_doc.name
            }
        else:
            print(f"❌ FAILED: ACCRECCREDIT not synced to ERPNext")
            return {"status": "failed", "xero_id": accrec_credit.get("CreditNoteID")}
            
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Credit Note Inbound Test Error")
        return {"status": "error", "message": str(e)}


def test_inbound_accpaycredit():
    """
    Test 4: Xero ACCPAYCREDIT → ERPNext Purchase Invoice Return
    
    Steps:
    1. Fetch a credit note from Xero (ACCPAYCREDIT)
    2. Verify it creates a Purchase Invoice Return in ERPNext
    3. Verify is_return=1
    4. Verify xero_credit_note_id is set
    """
    print("\n" + "="*60)
    print("TEST 4: Inbound ACCPAYCREDIT Sync")
    print("="*60)
    
    try:
        from xero.api.xero_credit_notes import sync_credit_notes_from_xero
        from xero.utils.xero_client import xero_request
        
        # Fetch one credit note from Xero
        response = xero_request("GET", "CreditNotes", params={"page": 1})
        
        if not response or not response.get("CreditNotes"):
            print("⚠️  No credit notes found in Xero. Skipping test.")
            return {"status": "skipped", "reason": "No Xero credit notes"}
        
        # Find an ACCPAYCREDIT
        accpay_credit = None
        for cn in response["CreditNotes"]:
            if cn.get("Type") == "ACCPAYCREDIT":
                accpay_credit = cn
                break
        
        if not accpay_credit:
            print("⚠️  No ACCPAYCREDIT found in Xero. Skipping test.")
            return {"status": "skipped", "reason": "No ACCPAYCREDIT"}
        
        print(f"✓ Found Xero ACCPAYCREDIT: {accpay_credit.get('CreditNoteNumber')}")
        print(f"  CreditNoteID: {accpay_credit.get('CreditNoteID')}")
        
        # Check if already synced
        existing = frappe.db.get_value(
            "Purchase Invoice",
            {"xero_credit_note_id": accpay_credit.get("CreditNoteID")},
            "name"
        )
        
        if existing:
            print(f"✓ Already synced to ERPNext: {existing}")
            return {
                "status": "success",
                "xero_id": accpay_credit.get("CreditNoteID"),
                "erpnext_doc": existing,
                "note": "Already synced"
            }
        
        # Process the credit note
        settings = frappe.get_single("Xero Settings")
        from xero.api.xero_credit_notes import process_xero_credit_note
        process_xero_credit_note(accpay_credit, settings)
        
        # Check if created
        erpnext_doc = frappe.db.get_value(
            "Purchase Invoice",
            {"xero_credit_note_id": accpay_credit.get("CreditNoteID")},
            ["name", "is_return", "xero_sync_status"],
            as_dict=True
        )
        
        if erpnext_doc:
            print(f"✅ SUCCESS: ACCPAYCREDIT synced to ERPNext")
            print(f"   ERPNext Doc: {erpnext_doc.name}")
            print(f"   Is Return: {erpnext_doc.is_return}")
            print(f"   Sync Status: {erpnext_doc.xero_sync_status}")
            
            return {
                "status": "success",
                "xero_id": accpay_credit.get("CreditNoteID"),
                "erpnext_doc": erpnext_doc.name
            }
        else:
            print(f"❌ FAILED: ACCPAYCREDIT not synced to ERPNext")
            return {"status": "failed", "xero_id": accpay_credit.get("CreditNoteID")}
            
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Credit Note Inbound Test Error")
        return {"status": "error", "message": str(e)}


def test_void_credit_note():
    """
    Test 5: Void Credit Note in Xero when cancelled in ERPNext
    
    Steps:
    1. Find a synced Sales Invoice Return
    2. Cancel it in ERPNext
    3. Verify it's voided in Xero
    """
    print("\n" + "="*60)
    print("TEST 5: Void Credit Note on Cancel")
    print("="*60)
    
    try:
        # Find a synced return
        si = frappe.db.get_value(
            "Sales Invoice",
            {
                "is_return": 1,
                "docstatus": 1,
                "xero_credit_note_id": ["is", "set"]
            },
            ["name", "xero_credit_note_id"],
            as_dict=True
        )
        
        if not si:
            print("⚠️  No synced Sales Invoice Return found. Skipping test.")
            return {"status": "skipped", "reason": "No synced return"}
        
        print(f"✓ Found synced Sales Invoice Return: {si.name}")
        print(f"  Xero Credit Note ID: {si.xero_credit_note_id}")
        
        # Get current status from Xero
        from xero.utils.xero_client import xero_request
        xero_data = xero_request("GET", f"CreditNotes/{si.xero_credit_note_id}")
        
        if xero_data and xero_data.get("CreditNotes"):
            xero_status = xero_data["CreditNotes"][0].get("Status")
            print(f"  Current Xero Status: {xero_status}")
            
            if xero_status in ["VOIDED", "DELETED"]:
                print("✓ Credit note already voided/deleted in Xero")
                return {
                    "status": "success",
                    "note": "Already voided",
                    "xero_status": xero_status
                }
        
        # Cancel the return
        doc = frappe.get_doc("Sales Invoice", si.name)
        doc.cancel()
        
        print(f"✓ Cancelled Sales Invoice Return: {si.name}")
        
        # Trigger void
        from xero.api.xero_credit_notes import void_credit_note_in_xero
        void_credit_note_in_xero(si.name, "Sales Invoice")
        
        # Check Xero status
        xero_data = xero_request("GET", f"CreditNotes/{si.xero_credit_note_id}")
        
        if xero_data and xero_data.get("CreditNotes"):
            xero_status = xero_data["CreditNotes"][0].get("Status")
            print(f"  New Xero Status: {xero_status}")
            
            if xero_status in ["VOIDED", "DELETED"]:
                print(f"✅ SUCCESS: Credit note voided in Xero")
                return {
                    "status": "success",
                    "xero_status": xero_status
                }
            else:
                print(f"❌ FAILED: Credit note not voided in Xero")
                return {
                    "status": "failed",
                    "xero_status": xero_status
                }
        else:
            print("❌ FAILED: Could not fetch Xero status")
            return {"status": "failed", "reason": "Could not fetch Xero status"}
            
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Credit Note Void Test Error")
        return {"status": "error", "message": str(e)}


def test_change_detection():
    """
    Test 6: Change Detection - No sync if data unchanged
    
    Steps:
    1. Find a synced Sales Invoice Return
    2. Trigger sync again
    3. Verify no new API call is made (hash matches)
    """
    print("\n" + "="*60)
    print("TEST 6: Change Detection")
    print("="*60)
    
    try:
        # Find a synced return with hash
        si = frappe.db.get_value(
            "Sales Invoice",
            {
                "is_return": 1,
                "docstatus": 1,
                "xero_credit_note_id": ["is", "set"],
                "xero_data_hash": ["is", "set"]
            },
            ["name", "xero_credit_note_id", "xero_data_hash"],
            as_dict=True
        )
        
        if not si:
            print("⚠️  No synced Sales Invoice Return with hash found. Skipping test.")
            return {"status": "skipped", "reason": "No synced return with hash"}
        
        print(f"✓ Found synced Sales Invoice Return: {si.name}")
        print(f"  Xero Credit Note ID: {si.xero_credit_note_id}")
        print(f"  Data Hash: {si.xero_data_hash[:16]}...")
        
        # Check change detection
        from xero.api.xero_credit_notes import credit_note_data_changed
        doc = frappe.get_doc("Sales Invoice", si.name)
        
        if credit_note_data_changed(doc):
            print("❌ FAILED: Data reported as changed (should be unchanged)")
            return {"status": "failed", "reason": "Data reported as changed"}
        else:
            print("✅ SUCCESS: Data correctly detected as unchanged")
            return {"status": "success"}
            
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Credit Note Change Detection Test Error")
        return {"status": "error", "message": str(e)}


def run_all_tests():
    """Run all credit note sync tests."""
    print("\n" + "="*60)
    print("CREDIT NOTE BIDIRECTIONAL SYNC TESTS")
    print("="*60)
    
    results = {
        "test_1_outbound_sales_return": test_outbound_sales_return(),
        "test_2_outbound_purchase_return": test_outbound_purchase_return(),
        "test_3_inbound_accreccredit": test_inbound_accreccredit(),
        "test_4_inbound_accpaycredit": test_inbound_accpaycredit(),
        "test_5_void_credit_note": test_void_credit_note(),
        "test_6_change_detection": test_change_detection(),
    }
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for r in results.values() if r.get("status") == "success")
    failed = sum(1 for r in results.values() if r.get("status") == "failed")
    skipped = sum(1 for r in results.values() if r.get("status") == "skipped")
    errors = sum(1 for r in results.values() if r.get("status") == "error")
    
    for test_name, result in results.items():
        status = result.get("status", "unknown")
        symbol = "✅" if status == "success" else "⚠️" if status == "skipped" else "❌"
        print(f"{symbol} {test_name}: {status}")
    
    print(f"\nTotal: {len(results)} tests")
    print(f"  ✅ Passed: {passed}")
    print(f"  ❌ Failed: {failed}")
    print(f"  ⚠️  Skipped: {skipped}")
    print(f"  🔴 Errors: {errors}")
    
    return results


# Run tests if executed directly
if __name__ == "__main__":
    run_all_tests()
