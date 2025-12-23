# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
import json
import hashlib
import hmac
import base64
from .logging import log_xero_error
from .logging import log_xero_error
from .xero_client import get_xero_settings, xero_request
# Import necessary API functions
from ..api.xero_invoices import create_payment_entry_for_xero_payment
from ..api.xero_contacts import sync_xero_contact_to_erpnext # For contact updates
from frappe.utils import flt

@frappe.whitelist(allow_guest=True)
def handle_webhook():
    """
    Handles incoming webhooks from Xero.
    Verifies the signature and routes the event to the appropriate processor.
    """
    import time
    start_time = time.time()
    
    # 1. Verify Signature (Essential for security)
    webhook_key = get_webhook_key()
    if not webhook_key:
        log_xero_error(
            "Webhook received but signing key is not set in Xero Settings. Ignoring.",
            status="Warning",
            category="Authentication Issues"
        )
        frappe.response.status_code = 401 # Unauthorized
        return {"status": "error", "message": "Webhook key not configured"}

    signature = frappe.request.headers.get("X-Xero-Signature")
    raw_payload = frappe.request.get_data(as_text=True)

    if not signature or not verify_signature(webhook_key, raw_payload, signature):
        log_xero_error(
            "Webhook received with invalid or missing signature. Signature verification failed.",
            status="Error",
            category="Authentication Issues",
            error_details=f"Signature provided: {bool(signature)}, Payload length: {len(raw_payload)}"
        )
        frappe.response.status_code = 401 # Unauthorized
        return {"status": "error", "message": "Invalid signature"}

    # 2. Process Payload
    try:
        payload = json.loads(raw_payload)
        events = payload.get("events", [])

        if not events:
            log_xero_error(
                "Webhook received with empty events array.",
                status="Info",
                category="System Monitoring",
                processing_time=time.time() - start_time
            )
            return {"status": "success", "message": "Empty events array"}

        # Log successful webhook receipt
        log_xero_error(
            f"Webhook received with {len(events)} event(s). Signature verified successfully.",
            status="Success",
            category="System Monitoring",
            processing_time=time.time() - start_time
        )

        # Process each event - run in background
        for event in events:
            # Enqueue processing to avoid holding up the webhook response
            frappe.enqueue(
                "xero.utils.webhook_handler.process_webhook_event",
                queue="short",
                event_data=event
            )

        # Respond quickly to Xero
        return {"status": "success", "message": f"{len(events)} webhook event(s) queued for processing"}

    except json.JSONDecodeError as e:
        log_xero_error(
            "Webhook received with invalid JSON payload.",
            status="Error",
            category="Validation Errors",
            error_details=f"JSONDecodeError: {str(e)}\nPayload: {raw_payload[:500]}",
            processing_time=time.time() - start_time
        )
        frappe.response.status_code = 400 # Bad Request
        return {"status": "error", "message": "Invalid JSON payload"}
    except Exception as e:
        log_xero_error(
            "Error processing webhook payload.",
            status="Error",
            category="Other Errors",
            error_details=frappe.get_traceback(),
            processing_time=time.time() - start_time
        )
        frappe.response.status_code = 500 # Internal Server Error
        return {"status": "error", "message": "Internal server error"}


def get_webhook_key():
    """Retrieves the webhook signing key from settings."""
    settings = get_xero_settings()
    if settings.enable_webhooks:
        return settings.get_password("webhook_secret")
    return None

def verify_signature(key, payload, signature):
    """Verifies the HMAC-SHA256 signature of the webhook payload."""
    try:
        # Decode the key and compute the HMAC hash
        key_bytes = key.encode('utf-8')
        payload_bytes = payload.encode('utf-8')
        computed_hash = hmac.new(key_bytes, payload_bytes, hashlib.sha256)
        # Base64 encode the hash digest
        computed_signature = base64.b64encode(computed_hash.digest()).decode('utf-8')
        # Compare with the provided signature
        return hmac.compare_digest(computed_signature, signature)
    except Exception as e:
        log_xero_error("Error during webhook signature verification.", status="Error", error_details=str(e))
        return False


def process_webhook_event(event_data):
    """
    Processes a single event received from the Xero webhook.
    (This function runs in the background via enqueue)
    """
    event_category = event_data.get("eventCategory") # e.g., "INVOICE", "CONTACT"
    event_type = event_data.get("eventType") # e.g., "UPDATE", "CREATE"
    resource_id = event_data.get("resourceId")
    tenant_id = event_data.get("tenantId") # Verify tenant ID if needed

    log_xero_error(
        f"Processing webhook event: {event_category} - {event_type} for Resource ID: {resource_id}",
        status="Info",
        xero_entity_type=event_category,
        xero_entity_id=resource_id
    )

    # Route event to specific handlers based on category and type
    # Route event to specific handlers based on category and type
    try:
        settings = get_xero_settings() # Get settings once for the event

        if event_category == "INVOICE":
            if event_type == "UPDATE":
                # Check if payment sync or PE creation is enabled
                if settings.sync_payments or settings.create_payment_entry_on_sync:
                    process_invoice_update_webhook(resource_id, settings)
            # Handle other invoice event types (CREATE, DELETE?) if needed
            # elif event_type == "CREATE": etc.

        elif event_category == "CONTACT":
            # Check if contact sync is enabled
            if settings.sync_contacts:
                if event_type == "UPDATE" or event_type == "CREATE":
                    process_contact_update_webhook(resource_id)
                # Handle DELETE?
                # elif event_type == "DELETE": etc.
        # Add handlers for other categories (PAYMENTS, etc.) as needed

        # Example: Log unhandled events
        else:
             log_xero_error(f"Unhandled webhook event category: {event_category}", status="Warning")

    except Exception as e:
         log_xero_error(
            f"Error processing webhook event for {event_category} {resource_id}",
            status="Error",
            xero_entity_type=event_category,
            xero_entity_id=resource_id,
            error_details=frappe.get_traceback()
        )

# --- Specific Event Processors ---

def process_invoice_update_webhook(xero_invoice_id, settings):
    """
    Fetches the updated invoice from Xero and updates ERPNext if paid.
    Called by the background job processing webhook events.
    """
    try:
        # Fetch the full invoice details from Xero
        xero_inv_data = xero_request("GET", f"Invoices/{xero_invoice_id}")
        if not xero_inv_data or not xero_inv_data.get("Invoices"):
            log_xero_error(f"Webhook: Could not fetch details for updated Xero Invoice ID {xero_invoice_id}", status="Warning")
            return

        xero_invoice = xero_inv_data["Invoices"][0]
        amount_due = flt(xero_invoice.get("AmountDue", 0.0))

        # Find corresponding ERPNext invoice
        erpnext_inv_info = None
        for doctype in ["Sales Invoice", "Purchase Invoice"]:
            info = frappe.db.get_value(doctype, {"xero_invoice_id": xero_invoice_id, "docstatus": 1}, ["name", "outstanding_amount", "status"], as_dict=True)
            if info:
                erpnext_inv_info = info
                erpnext_inv_info["doctype"] = doctype
                break

        if not erpnext_inv_info:
            log_xero_error(f"Webhook: Received update for Xero Invoice {xero_invoice_id}, but no matching submitted ERPNext invoice found.", status="Warning")
            return

        # Check if paid in Xero and not yet paid in ERPNext
        if amount_due <= 0 and flt(erpnext_inv_info.outstanding_amount) > 0:
            log_xero_error(
                f"Webhook: Invoice {erpnext_inv_info.doctype} {erpnext_inv_info.name} paid in Xero (ID: {xero_invoice_id}). Updating ERPNext.",
                status="Info",
                erpnext_doc_type=erpnext_inv_info.doctype,
                erpnext_doc_name=erpnext_inv_info.name,
                xero_entity_id=xero_invoice_id,
                xero_entity_type="Invoice",
                direction="Xero to ERPNext (Webhook)"
            )
            # Get the full doc to pass to PE creation
            erpnext_inv_doc = frappe.get_doc(erpnext_inv_info.doctype, erpnext_inv_info.name)
            # Trigger PE creation or status update
            create_payment_entry_for_xero_payment(erpnext_inv_doc, xero_invoice, settings)
        # Optionally handle other status changes received via webhook (e.g., VOIDED)

    except Exception as e:
        log_xero_error(
            f"Webhook: Error processing invoice update for Xero ID {xero_invoice_id}",
            status="Error",
            xero_entity_id=xero_invoice_id,
            xero_entity_type="Invoice",
            error_details=frappe.get_traceback()
        )


def process_contact_update_webhook(xero_contact_id):
    """
    Fetches the updated contact from Xero and updates the corresponding ERPNext Customer/Supplier.
    Called by the background job processing webhook events.
    """
    try:
        # Fetch the full contact details from Xero
        xero_contact_data = xero_request("GET", f"Contacts/{xero_contact_id}")
        if not xero_contact_data or not xero_contact_data.get("Contacts"):
            log_xero_error(f"Webhook: Could not fetch details for updated Xero Contact ID {xero_contact_id}", status="Warning")
            return

        xero_contact = xero_contact_data["Contacts"][0]

        # Determine if Customer or Supplier and trigger sync
        is_customer = xero_contact.get("IsCustomer", False)
        is_supplier = xero_contact.get("IsSupplier", False)

        if is_customer:
            sync_xero_contact_to_erpnext(xero_contact, "Customer")
        if is_supplier:
            sync_xero_contact_to_erpnext(xero_contact, "Supplier")

    except Exception as e:
        log_xero_error(
            f"Webhook: Error processing contact update for Xero ID {xero_contact_id}",
            status="Error",
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            error_details=frappe.get_traceback()
        )
