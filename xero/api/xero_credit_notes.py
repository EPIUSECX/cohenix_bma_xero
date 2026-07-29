# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
from ..utils.transactions import commit_checkpoint, commit_error_state, commit_external_outcome
from frappe.utils import flt, getdate
import hashlib
import json
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff
from ..utils.sync_status import mark_sync_failure
from .xero_line_builder import build_xero_lines


# --- Validation Functions ---
# Line descriptions are validated inside xero_line_builder.build_xero_lines.


def validate_credit_note_number(cn_name):
    """
    Validate credit note number for Xero.
    Xero requires: max 255 chars, printable ASCII only
    ACCRECCREDIT must be unique in Xero.
    """
    if not cn_name:
        return None

    # Truncate to 255 chars
    cn_number = cn_name[:255]

    # Remove non-printable ASCII characters (keep 32-126)
    cn_number = "".join(c for c in cn_number if 32 <= ord(c) <= 126)

    return cn_number or None


def validate_credit_note_reference(reference):
    """
    Validate credit note reference for Xero.
    Xero requires: max 255 chars
    Note: Reference is only for ACCRECCREDIT (Sales Credit Notes)
    """
    if not reference:
        return None

    # Truncate to 255 chars
    reference = str(reference)[:255]

    return reference or None


def find_xero_credit_note_by_number(cn_number, cn_type):
    """
    HI-10: Self-healing lookup mirroring find_xero_invoice_by_number. Query
    Xero for an existing credit note with the given CreditNoteNumber, excluding
    VOIDED/DELETED. Returns the CreditNoteID for a SINGLE live match, else None.

    Used to recover a lost xero_credit_note_id: if a previous outbound POST
    succeeded on Xero but the local DB write crashed before committing the ID,
    a naive re-sync would create a DUPLICATE credit note. ACCRECCREDIT numbers
    are unique in Xero; ACCPAYCREDIT numbers are not, so matching is only safe
    for ACCRECCREDIT.
    """
    if not cn_number or cn_type != "ACCRECCREDIT":
        return None

    try:
        safe_number = str(cn_number).replace('"', "")
        response = xero_request(
            "GET",
            "CreditNotes",
            params={
                "where": (
                    f'CreditNoteNumber=="{safe_number}" '
                    'AND Status!="VOIDED" AND Status!="DELETED"'
                )
            },
        )
    except Exception:
        # Transient failure — treat as not found and let the create path run.
        return None

    credit_notes = (response or {}).get("CreditNotes") or []
    if len(credit_notes) == 1:
        matched = credit_notes[0]
        if matched.get("Status") in ("AUTHORISED", "DRAFT", "SUBMITTED"):
            return matched.get("CreditNoteID")
        return None
    return None


# --- Hash Functions for Change Detection ---


def compute_credit_note_hash(doc):
    """
    Compute MD5 hash of credit note data for change detection.
    """
    hash_data = {
        "posting_date": str(doc.posting_date),
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


def credit_note_data_changed(doc):
    """
    Check if credit note data has changed since last sync.
    Returns True if data has changed or no hash exists.
    """
    stored_hash = doc.get("xero_data_hash")
    if not stored_hash:
        return True

    current_hash = compute_credit_note_hash(doc)
    return current_hash != stored_hash


# --- Outbound Sync (ERPNext to Xero) ---


# doc_event handler: takes the Document the hook passes, so it is not
# HTTP-callable. Manual syncs go through xero.api.manual_sync instead.
def enqueue_sync_return(doc, method):
    """
    Enqueue background job to sync a return document (Credit Note) to Xero.

    ERPNext Sales Invoice (is_return=1) → Xero ACCRECCREDIT
    ERPNext Purchase Invoice (is_return=1) → Xero ACCPAYCREDIT
    """
    # HI-4: the inbound (Xero -> ERPNext) import sets this flag before submitting
    # an imported credit note, so this on_submit hook does not bounce it straight
    # back out to Xero as an update (echo loop).
    if getattr(doc.flags, "ignore_xero_sync", False):
        return
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_credit_notes"):
        return

    # Double-trigger guard: Only sync if not already synced or data has changed
    # This prevents infinite loops when syncing FROM Xero triggers on_submit
    if doc.get("xero_sync_status") == "Synced" and doc.get("xero_credit_note_id"):
        if not credit_note_data_changed(doc):
            log_xero_error(
                message=f"Skipping sync for {doc.doctype} {doc.name}: already synced and data unchanged",
                status="Info",
                erpnext_doc_type=doc.doctype,
                erpnext_doc_name=doc.name,
                category="System Monitoring",
            )
            return

    frappe.enqueue(
        "xero.api.xero_credit_notes.sync_return_to_xero",
        queue="short",
        timeout=600,
        enqueue_after_commit=True,
        doc_name=doc.name,
        doc_type=doc.doctype,
    )
    frappe.logger().info(
        f"Queued sync for return document {doc.name} to Xero.", "Xero Sync"
    )


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_return_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs a submitted ERPNext return document to Xero.

    - Sales Invoice with is_return=1 → Xero Credit Note (Type ACCRECCREDIT)
    - Purchase Invoice with is_return=1 → Xero Credit Note (Type ACCPAYCREDIT)

    Uses POST for both create and update (Xero API requirement).

    Ref: https://developer.xero.com/documentation/api/accounting/creditnotes
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return

    # Check per-entity directional toggle for outbound sync
    if not settings.get("sync_credit_notes_to_xero"):
        log_xero_error(
            message=f"Credit note outbound sync is disabled. Skipping {doc_type} {doc_name}.",
            status="Info",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            category="System Monitoring",
        )
        return

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_cn_id = doc.get("xero_credit_note_id")

        # --- Basic Validation ---
        if doc.docstatus != 1 or not doc.is_return:
            log_xero_error(
                f"Cannot sync non-submitted or non-return document: {doc_type} {doc_name}",
                status="Info",
            )
            return

        # --- Check if data has changed (for already synced credit notes) ---
        if xero_cn_id:
            if not credit_note_data_changed(doc):
                log_xero_error(
                    message=f"{doc_type} {doc_name} already synced and data unchanged. Skipping.",
                    status="Info",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=xero_cn_id,
                    xero_entity_type="CreditNote",
                    category="System Monitoring",
                )
                return

        # --- Determine Credit Note Type and Contact ---
        if doc_type == "Sales Invoice":
            cn_type = "ACCRECCREDIT"
            party_type = "Customer"
            party_name = doc.customer
        elif doc_type == "Purchase Invoice":
            cn_type = "ACCPAYCREDIT"
            party_type = "Supplier"
            party_name = doc.supplier
        else:
            return  # Not a return document we handle here

        # --- Get Linked Xero Contact ID ---
        xero_contact_id = frappe.db.get_value(party_type, party_name, "xero_contact_id")
        if not xero_contact_id:
            # Queue contact sync asynchronously
            frappe.logger().info(
                f"Xero Contact ID not found for {party_type} {party_name}. Queuing contact sync.",
                "Xero Sync",
            )

            from .xero_contacts import enqueue_sync_contact

            try:
                enqueue_sync_contact(party_name, party_type)
            except Exception as e:
                frappe.log_error(
                    f"Failed to queue contact sync: {str(e)}",
                    "Xero Contact Queue Error",
                )

            # Mark as pending prerequisites
            frappe.db.set_value(
                doc_type,
                doc_name,
                {"xero_sync_status": "Pending Prerequisites"},
                update_modified=False,
            )
            commit_checkpoint()

            log_xero_error(
                message=f"{doc_type} {doc_name} sync deferred: {party_type} {party_name} must be synced to Xero first.",
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="System Monitoring",
            )

            # Re-queue for later
            frappe.enqueue(
                "xero.api.xero_credit_notes.sync_return_to_xero",
                queue="short",
                timeout=600,
                doc_name=doc_name,
                doc_type=doc_type,
                enqueue_after_commit=True,
            )
            return

        # --- Map Line Items ---
        # Shared builder: per-line TaxType + explicit TaxAmount (never tax rows
        # as extra lines), rounding line, and a reconciliation check that
        # RAISES instead of warn-and-send. absolute=True because ERPNext stores
        # returns with negative quantities/amounts while Xero credit notes are
        # positive.
        built = build_xero_lines(doc, doc_type, settings, absolute=True)

        # --- Construct Credit Note Payload ---
        cn_payload = {
            "Type": cn_type,
            "Contact": {"ContactID": xero_contact_id},
            "Date": getdate(doc.posting_date).isoformat(),
            "LineItems": built.line_items,
            "CreditNoteNumber": validate_credit_note_number(doc.name),
            "Status": "AUTHORISED",
            "LineAmountTypes": built.line_amount_types,
        }

        # Add Reference field for ACCRECCREDIT only
        if cn_type == "ACCRECCREDIT":
            reference = validate_credit_note_reference(
                doc.get("remarks") or doc.get("po_no")
            )
            if reference:
                cn_payload["Reference"] = reference

        # --- HI-10: Self-healing recovery of a lost xero_credit_note_id ---
        # If we have no stored ID, ask Xero whether a credit note with this
        # CreditNoteNumber already exists (ACCRECCREDIT only). If so, attach it
        # so this becomes an UPDATE not a CREATE, preventing a duplicate when a
        # prior POST succeeded on Xero but failed to commit the ID locally.
        if not xero_cn_id and cn_type == "ACCRECCREDIT":
            recovered_id = find_xero_credit_note_by_number(
                cn_payload["CreditNoteNumber"], cn_type
            )
            if recovered_id:
                xero_cn_id = recovered_id
                # Persist immediately so any retry sees it.
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {"xero_credit_note_id": recovered_id},
                    update_modified=False,
                )
                commit_external_outcome()
                log_xero_error(
                    message=(
                        f"Recovered Xero CreditNoteID {recovered_id} for "
                        f"{doc_type} {doc_name} via CreditNoteNumber lookup. "
                        f"Switching from CREATE to UPDATE to avoid duplicating "
                        f"the credit note in Xero."
                    ),
                    status="Info",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=recovered_id,
                    xero_entity_type="CreditNote",
                    direction="ERPNext to Xero",
                    category="Duplicate Entity",
                )

        # If updating, include the Xero Credit Note ID
        if xero_cn_id:
            cn_payload["CreditNoteID"] = xero_cn_id

        # --- Make API Call (POST for both create and update) ---
        # Xero API: POST creates OR updates (if CreditNoteID provided, updates; otherwise creates)
        # idempotency: pass a stable key only when CREATING. On UPDATE the
        # CreditNoteID already targets the existing record; reusing a create key
        # across edits would wrongly dedup legitimate edits within Xero's 24h
        # window.
        idempotency_key = None
        if not xero_cn_id:
            idempotency_key = f"{doc_type}:{doc_name}:create-credit-note"
        response = xero_request(
            "POST",
            "CreditNotes",
            data={"CreditNotes": [cn_payload]},
            idempotency_key=idempotency_key,
        )

        # --- Process Response ---
        if response and response.get("CreditNotes"):
            updated_cn = response["CreditNotes"][0]
            new_xero_id = updated_cn.get("CreditNoteID")

            if new_xero_id:
                # HI-10: id-first commit ordering. Commit xero_credit_note_id to
                # the DB FIRST and unconditionally, BEFORE computing/writing the
                # data hash. If a later step raises, a retry will see the ID
                # already present, send it as CreditNoteID, and Xero will UPDATE
                # the existing credit note rather than CREATE a duplicate.
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {"xero_credit_note_id": new_xero_id},
                    update_modified=False,
                )
                commit_external_outcome()

                # Compute hash for change detection
                data_hash = compute_credit_note_hash(doc)

                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {
                        "xero_credit_note_id": new_xero_id,
                        "xero_sync_status": "Synced",
                        "xero_data_hash": data_hash,
                    },
                    update_modified=False,
                )
                commit_external_outcome()

                log_xero_error(
                    message=f"Successfully synced {doc_type} (Return) {doc_name} to Xero.",
                    status="Success",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=new_xero_id,
                    xero_entity_type="CreditNote",
                    direction="ERPNext to Xero",
                )
            else:
                raise Exception("Xero API response did not contain a CreditNoteID.")
        else:
            raise Exception("Invalid response received from Xero CreditNotes API.")

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        # Check if this is an "already exists" type error from Xero API
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
                message=f"{doc_type} (Return) {doc_name} already exists in Xero. No action needed.",
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


# --- Void/Delete Functions ---


def enqueue_void_credit_note(doc, method):
    """
    Enqueue background job to void a cancelled credit note in Xero.
    Called from on_cancel hook for return documents.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_credit_notes"):
        return

    frappe.enqueue(
        "xero.api.xero_credit_notes.void_credit_note_in_xero",
        queue="short",
        enqueue_after_commit=True,
        doc_name=doc.name,
        doc_type=doc.doctype,
    )
    frappe.logger().info(
        f"Queued void for {doc.doctype} {doc.name} in Xero.", "Xero Sync"
    )


def void_credit_note_in_xero(doc_name, doc_type):
    """
    Finds the corresponding Xero credit note and voids or deletes it.

    - DRAFT credit notes can be DELETED
    - AUTHORISED credit notes can be VOIDED (if no payments applied)
    """
    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_cn_id = doc.get("xero_credit_note_id")

        if not xero_cn_id:
            log_xero_error(
                f"Cannot void credit note {doc_name}: Xero Credit Note ID not found.",
                status="Info",
            )
            return

        # First, get the current status from Xero
        try:
            xero_data = xero_request("GET", f"CreditNotes/{xero_cn_id}")
            if not xero_data or not xero_data.get("CreditNotes"):
                log_xero_error(
                    message=f"Could not fetch Xero credit note {xero_cn_id} for void/delete",
                    status="Warning",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=xero_cn_id,
                )
                return

            xero_cn = xero_data["CreditNotes"][0]
            xero_status = xero_cn.get("Status")
        except Exception as fetch_error:
            log_xero_error(
                message=f"Error fetching Xero credit note status: {str(fetch_error)}",
                status="Warning",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=xero_cn_id,
            )
            # Default to VOIDED if we can't fetch status
            xero_status = "AUTHORISED"

        # Determine the appropriate status change
        # DRAFT or SUBMITTED → DELETED
        # AUTHORISED → VOIDED
        if xero_status in ["DRAFT", "SUBMITTED"]:
            new_status = "DELETED"
            action = "delete"
        else:
            new_status = "VOIDED"
            action = "void"

        cn_payload = {"CreditNoteID": xero_cn_id, "Status": new_status}

        # Xero API for voiding/deleting is a POST to the CreditNotes endpoint
        response = xero_request(
            "POST", "CreditNotes", data={"CreditNotes": [cn_payload]}
        )

        if response and response.get("CreditNotes"):
            frappe.db.set_value(
                doc_type,
                doc_name,
                "xero_sync_status",
                f"{action.capitalize()}d in Xero",
                update_modified=False,
            )
            commit_external_outcome()
            log_xero_error(
                message=f"Successfully {action}d {doc_type} {doc_name} in Xero (status: {new_status}).",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=xero_cn_id,
                xero_entity_type="CreditNote",
                direction="ERPNext to Xero",
            )
        else:
            raise Exception(
                "Invalid response received from Xero when voiding/deleting credit note."
            )

    except Exception as e:
        log_xero_error(
            message=f"Failed to void/delete {doc_type} {doc_name} in Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback(),
        )


# --- Inbound Sync (Xero to ERPNext) ---


def sync_credit_notes_from_xero(modified_since=None):
    """
    Fetches credit notes from Xero and creates/updates corresponding
    return invoices in ERPNext.

    Args:
        modified_since: ISO date string to fetch only recent credit notes
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return

    # Check per-entity directional toggle for inbound sync
    if not settings.get("sync_credit_notes_from_xero"):
        log_xero_error(
            message="Credit note inbound sync is disabled. Skipping credit notes from Xero.",
            status="Info",
            category="System Monitoring",
        )
        return

    if not settings.get("sync_credit_notes"):
        return

    # Incremental sync: fetch only credit notes changed since the last
    # successful run. An explicit modified_since argument overrides the stored
    # watermark. Xero ignores a ModifiedSince query param — the value must go in
    # the If-Modified-Since header via modified_since= on the GET.
    from ..utils.xero_client import (
        incremental_since,
        commit_watermark,
        start_incremental_run,
    )

    watermark_key = "credit_notes"
    run_started_at = start_incremental_run()
    if_modified_since = modified_since or incremental_since(watermark_key)

    try:
        page = 1
        params = {"page": page}

        while True:
            frappe.logger().info(f"Fetching Xero Credit Notes page {page}", "Xero Sync")
            response = xero_request(
                "GET", "CreditNotes", params=params, modified_since=if_modified_since
            )

            if not response or not response.get("CreditNotes"):
                break

            credit_notes = response["CreditNotes"]
            if not credit_notes:
                break

            for cn_data in credit_notes:
                try:
                    process_xero_credit_note(cn_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Credit Note ID {cn_data.get('CreditNoteID')}",
                        xero_entity_id=cn_data.get("CreditNoteID"),
                        xero_entity_type="CreditNote",
                        error_details=frappe.get_traceback(),
                    )

            if len(credit_notes) < 100:
                break
            page += 1
            params["page"] = page

        # Only advance the watermark after a fully successful sweep — if an
        # exception aborted the loop, the next run re-fetches from the old
        # watermark so nothing is missed.
        commit_watermark(watermark_key, run_started_at)
        log_xero_error(
            message="Finished syncing credit notes from Xero.", status="Info"
        )

    except Exception as e:
        log_xero_error(
            message="Error during sync_credit_notes_from_xero",
            error_details=frappe.get_traceback(),
        )


def _apply_credit_note_allocations(
    xero_cn_data, erpnext_doctype, erpnext_doc_name, cn_number, xero_cn_id
):
    """
    HI-13: Apply a Xero credit note's Allocations against the referenced
    ERPNext invoice(s) so outstanding balances do not drift.

    Previously the allocation data was only stringified into the credit note's
    remarks; the credit was never applied to the original invoice, so the
    invoice's outstanding_amount stayed too high forever.

    Approach (partial, by design — see LIMITATION below):
      - For each Xero Allocation, resolve the referenced Xero invoice to its
        ERPNext document via xero_invoice_id.
      - When found, record the linkage on the credit-note doc's remarks in a
        machine-parseable form AND emit an explicit, actionable log row naming
        the ERPNext invoice, the credit note, and the amount to apply.

    LIMITATION (needs human follow-up): full reconciliation (creating the
    Journal Entry / running reconcile_against_document, or appending the credit
    note to the invoice's references) requires BOTH the credit note return doc
    AND the target invoice to be SUBMITTED in ERPNext. Inbound docs are created
    as DRAFT (HI-8) and are not auto-submitted, so we cannot post the
    allocation here without violating that policy. We therefore create the
    linkage data + a clear operator instruction; an operator (or a future
    submit-time hook) must perform the actual reconciliation. If the referenced
    invoice is not yet in ERPNext, we log a Warning so it is not lost.
    """
    allocations = xero_cn_data.get("Allocations") or []
    if not allocations:
        return

    invoice_doctype = (
        "Sales Invoice" if erpnext_doctype == "Sales Invoice" else "Purchase Invoice"
    )

    linkages = []
    for alloc in allocations:
        alloc_invoice = (alloc or {}).get("Invoice", {}) or {}
        alloc_amount = flt(alloc.get("Amount", 0))
        xero_inv_id = alloc_invoice.get("InvoiceID")
        xero_inv_number = alloc_invoice.get("InvoiceNumber", "Unknown")

        target_invoice = None
        if xero_inv_id:
            target_invoice = frappe.db.get_value(
                invoice_doctype, {"xero_invoice_id": xero_inv_id}, "name"
            )

        if not target_invoice:
            log_xero_error(
                message=(
                    f"Credit note {cn_number} allocates {alloc_amount} to Xero "
                    f"invoice {xero_inv_number} ({xero_inv_id}), but that "
                    f"invoice is not yet in ERPNext. The credit cannot be "
                    f"applied; sync the invoice and reconcile manually so the "
                    f"outstanding balance is correct."
                ),
                status="Warning",
                xero_entity_id=xero_cn_id,
                xero_entity_type="CreditNote",
                erpnext_doc_type=erpnext_doctype,
                erpnext_doc_name=erpnext_doc_name,
                direction="Xero to ERPNext",
                category="Missing Prerequisites",
            )
            continue

        linkages.append(
            {
                "erpnext_invoice": target_invoice,
                "amount": alloc_amount,
                "xero_invoice_number": xero_inv_number,
            }
        )
        log_xero_error(
            message=(
                f"Credit note {cn_number} ({erpnext_doctype} "
                f"{erpnext_doc_name}) should apply {alloc_amount} against "
                f"{invoice_doctype} {target_invoice} (Xero invoice "
                f"{xero_inv_number}). Linkage recorded; submit both documents "
                f"and reconcile to clear the outstanding balance (HI-13: full "
                f"auto-reconciliation not yet implemented)."
            ),
            status="Warning",
            xero_entity_id=xero_cn_id,
            xero_entity_type="CreditNote",
            erpnext_doc_type=erpnext_doctype,
            erpnext_doc_name=erpnext_doc_name,
            direction="Xero to ERPNext",
            category="Validation Errors",
        )

    # Persist a machine-parseable linkage record on the doc so a later
    # submit-time hook (or operator) can act on it. We store it as JSON inside
    # remarks alongside the human-readable summary already written above.
    if linkages:
        try:
            existing_remarks = (
                frappe.db.get_value(erpnext_doctype, erpnext_doc_name, "remarks")
                or ""
            )
            linkage_blob = json.dumps({"xero_credit_allocations": linkages})
            new_remarks = f"{existing_remarks}\n[XERO_CREDIT_LINKAGE] {linkage_blob}"
            frappe.db.set_value(
                erpnext_doctype,
                erpnext_doc_name,
                "remarks",
                new_remarks,
                update_modified=False,
            )
        except Exception:
            # Linkage persistence is best-effort; the explicit Warning logs
            # above are the authoritative operator signal.
            pass


def process_xero_credit_note(xero_cn_data, settings):
    """
    Creates or updates an ERPNext return invoice from Xero credit note data.

    Xero ACCRECCREDIT → ERPNext Sales Invoice (is_return=1)
    Xero ACCPAYCREDIT → ERPNext Purchase Invoice (is_return=1)
    """
    from .xero_invoices import (
        parse_xero_date,
        get_or_create_item_from_xero_code,
        get_erpnext_account_from_xero_code,
        get_erpnext_tax_from_xero_type,
    )

    xero_cn_id = xero_cn_data.get("CreditNoteID")
    cn_number = xero_cn_data.get("CreditNoteNumber")
    cn_type = xero_cn_data.get("Type")  # ACCRECCREDIT or ACCPAYCREDIT
    cn_status = xero_cn_data.get("Status", "DRAFT")
    remaining_credit = flt(xero_cn_data.get("RemainingCredit", 0))
    allocations = xero_cn_data.get("Allocations", [])

    if not xero_cn_id or not cn_type:
        log_xero_error(
            message=f"Skipping Xero credit note due to missing ID or Type",
            status="Info",
        )
        return

    # Skip VOIDED or DELETED credit notes
    if cn_status in ["VOIDED", "DELETED"]:
        log_xero_error(
            message=f"Skipping Xero credit note {cn_number}: Status is {cn_status}",
            status="Info",
            xero_entity_id=xero_cn_id,
            xero_entity_type="CreditNote",
        )
        return

    # Determine ERPNext DocType
    erpnext_doctype = (
        "Sales Invoice" if cn_type == "ACCRECCREDIT" else "Purchase Invoice"
    )

    # Check if credit note already exists
    erpnext_doc_name = frappe.db.get_value(
        erpnext_doctype, {"xero_credit_note_id": xero_cn_id}, "name"
    )

    # Get contact information
    xero_contact_id = xero_cn_data.get("Contact", {}).get("ContactID")
    if not xero_contact_id:
        log_xero_error(
            message=f"Skipping Xero credit note {cn_number}: No contact information",
            status="Info",
        )
        return

    # Find corresponding ERPNext customer/supplier
    party_doctype = "Customer" if cn_type == "ACCRECCREDIT" else "Supplier"
    party_name = frappe.db.get_value(
        party_doctype, {"xero_contact_id": xero_contact_id}, "name"
    )

    if not party_name:
        log_xero_error(
            message=f"Skipping Xero credit note {cn_number}: {party_doctype} not found for Xero Contact {xero_contact_id}",
            status="Info",
            xero_entity_id=xero_cn_id,
            xero_entity_type="CreditNote",
        )
        return

    try:
        # Get company
        company = frappe.defaults.get_global_default("company")
        if not company:
            company = frappe.get_all("Company", limit=1, pluck="name")[0]

        # Build remarks with allocation info
        remarks_parts = [
            f"Xero Credit Note: {cn_number}" if cn_number else "Xero Credit Note"
        ]
        if remaining_credit > 0:
            remarks_parts.append(f"Remaining Credit: {remaining_credit}")
        if allocations:
            alloc_info = ", ".join(
                [
                    f"{a.get('Invoice', {}).get('InvoiceNumber', 'Unknown')}: {a.get('Amount', 0)}"
                    for a in allocations
                ]
            )
            remarks_parts.append(f"Allocations: {alloc_info}")
        remarks = " | ".join(remarks_parts)

        # HI-13: resolve the original ERPNext invoice this credit note returns
        # against (ERPNext's structural link for returns). We use the first Xero
        # allocation whose invoice exists and is already submitted in ERPNext —
        # return_against must point to a submitted invoice. When set and the
        # credit note is later submitted (manually, or via auto_submit_inbound),
        # ERPNext posts the credit and adjusts the original's outstanding.
        return_against = None
        for alloc in allocations:
            _inv = (alloc or {}).get("Invoice", {}) or {}
            _xinv_id = _inv.get("InvoiceID")
            if _xinv_id:
                _cand = frappe.db.get_value(
                    erpnext_doctype,
                    {"xero_invoice_id": _xinv_id, "docstatus": 1},
                    "name",
                )
                if _cand:
                    return_against = _cand
                    break

        # ME-5 consistency: default currency to the company base currency, not a
        # hardcoded "USD", and only force rate 1.0 when currencies actually match.
        company_currency = frappe.get_cached_value("Company", company, "default_currency")
        cn_currency = xero_cn_data.get("CurrencyCode") or company_currency
        cn_rate = flt(xero_cn_data.get("CurrencyRate")) or None
        if not cn_rate:
            if cn_currency == company_currency:
                cn_rate = 1.0
            else:
                from erpnext.setup.utils import get_exchange_rate
                cn_rate = get_exchange_rate(
                    cn_currency, company_currency, parse_xero_date(xero_cn_data.get("Date"))
                )

        # Map header fields.
        # HI-8: Inbound credit notes are created as DRAFT (docstatus=0). When
        # auto_submit_inbound is OFF (default) they stay Draft for manual review
        # (status "Pending"); when ON they are submitted below. xero_sync_status
        # is a Select (Pending/Synced/Error/Skipped); "Pending" means "imported,
        # awaiting submission".
        erpnext_data = {
            "xero_credit_note_id": xero_cn_id,
            "xero_sync_status": "Pending",
            "is_return": 1,  # Mark as return invoice
            "company": company,
            "posting_date": parse_xero_date(xero_cn_data.get("Date")),
            "currency": cn_currency,
            "conversion_rate": cn_rate,
            "remarks": remarks,
        }
        if return_against:
            erpnext_data["return_against"] = return_against

        # Add party-specific fields
        if erpnext_doctype == "Sales Invoice":
            erpnext_data["customer"] = party_name
            erpnext_data["customer_name"] = xero_cn_data.get("Contact", {}).get("Name")
            erpnext_data["debit_to"] = frappe.get_cached_value(
                "Company", company, "default_receivable_account"
            )
        else:  # Purchase Invoice
            erpnext_data["supplier"] = party_name
            erpnext_data["supplier_name"] = xero_cn_data.get("Contact", {}).get("Name")
            erpnext_data["credit_to"] = frappe.get_cached_value(
                "Company", company, "default_payable_account"
            )

        # Create or update credit note
        if erpnext_doc_name:
            # Update existing
            doc = frappe.get_doc(erpnext_doctype, erpnext_doc_name)
            # A submitted (1) or cancelled (2) return cannot be rewritten from
            # Xero — ERPNext blocks editing it, and regressing xero_sync_status
            # to "Pending" on a submitted doc is invalid. Skip cleanly.
            if doc.docstatus != 0:
                log_xero_error(
                    message=f"Xero Credit Note {cn_number} already exists as {erpnext_doctype} {erpnext_doc_name} (docstatus {doc.docstatus}); skipping update.",
                    status="Info",
                    category="Duplicate Entity",
                    xero_entity_id=xero_cn_id,
                    xero_entity_type="CreditNote",
                    erpnext_doc_type=erpnext_doctype,
                    erpnext_doc_name=erpnext_doc_name,
                    direction="Xero to ERPNext",
                )
                return
            doc.update(erpnext_data)
            doc.save(ignore_permissions=True)
            log_message = f"Updated {erpnext_doctype} (Return) {erpnext_doc_name} from Xero Credit Note {xero_cn_id}"
        else:
            # Create new
            doc = frappe.new_doc(erpnext_doctype)
            doc.update(erpnext_data)

            # Add line items. Inclusive Xero documents carry gross amounts, so
            # net the per-line tax out of the rate (the taxes row below carries
            # the tax) — same treatment as inbound invoices.
            from .xero_line_builder import apply_inbound_taxes, inbound_line_rate

            inclusive = xero_cn_data.get("LineAmountTypes") == "Inclusive"
            line_items = xero_cn_data.get("LineItems", [])
            for line in line_items:
                item_code = get_or_create_item_from_xero_code(
                    line.get("ItemCode"), line.get("Description"), settings
                )
                account = get_erpnext_account_from_xero_code(
                    line.get("AccountCode"), settings
                )

                if not account:
                    log_xero_error(
                        message=f"Skipping line item in credit note {cn_number}: No account mapping for Xero AccountCode {line.get('AccountCode')}",
                        status="Warning",
                        xero_entity_id=xero_cn_id,
                        xero_entity_type="CreditNote",
                    )
                    continue

                # For credit notes, quantities should be negative in ERPNext
                net_rate = inbound_line_rate(line, inclusive)
                qty = abs(flt(line.get("Quantity", 1)))
                item_dict = {
                    "description": line.get("Description", "Item from Xero"),
                    "qty": -qty,  # Negative for return
                    "rate": net_rate,
                    "amount": -abs(flt(net_rate * qty)),  # Negative for return
                }

                # item_name is a 140-char field; Xero descriptions run to 4000.
                if item_code:
                    item_dict["item_code"] = item_code
                    item_dict["item_name"] = (line.get("Description") or "")[:140] or None
                else:
                    item_dict["item_name"] = (line.get("Description") or "Xero Item")[:140]
                    # C3: description-only lines have no Item to backfill the
                    # mandatory UOM from; without these the insert fails with
                    # the bare MandatoryError "uom".
                    from .xero_invoices import _default_uom

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

            if not doc.items:
                log_xero_error(
                    message=f"Skipping Xero credit note {cn_number}: No valid line items",
                    status="Warning",
                    xero_entity_id=xero_cn_id,
                    xero_entity_type="CreditNote",
                )
                return

            # Reconstruct Xero's tax as a negative Actual charge so the return's
            # |grand_total| matches Xero's Total (the reconcile guard below
            # otherwise refuses to post it).
            apply_inbound_taxes(doc, xero_cn_data, erpnext_doctype, sign=-1)

            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created {erpnext_doctype} (Return) {erpnext_doc_name} from Xero Credit Note {xero_cn_id} ({cn_number})"

        # ME-12: Verify the ERPNext document total matches the Xero Total.
        # Credit notes carry Total as a positive figure in Xero; the ERPNext
        # return doc grand_total is negative, so compare magnitudes. Warn (do
        # not block) on divergence beyond a 0.02 tolerance.
        # 6a: if the ERPNext total diverges from Xero beyond tolerance (e.g. tax
        # could not be reconstructed), do NOT post to the GL — leave it Draft and
        # flag it. Posting an under-taxed credit note is silent GL corruption.
        xero_total = flt(xero_cn_data.get("Total", 0))
        erpnext_total = abs(flt(doc.get("grand_total")))
        totals_reconcile = not (xero_total and abs(erpnext_total - abs(xero_total)) > 0.02)
        if not totals_reconcile:
            log_xero_error(
                message=(
                    f"Total mismatch on inbound credit note {erpnext_doctype} "
                    f"{erpnext_doc_name} (Xero CN {cn_number}): ERPNext "
                    f"|grand_total| {erpnext_total} vs Xero |Total| "
                    f"{abs(xero_total)}. NOT auto-submitting; left as Draft for review."
                ),
                status="Error",
                xero_entity_id=xero_cn_id,
                xero_entity_type="CreditNote",
                erpnext_doc_type=erpnext_doctype,
                erpnext_doc_name=erpnext_doc_name,
                direction="Xero to ERPNext",
                category="Validation Errors",
            )

        # HI-13: Apply the Xero credit-note Allocations against the referenced
        # ERPNext invoice(s) so outstanding balances do not drift.
        _apply_credit_note_allocations(
            xero_cn_data,
            erpnext_doctype,
            erpnext_doc_name,
            cn_number,
            xero_cn_id,
        )

        # HI-4 (suspenders): stamp the data hash on the imported credit note so
        # the outbound worker short-circuits on an unchanged inbound doc and a
        # LATER genuine ERPNext edit is still detected as changed.
        frappe.db.set_value(
            doc.doctype, erpnext_doc_name, "xero_data_hash",
            compute_credit_note_hash(doc), update_modified=False,
        )

        commit_checkpoint()

        # Opt-in: post the imported credit note to the GL when auto-submit is
        # enabled. With return_against set above, submitting reconciles the
        # credit against the original invoice. Draft is already committed, so a
        # failed submit leaves it as Draft for manual review.
        from .xero_invoices import maybe_submit_inbound

        # Only auto-post when the totals reconcile (see 6a above).
        if totals_reconcile:
            maybe_submit_inbound(
                doc, settings, xero_cn_id, "CreditNote", xero_status=cn_status
            )

        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type=erpnext_doctype,
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_cn_id,
            xero_entity_type="CreditNote",
            direction="Xero to ERPNext",
        )

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        # Check if this is an "already exists" type error (e.g. DocstatusTransitionError)
        if is_already_exists_error(str(e), error_traceback):
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
                message=f"Xero Credit Note {xero_cn_id} ({cn_number}) already exists in ERPNext as {erpnext_doc_name or 'submitted document'}. Skipping update.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=erpnext_doctype
                if "erpnext_doctype" in locals()
                else None,
                erpnext_doc_name=erpnext_doc_name
                if "erpnext_doc_name" in locals()
                else None,
                xero_entity_id=xero_cn_id,
                xero_entity_type="CreditNote",
                direction="Xero to ERPNext",
            )
        else:
            mark_sync_failure(
                erpnext_doctype,
                erpnext_doc_name,
                e,
                "Xero to ERPNext",
                source_type="Xero Credit Note",
                source_id=xero_cn_id,
                source_display=cn_number,
                xero_entity_id=xero_cn_id,
                xero_entity_type="CreditNote",
                traceback_text=error_traceback,
            )
