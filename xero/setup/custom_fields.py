import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def setup_custom_fields():
    """Setup (install/upgrade) custom fields for the Xero integration.

    CR-1: This runs on BOTH after_install and after_migrate. It must be
    idempotent and MUST NOT delete existing fields — `frappe.delete_doc` on a
    Custom Field drops the underlying column, which on `bench migrate` would
    wipe the sync-tracking values (xero_invoice_id, xero_payment_id,
    xero_contact_id, xero_data_hash, ...). Losing those makes the integration
    forget what it already synced and re-create duplicate records in Xero.

    `create_custom_fields(..., update=True)` is an idempotent upsert: it creates
    missing fields and updates the definition of existing ones in place, without
    dropping columns or data. Field removal, if ever needed, is an explicit,
    manually invoked operation (see `remove_custom_fields`), never part of migrate.
    """

    # Define all custom fields
    custom_fields = {
        "Sales Invoice": [
            {
                "fieldname": "xero_invoice_id",
                "fieldtype": "Data",
                "label": "Xero Invoice ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "scan_barcode"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_invoice_id"
            },
            {
                "fieldname": "xero_data_hash",
                "fieldtype": "Data",
                "label": "Xero Data Hash",
                "length": 32,
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "hidden": 1,
                "insert_after": "xero_sync_status"
            },
            {
                "fieldname": "xero_credit_note_id",
                "fieldtype": "Data",
                "label": "Xero Credit Note ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "xero_data_hash"
            }
        ],
        "Purchase Invoice": [
            {
                "fieldname": "xero_invoice_id",
                "fieldtype": "Data",
                "label": "Xero Invoice ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "scan_barcode"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_invoice_id"
            },
            {
                "fieldname": "xero_data_hash",
                "fieldtype": "Data",
                "label": "Xero Data Hash",
                "length": 32,
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "hidden": 1,
                "insert_after": "xero_sync_status"
            },
            {
                "fieldname": "xero_credit_note_id",
                "fieldtype": "Data",
                "label": "Xero Credit Note ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "xero_data_hash"
            }
        ],
        "Payment Entry": [
            {
                "fieldname": "xero_payment_id",
                "fieldtype": "Data",
                "label": "Xero Payment ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "title"
            },
            {
                "fieldname": "xero_bank_transaction_id",
                "fieldtype": "Data",
                "label": "Xero Bank Transaction ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "xero_payment_id"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 0,
                "print_hide": 1,
                "in_list_view": 1,
                "in_standard_filter": 1,
                "insert_after": "xero_bank_transaction_id"
            },
            {
                "fieldname": "xero_last_sync",
                "fieldtype": "Datetime",
                "label": "Xero Last Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_sync_status"
            },
            {
                "fieldname": "xero_payment_data",
                "fieldtype": "Long Text",
                "label": "Xero Payment Data",
                "description": "JSON data for multiple Xero payment IDs and reconciliation info",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "hidden": 1,
                "insert_after": "xero_last_sync"
            }
        ],
        "Journal Entry": [
            {
                "fieldname": "xero_manual_journal_id",
                "fieldtype": "Data",
                "label": "Xero Manual Journal ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "voucher_type"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped\nCancelled",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 0,
                "print_hide": 1,
                "in_list_view": 1,
                "in_standard_filter": 1,
                "insert_after": "xero_manual_journal_id"
            },
            {
                "fieldname": "xero_last_sync",
                "fieldtype": "Datetime",
                "label": "Xero Last Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_sync_status"
            }
        ],
        "Customer": [
            {
                "fieldname": "xero_contact_id",
                "fieldtype": "Data",
                "label": "Xero Contact ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "customer_name"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 0,
                "print_hide": 1,
                "in_list_view": 1,
                "in_standard_filter": 1,
                "insert_after": "xero_contact_id"
            },
            {
                "fieldname": "xero_data_hash",
                "fieldtype": "Data",
                "label": "Xero Data Hash",
                "length": 32,
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "hidden": 1,
                "insert_after": "xero_sync_status"
            },
            {
                "fieldname": "xero_last_contact_sync",
                "fieldtype": "Datetime",
                "label": "Xero Last Contact Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_data_hash"
            },
            {
                "fieldname": "xero_notes_last_sync",
                "fieldtype": "Datetime",
                "label": "Xero Notes Last Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_last_contact_sync"
            }
        ],
        "Supplier": [
            {
                "fieldname": "xero_contact_id",
                "fieldtype": "Data",
                "label": "Xero Contact ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "supplier_name"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 0,
                "print_hide": 1,
                "in_list_view": 1,
                "in_standard_filter": 1,
                "insert_after": "xero_contact_id"
            },
            {
                "fieldname": "xero_data_hash",
                "fieldtype": "Data",
                "label": "Xero Data Hash",
                "length": 32,
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "hidden": 1,
                "insert_after": "xero_sync_status"
            },
            {
                "fieldname": "xero_last_contact_sync",
                "fieldtype": "Datetime",
                "label": "Xero Last Contact Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_data_hash"
            },
            {
                "fieldname": "xero_notes_last_sync",
                "fieldtype": "Datetime",
                "label": "Xero Notes Last Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_last_contact_sync"
            }
        ],
        "Item": [
            {
                "fieldname": "xero_item_id",
                "fieldtype": "Data",
                "label": "Xero Item ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "item_name"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 0,
                "print_hide": 1,
                "in_list_view": 1,
                "in_standard_filter": 1,
                "insert_after": "xero_item_id"
            },
            {
                "fieldname": "xero_data_hash",
                "fieldtype": "Data",
                "label": "Xero Data Hash",
                "length": 32,
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "hidden": 1,
                "insert_after": "xero_sync_status"
            },
            {
                "fieldname": "xero_last_item_sync",
                "fieldtype": "Datetime",
                "label": "Xero Last Item Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_data_hash"
            }
        ],
        "Account": [
            {
                "fieldname": "xero_account_id",
                "fieldtype": "Data",
                "label": "Xero Account ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "account_name"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 0,
                "print_hide": 1,
                "in_list_view": 1,
                "in_standard_filter": 1,
                "insert_after": "xero_account_id"
            },
            {
                "fieldname": "xero_data_hash",
                "fieldtype": "Data",
                "label": "Xero Data Hash",
                "length": 32,
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "hidden": 1,
                "insert_after": "xero_sync_status"
            },
            {
                "fieldname": "xero_last_account_sync",
                "fieldtype": "Datetime",
                "label": "Xero Last Account Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_data_hash"
            },
            {
                # ME-3: original Xero account Type (e.g. PREPAYMENT, CURRENT),
                # captured on inbound sync so outbound sync can re-use it verbatim
                # instead of re-deriving it through the lossy ERPNext->Xero map.
                "fieldname": "xero_account_type",
                "fieldtype": "Data",
                "label": "Xero Account Type",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "insert_after": "xero_last_account_sync"
            }
        ],
        "Quotation": [
            {
                "fieldname": "xero_quote_id",
                "fieldtype": "Data",
                "label": "Xero Quote ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "quotation_to"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 0,
                "print_hide": 1,
                "in_list_view": 1,
                "in_standard_filter": 1,
                "insert_after": "xero_quote_id"
            },
            {
                "fieldname": "xero_last_quote_sync",
                "fieldtype": "Datetime",
                "label": "Xero Last Quote Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_sync_status"
            }
        ],
        "Bank Transaction": [
            {
                "fieldname": "xero_bank_transaction_id",
                "fieldtype": "Data",
                "label": "Xero Bank Transaction ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "name"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 0,
                "print_hide": 1,
                "in_list_view": 1,
                "in_standard_filter": 1,
                "insert_after": "xero_bank_transaction_id"
            },
            {
                "fieldname": "xero_last_bank_sync",
                "fieldtype": "Datetime",
                "label": "Xero Last Bank Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_sync_status"
            }
        ],
        "Purchase Order": [
            {
                "fieldname": "xero_purchase_order_id",
                "fieldtype": "Data",
                "label": "Xero Purchase Order ID",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "report_hide": 1,
                "search_index": 1,
                "insert_after": "title"
            },
            {
                "fieldname": "xero_sync_status",
                "fieldtype": "Select",
                "label": "Xero Sync Status",
                "options": "\nPending\nSynced\nError\nSkipped",
                "default": "Pending",
                "no_copy": 1,
                "read_only": 0,
                "print_hide": 1,
                "in_list_view": 1,
                "in_standard_filter": 1,
                "insert_after": "xero_purchase_order_id"
            },
            {
                "fieldname": "xero_last_purchase_order_sync",
                "fieldtype": "Datetime",
                "label": "Xero Last Purchase Order Sync",
                "no_copy": 1,
                "read_only": 1,
                "print_hide": 1,
                "insert_after": "xero_sync_status"
            }
        ]
    }
    
    # Create the custom fields
    # update=True: idempotent upsert; never drops columns/data (CR-1).
    create_custom_fields(custom_fields, update=True)
    print("Xero custom fields created successfully!")

def remove_custom_fields():
    """Remove all Xero custom fields"""
    
    fields_to_delete = [
        # Sales Invoice fields
        "xero_invoice_id",
        "xero_sync_status",
        "xero_credit_note_id",
        # Payment Entry fields
        "xero_payment_id",
        "xero_bank_transaction_id",
        "xero_last_sync",
        "xero_payment_data",
        # Journal Entry fields
        "xero_manual_journal_id",
        # Customer fields
        "xero_contact_id",
        "xero_contact_sync_status",
        "xero_last_contact_sync",
        # Item fields
        "xero_item_id",
        "xero_item_sync_status",
        "xero_last_item_sync",
        # Account fields
        "xero_account_id",
        "xero_account_sync_status",
        "xero_last_account_sync",
        # Quotation fields
        "xero_quote_id",
        "xero_quote_sync_status",
        "xero_last_quote_sync",
        # Bank Transaction fields
        "xero_bank_transaction_sync_status",
        "xero_last_bank_sync",
        # Purchase Order fields
        "xero_purchase_order_id",
        "xero_purchase_order_sync_status",
        "xero_last_purchase_order_sync"
    ]

    doctypes_to_clean = [
        "Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry",
        "Customer", "Supplier", "Item", "Account", "Quotation", 
        "Bank Transaction", "Purchase Order"
    ]
    
    for doctype in doctypes_to_clean:
        for fieldname in fields_to_delete:
            custom_field_name = f"{doctype}-{fieldname}"
            if frappe.db.exists("Custom Field", custom_field_name):
                try:
                    frappe.delete_doc("Custom Field", custom_field_name, ignore_permissions=True, force=True)
                    frappe.db.commit()
                    print(f"Deleted custom field: {custom_field_name}")
                except Exception as e:
                    print(f"Error deleting custom field {custom_field_name}: {e}")
    
    print("Xero custom fields removed successfully!")