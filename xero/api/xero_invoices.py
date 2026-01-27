# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate, now_datetime
from frappe.model.mapper import get_mapped_doc
from ..utils.xero_client import xero_request, get_xero_settings, check_xero_entity_exists
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff
# from .xero_accounts import get_xero_tax_rates # No longer needed here directly

# --- Invoice Sync (ERPNext to Xero) ---

@frappe.whitelist()
def enqueue_sync_invoice_or_return(doc, method):
    """
    Wrapper function for on_submit event.
    Checks if the document is a return and enqueues the correct sync job.
    """
    if doc.get("is_return"):
        from .xero_credit_notes import enqueue_sync_return
        enqueue_sync_return(doc, method)
    else:
        enqueue_sync_invoice(doc, method)


def enqueue_sync_invoice(doc, method):
    """Enqueue background job to sync a standard invoice to Xero."""
    settings = get_xero_settings()
    if not settings.sync_invoices:
        return

    frappe.enqueue(
        "xero.api.xero_invoices.sync_invoice_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync")


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_invoice_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs a submitted ERPNext Sales Invoice or Purchase Invoice to Xero.
    Uses PUT for create/update.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        # frappe.logger().info("Xero Sync master switch is disabled.", "Xero Info")
        return # Master switch disabled
    
    # Check directional toggle for outbound sync
    if not settings.enable_sync_to_xero:
        log_xero_error(
            message=f"Sync to Xero is disabled. Skipping {doc_type} {doc_name} outbound sync.",
            status="Info",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            category="System Monitoring"
        )
        return
    
    if not settings.sync_invoices:
        return # Invoice sync specifically disabled

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_invoice_id = doc.get("xero_invoice_id")

        # --- Basic Validation ---
        if doc.docstatus != 1:
            log_xero_error(f"Cannot sync non-submitted document: {doc_type} {doc_name}", status="Info")
            return
        
        # --- Duplicate Prevention ---
        # Check if already synced and verify in Xero
        if xero_invoice_id:
            if check_xero_entity_exists("Invoices", xero_invoice_id):
                log_xero_error(
                    message=f"{doc_type} {doc_name} already synced to Xero (ID: {xero_invoice_id}). Skipping to prevent duplicate.",
                    status="Info",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=xero_invoice_id,
                    xero_entity_type="Invoice",
                    category="System Monitoring"
                )
                return
            else:
                # Xero ID exists in ERPNext but not found in Xero - might have been deleted
                log_xero_error(
                    message=f"{doc_type} {doc_name} has Xero ID {xero_invoice_id} but not found in Xero. Will re-sync.",
                    status="Warning",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=xero_invoice_id,
                    category="System Monitoring"
                )
                xero_invoice_id = None  # Reset to create new invoice

        # --- Determine Invoice Type and Contact ---
        if doc_type == "Sales Invoice":
            xero_invoice_type = "ACCREC" # Accounts Receivable
            contact_party_type = "Customer"
            contact_party_name = doc.customer
            party_account_field = "debit_to" # Account receivable
        elif doc_type == "Purchase Invoice":
            xero_invoice_type = "ACCPAY" # Accounts Payable
            contact_party_type = "Supplier"
            contact_party_name = doc.supplier
            party_account_field = "credit_to" # Account payable
        else:
            raise ValueError("Unsupported DocType for Xero Invoice sync.")

        # --- Get Linked Xero Contact ID ---
        xero_contact_id = frappe.db.get_value(contact_party_type, contact_party_name, "xero_contact_id")
        if not xero_contact_id:
            # Queue contact sync asynchronously instead of inline
            frappe.logger().info(f"Xero Contact ID not found for {contact_party_type} {contact_party_name}. Queuing contact sync.", "Xero Sync")
            
            # Queue contact sync
            from .xero_contacts import enqueue_sync_contact
            try:
                contact_doc = frappe.get_doc(contact_party_type, contact_party_name)
                enqueue_sync_contact(contact_doc, "manual_trigger")
            except Exception as e:
                frappe.log_error(f"Failed to queue contact sync: {str(e)}", "Xero Contact Queue Error")
            
            # Mark invoice as pending prerequisites
            frappe.db.set_value(doc_type, doc_name, {
                "xero_sync_status": "Pending Prerequisites"
            }, update_modified=False)
            frappe.db.commit()
            
            log_xero_error(
                message=f"{doc_type} {doc_name} sync deferred: {contact_party_type} {contact_party_name} must be synced to Xero first. Contact sync queued.",
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="System Monitoring"
            )
            
            # Re-queue this invoice for later (after contact sync completes)
            frappe.enqueue(
                "xero.api.xero_invoices.sync_invoice_to_xero",
                queue="short",
                timeout=600,
                retry=1,
                doc_name=doc_name,
                doc_type=doc_type,
                enqueue_after_commit=True,
                at_front=False,  # Don't jump the queue
                # Delay by 60 seconds to give contact sync time to complete
                job_id=f"invoice_retry_{doc_name}_{frappe.utils.now()}"
            )
            return


        # --- Map ERPNext Invoice Data to Xero Format ---
        # Ref: https://developer.xero.com/documentation/api/accounting/invoices
        invoice_payload = {
            "Type": xero_invoice_type,
            "Contact": {
                "ContactID": xero_contact_id
            },
            "Date": getdate(doc.posting_date).isoformat(),
            "DueDate": getdate(doc.due_date).isoformat(),
            "LineItems": [],
            "InvoiceNumber": doc.name, # Use ERPNext name as Invoice Number
            "Reference": doc.get("po_no") if doc_type == "Sales Invoice" else doc.get("bill_no"), # Optional reference
            "CurrencyCode": doc.currency,
            "Status": "AUTHORISED", # Or SUBMITTED? AUTHORISED seems more appropriate for synced invoices.
            # LineAmountTypes: Inclusive, Exclusive, NoTax (default Exclusive)
            # Determine based on ERPNext settings (e.g., taxes_and_charges_added_to_totals)
            "LineAmountTypes": "Exclusive" if doc.taxes_and_charges_added_to_totals == 0 else "Inclusive",
        }

        # If updating, include the Xero Invoice ID
        if xero_invoice_id:
            invoice_payload["InvoiceID"] = xero_invoice_id

        # --- Map Line Items ---
        for item in doc.items:
            # Get Xero Account Code from mapping in settings
            erpnext_account = item.income_account if doc_type == "Sales Invoice" else item.expense_account
            xero_account_code = get_xero_account_code(erpnext_account, settings) # Pass settings
            if not xero_account_code:
                 raise Exception(f"Xero Account Code mapping not found in Xero Settings for ERPNext Account: {erpnext_account} (Item: {item.item_code or item.description})")

            line_item = {
                "Description": item.description,
                "Quantity": item.qty,
                "UnitAmount": item.rate,
                "AccountCode": xero_account_code,
                "LineAmount": item.amount,
                # Map Tax Type using mapping in settings
                "TaxType": map_erpnext_tax_to_xero(item.item_tax_template, settings), # Pass settings
            }
            invoice_payload["LineItems"].append(line_item)

        # --- Map Taxes and Charges ---
        # Add each tax/charge as a separate line item, as per Xero's recommendation for non-standard taxes/charges.
        for tax in doc.taxes:
            tax_account_code = get_xero_account_code(tax.account_head, settings)
            if not tax_account_code:
                raise Exception(f"Xero Account Code mapping not found for Tax/Charge Account: {tax.account_head}")

            tax_line_item = {
                "Description": tax.description,
                "Quantity": 1,
                "UnitAmount": tax.tax_amount_after_discount_amount,
                "AccountCode": tax_account_code,
                # We set the tax type to NONE for the charge itself, as the tax is part of the line total.
                # The tax on the main items should handle the actual tax calculation.
                "TaxType": "NONE"
            }
            invoice_payload["LineItems"].append(tax_line_item)

        # --- Make API Call (PUT for create/update) ---
        response = xero_request("PUT", "Invoices", data={"Invoices": [invoice_payload]})

        if response and response.get("Invoices"):
            updated_invoice = response["Invoices"][0]
            new_xero_invoice_id = updated_invoice.get("InvoiceID")

            # --- Update ERPNext Document ---
            if new_xero_invoice_id:
                frappe.db.set_value(doc_type, doc_name, {
                    "xero_invoice_id": new_xero_invoice_id,
                    "xero_sync_status": "Synced"
                }, update_modified=False)
                frappe.db.commit()

                log_xero_error(
                    message=f"Successfully synced {doc_type} {doc_name} to Xero.",
                    status="Success",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=new_xero_invoice_id,
                    xero_entity_type="Invoice",
                    direction="ERPNext to Xero"
                )
            else:
                raise Exception("Xero API response did not contain an InvoiceID.")
        else:
            raise Exception("Invalid response received from Xero Invoices API.")

    except Exception as e:
        # Ensure status is updated even if doc object wasn't fetched initially
        if doc_name and doc_type:
            frappe.db.set_value(doc_type, doc_name, {"xero_sync_status": "Error"}, update_modified=False)
            frappe.db.commit()

        log_xero_error(
            message=f"Failed to sync {doc_type} {doc_name} to Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )
        # Optionally re-raise
        # raise e

def enqueue_void_invoice(doc, method):
    """Enqueue background job to void a cancelled invoice in Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.sync_invoices:
        return

    frappe.enqueue(
        "xero.api.xero_invoices.void_invoice_in_xero",
        queue="short",
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued void for {doc.doctype} {doc.name} to Xero.", "Xero Sync")


def void_invoice_in_xero(doc_name, doc_type):
    """
    Finds the corresponding Xero invoice and voids it.
    This is done by updating the status to 'VOIDED'.
    """
    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_invoice_id = doc.get("xero_invoice_id")

        if not xero_invoice_id:
            log_xero_error(f"Cannot void invoice {doc_name}: Xero Invoice ID not found.", status="Info")
            return

        # Xero API voids invoices by updating their status
        invoice_payload = {
            "InvoiceID": xero_invoice_id,
            "Status": "VOIDED"
        }

        # Note: Xero API for voiding is a POST to the Invoices endpoint
        response = xero_request("POST", "Invoices", data={"Invoices": [invoice_payload]})

        if response and response.get("Invoices"):
            frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Voided in Xero", update_modified=False)
            frappe.db.commit()
            log_xero_error(
                message=f"Successfully voided {doc_type} {doc_name} in Xero.",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=xero_invoice_id,
                xero_entity_type="Invoice",
                direction="ERPNext to Xero"
            )
        else:
            raise Exception("Invalid response received from Xero when voiding invoice.")

    except Exception as e:
        log_xero_error(
            message=f"Failed to void {doc_type} {doc_name} in Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )

# --- Invoice Sync (Xero to ERPNext - Payments) ---

def check_invoice_payments():
    """
    Scheduled task to check for payments on synced invoices in Xero
    and update ERPNext status / create Payment Entries.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        # frappe.logger().info("Xero Sync master switch is disabled.", "Xero Info")
        return # Master switch disabled
    if not settings.sync_payments:
        return # Payment sync specifically disabled

    frappe.logger().info("Starting Xero Payment Check", "Xero Sync")
    processed_count = 0

    # Get ERPNext invoices (SI & PI) linked to Xero and not fully paid
    linked_invoices = []
    for doctype in ["Sales Invoice", "Purchase Invoice"]:
         filters = {
             "docstatus": 1,
             "status": ["not in", ["Paid", "Cancelled"]],
             "xero_invoice_id": ["is", "set"]
         }
         invoices = frappe.get_all(doctype, filters=filters, fields=["name", "xero_invoice_id", "grand_total", "outstanding_amount"])
         for inv in invoices:
             inv.doctype = doctype # Add doctype info for processing
             linked_invoices.append(inv)

    if not linked_invoices:
        frappe.logger().info("No unpaid linked invoices found to check for payments.", "Xero Sync")
        return

    for inv in linked_invoices:
        try:
            # Fetch invoice details from Xero using the ID
            xero_inv_data = xero_request("GET", f"Invoices/{inv.xero_invoice_id}")

            if not xero_inv_data or not xero_inv_data.get("Invoices"):
                log_xero_error(f"Could not fetch details for Xero Invoice ID {inv.xero_invoice_id}", status="Warning", erpnext_doc_type=inv.doctype, erpnext_doc_name=inv.name)
                continue

            xero_invoice = xero_inv_data["Invoices"][0]
            xero_status = xero_invoice.get("Status")
            amount_paid = flt(xero_invoice.get("AmountPaid", 0.0))
            amount_due = flt(xero_invoice.get("AmountDue", 0.0))

            # Compare Xero payment status with ERPNext
            if amount_due <= 0 and inv.outstanding_amount > 0:
                # Invoice is paid in Xero but not (fully) in ERPNext
                log_xero_error(
                    message=f"Invoice {inv.doctype} {inv.name} paid in Xero (ID: {inv.xero_invoice_id}). Updating ERPNext.",
                    status="Info",
                    erpnext_doc_type=inv.doctype,
                    erpnext_doc_name=inv.name,
                    xero_entity_id=inv.xero_invoice_id,
                    xero_entity_type="Invoice",
                    direction="Xero to ERPNext"
                )

                # Update ERPNext invoice status
                # This might trigger standard PE creation depending on settings, or we can create one manually
                erpnext_inv_doc = frappe.get_doc(inv.doctype, inv.name)
                # Simple update - more robust logic might be needed
                if erpnext_inv_doc.outstanding_amount > 0:
                    # Create Payment Entry if enabled
                    if settings.create_payment_entry_on_sync:
                        create_payment_entry_for_xero_payment(erpnext_inv_doc, xero_invoice, settings)
                    else:
                        # Just update status if PE creation is disabled
                        erpnext_inv_doc.db_set("status", "Paid")
                        frappe.db.commit() # Commit status change

                    processed_count += 1

            # Handle other status discrepancies if needed (e.g., VOIDED in Xero?)
            elif xero_status == "VOIDED" and erpnext_inv_doc.docstatus == 1:
                log_xero_error(
                    message=f"Invoice {inv.doctype} {inv.name} VOIDED in Xero (ID: {inv.xero_invoice_id}). Consider cancelling in ERPNext.",
                    status="Warning", # Log as warning, manual action might be needed
                    erpnext_doc_type=inv.doctype,
                    erpnext_doc_name=inv.name,
                    xero_entity_id=inv.xero_invoice_id,
                    xero_entity_type="Invoice",
                    direction="Xero to ERPNext"
                 )
                 # Optionally attempt to cancel if possible? Be careful with automation here.
                 # try:
                 #     erpnext_inv_doc.cancel()
                 # except Exception as cancel_e:
                 #     log_xero_error(f"Failed to auto-cancel {inv.doctype} {inv.name} after Xero void: {cancel_e}", status="Error")

        except Exception as e:
            log_xero_error(
                message=f"Error checking payment for {inv.doctype} {inv.name} (Xero ID: {inv.xero_invoice_id})",
                erpnext_doc_type=inv.doctype,
                erpnext_doc_name=inv.name,
                xero_entity_id=inv.xero_invoice_id,
                xero_entity_type="Invoice",
                direction="Xero to ERPNext",
                error_details=frappe.get_traceback()
            )

    log_xero_error(message=f"Finished Xero Payment Check. Updated {processed_count} invoices.", status="Info")


# --- Helper Functions ---

# Cache for mappings to avoid fetching settings repeatedly within a request/job
@frappe.whitelist(allow_guest=True) # Allow use in JS? Maybe not needed.
def get_cached_mapping(map_type):
    """Gets account or tax mapping from cache or settings."""
    cache_key = f"xero_{map_type}_map"
    mapping = frappe.cache().get_value(cache_key)
    if mapping is None:
        settings = get_xero_settings()
        if map_type == "account":
            mapping = settings.get_account_map()
        elif map_type == "tax":
            mapping = settings.get_tax_map()
        else:
            mapping = {}
        frappe.cache().set_value(cache_key, mapping) # Cache for short duration? e.g., 5 mins
    return mapping

def get_xero_account_code(erpnext_account, settings=None):
    """Maps an ERPNext account name to a Xero Account Code using the mapping table."""
    if not settings:
        settings = get_xero_settings() # Fetch if not passed
    account_map = settings.get_account_map() # Use method on settings doc
    return account_map.get(erpnext_account)


def map_erpnext_tax_to_xero(erpnext_tax_template, settings=None):
    """Maps ERPNext tax templates to Xero TaxTypes using the mapping table."""
    if not erpnext_tax_template:
        return "NONE" # Default if no tax template applied

    if not settings:
        settings = get_xero_settings() # Fetch if not passed
    tax_map = settings.get_tax_map() # Use method on settings doc
    xero_tax_code = tax_map.get(erpnext_tax_template)

    if not xero_tax_code:
        log_xero_error(f"Xero TaxType mapping not found for ERPNext Tax Template: {erpnext_tax_template}. Defaulting to NONE.", status="Warning")
        return "NONE" # Default if no mapping found

    return xero_tax_code


def create_payment_entry_for_xero_payment(invoice_doc, xero_invoice_data, settings):
    """Creates and submits a Payment Entry in ERPNext based on Xero payment."""
    if not settings.create_payment_entry_on_sync or not settings.default_bank_account:
        log_xero_error(f"Skipping PE creation for {invoice_doc.doctype} {invoice_doc.name}: Setting disabled or default bank account missing.", status="Info")
        # Still update status if PE creation skipped
        if invoice_doc.status != "Paid":
            invoice_doc.db_set("status", "Paid")
            frappe.db.commit()
        return

    try:
        # Basic details
        paid_amount = flt(xero_invoice_data.get("AmountPaid", 0.0))
        if paid_amount <= 0:
             log_xero_error(f"Skipping PE creation for {invoice_doc.doctype} {invoice_doc.name}: Xero AmountPaid is zero or missing.", status="Info")
             return

        # Check if a PE already exists for this payment (simple check based on amount and invoice)
        # More robust check might involve storing Xero Payment ID if available
        existing_pe = frappe.db.exists("Payment Entry Reference", {
            "reference_doctype": invoice_doc.doctype,
            "reference_name": invoice_doc.name,
            # Check amount? This might be tricky with partial payments
        })
        if existing_pe:
            log_xero_error(f"Skipping PE creation for {invoice_doc.doctype} {invoice_doc.name}: Payment Entry reference already exists.", status="Info")
            # Ensure invoice status is Paid if PE exists but status wasn't updated
            if invoice_doc.status != "Paid":
                 invoice_doc.db_set("status", "Paid")
                 frappe.db.commit()
            return

        # Determine party type and account
        if invoice_doc.doctype == "Sales Invoice":
            party_type = "Customer"
            party = invoice_doc.customer
            party_account = invoice_doc.debit_to
            mode_of_payment = frappe.db.get_value("Mode of Payment", {"type": "General"}, "name") # Find a generic MOP
        else: # Purchase Invoice
            party_type = "Supplier"
            party = invoice_doc.supplier
            party_account = invoice_doc.credit_to
            mode_of_payment = frappe.db.get_value("Mode of Payment", {"type": "Pay"}, "name") # Find a generic MOP

        # Use default bank account from settings
        paid_from_or_to_account = settings.default_bank_account

        # Create Payment Entry doc
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive" if invoice_doc.doctype == "Sales Invoice" else "Pay"
        pe.party_type = party_type
        pe.party = party
        pe.party_account = party_account
        # Assign to correct field based on payment type
        if pe.payment_type == "Pay":
            pe.paid_from = paid_from_or_to_account
        else: # Receive
            pe.paid_to = paid_from_or_to_account
        pe.paid_amount = paid_amount
        pe.received_amount = paid_amount # Assuming payment currency matches invoice currency
        pe.base_paid_amount = paid_amount * invoice_doc.conversion_rate # Adjust for multi-currency
        pe.base_received_amount = paid_amount * invoice_doc.conversion_rate
        pe.target_exchange_rate = invoice_doc.conversion_rate
        pe.posting_date = nowdate() # Use today's date for payment? Or try to get from Xero?
        pe.mode_of_payment = mode_of_payment
        pe.reference_no = f"XERO-{xero_invoice_data.get('InvoiceID', invoice_doc.name)}" # Reference
        pe.reference_date = nowdate()

        pe.append("references", {
            "reference_doctype": invoice_doc.doctype,
            "reference_name": invoice_doc.name,
            "bill_no": invoice_doc.bill_no if invoice_doc.doctype == "Purchase Invoice" else None,
            "due_date": invoice_doc.due_date,
            "total_amount": invoice_doc.grand_total,
            "outstanding_amount": invoice_doc.outstanding_amount,
            "allocated_amount": paid_amount # Allocate the full paid amount
        })

        pe.flags.ignore_permissions = True
        pe.flags.ignore_mandatory = True # May need this depending on PE config
        pe.insert()
        pe.submit()

        log_xero_error(
            f"Created Payment Entry {pe.name} for paid {invoice_doc.doctype} {invoice_doc.name} from Xero.",
            status="Success",
            erpnext_doc_type=invoice_doc.doctype,
            erpnext_doc_name=invoice_doc.name,
            xero_entity_id=xero_invoice_data.get("InvoiceID"),
            xero_entity_type="Invoice/Payment"
        )

    except Exception as e:
        # Log error but don't stop main sync process
        log_xero_error(
            f"Failed to create Payment Entry for {invoice_doc.doctype} {invoice_doc.name}",
            status="Error",
            erpnext_doc_type=invoice_doc.doctype,
            erpnext_doc_name=invoice_doc.name,
            xero_entity_id=xero_invoice_data.get("InvoiceID"),
            error_details=frappe.get_traceback()
        )
        # Ensure invoice status is still updated even if PE fails? Or mark as error?
        # For safety, let's not mark as Paid if PE creation failed. User needs to resolve.
        # invoice_doc.db_set("status", "Paid") # Maybe don't do this on PE failure


# TODO: Implement Journal Entry sync
# TODO: Implement Credit Note sync
