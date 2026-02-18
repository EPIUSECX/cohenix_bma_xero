"""
Simple test runner for Credit Note sync tests.
Run with: bench --site cohenix.localhost execute xero.run_credit_note_tests.run
"""

def run():
    """Run all credit note sync tests."""
    import frappe
    
    print("\n" + "="*60)
    print("CREDIT NOTE BIDIRECTIONAL SYNC TESTS")
    print("="*60)
    
    results = {}
    
    # Test 1: Outbound Sales Return
    print("\n" + "-"*60)
    print("TEST 1: Outbound Sales Invoice Return Sync")
    print("-"*60)
    try:
        results["test_1"] = test_outbound_sales_return()
    except Exception as e:
        print(f"ERROR: {str(e)}")
        results["test_1"] = {"status": "error", "message": str(e)}
    
    # Test 2: Outbound Purchase Return
    print("\n" + "-"*60)
    print("TEST 2: Outbound Purchase Invoice Return Sync")
    print("-"*60)
    try:
        results["test_2"] = test_outbound_purchase_return()
    except Exception as e:
        print(f"ERROR: {str(e)}")
        results["test_2"] = {"status": "error", "message": str(e)}
    
    # Test 3: Inbound ACCRECCREDIT
    print("\n" + "-"*60)
    print("TEST 3: Inbound ACCRECCREDIT Sync")
    print("-"*60)
    try:
        results["test_3"] = test_inbound_accreccredit()
    except Exception as e:
        print(f"ERROR: {str(e)}")
        results["test_3"] = {"status": "error", "message": str(e)}
    
    # Test 4: Inbound ACCPAYCREDIT
    print("\n" + "-"*60)
    print("TEST 4: Inbound ACCPAYCREDIT Sync")
    print("-"*60)
    try:
        results["test_4"] = test_inbound_accpaycredit()
    except Exception as e:
        print(f"ERROR: {str(e)}")
        results["test_4"] = {"status": "error", "message": str(e)}
    
    # Test 5: Change Detection
    print("\n" + "-"*60)
    print("TEST 5: Change Detection")
    print("-"*60)
    try:
        results["test_5"] = test_change_detection()
    except Exception as e:
        print(f"ERROR: {str(e)}")
        results["test_5"] = {"status": "error", "message": str(e)}
    
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


def test_outbound_sales_return():
    """Test ERPNext Sales Invoice Return → Xero ACCRECCREDIT."""
    import frappe
    from frappe.utils import getdate
    from xero.api.xero_credit_notes import sync_return_to_xero
    
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
        if not xero_code:
            continue
        # Check if this is an income account
        acc_info = frappe.db.get_value("Account", acc, ["root_type", "account_type"], as_dict=True)
        if acc_info and acc_info.root_type == "Income":
            income_account = acc
            print(f"✓ Using Income Account: {income_account} (mapped to Xero: {xero_code})")
            break
    
    if not income_account:
        print("⚠️  No income account mapped. Skipping test.")
        return {"status": "skipped", "reason": "No account mapping"}
    
    # Get an item (prefer non-stock items to avoid account override issues)
    item = frappe.db.get_value(
        "Item",
        {"is_sales_item": 1, "disabled": 0, "is_stock_item": 0},
        "name"
    )
    
    # If no non-stock item, use any sales item
    if not item:
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
    # Use company's default currency to avoid currency mismatch
    company_currency = frappe.get_cached_value("Company", company, "default_currency")
    si.currency = company_currency
    
    si.append("items", {
        "item_code": item,
        "qty": -1,  # Negative for return
        "rate": 100.0,
        "income_account": income_account,  # Explicitly use mapped account
        "uom": frappe.db.get_value("Item", item, "stock_uom")  # Add UOM to avoid validation error
    })
    
    si.insert(ignore_permissions=True)
    si.submit()
    
    print(f"✓ Created Sales Invoice Return: {si.name}")
    
    # Trigger sync manually
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


def test_outbound_purchase_return():
    """Test ERPNext Purchase Invoice Return → Xero ACCPAYCREDIT."""
    import frappe
    from frappe.utils import getdate
    from xero.api.xero_credit_notes import sync_return_to_xero
    
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
        if not xero_code:
            continue
        # Check if this is an expense account
        acc_info = frappe.db.get_value("Account", acc, ["root_type", "account_type"], as_dict=True)
        if acc_info and acc_info.root_type == "Expense":
            expense_account = acc
            print(f"✓ Using Expense Account: {expense_account} (mapped to Xero: {xero_code})")
            break
    
    if not expense_account:
        print("⚠️  No expense account mapped. Skipping test.")
        return {"status": "skipped", "reason": "No account mapping"}
    
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
    # Use company's default currency to avoid currency mismatch
    company_currency = frappe.get_cached_value("Company", company, "default_currency")
    pi.currency = company_currency
    
    pi.append("items", {
        "item_code": item,
        "qty": -1,  # Negative for return
        "rate": 100.0,
        "expense_account": expense_account,  # Explicitly use mapped account
        "uom": frappe.db.get_value("Item", item, "stock_uom")  # Add UOM to avoid validation error
    })
    
    pi.insert(ignore_permissions=True)
    pi.submit()
    
    print(f"✓ Created Purchase Invoice Return: {pi.name}")
    
    # Trigger sync manually
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


def test_inbound_accreccredit():
    """Test Xero ACCRECCREDIT → ERPNext Sales Invoice Return."""
    import frappe
    from xero.utils.xero_client import xero_request
    from xero.api.xero_credit_notes import process_xero_credit_note
    
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


def test_inbound_accpaycredit():
    """Test Xero ACCPAYCREDIT → ERPNext Purchase Invoice Return."""
    import frappe
    from xero.utils.xero_client import xero_request
    from xero.api.xero_credit_notes import process_xero_credit_note
    
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


def test_change_detection():
    """Test change detection - no sync if data unchanged."""
    import frappe
    from xero.api.xero_credit_notes import credit_note_data_changed
    
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
    doc = frappe.get_doc("Sales Invoice", si.name)
    
    if credit_note_data_changed(doc):
        print("❌ FAILED: Data reported as changed (should be unchanged)")
        return {"status": "failed", "reason": "Data reported as changed"}
    else:
        print("✅ SUCCESS: Data correctly detected as unchanged")
        return {"status": "success"}
