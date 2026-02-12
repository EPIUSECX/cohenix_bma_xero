#!/usr/bin/env python3
"""
Sync Test Contacts to Xero
This script syncs the test customers and suppliers created for outbound sync testing.
Run this after the test contacts have been properly configured (addresses, contact persons, etc.)
"""

import frappe
from frappe.utils import now_datetime

def sync_test_contacts():
    """Sync all test contacts to Xero"""
    print("\n" + "="*80)
    print("SYNCING TEST CONTACTS TO XERO")
    print("="*80)
    
    results = {
        "customers_synced": 0,
        "customers_failed": 0,
        "suppliers_synced": 0,
        "suppliers_failed": 0,
        "errors": []
    }
    
    # Find test customers
    customers = frappe.get_all("Customer",
        filters={"name": ["like", "Test Customer - Outbound Sync%"]},
        fields=["name", "customer_name", "xero_sync_status", "xero_contact_id"]
    )
    
    print(f"\nFound {len(customers)} test customers to sync")
    
    for customer in customers:
        try:
            print(f"\nSyncing customer: {customer.customer_name}")
            
            # Import and call sync function
            from xero.api.xero_contacts import sync_contact_to_xero
            
            sync_contact_to_xero(customer.name, "Customer")
            
            # Check if synced
            updated = frappe.get_doc("Customer", customer.name)
            if updated.xero_sync_status == "Synced" and updated.xero_contact_id:
                print(f"  ✅ SUCCESS: Xero ID = {updated.xero_contact_id}")
                results["customers_synced"] += 1
            else:
                print(f"  ❌ FAILED: Status = {updated.xero_sync_status}")
                results["customers_failed"] += 1
                results["errors"].append({
                    "type": "Customer",
                    "name": customer.name,
                    "status": updated.xero_sync_status
                })
                
        except Exception as e:
            print(f"  ❌ ERROR: {str(e)}")
            results["customers_failed"] += 1
            results["errors"].append({
                "type": "Customer",
                "name": customer.name,
                "error": str(e)
            })
    
    # Find test suppliers
    suppliers = frappe.get_all("Supplier",
        filters={"name": ["like", "Test Supplier - Outbound Sync%"]},
        fields=["name", "supplier_name", "xero_sync_status", "xero_contact_id"]
    )
    
    print(f"\nFound {len(suppliers)} test suppliers to sync")
    
    for supplier in suppliers:
        try:
            print(f"\nSyncing supplier: {supplier.supplier_name}")
            
            # Import and call sync function
            from xero.api.xero_contacts import sync_contact_to_xero
            
            sync_contact_to_xero(supplier.name, "Supplier")
            
            # Check if synced
            updated = frappe.get_doc("Supplier", supplier.name)
            if updated.xero_sync_status == "Synced" and updated.xero_contact_id:
                print(f"  ✅ SUCCESS: Xero ID = {updated.xero_contact_id}")
                results["suppliers_synced"] += 1
            else:
                print(f"  ❌ FAILED: Status = {updated.xero_sync_status}")
                results["suppliers_failed"] += 1
                results["errors"].append({
                    "type": "Supplier",
                    "name": supplier.name,
                    "status": updated.xero_sync_status
                })
                
        except Exception as e:
            print(f"  ❌ ERROR: {str(e)}")
            results["suppliers_failed"] += 1
            results["errors"].append({
                "type": "Supplier",
                "name": supplier.name,
                "error": str(e)
            })
    
    # Summary
    print("\n" + "="*80)
    print("SYNC SUMMARY")
    print("="*80)
    print(f"Customers Synced: {results['customers_synced']}")
    print(f"Customers Failed: {results['customers_failed']}")
    print(f"Suppliers Synced: {results['suppliers_synced']}")
    print(f"Suppliers Failed: {results['suppliers_failed']}")
    
    if results["errors"]:
        print(f"\n❌ Errors ({len(results['errors'])}):")
        for error in results["errors"]:
            print(f"  - {error['type']}: {error['name']}")
            if "error" in error:
                print(f"    Error: {error['error']}")
            else:
                print(f"    Status: {error.get('status', 'Unknown')}")
    
    print("\n✅ Contact sync complete!")
    
    return results

if __name__ == "__main__":
    sync_test_contacts()
