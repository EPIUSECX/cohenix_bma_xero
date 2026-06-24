# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, add_days, flt
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff

# --- Financial Reports Sync (Xero to ERPNext) ---

@retry_with_exponential_backoff(max_retries=2, base_delay=3)
def sync_trial_balance_from_xero(date=None):
    """
    Fetches the Trial Balance from Xero and stores it as Xero Trial Balance
    summary records in ERPNext. This does NOT create or update GL Entry records;
    it only mirrors Xero's report figures into a read-only summary doctype.

    Args:
        date: Date for the trial balance (defaults to today)
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping trial balance inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_financial_reports"): return

    if not date:
        date = nowdate()

    try:
        frappe.logger().info(f"Fetching Trial Balance from Xero for date {date}", "Xero Sync")
        
        params = {"date": date}
        response = xero_request("GET", "Reports/TrialBalance", params=params)

        if not response or not response.get("Reports"):
            log_xero_error(message="No trial balance data found or error fetching from Xero.", status="Warning")
            return

        trial_balance = response["Reports"][0]
        process_trial_balance_data(trial_balance, date)

        log_xero_error(message=f"Successfully synced Trial Balance from Xero for {date}", status="Success")

    except Exception as e:
        log_xero_error(
            message=f"Error syncing Trial Balance from Xero for {date}",
            error_details=frappe.get_traceback()
        )


def process_trial_balance_data(trial_balance_data, date):
    """Process trial balance data and create summary records."""
    try:
        # Create or update a custom DocType for storing trial balance data
        # This is a summary view, not detailed GL entries
        
        rows = trial_balance_data.get("Rows", [])
        company = frappe.defaults.get_user_default("company")
        
        for row in rows:
            if row.get("RowType") == "Row" and row.get("Cells"):
                cells = row["Cells"]
                if len(cells) >= 3:
                    account_name = cells[0].get("Value", "")
                    # flt tolerates blank cells and thousands separators
                    debit_amount = flt(cells[1].get("Value"))
                    credit_amount = flt(cells[2].get("Value"))
                    
                    if account_name and (debit_amount != 0 or credit_amount != 0):
                        # Find corresponding ERPNext account
                        erpnext_account = find_erpnext_account_by_name(account_name, company)
                        
                        if erpnext_account:
                            create_trial_balance_entry(
                                date, erpnext_account, account_name, 
                                debit_amount, credit_amount, company
                            )

    except Exception as e:
        log_xero_error(
            message="Error processing trial balance data",
            error_details=frappe.get_traceback()
        )


def create_trial_balance_entry(date, account, xero_account_name, debit, credit, company):
    """Create a trial balance summary entry."""
    try:
        # Check if entry already exists
        existing = frappe.db.exists("Xero Trial Balance", {
            "date": date,
            "account": account,
            "company": company
        })
        
        if existing:
            # Update existing entry
            doc = frappe.get_doc("Xero Trial Balance", existing)
            doc.debit_amount = debit
            doc.credit_amount = credit
            doc.xero_account_name = xero_account_name
            doc.save(ignore_permissions=True)
        else:
            # Create new entry
            doc = frappe.new_doc("Xero Trial Balance")
            doc.date = date
            doc.account = account
            doc.xero_account_name = xero_account_name
            doc.debit_amount = debit
            doc.credit_amount = credit
            doc.company = company
            doc.insert(ignore_permissions=True)
        
        frappe.db.commit()
        
    except Exception as e:
        log_xero_error(
            message=f"Error creating trial balance entry for account {account}",
            error_details=str(e)
        )


@retry_with_exponential_backoff(max_retries=2, base_delay=3)
def sync_profit_loss_from_xero(from_date=None, to_date=None):
    """
    Fetches the Profit & Loss report from Xero and stores it as Xero Profit Loss
    summary records in ERPNext. This does NOT create or update GL Entry records;
    it only mirrors Xero's report figures into a read-only summary doctype.

    Args:
        from_date: Start date for the report
        to_date: End date for the report
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping P&L inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_financial_reports"): return

    if not from_date:
        from_date = add_days(nowdate(), -30)  # Last 30 days
    if not to_date:
        to_date = nowdate()

    try:
        frappe.logger().info(f"Fetching P&L from Xero from {from_date} to {to_date}", "Xero Sync")
        
        params = {
            "fromDate": from_date,
            "toDate": to_date
        }
        response = xero_request("GET", "Reports/ProfitAndLoss", params=params)

        if not response or not response.get("Reports"):
            log_xero_error(message="No P&L data found or error fetching from Xero.", status="Warning")
            return

        pl_report = response["Reports"][0]
        process_profit_loss_data(pl_report, from_date, to_date)

        log_xero_error(message=f"Successfully synced P&L from Xero for {from_date} to {to_date}", status="Success")

    except Exception as e:
        log_xero_error(
            message=f"Error syncing P&L from Xero for {from_date} to {to_date}",
            error_details=frappe.get_traceback()
        )


def process_profit_loss_data(pl_data, from_date, to_date):
    """Process P&L data and create summary records."""
    try:
        rows = pl_data.get("Rows", [])
        company = frappe.defaults.get_user_default("company")
        
        for row in rows:
            if row.get("RowType") == "Row" and row.get("Cells"):
                cells = row["Cells"]
                if len(cells) >= 2:
                    account_name = cells[0].get("Value", "")
                    # flt tolerates blank cells and thousands separators
                    amount = flt(cells[1].get("Value"))

                    if account_name and amount != 0:
                        # Find corresponding ERPNext account
                        erpnext_account = find_erpnext_account_by_name(account_name, company)

                        if erpnext_account:
                            create_pl_entry(
                                from_date, to_date, erpnext_account, 
                                account_name, amount, company
                            )

    except Exception as e:
        log_xero_error(
            message="Error processing P&L data",
            error_details=frappe.get_traceback()
        )


def create_pl_entry(from_date, to_date, account, xero_account_name, amount, company):
    """Create a P&L summary entry."""
    try:
        # Check if entry already exists
        existing = frappe.db.exists("Xero Profit Loss", {
            "from_date": from_date,
            "to_date": to_date,
            "account": account,
            "company": company
        })
        
        if existing:
            # Update existing entry
            doc = frappe.get_doc("Xero Profit Loss", existing)
            doc.amount = amount
            doc.xero_account_name = xero_account_name
            doc.save(ignore_permissions=True)
        else:
            # Create new entry
            doc = frappe.new_doc("Xero Profit Loss")
            doc.from_date = from_date
            doc.to_date = to_date
            doc.account = account
            doc.xero_account_name = xero_account_name
            doc.amount = amount
            doc.company = company
            doc.insert(ignore_permissions=True)
        
        frappe.db.commit()
        
    except Exception as e:
        log_xero_error(
            message=f"Error creating P&L entry for account {account}",
            error_details=str(e)
        )


@retry_with_exponential_backoff(max_retries=2, base_delay=3)
def sync_balance_sheet_from_xero(date=None):
    """
    Fetches the Balance Sheet from Xero and stores it as Xero Balance Sheet
    summary records in ERPNext. This does NOT create or update GL Entry records;
    it only mirrors Xero's report figures into a read-only summary doctype.

    Args:
        date: Date for the balance sheet (defaults to today)
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping balance sheet inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_financial_reports"): return

    if not date:
        date = nowdate()

    try:
        frappe.logger().info(f"Fetching Balance Sheet from Xero for date {date}", "Xero Sync")
        
        params = {"date": date}
        response = xero_request("GET", "Reports/BalanceSheet", params=params)

        if not response or not response.get("Reports"):
            log_xero_error(message="No balance sheet data found or error fetching from Xero.", status="Warning")
            return

        balance_sheet = response["Reports"][0]
        process_balance_sheet_data(balance_sheet, date)

        log_xero_error(message=f"Successfully synced Balance Sheet from Xero for {date}", status="Success")

    except Exception as e:
        log_xero_error(
            message=f"Error syncing Balance Sheet from Xero for {date}",
            error_details=frappe.get_traceback()
        )


def process_balance_sheet_data(bs_data, date):
    """Process balance sheet data and create summary records."""
    try:
        rows = bs_data.get("Rows", [])
        company = frappe.defaults.get_user_default("company")
        
        for row in rows:
            if row.get("RowType") == "Row" and row.get("Cells"):
                cells = row["Cells"]
                if len(cells) >= 2:
                    account_name = cells[0].get("Value", "")
                    # flt tolerates blank cells and thousands separators
                    amount = flt(cells[1].get("Value"))

                    if account_name and amount != 0:
                        # Find corresponding ERPNext account
                        erpnext_account = find_erpnext_account_by_name(account_name, company)

                        if erpnext_account:
                            create_balance_sheet_entry(
                                date, erpnext_account, account_name, amount, company
                            )

    except Exception as e:
        log_xero_error(
            message="Error processing balance sheet data",
            error_details=frappe.get_traceback()
        )


def create_balance_sheet_entry(date, account, xero_account_name, amount, company):
    """Create a balance sheet summary entry."""
    try:
        # Check if entry already exists
        existing = frappe.db.exists("Xero Balance Sheet", {
            "date": date,
            "account": account,
            "company": company
        })
        
        if existing:
            # Update existing entry
            doc = frappe.get_doc("Xero Balance Sheet", existing)
            doc.amount = amount
            doc.xero_account_name = xero_account_name
            doc.save(ignore_permissions=True)
        else:
            # Create new entry
            doc = frappe.new_doc("Xero Balance Sheet")
            doc.date = date
            doc.account = account
            doc.xero_account_name = xero_account_name
            doc.amount = amount
            doc.company = company
            doc.insert(ignore_permissions=True)
        
        frappe.db.commit()
        
    except Exception as e:
        log_xero_error(
            message=f"Error creating balance sheet entry for account {account}",
            error_details=str(e)
        )


def find_erpnext_account_by_name(xero_account_name, company, xero_account_id=None):
    """Find the ERPNext account that corresponds to a Xero report row.

    Matching is EXACT ONLY. Fuzzy substring matching was removed because it
    silently mapped report figures onto the wrong account (e.g. "Sales" matching
    "Sales Tax"), which corrupts the mirrored summary. Resolution order:
      1. Stored Xero account id (xero_account_id custom field), if supplied.
      2. account_number == the Xero account code (report rows sometimes expose
         the code as the row value, e.g. "200").
      3. Exact account_name match.
    If none match exactly we log a Warning and return None so the caller SKIPS
    the row rather than guessing.
    """
    # 1. Exact match on the stored Xero account id, when the caller has one.
    if xero_account_id:
        account = frappe.db.get_value("Account", {
            "xero_account_id": xero_account_id,
            "company": company
        }, "name")
        if account:
            return account

    # 2. Exact match on the Xero account code stored in account_number.
    account = frappe.db.get_value("Account", {
        "account_number": xero_account_name,
        "company": company
    }, "name")
    if account:
        return account

    # 3. Exact match on the account name.
    account = frappe.db.get_value("Account", {
        "account_name": xero_account_name,
        "company": company
    }, "name")
    if account:
        return account

    # No exact match: skip rather than guess a wrong account.
    log_xero_error(
        message=(
            f"No exact ERPNext Account match for Xero account "
            f"'{xero_account_name}' (company {company}); skipping this report row."
        ),
        status="Warning",
        category="Validation Errors",
        direction="Xero to ERPNext"
    )
    return None


@frappe.whitelist()
def sync_aged_receivables_from_xero(contact_id=None, report_date=None):
    """
    Sync aged receivables report from Xero.
    
    Args:
        contact_id: Specific contact ID to get aged receivables for
        report_date: Date for the aged receivables report
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping aged receivables inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_financial_reports"): return

    if not report_date:
        report_date = nowdate()

    try:
        frappe.logger().info(f"Fetching Aged Receivables from Xero for {report_date}", "Xero Sync")
        
        if contact_id:
            # Get aged receivables for specific contact
            params = {
                "contactId": contact_id,
                "reportDate": report_date
            }
            response = xero_request("GET", f"Reports/AgedReceivablesByContact", params=params)
        else:
            # Get summary aged receivables
            params = {"date": report_date}
            response = xero_request("GET", "Reports/AgedReceivables", params=params)

        if response and response.get("Reports"):
            aged_receivables = response["Reports"][0]
            process_aged_receivables_data(aged_receivables, report_date, contact_id)
            
            log_xero_error(
                message=f"Successfully synced Aged Receivables from Xero for {report_date}",
                status="Success"
            )

    except Exception as e:
        log_xero_error(
            message=f"Error syncing Aged Receivables from Xero for {report_date}",
            error_details=frappe.get_traceback()
        )


def process_aged_receivables_data(aged_data, report_date, contact_id=None):
    """Process aged receivables data."""
    try:
        rows = aged_data.get("Rows", [])
        company = frappe.defaults.get_user_default("company")
        
        for row in rows:
            if row.get("RowType") == "Row" and row.get("Cells"):
                cells = row["Cells"]
                if len(cells) >= 6:  # Contact, Current, 1-30, 31-60, 61-90, 90+
                    contact_name = cells[0].get("Value", "")
                    # flt tolerates blank cells and thousands separators
                    current = flt(cells[1].get("Value"))
                    days_1_30 = flt(cells[2].get("Value"))
                    days_31_60 = flt(cells[3].get("Value"))
                    days_61_90 = flt(cells[4].get("Value"))
                    days_90_plus = flt(cells[5].get("Value"))
                    
                    total_outstanding = current + days_1_30 + days_31_60 + days_61_90 + days_90_plus
                    
                    if contact_name and total_outstanding != 0:
                        create_aged_receivables_entry(
                            report_date, contact_name, current, days_1_30,
                            days_31_60, days_61_90, days_90_plus, company
                        )

    except Exception as e:
        log_xero_error(
            message="Error processing aged receivables data",
            error_details=frappe.get_traceback()
        )


def create_aged_receivables_entry(date, contact_name, current, days_1_30, days_31_60, days_61_90, days_90_plus, company):
    """Create aged receivables entry."""
    try:
        # Check if entry already exists
        existing = frappe.db.exists("Xero Aged Receivables", {
            "date": date,
            "contact_name": contact_name,
            "company": company
        })
        
        if existing:
            # Update existing entry
            doc = frappe.get_doc("Xero Aged Receivables", existing)
        else:
            # Create new entry
            doc = frappe.new_doc("Xero Aged Receivables")
            doc.date = date
            doc.contact_name = contact_name
            doc.company = company
        
        doc.current = current
        doc.days_1_30 = days_1_30
        doc.days_31_60 = days_31_60
        doc.days_61_90 = days_61_90
        doc.days_90_plus = days_90_plus
        doc.total_outstanding = current + days_1_30 + days_31_60 + days_61_90 + days_90_plus
        
        if existing:
            doc.save(ignore_permissions=True)
        else:
            doc.insert(ignore_permissions=True)
        
        frappe.db.commit()
        
    except Exception as e:
        log_xero_error(
            message=f"Error creating aged receivables entry for {contact_name}",
            error_details=str(e)
        )