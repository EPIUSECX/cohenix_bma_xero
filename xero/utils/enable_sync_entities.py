#!/usr/bin/env python3
"""
Enable Disabled Entity Syncs in Xero Settings
This script enables the entity syncs that were disabled for testing
"""

import frappe

def enable_entity_syncs():
    """Enable all entity syncs for comprehensive testing"""
    print("\n" + "="*80)
    print("ENABLING ENTITY SYNCS IN XERO SETTINGS")
    print("="*80)
    
    try:
        settings = frappe.get_single("Xero Settings")
        
        # Track changes
        changes = []
        
        # Enable entities that are currently disabled
        if not settings.sync_quotes:
            settings.sync_quotes = 1
            changes.append("Quotations")
        
        if not settings.sync_credit_notes:
            settings.sync_credit_notes = 1
            changes.append("Credit Notes")
        
        if not settings.sync_journal_entries:
            settings.sync_journal_entries = 1
            changes.append("Journal Entries")
        
        if not settings.sync_bank_transactions:
            settings.sync_bank_transactions = 1
            changes.append("Bank Transactions")
        
        if changes:
            settings.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"\n✅ Enabled {len(changes)} entity syncs:")
            for entity in changes:
                print(f"  - {entity}")
        else:
            print("\nℹ️ All entity syncs are already enabled")
        
        # Display current status
        print("\n" + "="*80)
        print("CURRENT ENTITY SYNC STATUS")
        print("="*80)
        print(f"Items: {'✅ Enabled' if settings.sync_items else '❌ Disabled'}")
        print(f"Quotations: {'✅ Enabled' if settings.sync_quotes else '❌ Disabled'}")
        print(f"Invoices: {'✅ Enabled' if settings.sync_invoices else '❌ Disabled'}")
        print(f"Credit Notes: {'✅ Enabled' if settings.sync_credit_notes else '❌ Disabled'}")
        print(f"Payments: {'✅ Enabled' if settings.sync_payments else '❌ Disabled'}")
        print(f"Journal Entries: {'✅ Enabled' if settings.sync_journal_entries else '❌ Disabled'}")
        print(f"Bank Transactions: {'✅ Enabled' if settings.sync_bank_transactions else '❌ Disabled'}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        return False

if __name__ == "__main__":
    enable_entity_syncs()
