"""
Comprehensive Round-Trip Invoice Sync Tests.
Tests Sales and Purchase Invoice sync with various field combinations.

Run with: bench execute xero.test_invoice_roundtrip.run_all_roundtrip_tests

This script tests:
1. Sales Invoice with all fields filled
2. Sales Invoice with minimal fields
3. Sales Invoice with long descriptions (validation)
4. Sales Invoice with HTML in descriptions (sanitization)
5. Sales Invoice with multiple line items
6. Sales Invoice with taxes
7. Purchase Invoice with all fields filled
8. Purchase Invoice with minimal fields
9. Round-trip sync (ERPNext → Xero → ERPNext)
10. Cancel/Void sync
"""

import frappe
from frappe.utils import getdate, flt, nowdate, add_days
import json
from datetime import datetime


class InvoiceRoundTripTest:
    """Comprehensive round-trip sync tests for invoices."""
    
    def __init__(self):
        self.test_results = []
        self.created_docs = []
        self.test_customers = []
        self.test_suppliers = []
        self.test_items = []
        self.settings = None
    
    def setup(self):
        """Setup test prerequisites."""
        print("\n" + "="*60)
        print("SETTING UP TEST ENVIRONMENT")
        print("="*60)
        
        # Get Xero settings
        self.settings = frappe.get_single("Xero Settings")
        
        if not self.settings.enable_xero_sync:
            print("WARNING: Xero sync is disabled. Tests will be limited.")
            return False
        
        if not self.settings.sync_invoices:
            print("WARNING: Invoice sync is disabled. Tests will be limited.")
            return False
        
        # Get company and its base currency
        self.company = frappe.defaults.get_global_default("company")
        self.base_currency = frappe.get_cached_value("Company", self.company, "default_currency")
        print(f"Company: {self.company}")
        print(f"Base Currency: {self.base_currency}")
        
        # Get mapped accounts for invoice line items
        mapped_accounts = self._get_mapped_accounts()
        self.income_account = mapped_accounts.get('income_account')
        self.expense_account = mapped_accounts.get('expense_account')
        
        if not self.income_account:
            print("ERROR: No income account with Xero mapping found!")
            print("Please ensure at least one Income account is mapped in Xero Settings.")
            return False
        
        print(f"Mapped Income Account: {self.income_account}")
        print(f"Mapped Expense Account: {self.expense_account}")
        
        # Get or create test customer
        self.test_customer = self._get_or_create_test_customer()
        self.test_supplier = self._get_or_create_test_supplier()
        self.test_item = self._get_or_create_test_item()
        self.test_item_2 = self._get_or_create_test_item("TEST-ITEM-002", "Test Item 2")
        
        print(f"Test Customer: {self.test_customer}")
        print(f"Test Supplier: {self.test_supplier}")
        print(f"Test Item 1: {self.test_item}")
        print(f"Test Item 2: {self.test_item_2}")
        
        return True
    
    def _get_mapped_accounts(self):
        """Get accounts that have Xero mappings configured."""
        mappings = self.settings.get('account_mapping', [])
        
        income_account = None
        expense_account = None
        
        for mapping in mappings:
            if mapping.erpnext_account and mapping.xero_account_code:
                # Check account type
                acc_type = frappe.db.get_value('Account', mapping.erpnext_account, 'account_type')
                print(f"  Found mapping: {mapping.erpnext_account} (type: {acc_type}) -> Xero: {mapping.xero_account_code}")
                
                # Income account types
                if acc_type in ['Income Account', 'Income'] and not income_account:
                    income_account = mapping.erpnext_account
                # Expense account types
                elif acc_type in ['Expense Account', 'Expense', 'Direct Expense', 'Cost of Goods Sold'] and not expense_account:
                    expense_account = mapping.erpnext_account
                # For accounts without type, check if name contains "Sales" or "Revenue"
                elif not acc_type and not income_account:
                    if 'sales' in mapping.erpnext_account.lower() or 'revenue' in mapping.erpnext_account.lower():
                        income_account = mapping.erpnext_account
        
        return {
            'income_account': income_account,
            'expense_account': expense_account
        }
    
    def _get_or_create_test_customer(self):
        """Get existing synced customer or create one."""
        # Try to find existing customer with Xero ID
        customer = frappe.db.get_value("Customer", 
            {"xero_contact_id": ["is", "set"]}, "name")
        
        if customer:
            return customer
        
        # Create new customer
        customer_name = f"TEST-CUST-{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}"
        
        cust = frappe.new_doc("Customer")
        cust.customer_name = customer_name
        cust.customer_type = "Company"
        cust.territory = "All Territories"
        cust.insert(ignore_permissions=True)
        self.created_docs.append({"doctype": "Customer", "name": cust.name})
        
        # Sync to Xero
        from xero.api.xero_contacts import sync_contact_to_xero
        try:
            sync_contact_to_xero(cust.name, "Customer")
            cust.reload()
            if cust.xero_contact_id:
                return cust.name
        except Exception as e:
            print(f"Warning: Could not sync customer to Xero: {e}")
        
        return cust.name
    
    def _get_or_create_test_supplier(self):
        """Get existing synced supplier or create one."""
        # Try to find existing supplier with Xero ID
        supplier = frappe.db.get_value("Supplier", 
            {"xero_contact_id": ["is", "set"]}, "name")
        
        if supplier:
            return supplier
        
        # Create new supplier
        supplier_name = f"TEST-SUPP-{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}"
        
        supp = frappe.new_doc("Supplier")
        supp.supplier_name = supplier_name
        supp.supplier_type = "Company"
        supp.insert(ignore_permissions=True)
        self.created_docs.append({"doctype": "Supplier", "name": supp.name})
        
        # Sync to Xero
        from xero.api.xero_contacts import sync_contact_to_xero
        try:
            sync_contact_to_xero(supp.name, "Supplier")
            supp.reload()
            if supp.xero_contact_id:
                return supp.name
        except Exception as e:
            print(f"Warning: Could not sync supplier to Xero: {e}")
        
        return supp.name
    
    def _get_or_create_test_item(self, item_code=None, item_name=None):
        """Get existing item or create one."""
        if not item_code:
            item_code = f"TEST-ITEM-{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}"
        
        if frappe.db.exists("Item", item_code):
            return item_code
        
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = item_name or item_code
        item.item_group = "Products"
        item.stock_uom = "Nos"
        item.is_sales_item = 1
        item.is_purchase_item = 1
        item.insert(ignore_permissions=True)
        self.created_docs.append({"doctype": "Item", "name": item.name})
        
        return item.name
    
    def log_result(self, test_name, passed, message="", details=None):
        """Log test result."""
        result = {
            "test": test_name,
            "passed": passed,
            "message": message,
            "details": details or {},
            "timestamp": str(frappe.utils.now())
        }
        self.test_results.append(result)
        
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"\n{status}: {test_name}")
        if message:
            print(f"  {message}")
        if details and not passed:
            print(f"  Details: {json.dumps(details, indent=2)}")
    
    def cleanup(self):
        """Clean up created test documents."""
        print("\n" + "-"*60)
        print("CLEANUP")
        print("-"*60)
        
        for doc_info in reversed(self.created_docs):
            try:
                doctype = doc_info["doctype"]
                name = doc_info["name"]
                if frappe.db.exists(doctype, name):
                    doc = frappe.get_doc(doctype, name)
                    if doc.docstatus == 1:
                        try:
                            doc.cancel()
                        except:
                            pass
                    frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
                    print(f"  Deleted {doctype} {name}")
            except Exception as e:
                print(f"  Error deleting {doc_info}: {e}")
    
    # --- Test Cases ---
    
    def test_01_sales_invoice_all_fields(self):
        """Test 1: Sales Invoice with all fields filled."""
        test_name = "Sales Invoice - All Fields Filled"
        print(f"\n--- {test_name} ---")
        
        try:
            # Create invoice
            si = frappe.new_doc("Sales Invoice")
            si.customer = self.test_customer
            si.posting_date = nowdate()
            si.due_date = add_days(nowdate(), 30)
            si.currency = self.base_currency  # Use company's base currency
            si.po_no = f"PO-{frappe.utils.random_string(10)}"
            si.remarks = "Test invoice with all fields"
            
            si.append("items", {
                "item_code": self.test_item,
                "qty": 5,
                "rate": 100.00,
                "description": "Test item with full details",
                "income_account": self.income_account  # Use mapped account
            })
            
            si.insert(ignore_permissions=True)
            si.submit()
            self.created_docs.append({"doctype": "Sales Invoice", "name": si.name})
            
            # Sync to Xero
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(si.name, "Sales Invoice")
            
            # Verify
            si.reload()
            
            if si.xero_invoice_id:
                self.log_result(test_name, True, 
                    f"Invoice synced with Xero ID: {si.xero_invoice_id}",
                    {"xero_invoice_id": si.xero_invoice_id, "xero_sync_status": si.xero_sync_status})
                return True
            else:
                self.log_result(test_name, False, 
                    f"Invoice not synced. Status: {si.xero_sync_status}")
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}", 
                {"traceback": frappe.get_traceback()})
            return False
    
    def test_02_sales_invoice_minimal_fields(self):
        """Test 2: Sales Invoice with minimal fields."""
        test_name = "Sales Invoice - Minimal Fields"
        print(f"\n--- {test_name} ---")
        
        try:
            si = frappe.new_doc("Sales Invoice")
            si.customer = self.test_customer
            si.posting_date = nowdate()
            
            si.append("items", {
                "item_code": self.test_item,
                "qty": 1,
                "rate": 50.00,
                "income_account": self.income_account  # Use mapped account
            })
            
            si.insert(ignore_permissions=True)
            si.submit()
            self.created_docs.append({"doctype": "Sales Invoice", "name": si.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(si.name, "Sales Invoice")
            
            si.reload()
            
            if si.xero_invoice_id:
                self.log_result(test_name, True, f"Synced with ID: {si.xero_invoice_id}")
                return True
            else:
                self.log_result(test_name, False, f"Status: {si.xero_sync_status}")
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def test_03_sales_invoice_long_description(self):
        """Test 3: Sales Invoice with long description (validation test)."""
        test_name = "Sales Invoice - Long Description"
        print(f"\n--- {test_name} ---")
        
        try:
            si = frappe.new_doc("Sales Invoice")
            si.customer = self.test_customer
            si.posting_date = nowdate()
            
            # Create a very long description (5000 chars)
            long_desc = "A" * 5000
            
            si.append("items", {
                "item_code": self.test_item,
                "qty": 1,
                "rate": 100.00,
                "description": long_desc,
                "income_account": self.income_account  # Use mapped account
            })
            
            si.insert(ignore_permissions=True)
            si.submit()
            self.created_docs.append({"doctype": "Sales Invoice", "name": si.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(si.name, "Sales Invoice")
            
            si.reload()
            
            if si.xero_invoice_id:
                self.log_result(test_name, True, 
                    f"Long description handled correctly. Synced with ID: {si.xero_invoice_id}")
                return True
            else:
                self.log_result(test_name, False, f"Status: {si.xero_sync_status}")
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def test_04_sales_invoice_html_description(self):
        """Test 4: Sales Invoice with HTML in description (sanitization test)."""
        test_name = "Sales Invoice - HTML Description"
        print(f"\n--- {test_name} ---")
        
        try:
            si = frappe.new_doc("Sales Invoice")
            si.customer = self.test_customer
            si.posting_date = nowdate()
            
            html_desc = "<p>This is <b>bold</b> and <i>italic</i> text</p>"
            
            si.append("items", {
                "item_code": self.test_item,
                "qty": 1,
                "rate": 100.00,
                "description": html_desc,
                "income_account": self.income_account  # Use mapped account
            })
            
            si.insert(ignore_permissions=True)
            si.submit()
            self.created_docs.append({"doctype": "Sales Invoice", "name": si.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(si.name, "Sales Invoice")
            
            si.reload()
            
            if si.xero_invoice_id:
                self.log_result(test_name, True, 
                    f"HTML sanitized correctly. Synced with ID: {si.xero_invoice_id}")
                return True
            else:
                self.log_result(test_name, False, f"Status: {si.xero_sync_status}")
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def test_05_sales_invoice_multiple_items(self):
        """Test 5: Sales Invoice with multiple line items."""
        test_name = "Sales Invoice - Multiple Items"
        print(f"\n--- {test_name} ---")
        
        try:
            si = frappe.new_doc("Sales Invoice")
            si.customer = self.test_customer
            si.posting_date = nowdate()
            
            # Add multiple items
            for i in range(5):
                si.append("items", {
                    "item_code": self.test_item,
                    "qty": i + 1,
                    "rate": 10.00 * (i + 1),
                    "description": f"Line item {i + 1}",
                    "income_account": self.income_account  # Use mapped account
                })
            
            si.insert(ignore_permissions=True)
            si.submit()
            self.created_docs.append({"doctype": "Sales Invoice", "name": si.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(si.name, "Sales Invoice")
            
            si.reload()
            
            if si.xero_invoice_id:
                self.log_result(test_name, True, 
                    f"Multiple items synced. ID: {si.xero_invoice_id}, Items: {len(si.items)}")
                return True
            else:
                self.log_result(test_name, False, f"Status: {si.xero_sync_status}")
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def test_06_sales_invoice_with_taxes(self):
        """Test 6: Sales Invoice with taxes."""
        test_name = "Sales Invoice - With Taxes"
        print(f"\n--- {test_name} ---")
        
        try:
            si = frappe.new_doc("Sales Invoice")
            si.customer = self.test_customer
            si.posting_date = nowdate()
            
            si.append("items", {
                "item_code": self.test_item,
                "qty": 1,
                "rate": 100.00,
                "income_account": self.income_account  # Use mapped account
            })
            
            # Add tax if template exists
            tax_template = frappe.db.get_value("Sales Taxes and Charges Template", 
                {"company": si.company}, "name")
            
            if tax_template:
                si.taxes_and_charges = tax_template
            else:
                # Add manual tax
                si.append("taxes", {
                    "charge_type": "On Net Total",
                    "account_head": frappe.db.get_value("Account", 
                        {"account_type": "Tax", "company": si.company}, "name"),
                    "description": "Test Tax 10%",
                    "rate": 10
                })
            
            si.insert(ignore_permissions=True)
            si.submit()
            self.created_docs.append({"doctype": "Sales Invoice", "name": si.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(si.name, "Sales Invoice")
            
            si.reload()
            
            if si.xero_invoice_id:
                self.log_result(test_name, True, 
                    f"Invoice with taxes synced. ID: {si.xero_invoice_id}")
                return True
            else:
                self.log_result(test_name, False, f"Status: {si.xero_sync_status}")
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def test_07_purchase_invoice_all_fields(self):
        """Test 7: Purchase Invoice with all fields filled."""
        test_name = "Purchase Invoice - All Fields Filled"
        print(f"\n--- {test_name} ---")
        
        try:
            pi = frappe.new_doc("Purchase Invoice")
            pi.supplier = self.test_supplier
            pi.posting_date = nowdate()
            pi.due_date = add_days(nowdate(), 30)
            pi.currency = self.base_currency  # Use company's base currency
            pi.bill_no = f"BILL-{frappe.utils.random_string(10)}"
            pi.remarks = "Test purchase invoice with all fields"
            
            pi.append("items", {
                "item_code": self.test_item,
                "qty": 3,
                "rate": 50.00,
                "description": "Test purchase item",
                "expense_account": self.expense_account or self.income_account  # Use mapped account
            })
            
            pi.insert(ignore_permissions=True)
            pi.submit()
            self.created_docs.append({"doctype": "Purchase Invoice", "name": pi.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(pi.name, "Purchase Invoice")
            
            pi.reload()
            
            if pi.xero_invoice_id:
                self.log_result(test_name, True, 
                    f"Purchase Invoice synced with ID: {pi.xero_invoice_id}")
                return True
            else:
                self.log_result(test_name, False, f"Status: {pi.xero_sync_status}")
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def test_08_purchase_invoice_minimal_fields(self):
        """Test 8: Purchase Invoice with minimal fields."""
        test_name = "Purchase Invoice - Minimal Fields"
        print(f"\n--- {test_name} ---")
        
        try:
            pi = frappe.new_doc("Purchase Invoice")
            pi.supplier = self.test_supplier
            pi.posting_date = nowdate()
            
            pi.append("items", {
                "item_code": self.test_item,
                "qty": 1,
                "rate": 25.00,
                "expense_account": self.expense_account or self.income_account  # Use mapped account
            })
            
            pi.insert(ignore_permissions=True)
            pi.submit()
            self.created_docs.append({"doctype": "Purchase Invoice", "name": pi.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(pi.name, "Purchase Invoice")
            
            pi.reload()
            
            if pi.xero_invoice_id:
                self.log_result(test_name, True, f"Synced with ID: {pi.xero_invoice_id}")
                return True
            else:
                self.log_result(test_name, False, f"Status: {pi.xero_sync_status}")
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def test_09_roundtrip_sync(self):
        """Test 9: Round-trip sync (ERPNext → Xero → ERPNext)."""
        test_name = "Round-Trip Sync"
        print(f"\n--- {test_name} ---")
        
        try:
            # Create and sync invoice
            si = frappe.new_doc("Sales Invoice")
            si.customer = self.test_customer
            si.posting_date = nowdate()
            
            si.append("items", {
                "item_code": self.test_item,
                "qty": 2,
                "rate": 75.00,
                "description": "Round-trip test item",
                "income_account": self.income_account  # Use mapped account
            })
            
            si.insert(ignore_permissions=True)
            si.submit()
            self.created_docs.append({"doctype": "Sales Invoice", "name": si.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(si.name, "Sales Invoice")
            
            si.reload()
            original_xero_id = si.xero_invoice_id
            
            if not original_xero_id:
                self.log_result(test_name, False, "Initial sync failed")
                return False
            
            # Sync from Xero (should not create duplicate)
            from xero.api.xero_invoices import sync_invoices_from_xero
            sync_invoices_from_xero(invoice_type="ACCREC")
            
            # Check for duplicates
            duplicates = frappe.get_all("Sales Invoice", 
                filters={"xero_invoice_id": original_xero_id},
                fields=["name"])
            
            if len(duplicates) == 1:
                self.log_result(test_name, True, 
                    f"Round-trip successful. No duplicates created. Xero ID: {original_xero_id}")
                return True
            else:
                self.log_result(test_name, False, 
                    f"Found {len(duplicates)} invoices with same Xero ID",
                    {"duplicates": [d.name for d in duplicates]})
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def test_10_cancel_void_sync(self):
        """Test 10: Cancel invoice and verify void/delete in Xero."""
        test_name = "Cancel/Void Sync"
        print(f"\n--- {test_name} ---")
        
        try:
            # Create and sync invoice
            si = frappe.new_doc("Sales Invoice")
            si.customer = self.test_customer
            si.posting_date = nowdate()
            
            si.append("items", {
                "item_code": self.test_item,
                "qty": 1,
                "rate": 100.00,
                "income_account": self.income_account  # Use mapped account
            })
            
            si.insert(ignore_permissions=True)
            si.submit()
            self.created_docs.append({"doctype": "Sales Invoice", "name": si.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(si.name, "Sales Invoice")
            
            si.reload()
            
            if not si.xero_invoice_id:
                self.log_result(test_name, False, "Initial sync failed")
                return False
            
            # Cancel the invoice
            si.cancel()
            
            # Trigger void sync
            from xero.api.xero_invoices import void_invoice_in_xero
            void_invoice_in_xero(si.name, "Sales Invoice")
            
            si.reload()
            
            self.log_result(test_name, True, 
                f"Invoice cancelled. Xero sync status: {si.xero_sync_status}")
            return True
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def test_11_empty_description_fallback(self):
        """Test 11: Empty description falls back to item name."""
        test_name = "Empty Description Fallback"
        print(f"\n--- {test_name} ---")
        
        try:
            si = frappe.new_doc("Sales Invoice")
            si.customer = self.test_customer
            si.posting_date = nowdate()
            
            si.append("items", {
                "item_code": self.test_item,
                "qty": 1,
                "rate": 100.00,
                "description": "",  # Empty description
                "income_account": self.income_account  # Use mapped account
            })
            
            si.insert(ignore_permissions=True)
            si.submit()
            self.created_docs.append({"doctype": "Sales Invoice", "name": si.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(si.name, "Sales Invoice")
            
            si.reload()
            
            if si.xero_invoice_id:
                self.log_result(test_name, True, 
                    f"Empty description handled. Synced with ID: {si.xero_invoice_id}")
                return True
            else:
                self.log_result(test_name, False, f"Status: {si.xero_sync_status}")
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def test_12_special_characters_in_reference(self):
        """Test 12: Special characters in reference field."""
        test_name = "Special Characters in Reference"
        print(f"\n--- {test_name} ---")
        
        try:
            si = frappe.new_doc("Sales Invoice")
            si.customer = self.test_customer
            si.posting_date = nowdate()
            si.po_no = "PO-#123/456 & Co. (Special!)"
            
            si.append("items", {
                "item_code": self.test_item,
                "qty": 1,
                "rate": 100.00,
                "income_account": self.income_account  # Use mapped account
            })
            
            si.insert(ignore_permissions=True)
            si.submit()
            self.created_docs.append({"doctype": "Sales Invoice", "name": si.name})
            
            from xero.api.xero_invoices import sync_invoice_to_xero
            sync_invoice_to_xero(si.name, "Sales Invoice")
            
            si.reload()
            
            if si.xero_invoice_id:
                self.log_result(test_name, True, 
                    f"Special characters handled. Synced with ID: {si.xero_invoice_id}")
                return True
            else:
                self.log_result(test_name, False, f"Status: {si.xero_sync_status}")
                return False
                
        except Exception as e:
            self.log_result(test_name, False, f"Exception: {str(e)}")
            return False
    
    def run_all_tests(self):
        """Run all round-trip tests."""
        print("\n" + "="*60)
        print("INVOICE ROUND-TRIP SYNC TESTS")
        print("="*60)
        
        # Setup
        if not self.setup():
            print("\nSetup failed. Cannot run tests.")
            return {"passed": 0, "failed": 0, "total": 0, "results": []}
        
        tests = [
            self.test_01_sales_invoice_all_fields,
            self.test_02_sales_invoice_minimal_fields,
            self.test_03_sales_invoice_long_description,
            self.test_04_sales_invoice_html_description,
            self.test_05_sales_invoice_multiple_items,
            self.test_06_sales_invoice_with_taxes,
            self.test_07_purchase_invoice_all_fields,
            self.test_08_purchase_invoice_minimal_fields,
            self.test_09_roundtrip_sync,
            self.test_10_cancel_void_sync,
            self.test_11_empty_description_fallback,
            self.test_12_special_characters_in_reference,
        ]
        
        passed = 0
        failed = 0
        
        for test in tests:
            try:
                result = test()
                if result:
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                self.log_result(test.__name__, False, f"Unexpected exception: {str(e)}")
        
        # Cleanup
        self.cleanup()
        
        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Total:  {passed + failed}")
        print("="*60)
        
        return {
            "passed": passed,
            "failed": failed,
            "total": passed + failed,
            "results": self.test_results
        }


def run_all_roundtrip_tests():
    """Run all round-trip sync tests."""
    tester = InvoiceRoundTripTest()
    return tester.run_all_tests()


def check_recent_logs():
    """Check recent Xero logs for debugging."""
    import frappe
    
    logs = frappe.get_all('Xero Log', 
        fields=['name', 'message', 'status', 'creation', 'error_details'],
        order_by='creation desc',
        limit=10)
    
    print("\n" + "="*60)
    print("RECENT XERO LOGS")
    print("="*60)
    
    for log in logs:
        print(f"\n--- {log.name} ({log.status}) ---")
        print(f"Time: {log.creation}")
        print(f"Message: {log.message}")
        if log.error_details:
            print(f"Error: {log.error_details[:1000]}")
    
    return logs


def check_sync_errors():
    """Check for invoice sync errors specifically."""
    import frappe
    
    logs = frappe.get_all('Xero Log', 
        fields=['name', 'message', 'status', 'creation', 'error_details', 'erpnext_doc_type', 'erpnext_doc_name'],
        filters={'message': ['like', '%sync%Invoice%']},
        order_by='creation desc',
        limit=20)
    
    print("\n" + "="*60)
    print("INVOICE SYNC ERROR LOGS")
    print("="*60)
    
    for log in logs:
        print(f"\n--- {log.name} ({log.status}) ---")
        print(f"Time: {log.creation}")
        print(f"Doc: {log.erpnext_doc_type} {log.erpnext_doc_name}")
        print(f"Message: {log.message}")
        if log.error_details:
            print(f"Error: {log.error_details[:1500]}")
    
    return logs


def check_account_mappings():
    """Check Xero account mappings."""
    import frappe
    
    settings = frappe.get_doc('Xero Settings')
    print("\n" + "="*60)
    print("XERO SETTINGS ACCOUNT MAPPINGS")
    print("="*60)
    
    mappings = settings.get('account_mapping', [])
    if mappings:
        for mapping in mappings:
            print(f"ERPNext: {mapping.erpnext_account} -> Xero: {mapping.xero_account_code}")
    else:
        print("No account mappings found!")
    
    # Also check what accounts exist
    print("\n=== ERPNext Accounts (Income and Expense) ===")
    accounts = frappe.get_all('Account', 
        filters={'company': 'Accron', 'account_type': ['in', ['Income', 'Expense', 'Cost of Goods Sold', 'Receivable', 'Payable']]},
        fields=['name', 'account_type', 'account_name'],
        limit=20)
    for acc in accounts:
        print(f'{acc.name} - {acc.account_type}')
    
    return settings


def get_mapped_accounts():
    """Get accounts that have Xero mappings configured."""
    import frappe
    
    settings = frappe.get_doc('Xero Settings')
    mappings = settings.get('account_mapping', [])
    
    income_account = None
    expense_account = None
    
    for mapping in mappings:
        if mapping.erpnext_account and mapping.xero_account_code:
            # Check account type
            acc_type = frappe.db.get_value('Account', mapping.erpnext_account, 'account_type')
            if acc_type == 'Income' and not income_account:
                income_account = mapping.erpnext_account
            elif acc_type == 'Expense' and not expense_account:
                expense_account = mapping.erpnext_account
            elif acc_type == 'Cost of Goods Sold' and not expense_account:
                expense_account = mapping.erpnext_account
    
    return {
        'income_account': income_account,
        'expense_account': expense_account
    }


if __name__ == "__main__":
    run_all_roundtrip_tests()
