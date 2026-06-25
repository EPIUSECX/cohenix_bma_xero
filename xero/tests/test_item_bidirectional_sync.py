"""
Test bi-directional Item sync between ERPNext and Xero.

Run with: bench execute xero.test_item_bidirectional_sync.run_tests
"""

import frappe
from frappe.utils import now


def run_tests():
    """Run bi-directional sync tests."""
    print("\n" + "="*60)
    print("Bi-Directional Item Sync Tests")
    print("="*60 + "\n")
    
    # Check Xero settings
    settings = frappe.get_single("Xero Settings")
    if not settings.enable_xero_sync:
        print("Xero sync is disabled. Skipping tests.")
        return
    
    if not settings.access_token:
        print("Xero is not connected. Skipping tests.")
        return
    
    # Test 1: Check items in ERPNext
    print("1. Checking items in ERPNext...")
    items = frappe.get_all('Item', 
        fields=['name', 'item_code', 'item_name', 'is_stock_item', 
                'is_sales_item', 'is_purchase_item', 'xero_item_id', 
                'xero_sync_status', 'xero_data_hash'],
        limit=10
    )
    
    print(f"   Found {len(items)} items:")
    for item in items:
        print(f"   - {item.item_code}: {item.item_name[:40]}")
        print(f"     stock={item.is_stock_item}, sales={item.is_sales_item}, purchase={item.is_purchase_item}")
        print(f"     xero_id={item.xero_item_id or 'None'}, status={item.xero_sync_status or 'None'}")
    
    # Test 2: Test outbound sync for one item
    print("\n2. Testing outbound sync (ERPNext → Xero)...")
    test_item = None
    for item in items:
        if not item.xero_item_id:  # Find an unsynced item
            test_item = item
            break
    
    if test_item:
        print(f"   Testing sync for: {test_item.item_code}")
        try:
            from xero.api.xero_items import sync_item_to_xero
            sync_item_to_xero(test_item.name)
            
            # Check result
            updated = frappe.db.get_value("Item", test_item.name, 
                ["xero_item_id", "xero_sync_status", "xero_data_hash"], as_dict=True)
            
            if updated.xero_item_id:
                print(f"   ✓ SUCCESS: Item synced to Xero")
                print(f"     Xero ID: {updated.xero_item_id}")
                print(f"     Status: {updated.xero_sync_status}")
                print(f"     Hash: {updated.xero_data_hash[:16]}..." if updated.xero_data_hash else "     Hash: None")
            else:
                print(f"   ✗ FAILED: Item not synced")
                # Check error log
                logs = frappe.get_all("Xero Log", 
                    filters={"erpnext_doc_name": test_item.name},
                    fields=["message", "status", "error_details"],
                    order_by="timestamp desc",
                    limit=1
                )
                if logs:
                    print(f"     Error: {logs[0].message[:100]}")
        except Exception as e:
            print(f"   ✗ ERROR: {str(e)}")
    else:
        print("   No unsynced items found. Testing update sync...")
        # Test update for an already synced item
        synced_item = None
        for item in items:
            if item.xero_item_id:
                synced_item = item
                break
        
        if synced_item:
            print(f"   Testing update for: {synced_item.item_code}")
            try:
                from xero.api.xero_items import sync_item_to_xero
                sync_item_to_xero(synced_item.name)
                print(f"   ✓ Update sync completed")
            except Exception as e:
                print(f"   ✗ ERROR: {str(e)}")
    
    # Test 3: Test inbound sync
    print("\n3. Testing inbound sync (Xero → ERPNext)...")
    try:
        from xero.api.xero_items import sync_items_from_xero
        sync_items_from_xero()
        print("   ✓ Inbound sync completed")
        
        # Check for new/updated items
        synced_count = frappe.db.count("Item", {"xero_sync_status": "Synced"})
        print(f"   Total synced items: {synced_count}")
    except Exception as e:
        print(f"   ✗ ERROR: {str(e)}")
    
    # Test 4: Verify hash-based change detection
    print("\n4. Testing change detection...")
    synced_items = frappe.get_all("Item",
        filters={"xero_sync_status": "Synced", "xero_data_hash": ["!=", ""]},
        fields=["name", "item_code", "xero_data_hash"],
        limit=5
    )
    
    if synced_items:
        from xero.api.xero_items import item_data_changed, compute_item_hash
        for item in synced_items:
            doc = frappe.get_doc("Item", item.name)
            changed = item_data_changed(doc)
            print(f"   {item.item_code}: changed={changed}")
    else:
        print("   No synced items with hash found")
    
    print("\n" + "="*60)
    print("Tests completed")
    print("="*60 + "\n")


if __name__ == "__main__":
    run_tests()
