#!/usr/bin/env python3
"""
Systematic Outbound Sync Testing Script - 2026-02-11
Tests all active entity types in dependency order
Skips contacts as per user request (another developer working on it)
"""

import frappe
from frappe.utils import now_datetime, get_datetime
import json
from datetime import datetime

# Test Results Storage
test_results = {
    "test_date": str(now_datetime()),
    "entities_tested": [],
    "total_attempted": 0,
    "total_successful": 0,
    "total_failed": 0,
    "failures": []
}

def log_test_result(entity_type, doc_name, status, error=None, notes=None):
    """Log test result for an entity"""
    result = {
        "entity_type": entity_type,
        "doc_name": doc_name,
        "status": status,  # "success", "failed", "skipped"
        "timestamp": str(now_datetime()),
        "error": error,
        "notes": notes
    }
    
    test_results["entities_tested"].append(result)
    test_results["total_attempted"] += 1
    
    if status == "success":
        test_results["total_successful"] += 1
        print(f"✅ {entity_type} {doc_name}: {status}")
    elif status == "failed":
        test_results["total_failed"] += 1
        test_results["failures"].append(result)
        print(f"❌ {entity_type} {doc_name}: {status}")
        if error:
            print(f"   Error: {error}")
    else:
        print(f"⚠️  {entity_type} {doc_name}: {status}")
    
    if notes:
        print(f"   Notes: {notes}")

def check_xero_settings():
    """Verify Xero settings are configured"""
    print("\n" + "="*80)
    print("PHASE 0: Checking Xero Settings")
    print("="*80)
    
    try:
        settings = frappe.get_single("Xero Settings")
        
        print(f"✓ Xero sync enabled: {settings.enable_xero_sync}")
        print(f"✓ Sync to Xero enabled: {settings.enable_sync_to_xero}")
        print(f"✓ Connection status: {settings.connection_status}")
        print(f"✓ Tenant: {settings.tenant_name}")
        
        if not settings.enable_xero_sync:
            print("❌ ERROR: Xero sync is disabled!")
            return False
        
        if not settings.enable_sync_to_xero:
            print("❌ ERROR: Outbound sync (to Xero) is disabled!")
            return False
        
        # Check which entity syncs are enabled
        print("\nEnabled entity syncs:")
        entity_flags = {
            "Items": settings.sync_items,
            "Quotations": settings.sync_quotes,
            "Invoices": settings.sync_invoices,
            "Credit Notes": settings.sync_credit_notes,
            "Payments": settings.sync_payments,
            "Journal Entries": settings.sync_journal_entries,
            "Bank Transactions": settings.sync_bank_transactions,
        }
        
        for entity, enabled in entity_flags.items():
            status = "✓" if enabled else "✗"
            print(f"  {status} {entity}: {enabled}")
        
        return True
        
    except Exception as e:
        print(f"❌ ERROR checking Xero settings: {str(e)}")
        return False

def test_items_sync():
    """Test Item sync to Xero"""
    print("\n" + "="*80)
    print("PHASE 1: Testing Items Sync")
    print("="*80)
    
    try:
        # Find test items (created in previous test data generation)
        items = frappe.get_all("Item", 
            filters={"item_code": ["like", "TEST-%"]},
            fields=["name", "item_code", "xero_sync_status", "xero_item_id"],
            limit=5
        )
        
        if not items:
            log_test_result("Item", "N/A", "skipped", notes="No test items found")
            return
        
        print(f"Found {len(items)} test items")
        
        for item in items:
            try:
                # Import the sync function
                from xero.api.xero_items import sync_item_to_xero
                
                # Attempt sync
                print(f"\nSyncing item: {item.item_code}")
                sync_item_to_xero(item.name)  # Only pass item_code
                
                # Check if sync was successful
                item_doc = frappe.get_doc("Item", item.name)
                if item_doc.xero_item_id and item_doc.xero_sync_status == "Synced":
                    log_test_result("Item", item.item_code, "success", 
                        notes=f"Xero ID: {item_doc.xero_item_id}")
                else:
                    log_test_result("Item", item.item_code, "failed",
                        error=f"Status: {item_doc.xero_sync_status}")
                    
            except Exception as e:
                log_test_result("Item", item.item_code, "failed", error=str(e))
                
    except Exception as e:
        log_test_result("Item", "N/A", "failed", error=f"Phase error: {str(e)}")

def test_quotations_sync():
    """Test Quotation sync to Xero"""
    print("\n" + "="*80)
    print("PHASE 2: Testing Quotations Sync")
    print("="*80)
    
    try:
        # Find submitted quotations
        quotations = frappe.get_all("Quotation",
            filters={"docstatus": 1, "quotation_to": "Customer"},
            fields=["name", "customer_name", "xero_sync_status", "xero_quote_id"],
            order_by="creation desc",
            limit=3
        )
        
        if not quotations:
            log_test_result("Quotation", "N/A", "skipped", notes="No submitted quotations found")
            return
        
        print(f"Found {len(quotations)} submitted quotations")
        
        for quot in quotations:
            try:
                from xero.api.xero_quotes import sync_quotation_to_xero
                
                print(f"\nSyncing quotation: {quot.name}")
                sync_quotation_to_xero(quot.name, "Quotation")
                
                quot_doc = frappe.get_doc("Quotation", quot.name)
                if quot_doc.xero_quote_id and quot_doc.xero_sync_status == "Synced":
                    log_test_result("Quotation", quot.name, "success",
                        notes=f"Xero ID: {quot_doc.xero_quote_id}")
                else:
                    log_test_result("Quotation", quot.name, "failed",
                        error=f"Status: {quot_doc.xero_sync_status}")
                    
            except Exception as e:
                log_test_result("Quotation", quot.name, "failed", error=str(e))
                
    except Exception as e:
        log_test_result("Quotation", "N/A", "failed", error=f"Phase error: {str(e)}")

def test_sales_invoices_sync():
    """Test Sales Invoice sync to Xero"""
    print("\n" + "="*80)
    print("PHASE 3: Testing Sales Invoices Sync")
    print("="*80)
    
    try:
        # Find submitted sales invoices (non-return)
        invoices = frappe.get_all("Sales Invoice",
            filters={"docstatus": 1, "is_return": 0},
            fields=["name", "customer_name", "xero_sync_status", "xero_invoice_id"],
            order_by="creation desc",
            limit=3
        )
        
        if not invoices:
            log_test_result("Sales Invoice", "N/A", "skipped", notes="No submitted sales invoices found")
            return
        
        print(f"Found {len(invoices)} submitted sales invoices")
        
        for inv in invoices:
            try:
                from xero.api.xero_invoices import sync_invoice_to_xero
                
                print(f"\nSyncing sales invoice: {inv.name}")
                sync_invoice_to_xero(inv.name, "Sales Invoice")
                
                inv_doc = frappe.get_doc("Sales Invoice", inv.name)
                if inv_doc.xero_invoice_id and inv_doc.xero_sync_status == "Synced":
                    log_test_result("Sales Invoice", inv.name, "success",
                        notes=f"Xero ID: {inv_doc.xero_invoice_id}")
                else:
                    log_test_result("Sales Invoice", inv.name, "failed",
                        error=f"Status: {inv_doc.xero_sync_status}")
                    
            except Exception as e:
                log_test_result("Sales Invoice", inv.name, "failed", error=str(e))
                
    except Exception as e:
        log_test_result("Sales Invoice", "N/A", "failed", error=f"Phase error: {str(e)}")

def test_purchase_invoices_sync():
    """Test Purchase Invoice sync to Xero"""
    print("\n" + "="*80)
    print("PHASE 4: Testing Purchase Invoices Sync")
    print("="*80)
    
    try:
        # Find submitted purchase invoices (non-return)
        invoices = frappe.get_all("Purchase Invoice",
            filters={"docstatus": 1, "is_return": 0},
            fields=["name", "supplier_name", "xero_sync_status", "xero_invoice_id"],
            order_by="creation desc",
            limit=3
        )
        
        if not invoices:
            log_test_result("Purchase Invoice", "N/A", "skipped", notes="No submitted purchase invoices found")
            return
        
        print(f"Found {len(invoices)} submitted purchase invoices")
        
        for inv in invoices:
            try:
                from xero.api.xero_invoices import sync_invoice_to_xero
                
                print(f"\nSyncing purchase invoice: {inv.name}")
                sync_invoice_to_xero(inv.name, "Purchase Invoice")
                
                inv_doc = frappe.get_doc("Purchase Invoice", inv.name)
                if inv_doc.xero_invoice_id and inv_doc.xero_sync_status == "Synced":
                    log_test_result("Purchase Invoice", inv.name, "success",
                        notes=f"Xero ID: {inv_doc.xero_invoice_id}")
                else:
                    log_test_result("Purchase Invoice", inv.name, "failed",
                        error=f"Status: {inv_doc.xero_sync_status}")
                    
            except Exception as e:
                log_test_result("Purchase Invoice", inv.name, "failed", error=str(e))
                
    except Exception as e:
        log_test_result("Purchase Invoice", "N/A", "failed", error=f"Phase error: {str(e)}")

def test_credit_notes_sync():
    """Test Credit Note (return invoice) sync to Xero"""
    print("\n" + "="*80)
    print("PHASE 5: Testing Credit Notes Sync")
    print("="*80)
    
    try:
        # Find submitted return sales invoices
        credit_notes = frappe.get_all("Sales Invoice",
            filters={"docstatus": 1, "is_return": 1},
            fields=["name", "customer_name", "xero_sync_status", "xero_credit_note_id"],
            order_by="creation desc",
            limit=2
        )
        
        if not credit_notes:
            log_test_result("Credit Note", "N/A", "skipped", notes="No credit notes found")
            return
        
        print(f"Found {len(credit_notes)} credit notes")
        
        for cn in credit_notes:
            try:
                from xero.api.xero_credit_notes import sync_return_to_xero
                
                print(f"\nSyncing credit note: {cn.name}")
                sync_return_to_xero(cn.name, "Sales Invoice")
                
                cn_doc = frappe.get_doc("Sales Invoice", cn.name)
                if cn_doc.xero_credit_note_id and cn_doc.xero_sync_status == "Synced":
                    log_test_result("Credit Note", cn.name, "success",
                        notes=f"Xero ID: {cn_doc.xero_credit_note_id}")
                else:
                    log_test_result("Credit Note", cn.name, "failed",
                        error=f"Status: {cn_doc.xero_sync_status}")
                    
            except Exception as e:
                log_test_result("Credit Note", cn.name, "failed", error=str(e))
                
    except Exception as e:
        log_test_result("Credit Note", "N/A", "failed", error=f"Phase error: {str(e)}")

def test_payments_sync():
    """Test Payment Entry sync to Xero"""
    print("\n" + "="*80)
    print("PHASE 6: Testing Payment Entries Sync")
    print("="*80)
    
    try:
        # Find submitted payment entries
        payments = frappe.get_all("Payment Entry",
            filters={"docstatus": 1},
            fields=["name", "party_name", "payment_type", "xero_sync_status", "xero_payment_id"],
            order_by="creation desc",
            limit=3
        )
        
        if not payments:
            log_test_result("Payment Entry", "N/A", "skipped", notes="No submitted payments found")
            return
        
        print(f"Found {len(payments)} submitted payments")
        
        for pay in payments:
            try:
                from xero.api.xero_payments import sync_payment_to_xero
                
                print(f"\nSyncing payment: {pay.name} ({pay.payment_type})")
                sync_payment_to_xero(pay.name, "Payment Entry")
                
                pay_doc = frappe.get_doc("Payment Entry", pay.name)
                if pay_doc.xero_payment_id and pay_doc.xero_sync_status == "Synced":
                    log_test_result("Payment Entry", pay.name, "success",
                        notes=f"Xero ID: {pay_doc.xero_payment_id}")
                else:
                    log_test_result("Payment Entry", pay.name, "failed",
                        error=f"Status: {pay_doc.xero_sync_status}")
                    
            except Exception as e:
                log_test_result("Payment Entry", pay.name, "failed", error=str(e))
                
    except Exception as e:
        log_test_result("Payment Entry", "N/A", "failed", error=f"Phase error: {str(e)}")

def test_purchase_orders_sync():
    """Test Purchase Order sync to Xero"""
    print("\n" + "="*80)
    print("PHASE 7: Testing Purchase Orders Sync")
    print("="*80)
    
    try:
        # Find submitted purchase orders
        pos = frappe.get_all("Purchase Order",
            filters={"docstatus": 1},
            fields=["name", "supplier_name", "xero_sync_status", "xero_purchase_order_id"],
            order_by="creation desc",
            limit=3
        )
        
        if not pos:
            log_test_result("Purchase Order", "N/A", "skipped", notes="No submitted purchase orders found")
            return
        
        print(f"Found {len(pos)} submitted purchase orders")
        
        for po in pos:
            try:
                from xero.api.xero_purchase_orders import sync_purchase_order_to_xero
                
                print(f"\nSyncing purchase order: {po.name}")
                sync_purchase_order_to_xero(po.name, "Purchase Order")
                
                po_doc = frappe.get_doc("Purchase Order", po.name)
                if po_doc.xero_purchase_order_id and po_doc.xero_sync_status == "Synced":
                    log_test_result("Purchase Order", po.name, "success",
                        notes=f"Xero ID: {po_doc.xero_purchase_order_id}")
                else:
                    log_test_result("Purchase Order", po.name, "failed",
                        error=f"Status: {po_doc.xero_sync_status}")
                    
            except Exception as e:
                log_test_result("Purchase Order", po.name, "failed", error=str(e))
                
    except Exception as e:
        log_test_result("Purchase Order", "N/A", "failed", error=f"Phase error: {str(e)}")

def test_journal_entries_sync():
    """Test Journal Entry sync to Xero"""
    print("\n" + "="*80)
    print("PHASE 8: Testing Journal Entries Sync")
    print("="*80)
    
    try:
        # Find submitted journal entries
        jes = frappe.get_all("Journal Entry",
            filters={"docstatus": 1},
            fields=["name", "xero_sync_status", "xero_manual_journal_id"],
            order_by="creation desc",
            limit=2
        )
        
        if not jes:
            log_test_result("Journal Entry", "N/A", "skipped", notes="No submitted journal entries found")
            return
        
        print(f"Found {len(jes)} submitted journal entries")
        
        for je in jes:
            try:
                from xero.api.xero_journals import sync_journal_to_xero
                
                print(f"\nSyncing journal entry: {je.name}")
                sync_journal_to_xero(je.name, "Journal Entry")
                
                je_doc = frappe.get_doc("Journal Entry", je.name)
                if je_doc.xero_manual_journal_id and je_doc.xero_sync_status == "Synced":
                    log_test_result("Journal Entry", je.name, "success",
                        notes=f"Xero ID: {je_doc.xero_manual_journal_id}")
                else:
                    log_test_result("Journal Entry", je.name, "failed",
                        error=f"Status: {je_doc.xero_sync_status}")
                    
            except Exception as e:
                log_test_result("Journal Entry", je.name, "failed", error=str(e))
                
    except Exception as e:
        log_test_result("Journal Entry", "N/A", "failed", error=f"Phase error: {str(e)}")

def test_bank_transactions_sync():
    """Test Bank Transaction sync to Xero"""
    print("\n" + "="*80)
    print("PHASE 9: Testing Bank Transactions Sync")
    print("="*80)
    
    try:
        # Find submitted bank transactions
        bts = frappe.get_all("Bank Transaction",
            filters={"docstatus": 1},
            fields=["name", "xero_sync_status", "xero_bank_transaction_id"],
            order_by="creation desc",
            limit=3
        )
        
        if not bts:
            log_test_result("Bank Transaction", "N/A", "skipped", notes="No submitted bank transactions found")
            return
        
        print(f"Found {len(bts)} submitted bank transactions")
        
        for bt in bts:
            try:
                from xero.api.xero_bank_transactions import sync_bank_transaction_to_xero
                
                print(f"\nSyncing bank transaction: {bt.name}")
                sync_bank_transaction_to_xero(bt.name, "Bank Transaction")
                
                bt_doc = frappe.get_doc("Bank Transaction", bt.name)
                if bt_doc.xero_bank_transaction_id and bt_doc.xero_sync_status == "Synced":
                    log_test_result("Bank Transaction", bt.name, "success",
                        notes=f"Xero ID: {bt_doc.xero_bank_transaction_id}")
                else:
                    log_test_result("Bank Transaction", bt.name, "failed",
                        error=f"Status: {bt_doc.xero_sync_status}")
                    
            except Exception as e:
                log_test_result("Bank Transaction", bt.name, "failed", error=str(e))
                
    except Exception as e:
        log_test_result("Bank Transaction", "N/A", "failed", error=f"Phase error: {str(e)}")

def check_xero_logs():
    """Check recent Xero logs for errors"""
    print("\n" + "="*80)
    print("PHASE 10: Checking Recent Xero Logs")
    print("="*80)
    
    try:
        # Get recent error logs
        error_logs = frappe.get_all("Xero Log",
            filters={"status": "Error", "direction": "ERPNext to Xero"},
            fields=["name", "timestamp", "message", "erpnext_doc_type", "erpnext_doc_name", "category"],
            order_by="timestamp desc",
            limit=10
        )
        
        if error_logs:
            print(f"\n⚠️  Found {len(error_logs)} recent error logs:")
            for log in error_logs:
                print(f"\n  - {log.timestamp}: {log.erpnext_doc_type} {log.erpnext_doc_name}")
                print(f"    Category: {log.category}")
                print(f"    Message: {log.message[:100]}...")
        else:
            print("✓ No recent error logs found")
            
    except Exception as e:
        print(f"❌ Error checking logs: {str(e)}")

def print_summary():
    """Print test summary"""
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    success_rate = (test_results["total_successful"] / test_results["total_attempted"] * 100) if test_results["total_attempted"] > 0 else 0
    
    print(f"\nTest Date: {test_results['test_date']}")
    print(f"Total Entities Attempted: {test_results['total_attempted']}")
    print(f"Successful: {test_results['total_successful']}")
    print(f"Failed: {test_results['total_failed']}")
    print(f"Success Rate: {success_rate:.1f}%")
    
    if test_results["failures"]:
        print(f"\n❌ FAILURES ({len(test_results['failures'])}):")
        for failure in test_results["failures"]:
            print(f"\n  {failure['entity_type']} - {failure['doc_name']}")
            print(f"  Error: {failure['error']}")
            if failure['notes']:
                print(f"  Notes: {failure['notes']}")
    
    # Save results to file
    results_file = f"/workspace/cohenix-bench/apps/xero/xero/utils/outbound_sync_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(test_results, f, indent=2)
    print(f"\n✓ Results saved to: {results_file}")

def run_all_tests():
    """Run all outbound sync tests"""
    print("\n" + "="*80)
    print("XERO OUTBOUND SYNC SYSTEMATIC TEST - 2026-02-11")
    print("="*80)
    print("Testing all active entity types in dependency order")
    print("Skipping: Contacts (another developer working on it)")
    print("="*80)
    
    # Check settings first
    if not check_xero_settings():
        print("\n❌ Cannot proceed - Xero settings not configured properly")
        return
    
    # Run tests in dependency order
    test_items_sync()
    test_quotations_sync()
    test_sales_invoices_sync()
    test_purchase_invoices_sync()
    test_credit_notes_sync()
    test_payments_sync()
    test_purchase_orders_sync()
    test_journal_entries_sync()
    test_bank_transactions_sync()
    
    # Check logs
    check_xero_logs()
    
    # Print summary
    print_summary()

if __name__ == "__main__":
    run_all_tests()
