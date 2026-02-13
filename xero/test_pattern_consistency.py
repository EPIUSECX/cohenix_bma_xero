"""
Test pattern consistency across sync modules.

Run with: bench execute xero.test_pattern_consistency.run_tests
"""

import frappe


def run_tests():
    """Check that all sync modules follow the same pattern."""
    print("\n" + "="*60)
    print("Pattern Consistency Check")
    print("="*60 + "\n")
    
    modules = {
        'xero_contacts': {
            'enqueue': 'enqueue_sync_contact',
            'sync_to': 'sync_contact_to_xero',
            'sync_from': 'sync_contacts_from_xero',
            'process': 'process_xero_contact',
        },
        'xero_accounts': {
            'enqueue': 'enqueue_sync_account',
            'sync_to': 'sync_account_to_xero',
            'sync_from': 'sync_accounts_from_xero',
            'process': 'process_xero_account',
        },
        'xero_items': {
            'enqueue': 'enqueue_sync_item',
            'sync_to': 'sync_item_to_xero',
            'sync_from': 'sync_items_from_xero',
            'process': 'process_xero_item',
        },
    }
    
    all_passed = True
    
    for module_name, functions in modules.items():
        print(f"{module_name}:")
        try:
            mod = __import__(f'xero.api.{module_name}', fromlist=[''])
            
            for func_type, func_name in functions.items():
                has_func = hasattr(mod, func_name)
                status = "✓" if has_func else "✗"
                print(f"  {status} {func_type}: {func_name}")
                if not has_func:
                    all_passed = False
            
            # Check for double-trigger guard in enqueue function
            import inspect
            enqueue_func = getattr(mod, functions['enqueue'])
            source = inspect.getsource(enqueue_func)
            
            has_guard = 'xero_sync_status' in source and 'Synced' in source
            status = "✓" if has_guard else "✗"
            print(f"  {status} double-trigger guard")
            if not has_guard:
                all_passed = False
            
            # Check for hash computation
            has_hash = 'compute_' in dir(mod) or 'data_hash' in source
            if 'hash' in dir(mod) or any('hash' in f.lower() for f in dir(mod)):
                has_hash = True
            
            # Check for retry decorator on sync_to function
            sync_to_func = getattr(mod, functions['sync_to'])
            sync_source = inspect.getsource(sync_to_func)
            has_retry = 'retry_with_exponential_backoff' in sync_source or '@retry' in sync_source
            status = "✓" if has_retry else "✗"
            print(f"  {status} retry decorator on sync_to_xero")
            if not has_retry:
                all_passed = False
            
        except Exception as e:
            print(f"  ✗ ERROR: {str(e)}")
            all_passed = False
        
        print()
    
    # Check hooks.py for all doc_events
    print("hooks.py doc_events:")
    try:
        from xero import hooks
        doc_events = hooks.doc_events
        
        expected_doctypes = ['Customer', 'Supplier', 'Account', 'Item']
        for doctype in expected_doctypes:
            has_hook = doctype in doc_events
            status = "✓" if has_hook else "✗"
            print(f"  {status} {doctype}")
            if not has_hook:
                all_passed = False
    except Exception as e:
        print(f"  ✗ ERROR: {str(e)}")
        all_passed = False
    
    print("\n" + "="*60)
    if all_passed:
        print("All pattern checks PASSED")
    else:
        print("Some pattern checks FAILED")
    print("="*60 + "\n")
    
    return all_passed


if __name__ == "__main__":
    run_tests()
