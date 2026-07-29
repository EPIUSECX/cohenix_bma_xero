# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
from ..utils.transactions import commit_checkpoint, commit_error_state, commit_external_outcome
from frappe import _
from frappe.utils import getdate, flt, now
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff
from ..utils.sync_status import mark_sync_failure
from .xero_accounts import validate_account_code

# --- Manual Journal Sync (ERPNext to Xero) ---

def resolve_line_account_code(erpnext_account, account_map, doc_type=None, doc_name=None):
    """
    Xero account code for a journal line's ERPNext account.

    The configured mapping row (Xero Settings → account_mapping) wins, except
    when the account is itself linked to Xero (xero_account_id set) and its
    own code — account_number sanitised the same way outbound account sync
    builds Code — disagrees. Then the live code is ground truth: a
    contradicting row is a configuration error (e.g. auto-mapped onto a Xero
    system account) and gets a loud Warning. Returns None if no code exists.
    """
    mapped_code = account_map.get(erpnext_account)
    account_number, account_xero_id = frappe.db.get_value(
        "Account", erpnext_account, ["account_number", "xero_account_id"]
    ) or (None, None)

    live_code = None
    if account_xero_id and account_number:
        try:
            live_code = validate_account_code(account_number)
        except ValueError:
            live_code = None

    if mapped_code and live_code and str(mapped_code).strip() != live_code:
        log_xero_error(
            message=(
                f"Account mapping conflict for {erpnext_account}: the mapping row "
                f"in Xero Settings says code {mapped_code}, but the account is "
                f"linked to Xero code {live_code}. Using {live_code} — correct "
                f"the row under Xero Settings → Mappings."
            ),
            status="Warning",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            category="Mapping Errors",
        )
        return live_code

    return mapped_code or account_number


# doc_event handler: takes the Document the hook passes, so it is not
# HTTP-callable. Manual syncs go through xero.api.manual_sync instead.
def enqueue_sync_journal(doc, method):
    """Enqueue background job to sync a Journal Entry to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_journal_entries"):
        return

    frappe.enqueue(
        "xero.api.xero_journals.sync_journal_to_xero",
        queue="short",
        timeout=600,
        enqueue_after_commit=True,
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync")


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_journal_to_xero(doc_name, doc_type="Journal Entry", **kwargs):
    """
    Enhanced sync for ERPNext Journal Entry to Xero Manual Journals.
    Supports create, update, and proper validation.
    Ref: https://developer.xero.com/documentation/api/accounting/manualjournals
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
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
    
    if not settings.get("sync_journal_entries"):
        return # Journal sync specifically disabled

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_journal_id = doc.get("xero_manual_journal_id")

        # --- Basic Validation ---
        if doc.docstatus != 1:
            log_xero_error(f"Cannot sync non-submitted document: {doc_type} {doc_name}", status="Info")
            return

        # --- Validate single currency (HI-11) ---
        # Xero manual journals are SINGLE-CURRENCY. If the ERPNext Journal Entry
        # mixes account currencies we cannot represent it as one Xero manual
        # journal, so reject it explicitly rather than silently posting wrong
        # amounts.
        account_currencies = {
            (acc.account_currency or "")
            for acc in doc.accounts
            if (acc.account_currency or "")
        }
        if len(account_currencies) > 1:
            frappe.throw(
                _(
                    "Journal Entry {0} mixes multiple account currencies ({1}). "
                    "Xero manual journals are single-currency and cannot be synced. "
                    "Split this into separate single-currency journals."
                ).format(doc_name, ", ".join(sorted(account_currencies)))
            )

        # --- Validate Journal Balance (HI-11) ---
        # Validate in COMPANY currency (debit/credit) rather than account currency.
        # The account-currency fields only balance per-currency; the company-currency
        # debit/credit are what actually post to the GL and what Xero will receive.
        total_debit = sum([flt(acc.debit) for acc in doc.accounts])
        total_credit = sum([flt(acc.credit) for acc in doc.accounts])

        if abs(total_debit - total_credit) > 0.01:  # Allow for minor rounding differences
            raise Exception(f"Journal Entry {doc_name} is not balanced. Debit: {total_debit}, Credit: {total_credit}")

        # --- Prepare Manual Journal Lines ---
        journal_lines = []
        account_map = settings.get_account_map()
        for acc in doc.accounts:
            # Get Xero Account Code from the configured account mapping (Xero
            # Settings → account_mapping). Fall back to the ERPNext account
            # number only if it happens to match a Xero code and no explicit
            # mapping exists. NOTE: the Account doctype has no
            # `xero_account_code` column — the mapping lives on Xero Settings.
            xero_account_code = resolve_line_account_code(
                acc.account, account_map, doc_type, doc_name
            )
            if not xero_account_code:
                raise Exception(
                    f"Xero Account Code mapping not found in Xero Settings for ERPNext Account: {acc.account}. "
                    f"Add it under Xero Settings → Mappings."
                )

            # Calculate line amount (Xero uses positive for debit, negative for credit)
            line_amount = flt(acc.debit_in_account_currency) - flt(acc.credit_in_account_currency)
            
            if line_amount == 0:
                continue  # Skip zero amount lines

            # Get tracking categories if available.
            # These rely on optional custom fields (xero_tracking_category_id /
            # xero_tracking_option_id) on Cost Center / Project. Those fields are
            # NOT part of the app's default install, so guard every lookup with
            # has_column — otherwise the query raises (1054 Unknown column) and
            # crashes the whole journal sync.
            tracking = []
            if acc.cost_center and frappe.db.has_column("Cost Center", "xero_tracking_category_id"):
                cost_center_tracking_id = frappe.db.get_value("Cost Center", acc.cost_center, "xero_tracking_category_id")
                cost_center_tracking_option = frappe.db.get_value("Cost Center", acc.cost_center, "xero_tracking_option_id")
                if cost_center_tracking_id and cost_center_tracking_option:
                    tracking.append({
                        "TrackingCategoryID": cost_center_tracking_id,
                        "TrackingOptionID": cost_center_tracking_option
                    })

            if acc.project and frappe.db.has_column("Project", "xero_tracking_category_id"):
                project_tracking_id = frappe.db.get_value("Project", acc.project, "xero_tracking_category_id")
                project_tracking_option = frappe.db.get_value("Project", acc.project, "xero_tracking_option_id")
                if project_tracking_id and project_tracking_option:
                    tracking.append({
                        "TrackingCategoryID": project_tracking_id,
                        "TrackingOptionID": project_tracking_option
                    })

            journal_line = {
                "AccountCode": xero_account_code,
                "Description": acc.user_remark or acc.account or "Journal Entry Line",
                "LineAmount": line_amount,
                "TaxType": "NONE"  # Manual journals typically don't have tax
            }

            # Add tracking if available (max 2 tracking categories per line)
            if tracking:
                journal_line["Tracking"] = tracking[:2]  # Xero allows max 2 tracking categories

            journal_lines.append(journal_line)

        if not journal_lines:
            raise Exception(f"No valid journal lines found for {doc_type} {doc_name}")

        # --- Construct Manual Journal Payload ---
        journal_payload = {
            "Date": getdate(doc.posting_date).isoformat(),
            "Narration": doc.user_remark or doc.title or f"Journal Entry {doc.name}",
            # Xero's Manual Journal element names the lines array "JournalLines"
            # (NOT "ManualJournalLines"). Using the wrong key makes Xero silently
            # ignore all lines and reject with "must contain at least 2 lines".
            "JournalLines": journal_lines,
            "Status": "POSTED",  # ERPNext submitted = Xero posted
            # HI-11: Every line carries TaxType "NONE", so the amounts are tax-free.
            # Sending "INCLUSIVE" tells Xero the amounts include tax and can make it
            # back out a tax component, distorting the posting. "NoTax" is the correct
            # LineAmountType when no line has tax.
            "LineAmountTypes": "NoTax",
            "ShowOnCashBasisReports": True
        }

        # If updating, include the Xero Manual Journal ID
        if xero_journal_id:
            journal_payload["ManualJournalID"] = xero_journal_id

        # --- Make API Call ---
        # Xero API: POST handles both create (no ID) and update (ID in payload).
        # PUT only creates new records and will not update existing ones.
        # Pass a stable idempotency key on CREATE so a retry after a network
        # timeout does not post a duplicate manual journal in Xero.
        idempotency_key = (
            None if xero_journal_id else f"{doc_type}:{doc_name}:create"
        )
        response = xero_request(
            "POST",
            "ManualJournals",
            data={"ManualJournals": [journal_payload]},
            idempotency_key=idempotency_key,
        )

        if response and response.get("ManualJournals"):
            updated_journal = response["ManualJournals"][0]
            new_xero_journal_id = updated_journal.get("ManualJournalID")

            # --- Update ERPNext Document ---
            if new_xero_journal_id:
                frappe.db.set_value(doc_type, doc_name, {
                    "xero_manual_journal_id": new_xero_journal_id,
                    "xero_sync_status": "Synced",
                    "xero_last_sync": now()
                }, update_modified=False)
                commit_external_outcome()

                log_xero_error(
                    message=f"Successfully synced {doc_type} {doc_name} to Xero Manual Journal.",
                    status="Success",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=new_xero_journal_id,
                    xero_entity_type="ManualJournal",
                    direction="ERPNext to Xero"
                )
            else:
                raise Exception("Xero API response did not contain a ManualJournalID.")
        else:
            raise Exception("Invalid response received from Xero ManualJournals API.")

    except Exception as e:
        from ..utils.logging import is_already_exists_error
        error_traceback = frappe.get_traceback()
        
        if is_already_exists_error(str(e), error_traceback):
            if doc_name and doc_type:
                frappe.db.set_value(doc_type, doc_name, {"xero_sync_status": "Synced"}, update_modified=False)
                commit_error_state()
            
            log_xero_error(
                message=f"{doc_type} {doc_name} already exists in Xero. No action needed.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                direction="ERPNext to Xero"
            )
        else:
            mark_sync_failure(
                doc_type, doc_name, e, "ERPNext to Xero", traceback_text=error_traceback
            )


def enqueue_delete_journal(doc, method):
    """Enqueue the void job for a cancelled Journal Entry.

    Wired to the Journal Entry on_cancel doc_event, so it receives (doc, method).
    The actual void runs on the worker in delete_journal_from_xero(doc_name,
    doc_type). Previously on_cancel pointed straight at that worker, which Frappe
    called as (doc, "on_cancel") — the signature mismatch meant journals were
    never voided in Xero.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_journal_entries"):
        return

    frappe.enqueue(
        "xero.api.xero_journals.delete_journal_from_xero",
        queue="short",
        timeout=600,
        enqueue_after_commit=True,
        doc_name=doc.name,
        doc_type=doc.doctype,
    )


def delete_journal_from_xero(doc_name, doc_type="Journal Entry"):
    """
    Delete/Void a Manual Journal in Xero when cancelled in ERPNext.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return
    
    # Check directional toggle for outbound sync (voiding is a write operation)
    if not settings.enable_sync_to_xero:
        log_xero_error(
            message=f"Sync to Xero is disabled. Skipping void operation for {doc_type} {doc_name}.",
            status="Info",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            category="System Monitoring"
        )
        return

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_journal_id = doc.get("xero_manual_journal_id")

        if not xero_journal_id:
            log_xero_error(f"No Xero Manual Journal ID found for {doc_type} {doc_name}. Cannot delete.", status="Info")
            return

        # Update the journal status to VOIDED in Xero
        journal_payload = {
            "ManualJournalID": xero_journal_id,
            "Status": "VOIDED"
        }

        response = xero_request("POST", "ManualJournals", data={"ManualJournals": [journal_payload]})

        if response and response.get("ManualJournals"):
            frappe.db.set_value(doc_type, doc_name, {
                "xero_sync_status": "Cancelled",
                "xero_last_sync": now()
            }, update_modified=False)
            commit_external_outcome()

            log_xero_error(
                message=f"Successfully voided Xero Manual Journal for {doc_type} {doc_name}.",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                xero_entity_id=xero_journal_id,
                xero_entity_type="ManualJournal",
                direction="ERPNext to Xero"
            )
        else:
            raise Exception("Failed to void Manual Journal in Xero.")

    except Exception as e:
        log_xero_error(
            message=f"Failed to void Xero Manual Journal for {doc_type} {doc_name}.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )


# --- Manual Journal Sync (Xero to ERPNext) ---

def sync_manual_journals_from_xero(from_date=None, to_date=None):
    """
    Fetches manual journals from Xero and creates corresponding entries in ERPNext.
    
    Args:
        from_date: Start date for sync
        to_date: End date for sync
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping manual journals inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_journal_entries"): return

    # Incremental sync: fetch only manual journals changed since the last
    # successful run. An explicit from_date overrides the stored watermark.
    # Xero filters ManualJournals by the If-Modified-Since header, NOT a
    # `modifiedAfter` query param (which it ignores), so the value goes through
    # modified_since= on the GET.
    from ..utils.xero_client import (
        incremental_since,
        commit_watermark,
        start_incremental_run,
    )

    watermark_key = "manual_journals"
    run_started_at = start_incremental_run()
    if_modified_since = from_date or incremental_since(watermark_key)

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Manual Journals page {page}", "Xero Sync")

            params = {"page": page}

            response = xero_request(
                "GET",
                "ManualJournals",
                params=params,
                modified_since=if_modified_since,
            )

            if not response or not response.get("ManualJournals"):
                break

            journals = response["ManualJournals"]
            if not journals:
                break

            for journal_data in journals:
                try:
                    process_xero_manual_journal(journal_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Manual Journal ID {journal_data.get('ManualJournalID')}",
                        xero_entity_id=journal_data.get('ManualJournalID'),
                        xero_entity_type="ManualJournal",
                        error_details=frappe.get_traceback()
                    )

            # Check if it was the last page
            if len(journals) < 100:
                break
            page += 1

        # Only advance the watermark after a fully successful sweep — if an
        # exception aborted the loop, the next run re-fetches from the old
        # watermark so nothing is missed.
        commit_watermark(watermark_key, run_started_at)
        log_xero_error(message="Finished syncing manual journals from Xero.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_manual_journals_from_xero",
            error_details=frappe.get_traceback()
        )


def process_xero_manual_journal(xero_journal_data, settings):
    """Creates or updates an ERPNext Journal Entry from Xero manual journal data."""
    xero_journal_id = xero_journal_data.get("ManualJournalID")
    
    if not xero_journal_id:
        log_xero_error(message=f"Skipping Xero manual journal due to missing ID: {xero_journal_data}", status="Info")
        return

    # Skip voided journals
    if xero_journal_data.get("Status") == "VOIDED":
        log_xero_error(message=f"Skipping voided Xero manual journal {xero_journal_id}", status="Info")
        return

    # Check if ERPNext journal already exists
    erpnext_doc_name = frappe.db.get_value("Journal Entry", {"xero_manual_journal_id": xero_journal_id}, "name")

    # Inbound is create-once: if this Xero manual journal is already mirrored in
    # ERPNext, skip it — never overwrite local edits or fail on a submitted doc.
    if erpnext_doc_name:
        log_xero_error(
            message=f"Xero Manual Journal {xero_journal_id} already mirrored as {erpnext_doc_name}; skipping (create-once).",
            status="Info", category="Duplicate Entity",
            erpnext_doc_type="Journal Entry", erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_journal_id, xero_entity_type="ManualJournal", direction="Xero to ERPNext",
        )
        return

    try:
        from .xero_invoices import parse_xero_date, get_erpnext_account_from_xero_code

        # Get journal lines — Xero returns them under "JournalLines"
        journal_lines = xero_journal_data.get("JournalLines", [])
        if not journal_lines:
            log_xero_error(message=f"Skipping Xero manual journal {xero_journal_id}: No journal lines", status="Info")
            return

        # Map Xero Data to ERPNext Fields
        accounts = []
        for line in journal_lines:
            account_code = line.get("AccountCode")
            if not account_code:
                continue

            # Find corresponding ERPNext account: prefer the configured account
            # mapping (Xero code -> ERPNext account), then fall back to matching
            # the ERPNext account_number. NOTE: the Account doctype has no
            # `xero_account_code` column — the mapping lives on Xero Settings.
            account = get_erpnext_account_from_xero_code(account_code, settings) or \
                frappe.db.get_value("Account", {"account_number": account_code}, "name")

            if not account:
                log_xero_error(message=f"Account not found for Xero Account Code {account_code} in manual journal {xero_journal_id}", status="Info")
                continue

            line_amount = flt(line.get("LineAmount", 0))
            
            # Convert Xero line amount to ERPNext debit/credit
            debit = line_amount if line_amount > 0 else 0
            credit = abs(line_amount) if line_amount < 0 else 0

            account_entry = {
                "account": account,
                "debit_in_account_currency": debit,
                "credit_in_account_currency": credit,
                "user_remark": line.get("Description", "")
            }

            # Add tracking categories if available
            tracking = line.get("Tracking", [])
            for track in tracking:
                tracking_category_id = track.get("TrackingCategoryID")
                tracking_option_id = track.get("TrackingOptionID")
                
                # Tracking -> Cost Center / Project mapping relies on optional
                # custom fields (xero_tracking_*) that are not part of the default
                # install; guard every lookup with has_column to avoid raising
                # 1054 Unknown column and crashing the sync.
                cost_center = None
                if frappe.db.has_column("Cost Center", "xero_tracking_category_id"):
                    cost_center = frappe.db.get_value("Cost Center", {
                        "xero_tracking_category_id": tracking_category_id,
                        "xero_tracking_option_id": tracking_option_id
                    }, "name")

                if cost_center:
                    account_entry["cost_center"] = cost_center
                elif frappe.db.has_column("Project", "xero_tracking_category_id"):
                    project = frappe.db.get_value("Project", {
                        "xero_tracking_category_id": tracking_category_id,
                        "xero_tracking_option_id": tracking_option_id
                    }, "name")
                    if project:
                        account_entry["project"] = project

            accounts.append(account_entry)

        if not accounts:
            log_xero_error(message=f"No valid accounts found for Xero manual journal {xero_journal_id}", status="Info")
            return

        # ME-11: Require an explicit company rather than silently picking the
        # "first" company, which is non-deterministic in multi-company sites and
        # can post journals against the wrong books. Xero Settings has no company
        # field, so we use the Frappe global default and throw a clear error if
        # none is configured.
        company = frappe.defaults.get_global_default("company")
        if not company:
            frappe.throw(
                _(
                    "No default Company is configured. Set a global Default Company "
                    "before syncing Xero manual journal {0} into ERPNext."
                ).format(xero_journal_id)
            )
        erpnext_data = {
            "company": company,
            "voucher_type": "Journal Entry",
            # Xero serialises dates as /Date(ms+offset)/ — use the shared parser.
            "posting_date": parse_xero_date(xero_journal_data.get("Date")),
            "title": xero_journal_data.get("Narration") or f"Manual Journal from Xero {xero_journal_id}",
            "user_remark": xero_journal_data.get("Narration"),
            "accounts": accounts,
            "xero_manual_journal_id": xero_journal_id,
            "xero_sync_status": "Synced",
        }

        # Create the new Journal Entry as a Draft (existing docs were skipped
        # above; inbound is create-once).
        doc = frappe.new_doc("Journal Entry")
        doc.update(erpnext_data)
        doc.insert(ignore_permissions=True)
        erpnext_doc_name = doc.name
        log_message = f"Created Journal Entry {erpnext_doc_name} from Xero Manual Journal {xero_journal_id}"

        commit_checkpoint()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type="Journal Entry",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_journal_id,
            xero_entity_type="ManualJournal",
            direction="Xero to ERPNext"
        )

    except Exception as e:
        from ..utils.logging import is_already_exists_error
        error_traceback = frappe.get_traceback()
        
        if is_already_exists_error(str(e), error_traceback):
            if erpnext_doc_name:
                frappe.db.set_value("Journal Entry", erpnext_doc_name, "xero_sync_status", "Synced", update_modified=False)
                commit_error_state()
            
            log_xero_error(
                message=f"Xero Manual Journal {xero_journal_id} already exists in ERPNext as {erpnext_doc_name or 'submitted document'}. Skipping update.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type="Journal Entry",
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_journal_id,
                xero_entity_type="ManualJournal",
                direction="Xero to ERPNext"
            )
        else:
            mark_sync_failure(
                "Journal Entry",
                erpnext_doc_name,
                e,
                "Xero to ERPNext",
                source_type="Xero Manual Journal",
                source_id=xero_journal_id,
                xero_entity_id=xero_journal_id,
                xero_entity_type="ManualJournal",
                traceback_text=error_traceback,
            )

