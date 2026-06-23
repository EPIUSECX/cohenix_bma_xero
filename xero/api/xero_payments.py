# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, flt, now
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff

# --- Payment Sync (ERPNext to Xero) ---


@frappe.whitelist()
def enqueue_sync_payment(doc, method):
    """Enqueue background job to sync a Payment Entry to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_payments"):
        return

    frappe.enqueue(
        "xero.api.xero_payments.sync_payment_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        doc_name=doc.name,
        doc_type=doc.doctype,
    )
    frappe.logger().info(
        f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync"
    )


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_payment_to_xero(doc_name, doc_type="Payment Entry", **kwargs):
    """
    Enhanced payment sync that handles multiple invoice payments and reconciliation.
    Syncs a submitted ERPNext Payment Entry to Xero as Payment or Bank Transaction.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return  # Master switch disabled

    # Check per-entity directional toggle for outbound sync
    if not settings.get("sync_payments_to_xero"):
        log_xero_error(
            message=f"Payment outbound sync is disabled. Skipping {doc_type} {doc_name}.",
            status="Info",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            category="System Monitoring",
        )
        return

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_payment_id = doc.get("xero_payment_id")

        # --- Basic Validation ---
        if doc.docstatus != 1:
            log_xero_error(
                f"Cannot sync non-submitted document: {doc_type} {doc_name}",
                status="Info",
            )
            return

        # --- Get Xero Contact ID ---
        xero_contact_id = frappe.db.get_value(
            doc.party_type, doc.party, "xero_contact_id"
        )
        if not xero_contact_id:
            # Attempt to sync the contact first
            frappe.logger().info(
                f"Xero Contact ID not found for {doc.party_type} {doc.party}. Attempting to sync contact first.",
                "Xero Sync",
            )
            from .xero_contacts import sync_contact_to_xero

            try:
                sync_contact_to_xero(doc.party, doc.party_type)
                xero_contact_id = frappe.db.get_value(
                    doc.party_type, doc.party, "xero_contact_id"
                )
                if not xero_contact_id:
                    raise Exception(
                        f"Failed to sync and retrieve Xero Contact ID for {doc.party_type} {doc.party}."
                    )
            except Exception as contact_sync_e:
                raise Exception(
                    f"Prerequisite failed: Could not sync {doc.party_type} {doc.party} to Xero. Error: {contact_sync_e}"
                )

        # --- Get Xero Bank Account ID ---
        bank_account = doc.paid_from if doc.payment_type == "Pay" else doc.paid_to
        xero_bank_account_id = frappe.db.get_value(
            "Account", bank_account, "xero_account_id"
        )
        if not xero_bank_account_id:
            raise Exception(
                f"Xero Account ID not found for Bank Account: {bank_account}. Please sync Chart of Accounts first."
            )

        # --- Determine Payment Type and Process ---
        if doc.references and len(doc.references) > 0:
            # This is a payment against invoice(s)
            sync_invoice_payments(doc, xero_bank_account_id, doc_type, doc_name)
        else:
            # This is a standalone payment (advance payment, etc.)
            sync_standalone_payment(
                doc, xero_contact_id, xero_bank_account_id, doc_type, doc_name
            )

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
                frappe.db.commit()

            log_xero_error(
                message=f"{doc_type} {doc_name} already exists in Xero. No action needed.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                direction="ERPNext to Xero",
            )
        else:
            from ..utils.logging import format_sync_error_message

            # Genuine sync error
            if doc_name and doc_type:
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {"xero_sync_status": "Error"},
                    update_modified=False,
                )
                frappe.db.commit()

            user_message = format_sync_error_message(
                doc_type, doc_name, doc_name, "ERPNext to Xero", e
            )

            log_xero_error(
                message=user_message,
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                error_details=error_traceback,
                direction="ERPNext to Xero",
            )


def _load_payment_idempotency_map(doc_type, doc_name):
    """
    Read xero_payment_data and decode it into a dict
    {invoice_id: payment_id} for fast idempotency lookups.

    Tolerates legacy storage formats:
      - new format: JSON object {"<invoice_id>": "<payment_id>", ...}
      - legacy v2:  JSON list   [{"invoice_id": "...", "payment_id": "..."}]
      - legacy v1:  raw string  "<single_payment_id>" (no invoice mapping)

    Legacy formats produce a best-effort map. The legacy v1 string cannot be
    mapped back to an invoice, so it is preserved on xero_payment_id but not
    used to short-circuit re-sync.
    """
    raw = frappe.db.get_value(doc_type, doc_name, "xero_payment_data")
    if not raw:
        return {}
    try:
        import json

        decoded = json.loads(raw)
    except (ValueError, TypeError):
        # legacy v1: bare string PaymentID, no invoice mapping
        return {}

    if isinstance(decoded, dict):
        return {str(k): str(v) for k, v in decoded.items() if k and v}
    if isinstance(decoded, list):
        # legacy v2: list of {invoice_id, payment_id, amount}
        out = {}
        for entry in decoded:
            if isinstance(entry, dict):
                inv = entry.get("invoice_id")
                pay = entry.get("payment_id")
                if inv and pay:
                    out[str(inv)] = str(pay)
        return out
    return {}


def _save_payment_idempotency_map(doc_type, doc_name, idemp_map):
    """
    Persist the {invoice_id: payment_id} map to xero_payment_data and mirror
    the first payment_id onto xero_payment_id for backward-compatible
    dashboard display. Commits immediately so a retry sees the map.
    """
    import json

    primary_payment_id = next(iter(idemp_map.values())) if idemp_map else None
    frappe.db.set_value(
        doc_type,
        doc_name,
        {
            "xero_payment_id": primary_payment_id,
            "xero_payment_data": json.dumps(idemp_map) if idemp_map else None,
            "xero_sync_status": "Synced" if idemp_map else "Pending",
            "xero_last_sync": now(),
        },
        update_modified=False,
    )
    frappe.db.commit()


def _xero_payment_exists_for_invoice(xero_invoice_id):
    """
    Defensive check: query Xero directly to see if there is already an
    AUTHORISED payment against this invoice. Used as a backstop when our
    local idempotency map is empty (e.g. the map was never written because
    a previous attempt crashed between the Xero-side success and the local
    DB commit).

    Returns the existing PaymentID string if found, else None.

    Per Xero API spec, payments can be filtered with
    where=Invoice.InvoiceID=guid("...") AND Status="AUTHORISED".
    """
    if not xero_invoice_id:
        return None
    try:
        params = {
            "where": (
                f'Invoice.InvoiceID=guid("{xero_invoice_id}") '
                'AND Status="AUTHORISED"'
            )
        }
        response = xero_request("GET", "Payments", params=params)
        payments = (response or {}).get("Payments") or []
        if payments:
            # Return first AUTHORISED payment ID; multi-payment cases are
            # rare and an existing payment is sufficient evidence of dedup.
            return payments[0].get("PaymentID")
    except Exception:
        # Best-effort: if the lookup fails, we fall through and let the
        # caller proceed with normal PUT. Xero will reject genuine
        # duplicates with an outstanding-amount error, which is safer
        # than blocking sync on a transient lookup failure.
        return None
    return None


def sync_invoice_payments(doc, xero_bank_account_id, doc_type, doc_name):
    """
    Handle payments against specific invoices, idempotently.

    Strategy:
      1. Load the {xero_invoice_id: xero_payment_id} idempotency map from
         xero_payment_data. Any reference whose invoice already has a
         payment ID in this map is skipped (no second PUT).
      2. For references not in the map, defensively query Xero
         (GET /Payments?where=Invoice.InvoiceID=...) before creating, so a
         crash between Xero-side success and local DB commit on a previous
         attempt does not produce a duplicate Xero payment.
      3. Persist the map after EACH successful PUT, before processing the
         next reference. This means a partial failure mid-loop leaves a
         consistent map; the retry only re-attempts unsynced references.
    """
    idemp_map = _load_payment_idempotency_map(doc_type, doc_name)
    initial_map_size = len(idemp_map)

    for reference in doc.references:
        if reference.allocated_amount <= 0:
            continue

        invoice_doctype = reference.reference_doctype
        invoice_name = reference.reference_name

        if invoice_doctype not in ("Sales Invoice", "Purchase Invoice"):
            log_xero_error(
                f"Unsupported invoice type for payment sync: {invoice_doctype}",
                status="Info",
            )
            continue

        xero_invoice_id = frappe.db.get_value(
            invoice_doctype, invoice_name, "xero_invoice_id"
        )

        if not xero_invoice_id:
            log_xero_error(
                f"Xero Invoice ID not found for {invoice_doctype} {invoice_name}. Skipping this reference.",
                status="Info",
            )
            continue

        # --- Idempotency check (local map) ---
        if xero_invoice_id in idemp_map:
            log_xero_error(
                message=(
                    f"Payment for {invoice_doctype} {invoice_name} already "
                    f"synced to Xero (PaymentID={idemp_map[xero_invoice_id]}). "
                    f"Skipping duplicate PUT."
                ),
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=idemp_map[xero_invoice_id],
                xero_entity_type="Payment",
                direction="ERPNext to Xero",
                category="Duplicate Entity",
            )
            continue

        # --- Idempotency check (Xero-side defensive lookup) ---
        existing_payment_id = _xero_payment_exists_for_invoice(xero_invoice_id)
        if existing_payment_id:
            idemp_map[xero_invoice_id] = existing_payment_id
            log_xero_error(
                message=(
                    f"Payment for {invoice_doctype} {invoice_name} already "
                    f"exists in Xero (PaymentID={existing_payment_id}); "
                    f"reattaching to ERPNext map without creating duplicate."
                ),
                status="Info",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=existing_payment_id,
                xero_entity_type="Payment",
                direction="ERPNext to Xero",
                category="Duplicate Entity",
            )
            # Persist immediately so any subsequent failure does not lose
            # the discovered link.
            _save_payment_idempotency_map(doc_type, doc_name, idemp_map)
            continue

        # --- Build payload & create payment ---
        payment_payload = {
            "Invoice": {"InvoiceID": xero_invoice_id},
            "Account": {"AccountID": xero_bank_account_id},
            "Date": getdate(doc.posting_date).isoformat(),
            "Amount": flt(reference.allocated_amount),
            "Reference": f"{doc.reference_no or doc.name} - {invoice_name}",
        }

        response = xero_request("PUT", "Payments", data={"Payments": [payment_payload]})

        if not response or not response.get("Payments"):
            raise Exception(
                f"Invalid response received from Xero Payments API for invoice {invoice_name}"
            )

        new_xero_payment_id = response["Payments"][0].get("PaymentID")
        if not new_xero_payment_id:
            raise Exception(
                f"Xero API response did not contain a PaymentID for invoice {invoice_name}"
            )

        # --- Persist BEFORE moving to the next reference ---
        # If the next reference fails, this commit ensures the retry will
        # see the just-created payment in the idempotency map and skip it.
        idemp_map[xero_invoice_id] = new_xero_payment_id
        _save_payment_idempotency_map(doc_type, doc_name, idemp_map)

        log_xero_error(
            message=f"Successfully synced payment for invoice {invoice_name} from {doc_type} {doc_name}",
            status="Success",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            xero_entity_id=new_xero_payment_id,
            xero_entity_type="Payment",
            direction="ERPNext to Xero",
        )

    # --- Final summary log ---
    if not idemp_map:
        # Map is empty — nothing was synced, ever. Treat as failure to
        # surface on dashboard, but only if the doc had references that
        # SHOULD have synced. (Refs with allocated_amount<=0 don't count.)
        eligible_refs = [r for r in doc.references if r.allocated_amount > 0]
        if eligible_refs:
            raise Exception("No payments were successfully created in Xero.")
        return

    new_count = len(idemp_map) - initial_map_size
    log_xero_error(
        message=(
            f"Payment sync complete for {doc_type} {doc_name}: "
            f"{len(idemp_map)} payment(s) tracked "
            f"({new_count} new this run, "
            f"{initial_map_size} pre-existing/idempotent)."
        ),
        status="Success",
        erpnext_doc_type=doc_type,
        erpnext_doc_name=doc_name,
        xero_entity_id=next(iter(idemp_map.values())),
        xero_entity_type="Payment",
        direction="ERPNext to Xero",
    )


def sync_standalone_payment(
    doc, xero_contact_id, xero_bank_account_id, doc_type, doc_name
):
    """Handle standalone payments (advances, etc.) as Bank Transactions."""
    from .xero_invoices import get_xero_account_code

    settings = get_xero_settings()

    # Get account code for the party account
    party_account = doc.party_account
    xero_account_code = get_xero_account_code(party_account, settings)
    if not xero_account_code:
        raise Exception(
            f"Xero Account Code mapping not found for Account: {party_account}"
        )

    # Create bank transaction payload
    transaction_payload = {
        "Type": "SPEND" if doc.payment_type == "Pay" else "RECEIVE",
        "Contact": {"ContactID": xero_contact_id},
        "Date": getdate(doc.posting_date).isoformat(),
        "LineItems": [
            {
                "Description": doc.remarks or f"Payment {doc.name}",
                "Quantity": 1,
                "UnitAmount": flt(doc.paid_amount),
                "AccountCode": xero_account_code,
                "LineAmount": flt(doc.paid_amount),
                "TaxType": "NONE",  # Payments typically don't have tax
            }
        ],
        "BankAccount": {"AccountID": xero_bank_account_id},
        "Reference": doc.reference_no or doc.name,
    }

    # If updating, include the Xero Bank Transaction ID
    xero_bank_transaction_id = doc.get("xero_bank_transaction_id")
    if xero_bank_transaction_id:
        transaction_payload["BankTransactionID"] = xero_bank_transaction_id

    # Make API call
    response = xero_request(
        "PUT", "BankTransactions", data={"BankTransactions": [transaction_payload]}
    )

    if response and response.get("BankTransactions"):
        updated_transaction = response["BankTransactions"][0]
        new_xero_transaction_id = updated_transaction.get("BankTransactionID")

        if new_xero_transaction_id:
            frappe.db.set_value(
                doc_type,
                doc_name,
                {
                    "xero_bank_transaction_id": new_xero_transaction_id,
                    "xero_sync_status": "Synced",
                    "xero_last_sync": now(),
                },
                update_modified=False,
            )
            frappe.db.commit()

            log_xero_error(
                message=f"Successfully synced standalone payment {doc_type} {doc_name} to Xero as Bank Transaction.",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=new_xero_transaction_id,
                xero_entity_type="BankTransaction",
                direction="ERPNext to Xero",
            )
        else:
            raise Exception("Xero API response did not contain a BankTransactionID.")
    else:
        raise Exception("Invalid response received from Xero BankTransactions API.")


# --- Payment Sync (Xero to ERPNext) ---


def sync_payments_from_xero(invoice_id=None):
    """
    Fetches payments from Xero and creates corresponding entries in ERPNext.

    Args:
        invoice_id: Specific Xero invoice ID to sync payments for
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return

    # Check per-entity directional toggle for inbound sync
    if not settings.get("sync_payments_from_xero"):
        log_xero_error(
            message="Payment inbound sync is disabled. Skipping payments from Xero.",
            status="Info",
            category="System Monitoring",
        )
        return

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Payments page {page}", "Xero Sync")

            params = {"page": page}
            if invoice_id:
                params["InvoiceID"] = invoice_id

            response = xero_request("GET", "Payments", params=params)

            if not response or not response.get("Payments"):
                break

            payments = response["Payments"]
            if not payments:
                break

            for payment_data in payments:
                try:
                    process_xero_payment(payment_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Payment ID {payment_data.get('PaymentID')}",
                        xero_entity_id=payment_data.get("PaymentID"),
                        xero_entity_type="Payment",
                        error_details=frappe.get_traceback(),
                    )

            # Check if it was the last page
            if len(payments) < 100:
                break
            page += 1

        log_xero_error(message="Finished syncing payments from Xero.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_payments_from_xero",
            error_details=frappe.get_traceback(),
        )


def process_xero_payment(xero_payment_data, settings):
    """Creates or updates an ERPNext Payment Entry from Xero payment data."""
    from .xero_invoices import parse_xero_date

    xero_payment_id = xero_payment_data.get("PaymentID")

    if not xero_payment_id:
        log_xero_error(
            message=f"Skipping Xero payment due to missing ID: {xero_payment_data}",
            status="Info",
        )
        return

    # --- Primary dedup: match by xero_payment_id ---
    erpnext_doc_name = frappe.db.get_value(
        "Payment Entry", {"xero_payment_id": xero_payment_id}, "name"
    )

    # Get invoice information
    xero_invoice_id = xero_payment_data.get("Invoice", {}).get("InvoiceID")

    # --- Secondary dedup: scan xero_payment_data for this PaymentID ---
    # When ERPNext synced this PE outbound, the payment_id was stored inside
    # the JSON map on xero_payment_data, NOT on xero_payment_id (which only
    # holds the FIRST payment for multi-reference PEs). Without this check,
    # a multi-reference PE round-tripping through inbound creates duplicate
    # ERPNext Payment Entries for every reference past the first.
    if not erpnext_doc_name and xero_payment_id:
        candidates = frappe.db.sql(
            """
            SELECT name FROM `tabPayment Entry`
            WHERE xero_payment_data LIKE %(needle)s
            LIMIT 1
            """,
            {"needle": f"%{xero_payment_id}%"},
            as_dict=True,
        )
        if candidates:
            erpnext_doc_name = candidates[0]["name"]
            # Backfill xero_payment_id for faster future lookups
            frappe.db.set_value(
                "Payment Entry",
                erpnext_doc_name,
                "xero_payment_id",
                xero_payment_id,
                update_modified=False,
            )
            frappe.db.commit()
            log_xero_error(
                message=(
                    f"Reattached Xero Payment {xero_payment_id} to existing "
                    f"Payment Entry {erpnext_doc_name} via xero_payment_data "
                    f"map (avoided duplicate)."
                ),
                status="Info",
                erpnext_doc_type="Payment Entry",
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_payment_id,
                xero_entity_type="Payment",
                direction="Xero to ERPNext",
                category="Duplicate Entity",
            )
            return  # Already linked, no further work needed

    if not xero_invoice_id:
        log_xero_error(
            message=f"Cannot sync payment from Xero: Payment has no linked invoice",
            status="Warning",
            xero_entity_id=xero_payment_id,
            xero_entity_type="Payment",
            direction="Xero to ERPNext",
            category="Missing Prerequisites",
        )
        return

    # Find corresponding ERPNext invoice
    invoice_doc = None
    invoice_doctype = None

    # Try Sales Invoice first
    invoice_name = frappe.db.get_value(
        "Sales Invoice", {"xero_invoice_id": xero_invoice_id}, "name"
    )
    if invoice_name:
        invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
        invoice_doctype = "Sales Invoice"
    else:
        # Try Purchase Invoice
        invoice_name = frappe.db.get_value(
            "Purchase Invoice", {"xero_invoice_id": xero_invoice_id}, "name"
        )
        if invoice_name:
            invoice_doc = frappe.get_doc("Purchase Invoice", invoice_name)
            invoice_doctype = "Purchase Invoice"

    if not invoice_doc:
        log_xero_error(
            message=f"Cannot sync payment from Xero: The invoice this payment is linked to has not been synced to ERPNext yet. Please sync invoices first.",
            status="Warning",
            xero_entity_id=xero_payment_id,
            xero_entity_type="Payment",
            direction="Xero to ERPNext",
            category="Missing Prerequisites",
        )
        return

    # Get account information
    xero_account_id = xero_payment_data.get("Account", {}).get("AccountID")
    if not xero_account_id:
        log_xero_error(
            message=f"Cannot sync payment from Xero: Payment has no bank account information",
            status="Warning",
            xero_entity_id=xero_payment_id,
            xero_entity_type="Payment",
            direction="Xero to ERPNext",
            category="Missing Prerequisites",
        )
        return

    # Find corresponding ERPNext account
    account = frappe.db.get_value(
        "Account", {"xero_account_id": xero_account_id}, "name"
    )
    if not account:
        log_xero_error(
            message=f"Cannot sync payment from Xero: The bank account used in Xero has not been synced to ERPNext. Please sync your Chart of Accounts first.",
            status="Warning",
            xero_entity_id=xero_payment_id,
            xero_entity_type="Payment",
            direction="Xero to ERPNext",
            category="Missing Prerequisites",
        )
        return

    # Verify account is a bank/cash account
    account_type = frappe.db.get_value("Account", account, "account_type")
    if account_type not in ["Bank", "Cash"]:
        log_xero_error(
            message=f"Cannot sync payment from Xero: The account '{account}' is not a Bank or Cash account (it's {account_type}). Please check your account mappings.",
            status="Warning",
            xero_entity_id=xero_payment_id,
            xero_entity_type="Payment",
            direction="Xero to ERPNext",
            category="Configuration Error",
        )
        return

    try:
        # Determine payment type based on invoice type
        payment_type = "Receive" if invoice_doctype == "Sales Invoice" else "Pay"
        party_type = "Customer" if invoice_doctype == "Sales Invoice" else "Supplier"

        # Calculate amounts
        payment_amount = flt(xero_payment_data.get("Amount", 0))

        # Parse date with fallback
        try:
            posting_date = parse_xero_date(xero_payment_data.get("Date"))
        except Exception as date_error:
            frappe.logger().warning(
                f"Failed to parse Xero payment date, using today: {date_error}"
            )
            posting_date = getdate()

        # Set paid_from and paid_to correctly based on payment type
        if payment_type == "Receive":  # Sales Invoice - receiving money
            paid_from = invoice_doc.debit_to  # Customer's receivable account
            paid_to = account  # Our bank account
        else:  # Pay - Purchase Invoice - paying money
            paid_from = account  # Our bank account
            paid_to = invoice_doc.credit_to  # Supplier's payable account

        # Map Xero Data to ERPNext Fields
        erpnext_data = {
            "payment_type": payment_type,
            "party_type": party_type,
            "party": invoice_doc.customer
            if invoice_doctype == "Sales Invoice"
            else invoice_doc.supplier,
            "posting_date": posting_date,
            "paid_amount": payment_amount,
            "received_amount": payment_amount,
            "paid_from": paid_from,
            "paid_to": paid_to,
            "reference_no": xero_payment_data.get("Reference")
            or xero_payment_id[:8],  # Use payment ID if no reference
            "reference_date": posting_date,  # Set reference date to match posting date
            "remarks": f"Payment from Xero for {invoice_doctype} {invoice_name}",
            "xero_payment_id": xero_payment_id,
            "xero_sync_status": "Synced",
            "references": [
                {
                    "reference_doctype": invoice_doctype,
                    "reference_name": invoice_name,
                    "allocated_amount": payment_amount,
                }
            ],
        }

        # --- Tertiary dedup: invoice + amount match ---
        # If we still have no ERPNext PE matched (neither by xero_payment_id
        # nor by xero_payment_data scan), try to find a submitted PE that is
        # already allocated to this invoice for this exact amount. This
        # catches the case where ERPNext synced the payment outbound, Xero
        # accepted it, but the local DB write failed before storing the
        # PaymentID. Without this, inbound creates a duplicate ERPNext PE.
        if not erpnext_doc_name:
            candidates = frappe.db.sql(
                """
                SELECT pe.name
                FROM `tabPayment Entry` pe
                INNER JOIN `tabPayment Entry Reference` per
                    ON per.parent = pe.name
                WHERE pe.docstatus = 1
                  AND per.reference_doctype = %(inv_dt)s
                  AND per.reference_name = %(inv_name)s
                  AND ABS(per.allocated_amount - %(amt)s) < 0.01
                  AND (pe.xero_payment_id IS NULL OR pe.xero_payment_id = '')
                LIMIT 1
                """,
                {
                    "inv_dt": invoice_doctype,
                    "inv_name": invoice_name,
                    "amt": payment_amount,
                },
                as_dict=True,
            )
            if candidates:
                matched = candidates[0]["name"]
                # Attach Xero IDs to the existing PE without modifying it
                # (it is submitted; only set_value on tracking fields).
                frappe.db.set_value(
                    "Payment Entry",
                    matched,
                    {
                        "xero_payment_id": xero_payment_id,
                        "xero_sync_status": "Synced",
                        "xero_last_sync": now(),
                    },
                    update_modified=False,
                )
                frappe.db.commit()
                log_xero_error(
                    message=(
                        f"Linked Xero Payment {xero_payment_id} to existing "
                        f"submitted Payment Entry {matched} (matched on "
                        f"{invoice_doctype} {invoice_name} + amount "
                        f"{payment_amount}). Avoided creating duplicate."
                    ),
                    status="Info",
                    erpnext_doc_type="Payment Entry",
                    erpnext_doc_name=matched,
                    xero_entity_id=xero_payment_id,
                    xero_entity_type="Payment",
                    direction="Xero to ERPNext",
                    category="Duplicate Entity",
                )
                return

        if erpnext_doc_name:
            # Check if existing payment is submitted
            existing_doc = frappe.get_doc("Payment Entry", erpnext_doc_name)
            if existing_doc.docstatus == 1:
                # Cannot modify submitted document - log and skip
                log_xero_error(
                    message=f"Cannot update Payment Entry {erpnext_doc_name}: Document is already submitted. Skipping update.",
                    status="Info",
                    erpnext_doc_type="Payment Entry",
                    erpnext_doc_name=erpnext_doc_name,
                    xero_entity_id=xero_payment_id,
                    xero_entity_type="Payment",
                    direction="Xero to ERPNext",
                )
                return

            # Update existing draft payment
            existing_doc.update(erpnext_data)
            existing_doc.save(ignore_permissions=True)
            log_message = f"Updated Payment Entry {erpnext_doc_name} from Xero Payment {xero_payment_id}"
        else:
            # Create new payment
            doc = frappe.new_doc("Payment Entry")
            doc.update(erpnext_data)
            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name

            # Auto-submit if configured
            if settings.get("auto_submit_payment_entries"):
                doc.submit()
                log_message = f"Created and submitted Payment Entry {erpnext_doc_name} from Xero Payment {xero_payment_id}"
            else:
                log_message = f"Created Payment Entry {erpnext_doc_name} from Xero Payment {xero_payment_id} (Draft - please review and submit)"

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type="Payment Entry",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_payment_id,
            xero_entity_type="Payment",
            direction="Xero to ERPNext",
        )

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        if is_already_exists_error(str(e), error_traceback):
            if erpnext_doc_name:
                frappe.db.set_value(
                    "Payment Entry",
                    erpnext_doc_name,
                    "xero_sync_status",
                    "Synced",
                    update_modified=False,
                )
                frappe.db.commit()

            log_xero_error(
                message=f"Xero Payment {xero_payment_id} already exists in ERPNext as {erpnext_doc_name or 'submitted document'}. Skipping update.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type="Payment Entry",
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_payment_id,
                xero_entity_type="Payment",
                direction="Xero to ERPNext",
            )
        else:
            sync_status = "Error"
            if erpnext_doc_name:
                frappe.db.set_value(
                    "Payment Entry",
                    erpnext_doc_name,
                    "xero_sync_status",
                    sync_status,
                    update_modified=False,
                )
                frappe.db.commit()

            # Create user-friendly error message
            error_str = str(e)
            user_friendly_message = f"Failed to sync payment from Xero: {error_str}"

            # Provide specific guidance for common errors
            if "paid_from" in error_str.lower() or "paid_to" in error_str.lower():
                user_friendly_message = "Failed to sync payment from Xero: There's an issue with the bank account configuration. Please check that your bank accounts are properly mapped in Xero Settings."
            elif (
                "party" in error_str.lower()
                or "customer" in error_str.lower()
                or "supplier" in error_str.lower()
            ):
                user_friendly_message = "Failed to sync payment from Xero: The customer or supplier linked to this payment may not be synced properly. Please sync contacts first."
            elif "reference" in error_str.lower():
                user_friendly_message = "Failed to sync payment from Xero: There's an issue with the payment reference information."
            elif "outstanding" in error_str.lower():
                user_friendly_message = "Failed to sync payment from Xero: The payment amount exceeds the outstanding amount on the invoice."

            log_xero_error(
                message=user_friendly_message,
                erpnext_doc_type="Payment Entry",
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_payment_id,
                xero_entity_type="Payment",
                direction="Xero to ERPNext",
                error_details=error_traceback,
                category="Sync Error",
            )


@frappe.whitelist()
def reconcile_payments(party=None, party_type=None, from_date=None, to_date=None):
    """
    Reconcile payments between ERPNext and Xero for a specific party or date range.

    Args:
        party: ERPNext party name (Customer/Supplier)
        party_type: "Customer" or "Supplier"
        from_date: Start date for reconciliation
        to_date: End date for reconciliation
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw("Xero sync is not enabled.")

    try:
        # Sync payments from Xero
        sync_payments_from_xero()

        # Get ERPNext payments for comparison
        filters = {"docstatus": 1}

        if party and party_type:
            filters["party"] = party
            filters["party_type"] = party_type

        if from_date:
            filters["posting_date"] = [">=", from_date]
        if to_date:
            if "posting_date" in filters:
                filters["posting_date"] = ["between", [from_date, to_date]]
            else:
                filters["posting_date"] = ["<=", to_date]

        erpnext_payments = frappe.get_all(
            "Payment Entry",
            filters=filters,
            fields=[
                "name",
                "posting_date",
                "paid_amount",
                "party",
                "party_type",
                "reference_no",
                "xero_payment_id",
            ],
        )

        # Create reconciliation report
        reconciliation_data = {
            "party": party,
            "party_type": party_type,
            "from_date": from_date,
            "to_date": to_date,
            "total_erpnext_payments": len(erpnext_payments),
            "synced_payments": len([p for p in erpnext_payments if p.xero_payment_id]),
            "unsynced_payments": len(
                [p for p in erpnext_payments if not p.xero_payment_id]
            ),
        }

        frappe.msgprint(
            f"Payment reconciliation completed. {reconciliation_data['synced_payments']} payments synced, {reconciliation_data['unsynced_payments']} unsynced."
        )

        return reconciliation_data

    except Exception as e:
        log_xero_error(
            message=f"Error during payment reconciliation",
            error_details=frappe.get_traceback(),
        )
        frappe.throw(f"Payment reconciliation failed: {str(e)}")
