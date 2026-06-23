#!/usr/bin/env python3
"""
Create Test Data for Outbound Sync Testing
Generates 2 example entries for each entity type following the pattern:
"Test [Entity] - Outbound Sync 1" and "Test [Entity] - Outbound Sync 2"
"""

import frappe
from frappe.utils import today, add_days, nowdate, now_datetime
from xero.utils.logging import get_leaf_doctype_value

def create_test_customers():
    """Create 2 test customers for outbound sync"""
    print("\n" + "="*80)
    print("Creating Test Customers")
    print("="*80)
    
    customers = []
    for i in range(1, 3):
        customer_name = f"Test Customer - Outbound Sync {i}"
        
        # Check if already exists
        if frappe.db.exists("Customer", customer_name):
            print(f"✓ Customer {customer_name} already exists")
            customers.append(customer_name)
            continue
        
        try:
            customer = frappe.new_doc("Customer")
            customer.customer_name = customer_name
            customer.customer_type = "Company"
            customer.customer_group = get_leaf_doctype_value("Customer Group", "Commercial")
            customer.territory = get_leaf_doctype_value("Territory")
            customer.insert(ignore_permissions=True)
            frappe.db.commit()
            
            print(f"✓ Created customer: {customer.name}")
            customers.append(customer.name)
        except Exception as e:
            print(f"✗ Failed to create customer {customer_name}: {str(e)}")
    
    return customers

def create_test_suppliers():
    """Create 2 test suppliers for outbound sync"""
    print("\n" + "="*80)
    print("Creating Test Suppliers")
    print("="*80)
    
    suppliers = []
    for i in range(1, 3):
        supplier_name = f"Test Supplier - Outbound Sync {i}"
        
        # Check if already exists
        if frappe.db.exists("Supplier", supplier_name):
            print(f"✓ Supplier {supplier_name} already exists")
            suppliers.append(supplier_name)
            continue
        
        try:
            supplier = frappe.new_doc("Supplier")
            supplier.supplier_name = supplier_name
            supplier.supplier_group = get_leaf_doctype_value("Supplier Group")
            supplier.supplier_type = "Company"
            supplier.insert(ignore_permissions=True)
            frappe.db.commit()
            
            print(f"✓ Created supplier: {supplier.name}")
            suppliers.append(supplier.name)
        except Exception as e:
            print(f"✗ Failed to create supplier {supplier_name}: {str(e)}")
    
    return suppliers

def create_test_items():
    """Create 2 test items for outbound sync"""
    print("\n" + "="*80)
    print("Creating Test Items")
    print("="*80)
    
    # Get default company
    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1)[0].name
    
    # Get default accounts
    income_account = frappe.db.get_value("Account", {
        "company": company,
        "account_type": "Income Account",
        "is_group": 0
    }, "name")
    
    expense_account = frappe.db.get_value("Account", {
        "company": company,
        "account_type": "Expense Account",
        "is_group": 0
    }, "name")
    
    items = []
    for i in range(1, 3):
        item_code = f"TEST-ITEM-OUTBOUND-{i:03d}"
        
        # Check if already exists
        if frappe.db.exists("Item", item_code):
            print(f"✓ Item {item_code} already exists")
            items.append(item_code)
            continue
        
        try:
            item = frappe.new_doc("Item")
            item.item_code = item_code
            item.item_name = f"Test Item - Outbound Sync {i}"
            item.item_group = "Products"
            item.stock_uom = "Nos"
            item.is_sales_item = 1
            item.is_purchase_item = 1
            item.is_stock_item = 0
            item.standard_rate = 100.00 * i  # 100, 200
            item.last_purchase_rate = 50.00 * i  # 50, 100
            
            # Set accounts
            if income_account:
                item.income_account = income_account
            if expense_account:
                item.expense_account = expense_account
            
            item.insert(ignore_permissions=True)
            frappe.db.commit()
            
            print(f"✓ Created item: {item.name} (Rate: {item.standard_rate})")
            items.append(item.name)
        except Exception as e:
            print(f"✗ Failed to create item {item_code}: {str(e)}")
    
    return items

def create_test_quotations(customers, items):
    """Create 2 test quotations for outbound sync"""
    print("\n" + "="*80)
    print("Creating Test Quotations")
    print("="*80)
    
    if not customers or not items:
        print("✗ Cannot create quotations without customers and items")
        return []
    
    quotations = []
    for i in range(1, 3):
        try:
            quotation = frappe.new_doc("Quotation")
            quotation.quotation_to = "Customer"
            quotation.party_name = customers[i-1] if i <= len(customers) else customers[0]
            quotation.transaction_date = today()
            quotation.valid_till = add_days(today(), 30)
            
            # Add item
            quotation.append("items", {
                "item_code": items[i-1] if i <= len(items) else items[0],
                "qty": i,
                "rate": 100.00 * i
            })
            
            quotation.insert(ignore_permissions=True)
            quotation.submit()
            frappe.db.commit()
            
            print(f"✓ Created and submitted quotation: {quotation.name}")
            quotations.append(quotation.name)
        except Exception as e:
            print(f"✗ Failed to create quotation {i}: {str(e)}")
    
    return quotations

def create_test_sales_invoices(customers, items):
    """Create 2 test sales invoices for outbound sync"""
    print("\n" + "="*80)
    print("Creating Test Sales Invoices")
    print("="*80)
    
    if not customers or not items:
        print("✗ Cannot create sales invoices without customers and items")
        return []
    
    # Get default company and income account
    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1)[0].name
    income_account = frappe.db.get_value("Account", {
        "company": company,
        "account_type": "Income Account",
        "is_group": 0
    }, "name")
    
    debit_to = frappe.db.get_value("Account", {
        "company": company,
        "account_type": "Receivable",
        "is_group": 0
    }, "name")
    
    invoices = []
    for i in range(1, 3):
        try:
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = customers[i-1] if i <= len(customers) else customers[0]
            invoice.posting_date = today()
            invoice.due_date = add_days(today(), 30)
            invoice.company = company
            invoice.debit_to = debit_to
            
            # Add item
            invoice.append("items", {
                "item_code": items[i-1] if i <= len(items) else items[0],
                "qty": i,
                "rate": 100.00 * i,
                "income_account": income_account
            })
            
            invoice.insert(ignore_permissions=True)
            invoice.submit()
            frappe.db.commit()
            
            print(f"✓ Created and submitted sales invoice: {invoice.name}")
            invoices.append(invoice.name)
        except Exception as e:
            print(f"✗ Failed to create sales invoice {i}: {str(e)}")
            print(f"   Error: {frappe.get_traceback()}")
    
    return invoices

def create_test_purchase_invoices(suppliers, items):
    """Create 2 test purchase invoices for outbound sync"""
    print("\n" + "="*80)
    print("Creating Test Purchase Invoices")
    print("="*80)
    
    if not suppliers or not items:
        print("✗ Cannot create purchase invoices without suppliers and items")
        return []
    
    # Get default company and expense account
    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1)[0].name
    expense_account = frappe.db.get_value("Account", {
        "company": company,
        "account_type": "Expense Account",
        "is_group": 0
    }, "name")
    
    credit_to = frappe.db.get_value("Account", {
        "company": company,
        "account_type": "Payable",
        "is_group": 0
    }, "name")
    
    invoices = []
    for i in range(1, 3):
        try:
            invoice = frappe.new_doc("Purchase Invoice")
            invoice.supplier = suppliers[i-1] if i <= len(suppliers) else suppliers[0]
            invoice.posting_date = today()
            invoice.due_date = add_days(today(), 30)
            invoice.company = company
            invoice.credit_to = credit_to
            
            # Add item
            invoice.append("items", {
                "item_code": items[i-1] if i <= len(items) else items[0],
                "qty": i,
                "rate": 50.00 * i,
                "expense_account": expense_account
            })
            
            invoice.insert(ignore_permissions=True)
            invoice.submit()
            frappe.db.commit()
            
            print(f"✓ Created and submitted purchase invoice: {invoice.name}")
            invoices.append(invoice.name)
        except Exception as e:
            print(f"✗ Failed to create purchase invoice {i}: {str(e)}")
            print(f"   Error: {frappe.get_traceback()}")
    
    return invoices

def create_test_payment_entries(sales_invoices, purchase_invoices):
    """Create 2 test payment entries for outbound sync"""
    print("\n" + "="*80)
    print("Creating Test Payment Entries")
    print("="*80)
    
    if not sales_invoices and not purchase_invoices:
        print("✗ Cannot create payment entries without invoices")
        return []
    
    # Get default company and bank account
    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1)[0].name
    bank_account = frappe.db.get_value("Account", {
        "company": company,
        "account_type": "Bank",
        "is_group": 0
    }, "name")
    
    payments = []
    
    # Create payment for sales invoice
    if sales_invoices:
        try:
            si = frappe.get_doc("Sales Invoice", sales_invoices[0])
            payment = frappe.new_doc("Payment Entry")
            payment.payment_type = "Receive"
            payment.party_type = "Customer"
            payment.party = si.customer
            payment.posting_date = today()
            payment.company = company
            payment.paid_to = bank_account
            payment.paid_from = si.debit_to
            payment.paid_amount = si.grand_total
            payment.received_amount = si.grand_total
            
            # Add reference
            payment.append("references", {
                "reference_doctype": "Sales Invoice",
                "reference_name": si.name,
                "allocated_amount": si.grand_total
            })
            
            payment.insert(ignore_permissions=True)
            payment.submit()
            frappe.db.commit()
            
            print(f"✓ Created and submitted payment entry: {payment.name} (Customer)")
            payments.append(payment.name)
        except Exception as e:
            print(f"✗ Failed to create customer payment: {str(e)}")
    
    # Create payment for purchase invoice
    if purchase_invoices:
        try:
            pi = frappe.get_doc("Purchase Invoice", purchase_invoices[0])
            payment = frappe.new_doc("Payment Entry")
            payment.payment_type = "Pay"
            payment.party_type = "Supplier"
            payment.party = pi.supplier
            payment.posting_date = today()
            payment.company = company
            payment.paid_from = bank_account
            payment.paid_to = pi.credit_to
            payment.paid_amount = pi.grand_total
            payment.received_amount = pi.grand_total
            
            # Add reference
            payment.append("references", {
                "reference_doctype": "Purchase Invoice",
                "reference_name": pi.name,
                "allocated_amount": pi.grand_total
            })
            
            payment.insert(ignore_permissions=True)
            payment.submit()
            frappe.db.commit()
            
            print(f"✓ Created and submitted payment entry: {payment.name} (Supplier)")
            payments.append(payment.name)
        except Exception as e:
            print(f"✗ Failed to create supplier payment: {str(e)}")
    
    return payments

def create_test_journal_entries():
    """Create 2 test journal entries for outbound sync"""
    print("\n" + "="*80)
    print("Creating Test Journal Entries")
    print("="*80)
    
    # Get default company
    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1)[0].name
    
    # Get two different accounts
    accounts = frappe.get_all("Account", 
        filters={
            "company": company,
            "is_group": 0,
            "account_type": ["in", ["Bank", "Cash"]]
        },
        fields=["name"],
        limit=2
    )
    
    if len(accounts) < 2:
        print("✗ Need at least 2 accounts to create journal entries")
        return []
    
    journal_entries = []
    for i in range(1, 3):
        try:
            je = frappe.new_doc("Journal Entry")
            je.posting_date = today()
            je.company = company
            je.user_remark = f"Test Journal Entry - Outbound Sync {i}"
            
            # Debit entry
            je.append("accounts", {
                "account": accounts[0].name,
                "debit_in_account_currency": 100.00 * i,
                "credit_in_account_currency": 0
            })
            
            # Credit entry
            je.append("accounts", {
                "account": accounts[1].name,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": 100.00 * i
            })
            
            je.insert(ignore_permissions=True)
            je.submit()
            frappe.db.commit()
            
            print(f"✓ Created and submitted journal entry: {je.name}")
            journal_entries.append(je.name)
        except Exception as e:
            print(f"✗ Failed to create journal entry {i}: {str(e)}")
    
    return journal_entries

def create_test_bank_transactions():
    """Create 2 test bank transactions for outbound sync"""
    print("\n" + "="*80)
    print("Creating Test Bank Transactions")
    print("="*80)
    
    # Get default company and bank account
    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1)[0].name
    bank_account = frappe.db.get_value("Account", {
        "company": company,
        "account_type": "Bank",
        "is_group": 0
    }, "name")
    
    if not bank_account:
        print("✗ No bank account found")
        return []
    
    transactions = []
    for i in range(1, 3):
        try:
            bt = frappe.new_doc("Bank Transaction")
            bt.date = today()
            bt.bank_account = bank_account
            bt.deposit = 100.00 * i if i == 1 else 0
            bt.withdrawal = 0 if i == 1 else 50.00 * i
            bt.description = f"Test Bank Transaction - Outbound Sync {i}"
            
            bt.insert(ignore_permissions=True)
            bt.submit()
            frappe.db.commit()
            
            print(f"✓ Created and submitted bank transaction: {bt.name}")
            transactions.append(bt.name)
        except Exception as e:
            print(f"✗ Failed to create bank transaction {i}: {str(e)}")
    
    return transactions

def run_all():
    """Create all test data"""
    print("\n" + "="*80)
    print("CREATING OUTBOUND SYNC TEST DATA")
    print("="*80)
    print("This will create 2 example entries for each entity type")
    print("="*80)
    
    # Create master data first
    customers = create_test_customers()
    suppliers = create_test_suppliers()
    items = create_test_items()
    
    # Create transactional documents
    quotations = create_test_quotations(customers, items)
    sales_invoices = create_test_sales_invoices(customers, items)
    purchase_invoices = create_test_purchase_invoices(suppliers, items)
    payment_entries = create_test_payment_entries(sales_invoices, purchase_invoices)
    journal_entries = create_test_journal_entries()
    bank_transactions = create_test_bank_transactions()
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Customers: {len(customers)}")
    print(f"Suppliers: {len(suppliers)}")
    print(f"Items: {len(items)}")
    print(f"Quotations: {len(quotations)}")
    print(f"Sales Invoices: {len(sales_invoices)}")
    print(f"Purchase Invoices: {len(purchase_invoices)}")
    print(f"Payment Entries: {len(payment_entries)}")
    print(f"Journal Entries: {len(journal_entries)}")
    print(f"Bank Transactions: {len(bank_transactions)}")
    print("="*80)
    print("\n✓ Test data creation complete!")
    print("\nNext steps:")
    print("1. Run: bench --site cohenix.localhost execute xero.utils.test_outbound_sync_2026.run_all_tests")
    print("2. Check Xero Sync Dashboard for sync status")
    print("3. Review Xero Logs for any errors")

if __name__ == "__main__":
    run_all()
