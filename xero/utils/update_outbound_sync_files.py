#!/usr/bin/env python3
"""
Script to batch update remaining outbound sync files with directional toggle checks.
"""

import re
import os

# Files to update with their sync function patterns
files_to_update = [
    {
        "path": "/workspace/cohenix-bench/apps/xero/xero/api/xero_bank_transactions.py",
        "function": "sync_bank_transaction_to_xero",
        "doc_type_var": "doc_type",
        "doc_name_var": "doc_name"
    },
    {
        "path": "/workspace/cohenix-bench/apps/xero/xero/api/xero_credit_notes.py",
        "function": "sync_return_to_xero",
        "doc_type_var": "doc_type",
        "doc_name_var": "doc_name"
    },
    {
        "path": "/workspace/cohenix-bench/apps/xero/xero/api/xero_sales_orders.py",
        "function": "sync_sales_order_to_xero",
        "doc_type_var": "doc_type",
        "doc_name_var": "doc_name"
    },
    {
        "path": "/workspace/cohenix-bench/apps/xero/xero/api/xero_purchase_orders.py",
        "function": "sync_purchase_order_to_xero",
        "doc_type_var": "doc_type",
        "doc_name_var": "doc_name"
    },
    {
        "path": "/workspace/cohenix-bench/apps/xero/xero/api/xero_delivery_notes.py",
        "function": "sync_delivery_note_to_xero",
        "doc_type_var": "doc_type",
        "doc_name_var": "doc_name"
    },
    {
        "path": "/workspace/cohenix-bench/apps/xero/xero/api/xero_purchase_receipts.py",
        "function": "sync_purchase_receipt_to_xero",
        "doc_type_var": "doc_type",
        "doc_name_var": "doc_name"
    },
    {
        "path": "/workspace/cohenix-bench/apps/xero/xero/api/xero_stock.py",
        "function": "sync_stock_ledger_to_xero",
        "doc_type_var": "doc_type",
        "doc_name_var": "doc_name"
    }
]

# The code block to insert after enable_xero_sync check
directional_check_code = '''    
    # Check directional toggle for outbound sync
    if not settings.enable_sync_to_xero:
        log_xero_error(
            message=f"Sync to Xero is disabled. Skipping {{{doc_type_var}}} {{{doc_name_var}}} outbound sync.",
            status="Info",
            erpnext_doc_type={doc_type_var},
            erpnext_doc_name={doc_name_var},
            category="System Monitoring"
        )
        return
'''

def update_file(file_info):
    """Update a single file with directional toggle check."""
    filepath = file_info["path"]
    
    if not os.path.exists(filepath):
        print(f"⚠️  File not found: {filepath}")
        return False
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Pattern to find: settings check followed by entity-specific check
    # We want to insert our code between these two checks
    pattern = r'(if not settings\.enable_xero_sync:.*?return.*?\n)(    if not settings\.)'
    
    # Create the replacement with our directional check
    doc_type_var = file_info["doc_type_var"]
    doc_name_var = file_info["doc_name_var"]
    
    directional_code = directional_check_code.format(
        doc_type_var=doc_type_var,
        doc_name_var=doc_name_var
    )
    
    replacement = r'\1' + directional_code + r'\2'
    
    # Check if already updated
    if 'enable_sync_to_xero' in content:
        print(f"✓ Already updated: {filepath}")
        return True
    
    # Perform replacement
    new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)
    
    if count > 0:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"✓ Updated: {filepath} ({count} occurrence(s))")
        return True
    else:
        print(f"⚠️  Pattern not found in: {filepath}")
        return False

def main():
    """Main function to update all files."""
    print("=" * 60)
    print("Updating Outbound Sync Files with Directional Toggle Checks")
    print("=" * 60)
    print()
    
    updated_count = 0
    failed_count = 0
    
    for file_info in files_to_update:
        if update_file(file_info):
            updated_count += 1
        else:
            failed_count += 1
        print()
    
    print("=" * 60)
    print(f"Summary: {updated_count} files updated, {failed_count} files failed/skipped")
    print("=" * 60)

if __name__ == "__main__":
    main()
