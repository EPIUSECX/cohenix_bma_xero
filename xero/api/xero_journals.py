# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, flt, now
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff

# --- Manual Journal Sync (ERPNext to Xero) ---

@frappe.whitelist()
def enqueue_sync_journal(doc, method):
    """Enqueue background job to sync a Journal Entry to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_journal_entries"):
        return

    frappe.enqueue(
        "xero.api.xero_journals.sync_journal_to_xero",
        queue="short",
        timeout=600,
        retry=1,
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

        # --- Validate Journal Balance ---
        total_debit = sum([flt(acc.debit_in_account_currency) for acc in doc.accounts])
        total_credit = sum([flt(acc.credit_in_account_currency) for acc in doc.accounts])
        
        if abs(total_debit - total_credit) > 0.01:  # Allow for minor rounding differences
            raise Exception(f"Journal Entry {doc_name} is not balanced. Debit: {total_debit}, Credit: {total_credit}")

        # --- Prepare Manual Journal Lines ---
        journal_lines = []
        for acc in doc.accounts:
            # Get Xero Account Code
            xero_account_code = frappe.db.get_value("Account", acc.account, "account_number")
            if not xero_account_code:
                # Try to get from account name mapping
                xero_account_code = frappe.db.get_value("Account", acc.account, "xero_account_code")
                if not xero_account_code:
                    raise Exception(f"Xero Account Code not found for ERPNext Account: {acc.account}. Please set 'account_number' or 'xero_account_code' field.")

            # Calculate line amount (Xero uses positive for debit, negative for credit)
            line_amount = flt(acc.debit_in_account_currency) - flt(acc.credit_in_account_currency)
            
            if line_amount == 0:
                continue  # Skip zero amount lines

            # Get tracking categories if available
            tracking = []
            if acc.cost_center:
                cost_center_tracking_id = frappe.db.get_value("Cost Center", acc.cost_center, "xero_tracking_category_id")
                cost_center_tracking_option = frappe.db.get_value("Cost Center", acc.cost_center, "xero_tracking_option_id")
                if cost_center_tracking_id and cost_center_tracking_option:
                    tracking.append({
                        "TrackingCategoryID": cost_center_tracking_id,
                        "TrackingOptionID": cost_center_tracking_option
                    })

            if acc.project:
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
            "ManualJournalLines": journal_lines,
            "Status": "POSTED",  # ERPNext submitted = Xero posted
            "LineAmountTypes": "INCLUSIVE",
            "ShowOnCashBasisReports": True
        }

        # If updating, include the Xero Manual Journal ID
        if xero_journal_id:
            journal_payload["ManualJournalID"] = xero_journal_id

        # --- Make API Call (PUT for create/update) ---
        response = xero_request("PUT", "ManualJournals", data={"ManualJournals": [journal_payload]})

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
                frappe.db.commit()

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


@frappe.whitelist()
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
            frappe.db.commit()

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

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Manual Journals page {page}", "Xero Sync")
            
            params = {"page": page}
            if from_date:
                params["modifiedAfter"] = from_date
                
            response = xero_request("GET", "ManualJournals", params=params)

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

    try:
        # Get journal lines
        journal_lines = xero_journal_data.get("ManualJournalLines", [])
        if not journal_lines:
            log_xero_error(message=f"Skipping Xero manual journal {xero_journal_id}: No journal lines", status="Info")
            return

        # Map Xero Data to ERPNext Fields
        accounts = []
        for line in journal_lines:
            account_code = line.get("AccountCode")
            if not account_code:
                continue

            # Find corresponding ERPNext account
            account = frappe.db.get_value("Account", {"account_number": account_code}, "name")
            if not account:
                account = frappe.db.get_value("Account", {"xero_account_code": account_code}, "name")
            
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
                
                # Try to find cost center
                cost_center = frappe.db.get_value("Cost Center", {
                    "xero_tracking_category_id": tracking_category_id,
                    "xero_tracking_option_id": tracking_option_id
                }, "name")
                
                if cost_center:
                    account_entry["cost_center"] = cost_center
                else:
                    # Try to find project
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

        erpnext_data = {
            "posting_date": getdate(xero_journal_data.get("Date")),
            "title": xero_journal_data.get("Narration", f"Manual Journal from Xero {xero_journal_id}"),
            "user_remark": xero_journal_data.get("Narration"),
            "accounts": accounts,
            "xero_manual_journal_id": xero_journal_id,
            "xero_sync_status": "Synced",
        }

        if erpnext_doc_name:
            # Update existing journal
            doc = frappe.get_doc("Journal Entry", erpnext_doc_name)
            doc.update(erpnext_data)
            doc.save(ignore_permissions=True)
            log_message = f"Updated Journal Entry {erpnext_doc_name} from Xero Manual Journal {xero_journal_id}"
        else:
            # Create new journal
            doc = frappe.new_doc("Journal Entry")
            doc.update(erpnext_data)
            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created Journal Entry {erpnext_doc_name} from Xero Manual Journal {xero_journal_id}"

        frappe.db.commit()
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
        sync_status = "Error"
        if erpnext_doc_name:
            frappe.db.set_value("Journal Entry", erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
            frappe.db.commit()

        log_xero_error(
            message=f"Failed to sync Xero Manual Journal {xero_journal_id} to ERPNext",
            erpnext_doc_type="Journal Entry",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_journal_id,
            xero_entity_type="ManualJournal",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )


@frappe.whitelist()
def reconcile_manual_journals(from_date=None, to_date=None):
    """
    Reconcile manual journals between ERPNext and Xero for a specific date range.
    
    Args:
        from_date: Start date for reconciliation
        to_date: End date for reconciliation
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw("Xero sync is not enabled.")

    try:
        # Sync manual journals from Xero
        sync_manual_journals_from_xero(from_date, to_date)

        # Get ERPNext journals for comparison
        filters = {
            "docstatus": 1
        }
        
        if from_date:
            filters["posting_date"] = [">=", from_date]
        if to_date:
            if "posting_date" in filters:
                filters["posting_date"] = ["between", [from_date, to_date]]
            else:
                filters["posting_date"] = ["<=", to_date]

        erpnext_journals = frappe.get_all(
            "Journal Entry",
            filters=filters,
            fields=["name", "posting_date", "title", "xero_manual_journal_id"]
        )

        # Create reconciliation report
        reconciliation_data = {
            "from_date": from_date,
            "to_date": to_date,
            "total_erpnext_journals": len(erpnext_journals),
            "synced_journals": len([j for j in erpnext_journals if j.xero_manual_journal_id]),
            "unsynced_journals": len([j for j in erpnext_journals if not j.xero_manual_journal_id]),
        }

        frappe.msgprint(f"Manual journal reconciliation completed. {reconciliation_data['synced_journals']} journals synced, {reconciliation_data['unsynced_journals']} unsynced.")
        
        return reconciliation_data

    except Exception as e:
        log_xero_error(
            message=f"Error during manual journal reconciliation",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Manual journal reconciliation failed: {str(e)}")
