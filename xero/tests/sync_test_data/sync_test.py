#!/usr/bin/env python3
"""
Comprehensive Xero Sync Test Script
Executes one-way sync from ERPNext to Xero following dependency order
"""

import frappe
from frappe import _

def run_comprehensive_sync():
    """Run comprehensive one-way sync test"""
    print('=== PHASE 1: MASTER DATA SYNC ===')
    print('Starting comprehensive Xero sync test...')

    # Phase 1.1: Contacts (Customers & Suppliers)
    print('\n1.1 SYNCING CONTACTS...')
    from xero.api.xero_contacts import sync_contact_to_xero

    customers = frappe.get_all('Customer', fields=['name'])
    suppliers = frappe.get_all('Supplier', fields=['name'])

    print(f'Found {len(customers)} customers and {len(suppliers)} suppliers')

    for c in customers:
        try:
            sync_contact_to_xero(c.name, 'Customer')
            print(f'✓ Synced Customer: {c.name}')
        except Exception as e:
            print(f'✗ Failed Customer {c.name}: {str(e)}')

    for s in suppliers:
        try:
            sync_contact_to_xero(s.name, 'Supplier')
            print(f'✓ Synced Supplier: {s.name}')
        except Exception as e:
            print(f'✗ Failed Supplier {s.name}: {str(e)}')

    print('Phase 1.1 Contacts completed!')

    # Phase 1.2: Items
    print('\n1.2 SYNCING ITEMS...')
    from xero.api.xero_items import sync_item_to_xero

    items = frappe.get_all('Item', fields=['item_code'])
    print(f'Found {len(items)} items')

    for item in items:
        try:
            sync_item_to_xero(item.item_code)
            print(f'✓ Synced Item: {item.item_code}')
        except Exception as e:
            print(f'✗ Failed Item {item.item_code}: {str(e)}')

    print('Phase 1.2 Items completed!')

    # Phase 2.1: Quotations
    print('\n2.1 SYNCING QUOTATIONS...')
    from xero.api.xero_quotes import sync_quotation_to_xero

    quotations = frappe.get_all('Quotation',
        filters={'company': 'EPIUSE', 'docstatus': ['in', [0, 1]]},
        fields=['name'])
    print(f'Found {len(quotations)} quotations')

    for quot in quotations:
        try:
            sync_quotation_to_xero(quot.name)
            print(f'✓ Synced Quotation: {quot.name}')
        except Exception as e:
            print(f'✗ Failed Quotation {quot.name}: {str(e)}')

    print('Phase 2.1 Quotations completed!')

    # Phase 2.2: Sales Orders
    print('\n2.2 SYNCING SALES ORDERS...')
    from xero.api.xero_sales_orders import sync_sales_order_to_xero

    sales_orders = frappe.get_all('Sales Order',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name'])
    print(f'Found {len(sales_orders)} sales orders')

    for so in sales_orders:
        try:
            sync_sales_order_to_xero(so.name)
            print(f'✓ Synced Sales Order: {so.name}')
        except Exception as e:
            print(f'✗ Failed Sales Order {so.name}: {str(e)}')

    print('Phase 2.2 Sales Orders completed!')

    # Phase 2.3: Delivery Notes
    print('\n2.3 SYNCING DELIVERY NOTES...')
    from xero.api.xero_delivery_notes import sync_delivery_note_to_xero

    delivery_notes = frappe.get_all('Delivery Note',
        filters={'company': 'EPIUSE', 'docstatus': ['in', [0, 1]]},
        fields=['name'])
    print(f'Found {len(delivery_notes)} delivery notes')

    for dn in delivery_notes:
        try:
            sync_delivery_note_to_xero(dn.name)
            print(f'✓ Synced Delivery Note: {dn.name}')
        except Exception as e:
            print(f'✗ Failed Delivery Note {dn.name}: {str(e)}')

    print('Phase 2.3 Delivery Notes completed!')

    # Phase 2.4: Sales Invoices
    print('\n2.4 SYNCING SALES INVOICES...')
    from xero.api.xero_invoices import sync_invoice_to_xero

    sales_invoices = frappe.get_all('Sales Invoice',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name', 'is_return'])
    print(f'Found {len(sales_invoices)} sales invoices')

    for si in sales_invoices:
        try:
            sync_invoice_to_xero(si.name, 'Sales Invoice')
            doc_type = 'Credit Note' if si.is_return else 'Invoice'
            print(f'✓ Synced {doc_type}: {si.name}')
        except Exception as e:
            print(f'✗ Failed Sales Invoice {si.name}: {str(e)}')

    print('Phase 2.4 Sales Invoices completed!')

    # Phase 2.5: Customer Payments
    print('\n2.5 SYNCING CUSTOMER PAYMENTS...')
    from xero.api.xero_payments import sync_payment_to_xero

    payments = frappe.get_all('Payment Entry',
        filters={'company': 'EPIUSE', 'party_type': 'Customer', 'docstatus': ['in', [0, 1]]},
        fields=['name'])
    print(f'Found {len(payments)} customer payments')

    for pe in payments:
        try:
            sync_payment_to_xero(pe.name)
            print(f'✓ Synced Payment: {pe.name}')
        except Exception as e:
            print(f'✗ Failed Payment {pe.name}: {str(e)}')

    print('Phase 2.5 Customer Payments completed!')

    # Phase 3.1: Purchase Orders
    print('\n3.1 SYNCING PURCHASE ORDERS...')
    from xero.api.xero_purchase_orders import sync_purchase_order_to_xero

    purchase_orders = frappe.get_all('Purchase Order',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name'])
    print(f'Found {len(purchase_orders)} purchase orders')

    for po in purchase_orders:
        try:
            sync_purchase_order_to_xero(po.name)
            print(f'✓ Synced Purchase Order: {po.name}')
        except Exception as e:
            print(f'✗ Failed Purchase Order {po.name}: {str(e)}')

    print('Phase 3.1 Purchase Orders completed!')

    # Phase 3.2: Purchase Receipts
    print('\n3.2 SYNCING PURCHASE RECEIPTS...')
    from xero.api.xero_purchase_receipts import sync_purchase_receipt_to_xero

    purchase_receipts = frappe.get_all('Purchase Receipt',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name'])
    print(f'Found {len(purchase_receipts)} purchase receipts')

    for pr in purchase_receipts:
        try:
            sync_purchase_receipt_to_xero(pr.name)
            print(f'✓ Synced Purchase Receipt: {pr.name}')
        except Exception as e:
            print(f'✗ Failed Purchase Receipt {pr.name}: {str(e)}')

    print('Phase 3.2 Purchase Receipts completed!')

    # Phase 3.3: Purchase Invoices
    print('\n3.3 SYNCING PURCHASE INVOICES...')
    purchase_invoices = frappe.get_all('Purchase Invoice',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name', 'is_return'])
    print(f'Found {len(purchase_invoices)} purchase invoices')

    for pi in purchase_invoices:
        try:
            sync_invoice_to_xero(pi.name, 'Purchase Invoice')
            doc_type = 'Debit Note' if pi.is_return else 'Bill'
            print(f'✓ Synced {doc_type}: {pi.name}')
        except Exception as e:
            print(f'✗ Failed Purchase Invoice {pi.name}: {str(e)}')

    print('Phase 3.3 Purchase Invoices completed!')

    # Phase 3.4: Supplier Payments
    print('\n3.4 SYNCING SUPPLIER PAYMENTS...')
    supplier_payments = frappe.get_all('Payment Entry',
        filters={'company': 'EPIUSE', 'party_type': 'Supplier', 'docstatus': ['in', [0, 1]]},
        fields=['name'])
    print(f'Found {len(supplier_payments)} supplier payments')

    for pe in supplier_payments:
        try:
            sync_payment_to_xero(pe.name)
            print(f'✓ Synced Payment: {pe.name}')
        except Exception as e:
            print(f'✗ Failed Payment {pe.name}: {str(e)}')

    print('Phase 3.4 Supplier Payments completed!')

    # Phase 4.1: Journal Entries
    print('\n4.1 SYNCING JOURNAL ENTRIES...')
    from xero.api.xero_journals import sync_journal_to_xero

    journals = frappe.get_all('Journal Entry',
        filters={'company': 'EPIUSE', 'docstatus': 1},
        fields=['name'])
    print(f'Found {len(journals)} journal entries')

    for je in journals:
        try:
            sync_journal_to_xero(je.name)
            print(f'✓ Synced Journal Entry: {je.name}')
        except Exception as e:
            print(f'✗ Failed Journal Entry {je.name}: {str(e)}')

    print('Phase 4.1 Journal Entries completed!')

    # Phase 4.2: Bank Transactions
    print('\n4.2 SYNCING BANK TRANSACTIONS...')
    from xero.api.xero_bank_transactions import sync_bank_transaction_to_xero

    bank_txns = frappe.get_all('Bank Transaction',
        filters={'company': 'EPIUSE', 'docstatus': ['in', [0, 1]]},
        fields=['name'])
    print(f'Found {len(bank_txns)} bank transactions')

    for bt in bank_txns:
        try:
            sync_bank_transaction_to_xero(bt.name)
            print(f'✓ Synced Bank Transaction: {bt.name}')
        except Exception as e:
            print(f'✗ Failed Bank Transaction {bt.name}: {str(e)}')

    print('Phase 4.2 Bank Transactions completed!')

    print('\n=== COMPREHENSIVE SYNC TEST COMPLETED ===')
    print('All phases executed. Check documentation for detailed results.')

if __name__ == "__main__":
    run_comprehensive_sync()