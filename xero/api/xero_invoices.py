# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
from ..utils.transactions import commit_checkpoint, commit_error_state, commit_external_outcome
from frappe import _
from frappe.utils import flt, getdate, nowdate, now_datetime
from frappe.model.mapper import get_mapped_doc
import hashlib
import json
import re
from ..utils.xero_client import (
    xero_request,
    get_xero_settings,
    check_xero_entity_exists,
)
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff
from ..utils.sync_status import mark_sync_failure
from .xero_line_builder import (
    apply_inbound_taxes,
    build_xero_lines,
    inbound_line_rate,
)


# Only these Xero document states have ledger effect in Xero itself; anything
# else (DRAFT, SUBMITTED awaiting approval, DELETED, VOIDED) must never post
# to the ERPNext GL, no matter what auto_submit_inbound says.
XERO_POSTED_STATUSES = ("AUTHORISED", "PAID")

# Lifetime of the per-invoice inbound mutex. Long enough to outlast one
# import, short enough that a killed worker's lock frees itself.
INBOUND_LOCK_TTL_SECONDS = 120


def maybe_submit_inbound(doc, settings, xero_entity_id, xero_entity_type, xero_status=None):
    """Opt-in auto-submit for documents imported FROM Xero (invoices, bills,
    credit notes).

    Default behaviour (auto_submit_inbound OFF): imported documents stay Draft
    for manual review and this is a no-op. When the operator enables
    auto_submit_inbound, the document is posted to the GL and marked 'Synced' —
    but only when the Xero document itself is posted (AUTHORISED/PAID). A Xero
    DRAFT has no ledger effect in Xero, so posting it here would fabricate a
    receivable/payable that Xero does not hold.

    The caller must have already committed the draft, so a submission failure
    here only rolls back the failed submit — the draft survives, is marked
    'Error', and the surrounding import batch continues. Returns True on submit.
    """
    if not settings or not settings.get("auto_submit_inbound"):
        return False
    if getattr(doc, "docstatus", 0) != 0:
        return False
    if (xero_status or "").upper() not in XERO_POSTED_STATUSES:
        log_xero_error(
            message=(
                f"Not auto-submitting inbound {doc.doctype} {doc.name}: Xero status is "
                f"{xero_status or 'unknown'} (only {' / '.join(XERO_POSTED_STATUSES)} post to the GL). "
                "Left as Draft."
            ),
            status="Info",
            erpnext_doc_type=doc.doctype,
            erpnext_doc_name=doc.name,
            xero_entity_id=xero_entity_id,
            xero_entity_type=xero_entity_type,
            direction="Xero to ERPNext",
        )
        return False
    try:
        # Don't bounce the document straight back out to Xero on submit hooks.
        doc.flags.ignore_xero_sync = True
        doc.submit()
        frappe.db.set_value(
            doc.doctype, doc.name, "xero_sync_status", "Synced", update_modified=False
        )
        commit_checkpoint()
        log_xero_error(
            message=f"Auto-submitted inbound {doc.doctype} {doc.name} from Xero {xero_entity_type} {xero_entity_id}",
            status="Success",
            erpnext_doc_type=doc.doctype,
            erpnext_doc_name=doc.name,
            xero_entity_id=xero_entity_id,
            xero_entity_type=xero_entity_type,
            direction="Xero to ERPNext",
        )
        return True
    except Exception:
        frappe.db.rollback()
        try:
            frappe.db.set_value(
                doc.doctype, doc.name, "xero_sync_status", "Error", update_modified=False
            )
            commit_error_state()
        except Exception:
            pass
        log_xero_error(
            message=f"Auto-submit failed for inbound {doc.doctype} {doc.name}; left as Draft for manual review.",
            status="Error",
            error_details=frappe.get_traceback(),
            erpnext_doc_type=doc.doctype,
            erpnext_doc_name=doc.name,
            xero_entity_id=xero_entity_id,
            xero_entity_type=xero_entity_type,
            direction="Xero to ERPNext",
            category="Validation Errors",
        )
        return False


# --- Validation Functions ---
# validate_invoice_description lives in xero_line_builder (shared with credit
# notes and purchase orders) and is re-exported above for existing importers.


def validate_invoice_number(invoice_name):
    """
    Validate invoice number for Xero.
    Xero requires: max 255 chars, printable ASCII only
    """
    if not invoice_name:
        return None

    # Truncate to 255 chars
    invoice_number = invoice_name[:255]

    # Remove non-printable ASCII characters (keep 32-126)
    invoice_number = "".join(c for c in invoice_number if 32 <= ord(c) <= 126)

    return invoice_number or None


def validate_invoice_reference(reference):
    """
    Validate invoice reference for Xero.
    Xero requires: max 255 chars
    """
    if not reference:
        return None

    # Truncate to 255 chars
    reference = str(reference)[:255]

    return reference or None


def find_xero_invoice_by_number(invoice_number, xero_invoice_type):
    """
    Self-healing lookup: query Xero for an existing invoice with the given
    InvoiceNumber. Returns the Xero InvoiceID if a SINGLE unambiguous match
    is found, otherwise None.

    Per Xero API spec (Invoices.md):
      - ACCREC (Sales) — InvoiceNumber is UNIQUE within an organisation.
      - ACCPAY (Bills) — InvoiceNumber is NOT unique. Auto-matching is
        therefore unsafe and disabled for bills.

    Used to recover from the duplicate-invoice scenario: if ERPNext lost
    its xero_invoice_id (e.g. a previous outbound POST succeeded on Xero
    but the local DB write crashed before the ID was committed), a naive
    re-sync would create a SECOND Xero invoice with the same InvoiceNumber.
    This helper detects the existing invoice and returns its ID so the
    caller can switch from CREATE to UPDATE semantics.
    """
    if not invoice_number or xero_invoice_type != "ACCREC":
        return None

    try:
        # Query by InvoiceNumber via a where-clause. This returns HTTP 200 with
        # an empty Invoices list when there is no match — UNLIKE
        # GET /Invoices/{InvoiceNumber}, which returns 404 for any not-yet-synced
        # invoice and made xero_request log a spurious "404" error on EVERY
        # first-time outbound invoice sync (a large source of Xero Log noise).
        safe_number = str(invoice_number).replace('"', "")
        # HI-10: Exclude VOIDED/DELETED invoices from the recovery lookup.
        # Without this, a dead invoice in Xero could be matched and then the
        # outbound sync would attempt to UPDATE it (Xero rejects edits on a
        # voided/deleted doc, or worse we'd reattach ERPNext to a dead record).
        response = xero_request(
            "GET",
            "Invoices",
            params={
                "where": (
                    f'InvoiceNumber=="{safe_number}" '
                    'AND Status!="VOIDED" AND Status!="DELETED"'
                )
            },
        )
    except Exception:
        # Network / parse error — treat as "not found" and let the normal create
        # path proceed. Xero will reject genuine duplicates via its own
        # validation, which is safer than blocking sync on a transient failure.
        return None

    invoices = (response or {}).get("Invoices") or []
    if len(invoices) == 1:
        # HI-10: Defensively verify the matched invoice is in a live, editable
        # state before handing the ID back for an UPDATE. Belt-and-braces with
        # the where-clause filter above.
        matched = invoices[0]
        if matched.get("Status") in ("AUTHORISED", "DRAFT", "SUBMITTED"):
            return matched.get("InvoiceID")
        return None
    # Either 0 (not found) or >1 (ambiguous — should not happen for
    # ACCREC but be defensive). In both cases return None.
    return None


# --- Hash Functions for Change Detection ---


def compute_invoice_hash(doc):
    """
    Compute MD5 hash of invoice data for change detection.
    """
    hash_data = {
        "posting_date": str(doc.posting_date),
        "due_date": str(doc.due_date),
        "currency": doc.currency,
        "customer": doc.get("customer") or doc.get("supplier"),
        "items": [],
        "taxes": [],
    }

    # Add line items
    for item in doc.items:
        hash_data["items"].append(
            {
                "item_code": item.item_code,
                "description": item.description,
                "qty": flt(item.qty),
                "rate": flt(item.rate),
                "amount": flt(item.amount),
                "income_account": item.get("income_account")
                or item.get("expense_account"),
            }
        )

    # Add taxes
    for tax in doc.taxes:
        hash_data["taxes"].append(
            {
                "account_head": tax.account_head,
                "tax_amount": flt(tax.tax_amount_after_discount_amount),
            }
        )

    # Compute hash
    hash_string = json.dumps(hash_data, sort_keys=True)
    return hashlib.md5(hash_string.encode()).hexdigest()


def invoice_data_changed(doc):
    """
    Check if invoice data has changed since last sync.
    Returns True if data has changed or no hash exists.
    """
    stored_hash = doc.get("xero_data_hash")
    if not stored_hash:
        return True

    current_hash = compute_invoice_hash(doc)
    return current_hash != stored_hash


# --- Invoice Sync (ERPNext to Xero) ---


@frappe.whitelist()
def enqueue_sync_invoice_or_return(doc, method):
    """
    Wrapper function for on_submit event.
    Checks if the document is a return and enqueues the correct sync job.
    """
    # HI-4: the inbound (Xero -> ERPNext) import sets this flag before submitting
    # an imported invoice/return, so the on_submit hook does not bounce the same
    # document straight back out to Xero as an update (echo loop).
    if getattr(doc.flags, "ignore_xero_sync", False):
        return
    if doc.get("is_return"):
        from .xero_credit_notes import enqueue_sync_return

        enqueue_sync_return(doc, method)
    else:
        enqueue_sync_invoice(doc, method)


def enqueue_sync_invoice(doc, method):
    """Enqueue background job to sync a standard invoice to Xero."""
    settings = get_xero_settings()
    # Use the correct per-entity directional flag at enqueue time
    if doc.doctype == "Sales Invoice":
        if not settings.get("sync_invoices_to_xero"):
            return
    else:  # Purchase Invoice
        if not settings.get("sync_bills_to_xero"):
            return

    # Double-trigger guard: read current sync state from DB, NOT from the
    # hook-passed doc object. The hook doc reflects the pre-save in-memory
    # state; the DB holds the authoritative committed values. Reading from
    # the doc can cause the guard to pass on already-synced invoices when
    # the object was loaded before the last set_value committed.
    db_xero_status = frappe.db.get_value(doc.doctype, doc.name, "xero_sync_status")
    db_xero_id = frappe.db.get_value(doc.doctype, doc.name, "xero_invoice_id")
    if db_xero_status == "Synced" and db_xero_id:
        # Check if data has changed since last sync
        if not invoice_data_changed(doc):
            log_xero_error(
                message=f"Skipping sync for {doc.doctype} {doc.name}: already synced and data unchanged",
                status="Info",
                erpnext_doc_type=doc.doctype,
                erpnext_doc_name=doc.name,
                category="System Monitoring",
            )
            return

    frappe.enqueue(
        "xero.api.xero_invoices.sync_invoice_to_xero",
        queue="short",
        timeout=600,
        enqueue_after_commit=True,
        doc_name=doc.name,
        doc_type=doc.doctype,
    )
    frappe.logger().info(
        f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync"
    )


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_invoice_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs a submitted ERPNext Sales Invoice or Purchase Invoice to Xero.
    Uses POST for both create and update (Xero API requirement).
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        # frappe.logger().info("Xero Sync master switch is disabled.", "Xero Info")
        return  # Master switch disabled

    # Check per-entity directional toggle for outbound sync
    if doc_type == "Sales Invoice":
        if not settings.get("sync_invoices_to_xero"):
            log_xero_error(
                message=f"Sales Invoice outbound sync is disabled. Skipping {doc_name}.",
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="System Monitoring",
            )
            return
    elif doc_type == "Purchase Invoice":
        if not settings.get("sync_bills_to_xero"):
            log_xero_error(
                message=f"Bills (Purchase Invoice) outbound sync is disabled. Skipping {doc_name}.",
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="System Monitoring",
            )
            return

    try:
        doc = frappe.get_doc(doc_type, doc_name)

        # Always read xero_invoice_id directly from DB — never trust the
        # in-memory doc, which may reflect a stale pre-commit state when
        # the function is retried by the decorator after a partial failure.
        xero_invoice_id = frappe.db.get_value(doc_type, doc_name, "xero_invoice_id")

        # --- Basic Validation ---
        if doc.docstatus != 1:
            log_xero_error(
                f"Cannot sync non-submitted document: {doc_type} {doc_name}",
                status="Info",
            )
            return

        # Return documents must go via xero_credit_notes, not here — Xero
        # rejects negative quantities on Invoice endpoints.
        if doc.get("is_return"):
            from .xero_credit_notes import enqueue_sync_return
            enqueue_sync_return(doc, "on_submit")
            return

        # --- Check if data has changed (for already synced invoices) ---
        if xero_invoice_id:
            if not invoice_data_changed(doc):
                log_xero_error(
                    message=f"{doc_type} {doc_name} already synced and data unchanged. Skipping.",
                    status="Info",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=xero_invoice_id,
                    xero_entity_type="Invoice",
                    category="System Monitoring",
                )
                return

        # --- Determine Invoice Type and Contact ---
        if doc_type == "Sales Invoice":
            xero_invoice_type = "ACCREC"  # Accounts Receivable
            contact_party_type = "Customer"
            contact_party_name = doc.customer
            party_account_field = "debit_to"  # Account receivable
        elif doc_type == "Purchase Invoice":
            xero_invoice_type = "ACCPAY"  # Accounts Payable
            contact_party_type = "Supplier"
            contact_party_name = doc.supplier
            party_account_field = "credit_to"  # Account payable
        else:
            raise ValueError("Unsupported DocType for Xero Invoice sync.")

        # --- Get Linked Xero Contact ID ---
        xero_contact_id = frappe.db.get_value(
            contact_party_type, contact_party_name, "xero_contact_id"
        )
        if not xero_contact_id:
            # Queue contact sync asynchronously instead of inline
            frappe.logger().info(
                f"Xero Contact ID not found for {contact_party_type} {contact_party_name}. Queuing contact sync.",
                "Xero Sync",
            )

            # Queue contact sync (pass party name and type so worker gets correct doc_name, doc_type)
            from .xero_contacts import enqueue_sync_contact

            try:
                enqueue_sync_contact(contact_party_name, contact_party_type)
            except Exception as e:
                frappe.log_error(
                    f"Failed to queue contact sync: {str(e)}",
                    "Xero Contact Queue Error",
                )

            # Mark invoice as pending prerequisites
            frappe.db.set_value(
                doc_type,
                doc_name,
                {"xero_sync_status": "Pending Prerequisites"},
                update_modified=False,
            )
            commit_checkpoint()

            log_xero_error(
                message=f"{doc_type} {doc_name} sync deferred: {contact_party_type} {contact_party_name} must be synced to Xero first. Contact sync queued.",
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="System Monitoring",
            )

            # Re-queue this invoice for later (after contact sync completes)
            frappe.enqueue(
                "xero.api.xero_invoices.sync_invoice_to_xero",
                queue="short",
                timeout=600,
                doc_name=doc_name,
                doc_type=doc_type,
                enqueue_after_commit=True,
                at_front=False,  # Don't jump the queue
                # Delay by 60 seconds to give contact sync time to complete
                job_id=f"invoice_retry_{doc_name}_{frappe.utils.now()}",
            )
            return

        # --- Map ERPNext Invoice Data to Xero Format ---
        # Ref: https://developer.xero.com/documentation/api/accounting/invoices
        # For Purchase Invoices, use bill_date (supplier's invoice date) if set; fall back to posting_date
        bill_date = doc.get("bill_date") if doc_type == "Purchase Invoice" else None

        # Line items + per-line TaxType/TaxAmount + LineAmountTypes + rounding
        # line. Raises TaxRepresentationError (doc marked Error below) instead
        # of ever sending a payload whose Total/TotalTax would not reconcile.
        built = build_xero_lines(doc, doc_type, settings)

        invoice_payload = {
            "Type": xero_invoice_type,
            "Contact": {"ContactID": xero_contact_id},
            "Date": getdate(bill_date or doc.posting_date).isoformat(),
            "DueDate": getdate(doc.due_date).isoformat(),
            "LineItems": built.line_items,
            "InvoiceNumber": validate_invoice_number(
                doc.name
            ),  # Validate invoice number
            "CurrencyCode": doc.currency,
            "Status": "AUTHORISED",  # Or SUBMITTED? AUTHORISED seems more appropriate for synced invoices.
            "LineAmountTypes": built.line_amount_types,
        }

        # Add Reference field (max 255 chars)
        # Sales Invoice: po_no (customer's PO number)
        # Purchase Invoice: bill_no (supplier's invoice number — the primary Bill identifier in Xero)
        if doc_type == "Sales Invoice":
            reference = validate_invoice_reference(doc.get("po_no"))
        else:
            reference = validate_invoice_reference(doc.get("bill_no"))
        if reference:
            invoice_payload["Reference"] = reference

        # --- Self-healing lookup: recover lost xero_invoice_id ---
        # If we have no stored xero_invoice_id, ask Xero whether an invoice
        # with this InvoiceNumber already exists. If it does, attach the ID
        # so this becomes an UPDATE rather than a CREATE — preventing
        # duplicate Xero invoices when a previous outbound attempt
        # succeeded on Xero's side but failed to commit the ID locally.
        # Only safe for ACCREC (Sales) — ACCPAY InvoiceNumbers are not
        # unique in Xero, so auto-matching could attach to the wrong bill.
        if not xero_invoice_id and xero_invoice_type == "ACCREC":
            recovered_id = find_xero_invoice_by_number(
                invoice_payload["InvoiceNumber"], xero_invoice_type
            )
            if recovered_id:
                xero_invoice_id = recovered_id
                # Persist immediately so any subsequent retry sees it.
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {"xero_invoice_id": recovered_id},
                    update_modified=False,
                )
                commit_external_outcome()
                log_xero_error(
                    message=(
                        f"Recovered Xero InvoiceID {recovered_id} for "
                        f"{doc_type} {doc_name} via InvoiceNumber lookup. "
                        f"Switching from CREATE to UPDATE to avoid "
                        f"duplicating the invoice in Xero."
                    ),
                    status="Info",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=recovered_id,
                    xero_entity_type="Invoice",
                    direction="ERPNext to Xero",
                    category="Duplicate Entity",
                )

        # If updating (either originally synced, or just recovered above),
        # include the Xero Invoice ID so Xero performs UPDATE not CREATE.
        if xero_invoice_id:
            invoice_payload["InvoiceID"] = xero_invoice_id

        # --- Make API Call (POST for both create and update) ---
        # Xero API: POST creates OR updates (if InvoiceID provided, updates; otherwise creates)
        # CR-6/idempotency: pass a stable idempotency key only when CREATING
        # (no xero_invoice_id). On UPDATE the InvoiceID already makes Xero
        # target the existing record; reusing a create key across edits would
        # wrongly dedup legitimate edits within Xero's 24h window.
        idempotency_key = None
        if not xero_invoice_id:
            idempotency_key = f"{doc_type}:{doc_name}:create-invoice"
        response = xero_request(
            "POST",
            "Invoices",
            data={"Invoices": [invoice_payload]},
            idempotency_key=idempotency_key,
        )

        if response and response.get("Invoices"):
            updated_invoice = response["Invoices"][0]
            new_xero_invoice_id = updated_invoice.get("InvoiceID")

            # --- Update ERPNext Document ---
            if new_xero_invoice_id:
                # IMPORTANT: Commit xero_invoice_id to DB immediately and
                # unconditionally BEFORE computing the hash or writing anything
                # else. This ensures that if any subsequent step raises (e.g.
                # a stale-document ValidationError on set_value), a retry of
                # this function will see the ID already present in the DB,
                # include it in the payload as InvoiceID, and Xero will UPDATE
                # the existing invoice rather than CREATE a second one.
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {"xero_invoice_id": new_xero_invoice_id},
                    update_modified=False,
                )
                commit_external_outcome()

                # Now write the remaining sync fields
                data_hash = compute_invoice_hash(doc)
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {
                        "xero_sync_status": "Synced",
                        "xero_data_hash": data_hash,
                    },
                    update_modified=False,
                )
                commit_external_outcome()

                log_xero_error(
                    message=f"Successfully synced {doc_type} {doc_name} to Xero.",
                    status="Success",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=new_xero_invoice_id,
                    xero_entity_type="Invoice",
                    direction="ERPNext to Xero",
                )
            else:
                raise Exception("Xero API response did not contain an InvoiceID.")
        else:
            raise Exception("Invalid response received from Xero Invoices API.")

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        # Check if this is an "already exists" type error from Xero API
        # These are not real sync failures — the entity already exists in Xero
        if is_already_exists_error(str(e), error_traceback):
            if doc_name and doc_type:
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {"xero_sync_status": "Synced"},
                    update_modified=False,
                )
                commit_error_state()

            log_xero_error(
                message=f"{doc_type} {doc_name} already exists in Xero. No action needed.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                direction="ERPNext to Xero",
            )
        else:
            mark_sync_failure(
                doc_type, doc_name, e, "ERPNext to Xero", traceback_text=error_traceback
            )


def enqueue_void_invoice(doc, method):
    """Enqueue background job to void a cancelled invoice in Xero."""
    settings = get_xero_settings()
    # ME-6: Voiding pushes a change TO Xero, so gate on the OUTBOUND directional
    # flag for this document type, not the legacy aggregate `sync_invoices`
    # (which is also true when only inbound sync is enabled).
    outbound_enabled = (
        settings.get("sync_bills_to_xero")
        if doc.doctype == "Purchase Invoice"
        else settings.get("sync_invoices_to_xero")
    )
    if not settings.enable_xero_sync or not settings.enable_sync_to_xero or not outbound_enabled:
        return

    # Route return documents to credit note void handler
    if doc.get("is_return"):
        from .xero_credit_notes import enqueue_void_credit_note

        enqueue_void_credit_note(doc, method)
        return

    frappe.enqueue(
        "xero.api.xero_invoices.void_invoice_in_xero",
        queue="short",
        enqueue_after_commit=True,
        doc_name=doc.name,
        doc_type=doc.doctype,
    )
    frappe.logger().info(
        f"Queued void for {doc.doctype} {doc.name} to Xero.", "Xero Sync"
    )


def void_invoice_in_xero(doc_name, doc_type):
    """
    Finds the corresponding Xero invoice and voids or deletes it.
    - DRAFT/SUBMITTED invoices can be DELETED
    - AUTHORISED invoices can be VOIDED (if no payments applied)
    """
    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_invoice_id = doc.get("xero_invoice_id")

        if not xero_invoice_id:
            log_xero_error(
                f"Cannot void invoice {doc_name}: Xero Invoice ID not found.",
                status="Info",
            )
            return

        # First, get the current status from Xero
        try:
            xero_data = xero_request("GET", f"Invoices/{xero_invoice_id}")
            if not xero_data or not xero_data.get("Invoices"):
                log_xero_error(
                    message=f"Could not fetch Xero invoice {xero_invoice_id} for void/delete",
                    status="Warning",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=xero_invoice_id,
                )
                return

            xero_invoice = xero_data["Invoices"][0]
            xero_status = xero_invoice.get("Status")
        except Exception as fetch_error:
            log_xero_error(
                message=f"Error fetching Xero invoice status: {str(fetch_error)}",
                status="Warning",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=xero_invoice_id,
            )
            # Default to VOIDED if we can't fetch status
            xero_status = "AUTHORISED"

        # Determine the appropriate status change
        # DRAFT or SUBMITTED → DELETED
        # AUTHORISED → VOIDED
        if xero_status in ["DRAFT", "SUBMITTED"]:
            new_status = "DELETED"
            action = "delete"
            action_past = "Deleted"
        else:
            new_status = "VOIDED"
            action = "void"
            action_past = "Voided"

        invoice_payload = {"InvoiceID": xero_invoice_id, "Status": new_status}

        # Xero API for voiding/deleting is a POST to the Invoices endpoint
        response = xero_request(
            "POST", "Invoices", data={"Invoices": [invoice_payload]}
        )

        if response and response.get("Invoices"):
            frappe.db.set_value(
                doc_type,
                doc_name,
                "xero_sync_status",
                f"{action_past} in Xero",
                update_modified=False,
            )
            commit_external_outcome()
            log_xero_error(
                message=f"Successfully {action_past.lower()} {doc_type} {doc_name} in Xero (status: {new_status}).",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=xero_invoice_id,
                xero_entity_type="Invoice",
                direction="ERPNext to Xero",
            )
        else:
            raise Exception(
                "Invalid response received from Xero when voiding/deleting invoice."
            )

    except Exception as e:
        log_xero_error(
            message=f"Failed to void/delete {doc_type} {doc_name} in Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback(),
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
        return  # Master switch disabled
    if not settings.sync_payments:
        return  # Payment sync specifically disabled

    frappe.logger().info("Starting Xero Payment Check", "Xero Sync")
    processed_count = 0

    # Get ERPNext invoices (SI & PI) linked to Xero and not fully paid
    linked_invoices = []
    for doctype in ["Sales Invoice", "Purchase Invoice"]:
        filters = {
            "docstatus": 1,
            "status": ["not in", ["Paid", "Cancelled"]],
            "xero_invoice_id": ["is", "set"],
        }
        invoices = frappe.get_all(
            doctype,
            filters=filters,
            fields=["name", "xero_invoice_id", "grand_total", "outstanding_amount"],
        )
        for inv in invoices:
            inv.doctype = doctype  # Add doctype info for processing
            linked_invoices.append(inv)

    if not linked_invoices:
        frappe.logger().info(
            "No unpaid linked invoices found to check for payments.", "Xero Sync"
        )
        return

    for inv in linked_invoices:
        try:
            # Fetch invoice details from Xero using the ID
            xero_inv_data = xero_request("GET", f"Invoices/{inv.xero_invoice_id}")

            if not xero_inv_data or not xero_inv_data.get("Invoices"):
                log_xero_error(
                    f"Could not fetch details for Xero Invoice ID {inv.xero_invoice_id}",
                    status="Warning",
                    erpnext_doc_type=inv.doctype,
                    erpnext_doc_name=inv.name,
                )
                continue

            xero_invoice = xero_inv_data["Invoices"][0]
            xero_status = xero_invoice.get("Status")
            amount_paid = flt(xero_invoice.get("AmountPaid", 0.0))
            amount_due = flt(xero_invoice.get("AmountDue", 0.0))

            # Load the ERPNext invoice doc once — needed by both branches below.
            # This fixes a NameError where erpnext_inv_doc was only defined
            # inside the 'if amount_due <= 0' block but referenced in the elif.
            erpnext_inv_doc = frappe.get_doc(inv.doctype, inv.name)

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
                    direction="Xero to ERPNext",
                )

                if erpnext_inv_doc.outstanding_amount > 0:
                    # Create Payment Entry if enabled
                    if settings.create_payment_entry_on_sync:
                        create_payment_entry_for_xero_payment(
                            erpnext_inv_doc, xero_invoice, settings
                        )
                    else:
                        # Just update status if PE creation is disabled
                        erpnext_inv_doc.db_set("status", "Paid")
                        commit_checkpoint()

                    processed_count += 1

            # Handle other status discrepancies if needed (e.g., VOIDED in Xero?)
            elif xero_status == "VOIDED" and erpnext_inv_doc.docstatus == 1:
                log_xero_error(
                    message=f"Invoice {inv.doctype} {inv.name} VOIDED in Xero (ID: {inv.xero_invoice_id}). Consider cancelling in ERPNext.",
                    status="Warning",  # Log as warning, manual action might be needed
                    erpnext_doc_type=inv.doctype,
                    erpnext_doc_name=inv.name,
                    xero_entity_id=inv.xero_invoice_id,
                    xero_entity_type="Invoice",
                    direction="Xero to ERPNext",
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
                error_details=frappe.get_traceback(),
            )

    log_xero_error(
        message=f"Finished Xero Payment Check. Updated {processed_count} invoices.",
        status="Info",
    )


# --- Helper Functions ---


# Cache for mappings to avoid fetching settings repeatedly within a request/job
# HI-2: Removed allow_guest=True. This exposed the account/tax mapping
# (internal Chart-of-Accounts structure) to unauthenticated callers. No guest
# JS relies on it (verified: no references in any .js file), so requiring an
# authenticated session is safe.
@frappe.whitelist()
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
        frappe.cache().set_value(
            cache_key, mapping
        )  # Cache for short duration? e.g., 5 mins
    return mapping


def get_xero_account_code(erpnext_account, settings=None):
    """Maps an ERPNext account name to a Xero Account Code using the mapping table."""
    if not settings:
        settings = get_xero_settings()  # Fetch if not passed
    account_map = settings.get_account_map()  # Use method on settings doc
    return account_map.get(erpnext_account)


def map_erpnext_tax_to_xero(erpnext_tax_template, settings=None):
    """Maps ERPNext tax templates to Xero TaxTypes using the mapping table."""
    if not erpnext_tax_template:
        return "NONE"  # Default if no tax template applied

    if not settings:
        settings = get_xero_settings()  # Fetch if not passed
    tax_map = settings.get_tax_map()  # Use method on settings doc
    xero_tax_code = tax_map.get(erpnext_tax_template)

    if not xero_tax_code:
        log_xero_error(
            f"Xero TaxType mapping not found for ERPNext Tax Template: {erpnext_tax_template}. Defaulting to NONE.",
            status="Warning",
        )
        return "NONE"  # Default if no mapping found

    return xero_tax_code


def create_payment_entry_for_xero_payment(invoice_doc, xero_invoice_data, settings):
    """
    Reconcile ERPNext with the payments recorded against a Xero invoice.

    CR-6 (duplicate Payment Entries): This routine and
    xero_payments.process_xero_payment used to both create Payment Entries for
    the same Xero payment, with DIFFERENT dedup keys, so they could double-book.
    They are now consolidated: this function NO LONGER creates Payment Entries
    itself. Instead it iterates the individual Xero invoice Payments[] rows and
    DELEGATES each one to xero_payments.process_xero_payment — the single
    creation routine. That routine owns the canonical dedup logic
    (xero_payment_id match, xero_payment_data scan, invoice+amount match, and a
    live pre-create Xero check via the inbound payments path) and stamps the
    Xero PaymentID onto the PE's xero_payment_id field, so no path can
    double-book a payment.

    CR-5 (payment date): process_xero_payment reads the real payment date from
    each Payments[].Date (parse_xero_date), so the PE posting_date / reference_date
    are the actual Xero payment date, not nowdate().

    HI-9 (FX): per-payment currency/amount is taken from the Xero Payments[]
    row, and process_xero_payment lets ERPNext compute exchange gain/loss
    instead of assuming payment currency == invoice currency. We additionally
    warn here when the invoice currency differs from the company currency so
    multi-currency cases are visible for manual review.
    """
    if not settings.create_payment_entry_on_sync or not settings.default_bank_account:
        log_xero_error(
            f"Skipping PE creation for {invoice_doc.doctype} {invoice_doc.name}: Setting disabled or default bank account missing.",
            status="Info",
        )
        # Still update status if PE creation skipped
        if invoice_doc.status != "Paid":
            invoice_doc.db_set("status", "Paid")
            commit_checkpoint()
        return

    from .xero_payments import process_xero_payment

    payments = xero_invoice_data.get("Payments") or []
    invoice_id = xero_invoice_data.get("InvoiceID")

    if not payments:
        # No itemised payments on the invoice payload. We deliberately do NOT
        # fabricate a lump Payment Entry from cumulative AmountPaid (the old
        # behaviour) because that PE could not be deduped against the inbound
        # payments path and would double-book. Log so the gap is visible; the
        # scheduled payments sync (sync_payments_from_xero) will pick the
        # payment up by PaymentID when Xero exposes it.
        log_xero_error(
            message=(
                f"Invoice {invoice_doc.doctype} {invoice_doc.name} shows as paid "
                f"in Xero (AmountPaid={flt(xero_invoice_data.get('AmountPaid', 0.0))}) "
                f"but the invoice payload carried no Payments[] rows. Deferring "
                f"Payment Entry creation to the payments sync to avoid creating "
                f"an un-deduplicable lump payment."
            ),
            status="Warning",
            erpnext_doc_type=invoice_doc.doctype,
            erpnext_doc_name=invoice_doc.name,
            xero_entity_id=invoice_id,
            xero_entity_type="Invoice",
            direction="Xero to ERPNext",
            category="Missing Prerequisites",
        )
        return

    # HI-9: surface FX cases. ERPNext will still compute the gain/loss; this is
    # purely to make multi-currency payments visible for manual reconciliation.
    company_currency = None
    try:
        company_currency = frappe.get_cached_value(
            "Company", invoice_doc.company, "default_currency"
        )
    except Exception:
        company_currency = None
    if company_currency and invoice_doc.currency != company_currency:
        log_xero_error(
            message=(
                f"Multi-currency payment(s) for {invoice_doc.doctype} "
                f"{invoice_doc.name}: invoice currency {invoice_doc.currency} "
                f"!= company currency {company_currency}. ERPNext will compute "
                f"exchange gain/loss; verify the applied FX rate."
            ),
            status="Warning",
            erpnext_doc_type=invoice_doc.doctype,
            erpnext_doc_name=invoice_doc.name,
            xero_entity_id=invoice_id,
            xero_entity_type="Invoice",
            direction="Xero to ERPNext",
            category="Validation Errors",
        )

    # Delegate each Xero payment to the single creation routine. Each payment
    # row needs the InvoiceID so process_xero_payment can resolve the invoice.
    for payment in payments:
        payment_data = dict(payment)
        if invoice_id and not payment_data.get("Invoice"):
            payment_data["Invoice"] = {"InvoiceID": invoice_id}
        try:
            process_xero_payment(payment_data, settings)
        except Exception:
            # process_xero_payment logs its own failures; keep going so one bad
            # payment row does not block the others.
            log_xero_error(
                message=(
                    f"Failed delegating Xero payment "
                    f"{payment_data.get('PaymentID')} for {invoice_doc.doctype} "
                    f"{invoice_doc.name} to process_xero_payment."
                ),
                status="Error",
                erpnext_doc_type=invoice_doc.doctype,
                erpnext_doc_name=invoice_doc.name,
                xero_entity_id=payment_data.get("PaymentID"),
                xero_entity_type="Payment",
                direction="Xero to ERPNext",
                error_details=frappe.get_traceback(),
            )


# --- Invoice Sync (Xero to ERPNext) ---


def parse_xero_date(xero_date_string):
    """
    Parse Xero date format /Date(milliseconds+timezone)/ to Python date
    Example: /Date(1769126400000+0000)/ → 2026-01-23

    NOTE: Xero always serialises invoice Date / DueDate as midnight UTC
    milliseconds. We must parse as UTC, NOT local server time, otherwise
    servers west of UTC (e.g. America/*) shift the date back by one day,
    which can spuriously make due_date < posting_date and break ERPNext
    validation.
    """
    if not xero_date_string:
        return None

    # Check if it's already in ISO format
    if not xero_date_string.startswith("/Date("):
        try:
            return getdate(xero_date_string)
        except Exception as e:
            # LO-3: Use a specific exception and log the failure rather than
            # silently swallowing it, so unparseable Xero dates are visible.
            log_xero_error(
                message=f"Failed to parse Xero date '{xero_date_string}': {e}",
                status="Warning",
                category="Validation Errors",
            )
            return None

    # Extract milliseconds from /Date(milliseconds+timezone)/
    import re

    match = re.search(r"/Date\((\d+)", xero_date_string)
    if match:
        milliseconds = int(match.group(1))
        # Convert milliseconds to seconds and create datetime IN UTC
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)
        return dt.date()

    return None


def get_erpnext_account_from_xero_code(
    xero_account_code, settings=None, erpnext_doc_type=None
):
    """
    Reverse lookup: Xero AccountCode → ERPNext Account
    Returns ERPNext account name or None if not found
    """
    if not settings:
        settings = get_xero_settings()

    # Get existing mapping (ERPNext → Xero)
    account_map = settings.get_account_map()

    # Reverse lookup
    for erpnext_account, xero_code in account_map.items():
        if xero_code == xero_account_code:
            return erpnext_account

    # Not found - log warning
    log_xero_error(
        message=f"No ERPNext account mapping found for Xero AccountCode: {xero_account_code}",
        status="Warning",
        category="Mapping Errors",
        xero_entity_type="Invoice",
        erpnext_doc_type=erpnext_doc_type,
        direction="Xero to ERPNext",
    )
    return None


def get_erpnext_tax_from_xero_type(xero_tax_type, settings=None):
    """
    Reverse lookup: Xero TaxType → ERPNext Tax Template
    Returns ERPNext tax template name or None if not found
    """
    if not xero_tax_type or xero_tax_type == "NONE":
        return None

    if not settings:
        settings = get_xero_settings()

    # Get existing mapping (ERPNext → Xero)
    tax_map = settings.get_tax_map()

    # Reverse lookup. Mapping keys may also be doc-level tax templates or tax
    # accounts (outbound resolution); only a real Item Tax Template is valid on
    # an ERPNext invoice line.
    for erpnext_tax, xero_type in tax_map.items():
        if xero_type == xero_tax_type and frappe.db.exists("Item Tax Template", erpnext_tax):
            return erpnext_tax

    # Not found - return None (will use no tax)
    return None


def get_or_create_item_from_xero_code(xero_item_code, description, settings=None):
    """
    Lookup ERPNext item by item_code
    Returns item_code or None if not found
    """
    if not xero_item_code:
        return None

    # Check if item exists
    if frappe.db.exists("Item", xero_item_code):
        return xero_item_code

    # Item doesn't exist - log info and return None (will use description only)
    log_xero_error(
        message=f"Item {xero_item_code} not found in ERPNext. Line will use description only.",
        status="Info",
        category="Mapping Errors",
    )
    return None


def sync_invoices_from_xero(invoice_type=None, modified_since=None, status=None):
    """
    Fetches invoices from Xero and creates/updates corresponding
    Sales/Purchase Invoices in ERPNext.

    Args:
        invoice_type: "ACCREC" (Sales) or "ACCPAY" (Purchase) or None (both)
        modified_since: ISO date string to fetch only recent invoices
        status: Filter by status (DRAFT, AUTHORISED, PAID, etc.)
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return

    # Check per-entity directional toggles for inbound sync
    # Allow through if EITHER Sales Invoice or Bills inbound is ON
    if not settings.get("sync_invoices_from_xero") and not settings.get(
        "sync_bills_from_xero"
    ):
        log_xero_error(
            message="Invoice inbound sync is disabled (both Sales Invoices and Bills are OFF). Skipping.",
            status="Info",
            category="System Monitoring",
        )
        return

    # Incremental sync: only fetch invoices changed since the last successful
    # run for this invoice type (separate watermark per ACCREC/ACCPAY). An
    # explicit modified_since argument overrides the stored watermark.
    from ..utils.xero_client import (
        incremental_since,
        commit_watermark,
        start_incremental_run,
    )

    watermark_key = f"invoices_{invoice_type or 'ALL'}"
    run_started_at = start_incremental_run()
    if_modified_since = modified_since or incremental_since(watermark_key)

    try:
        page = 1
        params = {"page": page}
        synced = skipped = failed = 0

        if invoice_type:
            params["Type"] = invoice_type
        if status:
            params["Status"] = status

        while True:
            frappe.logger().info(f"Fetching Xero Invoices page {page}", "Xero Sync")
            response = xero_request(
                "GET", "Invoices", params=params, modified_since=if_modified_since
            )

            if not response or not response.get("Invoices"):
                break

            invoices = response["Invoices"]
            if not invoices:
                break

            for invoice_data in invoices:
                try:
                    outcome = process_xero_invoice(invoice_data, settings)
                except Exception as e:
                    failed += 1
                    log_xero_error(
                        message=f"Failed to process Xero Invoice ID {invoice_data.get('InvoiceID')}",
                        xero_entity_id=invoice_data.get("InvoiceID"),
                        xero_entity_type="Invoice",
                        error_details=frappe.get_traceback(),
                    )
                else:
                    if outcome == "synced":
                        synced += 1
                    elif outcome == "failed":
                        failed += 1
                    else:
                        skipped += 1

            if len(invoices) < 100:
                break
            page += 1
            params["page"] = page

        # Only advance the watermark after a fully successful sweep — if an
        # exception aborted the loop, the next run re-fetches from the old
        # watermark so nothing is missed.
        commit_watermark(watermark_key, run_started_at)
        # skipped counts guards and duplicates; a skipped invoice is NOT
        # retried by the incremental sweep once the watermark advances past it
        # — recover individually via refetch_invoice after fixing the cause.
        log_xero_error(
            message=(
                f"Finished syncing invoices from Xero: "
                f"synced={synced}, skipped={skipped}, failed={failed}."
            ),
            status="Info",
        )

    except Exception as e:
        log_xero_error(
            message="Error during sync_invoices_from_xero",
            error_details=frappe.get_traceback(),
        )


@frappe.whitelist()
def refetch_invoice(invoice_id):
    """Fetch one invoice from Xero by ID and process it, without touching the
    incremental watermark. Targeted recovery for an invoice the sweep skipped
    (e.g. missing account mapping) after the underlying cause is fixed —
    re-running the sweep would not help because the watermark has already
    advanced past the invoice's UpdatedDateUTC.
    """
    from ..utils.xero_client import require_xero_manager

    require_xero_manager()

    invoice_id = (invoice_id or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", invoice_id):
        frappe.throw(_("'{0}' is not a valid Xero invoice ID.").format(invoice_id))

    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw(_("Xero sync is disabled in Xero Settings."))

    response = xero_request("GET", f"Invoices/{invoice_id}")
    invoices = (response or {}).get("Invoices") or []
    if not invoices:
        frappe.throw(_("Invoice {0} not found in Xero.").format(invoice_id))

    outcome = process_xero_invoice(invoices[0], settings)
    return {"invoice_id": invoice_id, "outcome": outcome}


def _default_uom():
    """UOM for inbound lines that carry no ItemCode. Xero has no UOM concept,
    so use the site's default stock UOM (falling back to any existing UOM)."""
    uom = frappe.db.get_single_value("Stock Settings", "stock_uom")
    if uom and frappe.db.exists("UOM", uom):
        return uom
    if frappe.db.exists("UOM", "Nos"):
        return "Nos"
    return frappe.db.get_value("UOM", {}, "name")


def process_xero_invoice(xero_invoice_data, settings):
    """
    Creates or updates an ERPNext Sales/Purchase Invoice from Xero invoice data.

    Returns an outcome string for the sweep's tally: "synced" (created/updated),
    "skipped" (guard or duplicate), or "failed" (error already logged here).
    """
    xero_invoice_id = xero_invoice_data.get("InvoiceID")
    invoice_number = xero_invoice_data.get("InvoiceNumber")
    invoice_type = xero_invoice_data.get("Type")  # ACCREC or ACCPAY

    if not xero_invoice_id or not invoice_type:
        log_xero_error(
            message=f"Skipping Xero invoice due to missing ID or Type", status="Info"
        )
        return "skipped"

    # Respect per-entity direction toggle for inbound
    if invoice_type == "ACCREC" and not settings.get("sync_invoices_from_xero"):
        return "skipped"  # Sales Invoice inbound disabled
    if invoice_type == "ACCPAY" and not settings.get("sync_bills_from_xero"):
        return "skipped"  # Bills inbound disabled

    # A voided/deleted Xero invoice has no ledger effect and must not be
    # imported (same guard credit notes have always had). An ERPNext doc that
    # was already imported from it stays untouched here — voiding in ERPNext
    # is an operator decision surfaced by check_invoice_payments.
    xero_status = xero_invoice_data.get("Status", "DRAFT")
    if xero_status in ("VOIDED", "DELETED"):
        log_xero_error(
            message=f"Skipping Xero invoice {invoice_number}: Status is {xero_status}.",
            status="Info",
            xero_entity_id=xero_invoice_id,
            xero_entity_type="Invoice",
            direction="Xero to ERPNext",
        )
        return "skipped"

    # Determine ERPNext DocType
    erpnext_doctype = (
        "Sales Invoice" if invoice_type == "ACCREC" else "Purchase Invoice"
    )

    # Per-Xero-ID mutex preventing duplicate creation when the hourly task and
    # a manual sync overlap. One atomic SET NX EX: a get-then-set pair leaves a
    # window in which both workers see no lock and both proceed. Raw set/delete
    # skip the site prefix set_value applies, so scope the key by hand.
    cache = frappe.cache()
    lock_key = f"xero_inbound_lock:{getattr(frappe.local, 'site', 'site')}:{xero_invoice_id}"
    if not cache.set(lock_key, "1", nx=True, ex=INBOUND_LOCK_TTL_SECONDS):
        log_xero_error(
            message=f"Inbound sync for Xero Invoice {xero_invoice_id} already in progress — skipping duplicate.",
            status="Info",
            xero_entity_id=xero_invoice_id,
            direction="Xero to ERPNext",
        )
        return "skipped"
    try:
        return _process_xero_invoice_locked(
            xero_invoice_data, settings, erpnext_doctype,
            xero_invoice_id, invoice_number,
        )
    finally:
        # Every exit path must release the mutex — a leaked lock blocks retries
        # of this invoice until the TTL expires.
        cache.delete(lock_key)


def _process_xero_invoice_locked(
    xero_invoice_data, settings, erpnext_doctype, xero_invoice_id, invoice_number
):
    """Create/update one inbound invoice. Caller holds the per-invoice mutex."""
    erpnext_doc_name = frappe.db.get_value(
        erpnext_doctype, {"xero_invoice_id": xero_invoice_id}, "name"
    )

    # Get contact information
    xero_contact_id = xero_invoice_data.get("Contact", {}).get("ContactID")
    if not xero_contact_id:
        log_xero_error(
            message=f"Skipping Xero invoice {invoice_number}: No contact information",
            status="Info",
        )
        return "skipped"

    # Find corresponding ERPNext customer/supplier
    party_doctype = "Customer" if erpnext_doctype == "Sales Invoice" else "Supplier"
    party_name = frappe.db.get_value(
        party_doctype, {"xero_contact_id": xero_contact_id}, "name"
    )

    if not party_name:
        log_xero_error(
            message=f"Skipping Xero invoice {invoice_number}: {party_doctype} not found for Xero Contact {xero_contact_id}. Please sync contacts first.",
            status="Info",
            xero_entity_id=xero_invoice_id,
            xero_entity_type="Invoice",
        )
        return "skipped"

    try:
        # Get company - use default company
        company = frappe.defaults.get_global_default("company")
        if not company:
            # Get first company
            company = frappe.get_all("Company", limit=1, pluck="name")[0]

        # Map header fields
        posting_date = parse_xero_date(xero_invoice_data.get("Date"))
        due_date = parse_xero_date(xero_invoice_data.get("DueDate"))

        # Fall back to posting_date if Xero did not supply a DueDate
        if not due_date:
            due_date = posting_date
            if posting_date:
                log_xero_error(
                    message=(
                        f"Xero invoice {invoice_number} had no DueDate; "
                        f"defaulting due_date to posting_date {posting_date}."
                    ),
                    status="Warning",
                    xero_entity_id=xero_invoice_id,
                    xero_entity_type="Invoice",
                    erpnext_doc_type=erpnext_doctype,
                    direction="Xero to ERPNext",
                    category="Validation Errors",
                )

        # Clamp: ERPNext rejects due_date < posting_date. Some Xero invoices
        # (back-dated, immediate-payment, imported) have DueDate before Date.
        # Allow the sync to proceed by clamping due_date up to posting_date,
        # and surface the discrepancy on the dashboard via Xero Log.
        if due_date and posting_date and due_date < posting_date:
            log_xero_error(
                message=(
                    f"Xero invoice {invoice_number} had DueDate {due_date} "
                    f"before posting Date {posting_date}; clamping due_date "
                    f"to posting_date so the invoice can sync."
                ),
                status="Warning",
                xero_entity_id=xero_invoice_id,
                xero_entity_type="Invoice",
                erpnext_doc_type=erpnext_doctype,
                direction="Xero to ERPNext",
                category="Validation Errors",
            )
            due_date = posting_date

        # HI-8: Inbound invoices are created as DRAFT (docstatus=0) and must be
        # manually reviewed/submitted before check_invoice_payments (which
        # filters docstatus=1) will reconcile them. Labelling them "Synced"
        # while they sit in draft was dishonest and hid them from operators.
        # xero_sync_status is a Select with fixed options
        # (Pending/Synced/Error/Skipped), so we use "Pending" to mean
        # "imported, awaiting manual submission" rather than inventing an option
        # that would fail Select validation. We do NOT auto-submit. The status
        # is upgraded to "Synced" only on the UPDATE path for an
        # already-existing local doc (handled below).
        erpnext_data = {
            "xero_invoice_id": xero_invoice_id,
            "xero_sync_status": "Pending",
            "company": company,
            "posting_date": posting_date,
            "due_date": due_date,
            "currency": xero_invoice_data.get("CurrencyCode", "USD"),
            "conversion_rate": flt(xero_invoice_data.get("CurrencyRate", 1.0)),
            # Trust Xero's Date / DueDate as the source of truth for inbound
            # invoices. ignore_default_payment_terms_template=1 skips ERPNext's
            # validate_due_date() entirely (see accounts_controller.py:660-662),
            # and clearing payment_terms_template prevents set_payment_schedule()
            # from generating template-driven rows that would conflict with the
            # dates we just clamped above.
            "ignore_default_payment_terms_template": 1,
            "payment_terms_template": None,
        }

        # Add party-specific fields
        if erpnext_doctype == "Sales Invoice":
            erpnext_data["customer"] = party_name
            erpnext_data["customer_name"] = xero_invoice_data.get("Contact", {}).get(
                "Name"
            )
            # Get default debit_to account
            erpnext_data["debit_to"] = frappe.get_cached_value(
                "Company", company, "default_receivable_account"
            )
        else:  # Purchase Invoice
            erpnext_data["supplier"] = party_name
            erpnext_data["supplier_name"] = xero_invoice_data.get("Contact", {}).get(
                "Name"
            )
            # Get default credit_to account
            erpnext_data["credit_to"] = frappe.get_cached_value(
                "Company", company, "default_payable_account"
            )
            # bill_date: map from the already-parsed/clamped posting_date
            # (NOT a fresh parse of Xero Date). For Purchase Invoices, ERPNext
            # validates due_date against bill_date, not posting_date — so this
            # must use the same value we just clamped above.
            erpnext_data["bill_date"] = posting_date

        # Map reference fields
        reference = xero_invoice_data.get("Reference")
        if reference:
            if erpnext_doctype == "Sales Invoice":
                erpnext_data["po_no"] = reference
            else:
                erpnext_data["bill_no"] = reference

        # Always create as Draft; posting to the GL is maybe_submit_inbound's
        # decision (gated on the Xero status further down).
        erpnext_data["docstatus"] = 0

        # Store Xero invoice number in remarks field (title doesn't exist on Sales/Purchase Invoice)
        if invoice_number:
            erpnext_data["remarks"] = f"Xero Invoice: {invoice_number}"

        # Create or update invoice
        if erpnext_doc_name:
            # Update existing invoice
            doc = frappe.get_doc(erpnext_doctype, erpnext_doc_name)
            # An existing ERPNext invoice that is already submitted (1) or
            # cancelled (2) must NOT be rewritten from Xero: ERPNext rejects
            # editing submitted/cancelled docs, and regressing xero_sync_status
            # to "Pending" on them is invalid. Skip cleanly (Info, not Error).
            if doc.docstatus != 0:
                log_xero_error(
                    message=f"Xero Invoice {xero_invoice_id} ({invoice_number}) already exists as {erpnext_doctype} {erpnext_doc_name} (docstatus {doc.docstatus}); skipping update.",
                    status="Info",
                    category="Duplicate Entity",
                    xero_entity_id=xero_invoice_id,
                    xero_entity_type="Invoice",
                    erpnext_doc_type=erpnext_doctype,
                    erpnext_doc_name=erpnext_doc_name,
                    direction="Xero to ERPNext",
                )
                return "skipped"
            doc.update(erpnext_data)
            doc.save(ignore_permissions=True)
            log_message = f"Updated {erpnext_doctype} {erpnext_doc_name} from Xero Invoice {xero_invoice_id}"
        else:
            # Create new invoice
            doc = frappe.new_doc(erpnext_doctype)
            doc.update(erpnext_data)

            # Add line items. ERPNext rates are tax-exclusive, so Inclusive
            # Xero documents must have the per-line tax netted out — otherwise
            # the reconstructed taxes row double-counts it and the total
            # reconciliation below refuses the document.
            inclusive = xero_invoice_data.get("LineAmountTypes") == "Inclusive"
            line_items = xero_invoice_data.get("LineItems", [])
            for line in line_items:
                # Get item code if available
                item_code = get_or_create_item_from_xero_code(
                    line.get("ItemCode"), line.get("Description"), settings
                )

                # Get account mapping
                account = get_erpnext_account_from_xero_code(
                    line.get("AccountCode"), settings, erpnext_doctype
                )

                if not account:
                    # Skip line if account not mapped
                    log_xero_error(
                        message=f"Skipping line item in invoice {invoice_number}: No account mapping for Xero AccountCode {line.get('AccountCode')}",
                        status="Warning",
                        xero_entity_id=xero_invoice_id,
                        xero_entity_type="Invoice",
                        erpnext_doc_type=erpnext_doctype,
                        direction="Xero to ERPNext",
                        category="Mapping Errors",
                    )
                    continue

                # Build line item dict (rate always tax-exclusive)
                net_rate = inbound_line_rate(line, inclusive)
                item_dict = {
                    "description": line.get("Description", "Item from Xero"),
                    "qty": flt(line.get("Quantity", 1)),
                    "rate": net_rate,
                    "amount": flt(net_rate * flt(line.get("Quantity", 1))),
                }

                # Add item code if found. item_name is a 140-char field while
                # Xero descriptions run to 4000 — truncate; the full text is
                # kept in description.
                if item_code:
                    item_dict["item_code"] = item_code
                    item_dict["item_name"] = (line.get("Description") or "")[:140] or None
                else:
                    item_dict["item_name"] = (line.get("Description") or "Xero Item")[:140]
                    # C3: description-only lines (the normal shape of a
                    # hand-entered Xero invoice) have no Item to backfill the
                    # mandatory UOM from — without these two fields every such
                    # invoice failed with the bare MandatoryError "uom".
                    item_dict["uom"] = _default_uom()
                    item_dict["conversion_factor"] = 1

                # Add account
                if erpnext_doctype == "Sales Invoice":
                    item_dict["income_account"] = account
                else:
                    item_dict["expense_account"] = account

                # Add tax template if mapped
                tax_template = get_erpnext_tax_from_xero_type(
                    line.get("TaxType"), settings
                )
                if tax_template:
                    item_dict["item_tax_template"] = tax_template

                # Add discount if present
                discount_rate = flt(line.get("DiscountRate", 0))
                if discount_rate > 0:
                    item_dict["discount_percentage"] = discount_rate

                doc.append("items", item_dict)

            # Check if we have at least one line item
            if not doc.items:
                log_xero_error(
                    message=f"Skipping Xero invoice {invoice_number}: No valid line items (all skipped due to missing account mappings)",
                    status="Warning",
                    xero_entity_id=xero_invoice_id,
                    xero_entity_type="Invoice",
                    erpnext_doc_type=erpnext_doctype,
                    direction="Xero to ERPNext",
                    category="Mapping Errors",
                )
                return "skipped"

            # 6b: reconstruct tax so the ERPNext total matches Xero. Imported
            # invoices otherwise carry only net line amounts and omit VAT, which
            # posts an under-taxed invoice to the GL. Safe no-op when no tax
            # account can be resolved (6a then keeps the doc as a Draft).
            apply_inbound_taxes(doc, xero_invoice_data, erpnext_doctype)

            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created {erpnext_doctype} {erpnext_doc_name} from Xero Invoice {xero_invoice_id} ({invoice_number})"

        # ME-12 / 6a: Verify the ERPNext total matches the Xero Total. Account
        # mappings, skipped lines, tax-template gaps or discount handling can
        # silently shift the total. If it diverges beyond a 0.02 tolerance the
        # document must NOT be posted to the GL — posting an under-taxed invoice
        # is silent financial corruption. Flag it and leave it as a Draft below.
        xero_total = flt(xero_invoice_data.get("Total", 0))
        erpnext_total = flt(doc.get("grand_total"))
        totals_reconcile = not (xero_total and abs(erpnext_total - xero_total) > 0.02)
        if not totals_reconcile:
            log_xero_error(
                message=(
                    f"Total mismatch on inbound {erpnext_doctype} "
                    f"{erpnext_doc_name} (Xero Invoice {invoice_number}): "
                    f"ERPNext grand_total {erpnext_total} vs Xero Total "
                    f"{xero_total}. NOT auto-submitting; left as Draft for review."
                ),
                status="Error",
                xero_entity_id=xero_invoice_id,
                xero_entity_type="Invoice",
                erpnext_doc_type=erpnext_doctype,
                erpnext_doc_name=erpnext_doc_name,
                direction="Xero to ERPNext",
                category="Validation Errors",
            )

        # HI-4 (suspenders): stamp the data hash on the imported doc so the
        # outbound worker short-circuits on an unchanged inbound doc (belt is the
        # ignore_xero_sync flag on submit) and a LATER genuine ERPNext edit is
        # still detected as changed.
        frappe.db.set_value(
            doc.doctype, erpnext_doc_name, "xero_data_hash",
            compute_invoice_hash(doc), update_modified=False,
        )

        commit_checkpoint()

        # Opt-in: post the imported invoice to the GL when auto-submit is enabled
        # — but ONLY when the totals reconcile. An under-taxed or otherwise
        # divergent invoice is never posted automatically; it stays a Draft
        # (already committed above) for manual review.
        if totals_reconcile:
            maybe_submit_inbound(
                doc, settings, xero_invoice_id, "Invoice",
                xero_status=xero_invoice_data.get("Status"),
            )

        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type=erpnext_doctype,
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_invoice_id,
            xero_entity_type="Invoice",
            direction="Xero to ERPNext",
        )
        return "synced"

    except Exception as e:
        # Discard the failed insert's uncommitted writes FIRST — including the
        # naming-series increment doc.insert() already reserved. Without this,
        # the commit inside log_xero_error persisted the series bump and every
        # failed inbound attempt burned an ACC-SINV number.
        frappe.db.rollback()
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        # Check if this is an "already exists" type error (e.g. DocstatusTransitionError)
        # These are not real sync failures — the entity already exists and is synced
        if is_already_exists_error(str(e), error_traceback):
            # Don't mark as Error — the document already exists and is synced
            if erpnext_doc_name:
                frappe.db.set_value(
                    erpnext_doctype,
                    erpnext_doc_name,
                    "xero_sync_status",
                    "Synced",
                    update_modified=False,
                )
                commit_error_state()

            log_xero_error(
                message=f"Xero Invoice {xero_invoice_id} ({invoice_number}) already exists in ERPNext as {erpnext_doc_name or 'submitted document'}. Skipping update.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=erpnext_doctype,
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_invoice_id,
                xero_entity_type="Invoice",
                direction="Xero to ERPNext",
            )
            return "skipped"

        mark_sync_failure(
            erpnext_doctype,
            erpnext_doc_name,
            e,
            "Xero to ERPNext",
            source_type="Xero Invoice",
            source_id=xero_invoice_id,
            source_display=invoice_number,
            xero_entity_id=xero_invoice_id,
            xero_entity_type="Invoice",
            traceback_text=error_traceback,
        )
        return "failed"


# TODO: Implement Journal Entry sync
# TODO: Implement Credit Note sync
