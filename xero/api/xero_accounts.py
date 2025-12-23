# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error

# Mapping from Xero Account Types to ERPNext Root Types / Account Types
# This might need refinement based on specific CoA structures
XERO_ACCOUNT_TYPE_MAP = {
    "BANK": {"root_type": "Asset", "account_type": "Bank"},
    "CURRENT": {"root_type": "Asset", "account_type": "Receivable"}, # Or other Current Asset
    "CURRLIAB": {"root_type": "Liability", "account_type": "Payable"}, # Or other Current Liability
    "DEPRECIATN": {"root_type": "Asset", "account_type": "Accumulated Depreciation"},
    "DIRECTCOSTS": {"root_type": "Expense", "account_type": "Direct Expense"},
    "EQUITY": {"root_type": "Equity", "account_type": "Equity"},
    "EXPENSE": {"root_type": "Expense", "account_type": "Expense Account"},
    "FIXED": {"root_type": "Asset", "account_type": "Fixed Asset"},
    "INVENTORY": {"root_type": "Asset", "account_type": "Stock"},
    "LIABILITY": {"root_type": "Liability", "account_type": "Liability"},
    "NONCURRENT": {"root_type": "Asset", "account_type": "Asset"}, # Non-current asset
    "OTHERINCOME": {"root_type": "Income", "account_type": "Other Income"},
    "OVERHEADS": {"root_type": "Expense", "account_type": "Indirect Expense"},
    "PREPAYMENT": {"root_type": "Asset", "account_type": "Prepaid Expense"},
    "REVENUE": {"root_type": "Income", "account_type": "Income Account"},
    "SALES": {"root_type": "Income", "account_type": "Sales"},
    "TERMLIAB": {"root_type": "Liability", "account_type": "Liability"}, # Long term liability
    # Add more mappings as needed based on Xero's full list:
    # https://developer.xero.com/documentation/api/types#AccountTypes
}

# --- Chart of Accounts Sync ---

def sync_accounts_from_xero():
    """
    Fetches the Chart of Accounts from Xero and creates/updates
    corresponding Accounts in ERPNext for the default company.
    Does not handle hierarchy/parenting yet.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        # frappe.logger().info("Xero Sync master switch is disabled.", "Xero Info")
        return # Master switch disabled
    if not settings.sync_chart_of_accounts:
        return # CoA sync specifically disabled

    # TODO: Handle multi-company environments - select company based on settings or context
    company = frappe.defaults.get_user_default("company")
    if not company:
        frappe.throw(_("Default Company not set for user {0}").format(frappe.session.user))

    try:
        frappe.logger().info("Starting Chart of Accounts sync from Xero", "Xero Sync")
        # Fetch all accounts (Xero doesn't seem to paginate Accounts endpoint by default?)
        response = xero_request("GET", "Accounts")

        if not response or not response.get("Accounts"):
            log_xero_error(message="No accounts found or error fetching accounts from Xero.", status="Info")
            return

        accounts = response["Accounts"]
        processed_count = 0
        for account in accounts:
            try:
                # We only sync accounts that can have payments made to them,
                # or standard types. Skip system accounts unless necessary.
                if account.get("SystemAccount") in ["DEBTORS", "CREDITORS", "BANKCURRENCYGAIN"]: # Example system accounts to skip
                     continue
                if not account.get("EnablePaymentsToAccount") and account.get("Type") not in XERO_ACCOUNT_TYPE_MAP:
                    continue # Skip accounts that can't receive payments and aren't standard types we map

                process_xero_account(account, company)
                processed_count += 1
            except Exception as e:
                 log_xero_error(
                    message=f"Failed to process Xero Account ID {account.get('AccountID')}",
                    xero_entity_id=account.get('AccountID'),
                    xero_entity_type="Account",
                    error_details=frappe.get_traceback()
                )

        log_xero_error(message=f"Finished syncing Chart of Accounts from Xero. Processed {processed_count} accounts.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_accounts_from_xero",
            error_details=frappe.get_traceback()
        )


def process_xero_account(xero_account_data, company):
    """Creates or updates an ERPNext Account from Xero account data."""
    xero_account_id = xero_account_data.get("AccountID")
    xero_code = xero_account_data.get("Code")
    xero_name = xero_account_data.get("Name")
    xero_type = xero_account_data.get("Type")

    if not xero_account_id or not xero_name or not xero_type:
        log_xero_error(message=f"Skipping Xero account due to missing ID, Name, or Type: {xero_account_data}", status="Info")
        return

    # --- Map Xero Type to ERPNext Type ---
    erpnext_type_info = XERO_ACCOUNT_TYPE_MAP.get(xero_type)
    if not erpnext_type_info:
        log_xero_error(message=f"Skipping Xero account '{xero_name}' ({xero_code}) - Unmapped Xero Type: {xero_type}", status="Info")
        return

    erpnext_account_name = f"{xero_code} - {xero_name}" if xero_code else xero_name
    # Truncate if name is too long for ERPNext Account Name (default 140)
    erpnext_account_name = erpnext_account_name[:140]

    # --- Check if ERPNext Account Exists ---
    # Prioritize matching by Xero ID stored in a custom field if we implement that later.
    # For now, match by name (combination of code and name) within the company.
    erpnext_doc_name = frappe.db.get_value("Account", {"account_name": erpnext_account_name, "company": company}, "name")

    # --- Prepare ERPNext Data ---
    erpnext_data = {
        "account_name": erpnext_account_name,
        "account_number": xero_code, # Use Xero code as account number
        "account_type": erpnext_type_info["account_type"],
        "root_type": erpnext_type_info["root_type"],
        "company": company,
        "currency": xero_account_data.get("CurrencyCode") or frappe.get_cached_value('Company', company, 'default_currency'),
        "report_type": "Balance Sheet" if erpnext_type_info["root_type"] in ["Asset", "Liability", "Equity"] else "Profit and Loss",
        "is_group": 0, # Assume all synced accounts are ledger accounts for now
        "xero_account_id": xero_account_id, # Store the Xero ID
        # TODO: Map Xero TaxType to ERPNext Account Subtype or Tax Rate? Requires Tax Rate sync first.
        # "tax_rate": map_xero_tax_type(xero_account_data.get("TaxType"))
    }

    # --- Create or Update ERPNext Account ---
    try:
        if erpnext_doc_name:
            # Update existing account
            doc = frappe.get_doc("Account", erpnext_doc_name)
            # Update existing account
            # Only update certain fields? Avoid changing root type/account type?
            doc.account_number = erpnext_data["account_number"]
            doc.currency = erpnext_data["currency"]
            doc.xero_account_id = xero_account_id # Ensure ID is updated if matched by name initially
            # doc.tax_rate = erpnext_data["tax_rate"] # If implemented
            doc.flags.ignore_mandatory = True # In case root type/account type makes other fields mandatory
            doc.save(ignore_permissions=True)
            log_message = f"Updated Account {erpnext_doc_name} from Xero Account {xero_account_id}"
        else:
            # Create new account
            doc = frappe.new_doc("Account")
            doc.update(erpnext_data)
            
            # Set parent account based on root type (requires standard Frappe CoA structure)
            parent_account = f"{erpnext_data['root_type']} - {frappe.get_cached_value('Company', company, 'abbr')}"
            if frappe.db.exists("Account", parent_account):
                doc.parent_account = parent_account
            else:
                # Try to find or create the root account as a group
                try:
                    root_doc = frappe.new_doc("Account")
                    root_doc.account_name = f"{erpnext_data['root_type']} - {frappe.get_cached_value('Company', company, 'abbr')}"
                    root_doc.account_type = None  # Root accounts don't have account types
                    root_doc.root_type = erpnext_data['root_type']
                    root_doc.company = company
                    root_doc.is_group = 1  # Root accounts must be groups
                    root_doc.flags.ignore_mandatory = True
                    root_doc.insert(ignore_permissions=True)
                    doc.parent_account = root_doc.name
                    log_xero_error(f"Created root account '{root_doc.name}' for new account '{erpnext_account_name}'.", status="Info")
                except Exception as e:
                    # If root creation fails, try to find existing root or use company default
                    existing_root = frappe.db.get_value("Account",
                        {"root_type": erpnext_data['root_type'], "company": company, "is_group": 1},
                        "name")
                    if existing_root:
                        doc.parent_account = existing_root
                    else:
                        log_xero_error(f"Could not create or find root account for '{erpnext_account_name}'. Account creation may fail.", status="Error")

            doc.flags.ignore_mandatory = True
            doc.flags.ignore_permissions = True
            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created Account {erpnext_doc_name} from Xero Account {xero_account_id}"

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type="Account",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_account_id,
            xero_entity_type="Account",
            direction="Xero to ERPNext"
        )

    except Exception as e:
        log_xero_error(
            message=f"Failed to sync Xero Account {xero_account_id} ({xero_name}) to ERPNext Account",
            erpnext_doc_type="Account",
            erpnext_doc_name=erpnext_doc_name, # Might be None if creation failed
            xero_entity_id=xero_account_id,
            xero_entity_type="Account",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )


# --- Whitelisted Functions for UI ---

@frappe.whitelist()
def fetch_xero_accounts():
    """
    Fetches accounts from Xero for display in the UI.
    Returns formatted account data for the Xero Settings interface.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw("Xero sync is not enabled.")
    
    try:
        response = xero_request("GET", "Accounts")
        
        if not response or not response.get("Accounts"):
            frappe.msgprint("No accounts found in Xero.")
            return []
        
        accounts = response["Accounts"]
        formatted_accounts = []
        
        for account in accounts:
            # Skip system accounts that shouldn't be displayed
            if account.get("SystemAccount") in ["DEBTORS", "CREDITORS", "BANKCURRENCYGAIN"]:
                continue
                
            formatted_accounts.append({
                "account_id": account.get("AccountID"),
                "code": account.get("Code"),
                "name": account.get("Name"),
                "type": account.get("Type"),
                "tax_type": account.get("TaxType"),
                "enable_payments": account.get("EnablePaymentsToAccount", False),
                "status": account.get("Status"),
                "currency_code": account.get("CurrencyCode")
            })
        
        log_xero_error(
            message=f"Successfully fetched {len(formatted_accounts)} accounts from Xero.",
            status="Success"
        )
        
        frappe.msgprint(f"Successfully fetched {len(formatted_accounts)} accounts from Xero.")
        return formatted_accounts
        
    except Exception as e:
        log_xero_error(
            message="Failed to fetch accounts from Xero for UI display.",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Failed to fetch accounts from Xero: {str(e)}")


@frappe.whitelist()
def fetch_xero_tax_rates():
    """
    Fetches tax rates from Xero for display in the UI.
    Returns formatted tax rate data for the Xero Settings interface.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw("Xero sync is not enabled.")
    
    try:
        response = xero_request("GET", "TaxRates")
        
        if not response or not response.get("TaxRates"):
            frappe.msgprint("No tax rates found in Xero.")
            return []
        
        tax_rates = response["TaxRates"]
        formatted_tax_rates = []
        
        for tax_rate in tax_rates:
            # Get tax components for detailed information
            components = tax_rate.get("TaxComponents", [])
            total_rate = sum([float(comp.get("Rate", 0)) for comp in components])
            
            formatted_tax_rates.append({
                "name": tax_rate.get("Name"),
                "tax_type": tax_rate.get("TaxType"),
                "status": tax_rate.get("Status"),
                "report_tax_type": tax_rate.get("ReportTaxType"),
                "total_rate": total_rate,
                "components": [
                    {
                        "name": comp.get("Name"),
                        "rate": float(comp.get("Rate", 0)),
                        "is_compound": comp.get("IsCompound", False)
                    } for comp in components
                ]
            })
        
        log_xero_error(
            message=f"Successfully fetched {len(formatted_tax_rates)} tax rates from Xero.",
            status="Success"
        )
        
        frappe.msgprint(f"Successfully fetched {len(formatted_tax_rates)} tax rates from Xero.")
        return formatted_tax_rates
        
    except Exception as e:
        log_xero_error(
            message="Failed to fetch tax rates from Xero for UI display.",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Failed to fetch tax rates from Xero: {str(e)}")


# --- Tax Rate Sync ---

def get_xero_tax_rates():
    """
    Internal function to fetch Tax Rates from Xero for sync operations.
    """
    try:
        response = xero_request("GET", "TaxRates")
        if response and response.get("TaxRates"):
            log_xero_error(message="Fetched Tax Rates from Xero.", status="Info")
            return response["TaxRates"]
        else:
            log_xero_error(message="No Tax Rates found or error fetching from Xero.", status="Info")
            return []
    except Exception as e:
        log_xero_error(
            message="Failed to fetch Tax Rates from Xero.",
            error_details=frappe.get_traceback()
        )
        return []

@frappe.whitelist()
def fetch_and_update_account_mapping():
    """
    Fetches accounts from Xero for display purposes only.
    Does not automatically populate the Account Mapping table since erpnext_account is required.
    This function is called by the "Fetch Xero Accounts" button.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw("Xero sync is not enabled.")
    
    try:
        # Fetch accounts from Xero
        response = xero_request("GET", "Accounts")
        
        if not response or not response.get("Accounts"):
            frappe.msgprint("No accounts found in Xero.")
            return []
        
        accounts = response["Accounts"]
        formatted_accounts = []
        
        for account in accounts:
            # Skip system accounts that shouldn't be displayed
            if account.get("SystemAccount") in ["DEBTORS", "CREDITORS", "BANKCURRENCYGAIN"]:
                continue
                
            # Skip inactive accounts
            if account.get("Status") != "ACTIVE":
                continue
                
            formatted_accounts.append({
                "account_id": account.get("AccountID"),
                "code": account.get("Code"),
                "name": account.get("Name"),
                "type": account.get("Type"),
                "tax_type": account.get("TaxType"),
                "enable_payments": account.get("EnablePaymentsToAccount", False),
                "status": account.get("Status"),
                "currency_code": account.get("CurrencyCode")
            })
        
        log_xero_error(
            message=f"Successfully fetched {len(formatted_accounts)} accounts from Xero.",
            status="Success"
        )
        
        frappe.msgprint(f"Successfully fetched {len(formatted_accounts)} accounts from Xero. You can now manually create account mappings by selecting ERPNext accounts and corresponding Xero account codes.")
        return formatted_accounts
        
    except Exception as e:
        log_xero_error(
            message="Failed to fetch accounts from Xero.",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Failed to fetch accounts from Xero: {str(e)}")


@frappe.whitelist()
def fetch_and_update_tax_mapping():
    """
    Fetches tax rates from Xero for display purposes only.
    Does not automatically populate the Tax Mapping table since erpnext_tax_template is required.
    This function is called by the "Fetch Xero Tax Rates" button.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        frappe.throw("Xero sync is not enabled.")
    
    try:
        # Fetch tax rates from Xero
        response = xero_request("GET", "TaxRates")
        
        if not response or not response.get("TaxRates"):
            frappe.msgprint("No tax rates found in Xero.")
            return []
        
        tax_rates = response["TaxRates"]
        formatted_tax_rates = []
        
        for tax_rate in tax_rates:
            # Skip inactive tax rates
            if tax_rate.get("Status") != "ACTIVE":
                continue
            
            # Get tax components for detailed information
            components = tax_rate.get("TaxComponents", [])
            total_rate = sum([float(comp.get("Rate", 0)) for comp in components])
            
            formatted_tax_rates.append({
                "name": tax_rate.get("Name"),
                "tax_type": tax_rate.get("TaxType"),
                "status": tax_rate.get("Status"),
                "report_tax_type": tax_rate.get("ReportTaxType"),
                "tax_rate": total_rate,
                "components": [
                    {
                        "name": comp.get("Name"),
                        "rate": float(comp.get("Rate", 0)),
                        "is_compound": comp.get("IsCompound", False)
                    } for comp in components
                ]
            })
        
        log_xero_error(
            message=f"Successfully fetched {len(formatted_tax_rates)} tax rates from Xero.",
            status="Success"
        )
        
        frappe.msgprint(f"Successfully fetched {len(formatted_tax_rates)} tax rates from Xero. You can now manually create tax mappings by selecting ERPNext tax templates and corresponding Xero tax types.")
        return formatted_tax_rates
        
    except Exception as e:
        log_xero_error(
            message="Failed to fetch tax rates from Xero.",
            error_details=frappe.get_traceback()
        )
        frappe.throw(f"Failed to fetch tax rates from Xero: {str(e)}")


@frappe.whitelist()
def get_xero_account_options():
    """
    Returns Xero account options for dropdown fields.
    """
    try:
        response = xero_request("GET", "Accounts")
        
        if not response or not response.get("Accounts"):
            return []
        
        accounts = response["Accounts"]
        options = []
        
        for account in accounts:
            if account.get("Status") == "ACTIVE" and account.get("Code"):
                options.append({
                    "value": account.get("Code"),
                    "label": f"{account.get('Code')} - {account.get('Name')}"
                })
        
        return sorted(options, key=lambda x: x["value"])
        
    except Exception as e:
        frappe.log_error(f"Error fetching Xero account options: {str(e)}")
        return []


@frappe.whitelist()
def get_xero_tax_type_options():
    """
    Returns Xero tax type options for dropdown fields.
    """
    try:
        response = xero_request("GET", "TaxRates")
        
        if not response or not response.get("TaxRates"):
            return []
        
        tax_rates = response["TaxRates"]
        options = []
        
        for tax_rate in tax_rates:
            if tax_rate.get("Status") == "ACTIVE" and tax_rate.get("TaxType"):
                options.append({
                    "value": tax_rate.get("TaxType"),
                    "label": f"{tax_rate.get('TaxType')} - {tax_rate.get('Name')}"
                })
        
        # Remove duplicates and sort
        unique_options = {opt["value"]: opt for opt in options}.values()
        return sorted(unique_options, key=lambda x: x["value"])
        
    except Exception as e:
        frappe.log_error(f"Error fetching Xero tax type options: {str(e)}")
        return []


# TODO: Implement map_xero_tax_type function if needed for account mapping
# def map_xero_tax_type(xero_tax_type):
#     # Logic to map Xero tax type code to an ERPNext Tax Rule or Account Subtype
#     # This likely requires fetching ERPNext tax templates/rules and comparing names/rates
#     pass

# TODO: Consider handling account hierarchy (parenting) based on Xero structure if possible/needed.

def sync_accounts_to_xero():
    """
    Sync ERPNext Accounts to Xero (placeholder function).
    This is a complex operation due to potential conflicts and different chart structures.
    For now, this is a placeholder that logs the operation.
    """
    from ..utils.logging import log_xero_error
    
    try:
        log_xero_error(
            message="Account sync to Xero initiated. This feature is under development.",
            status="Info"
        )
        
        # TODO: Implement actual account sync to Xero
        # This would involve:
        # 1. Getting ERPNext accounts that need to be synced
        # 2. Mapping ERPNext account types to Xero account types
        # 3. Creating/updating accounts in Xero via API
        # 4. Handling conflicts and validation errors
        
        return True
        
    except Exception as e:
        log_xero_error(
            message="Error during sync_accounts_to_xero",
            error_details=frappe.get_traceback()
        )
        return False
