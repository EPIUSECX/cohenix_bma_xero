# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import now_datetime
import hashlib
import re
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from ..utils.retry_handler import retry_with_exponential_backoff

# Mapping from Xero Account Types to ERPNext Root Types / Account Types
XERO_ACCOUNT_TYPE_MAP = {
    "BANK": {"root_type": "Asset", "account_type": "Bank"},
    "CURRENT": {"root_type": "Asset", "account_type": "Receivable"},
    "CURRLIAB": {"root_type": "Liability", "account_type": "Payable"},
    "DEPRECIATN": {"root_type": "Asset", "account_type": "Accumulated Depreciation"},
    "DIRECTCOSTS": {"root_type": "Expense", "account_type": "Direct Expense"},
    "EQUITY": {"root_type": "Equity", "account_type": "Equity"},
    "EXPENSE": {"root_type": "Expense", "account_type": "Expense Account"},
    "FIXED": {"root_type": "Asset", "account_type": "Fixed Asset"},
    "INVENTORY": {"root_type": "Asset", "account_type": "Stock"},
    "LIABILITY": {"root_type": "Liability", "account_type": "Liability"},
    "NONCURRENT": {"root_type": "Asset", "account_type": "Asset"},
    "OTHERINCOME": {"root_type": "Income", "account_type": "Other Income"},
    "OVERHEADS": {"root_type": "Expense", "account_type": "Indirect Expense"},
    "PREPAYMENT": {"root_type": "Asset", "account_type": "Prepaid Expense"},
    "REVENUE": {"root_type": "Income", "account_type": "Income Account"},
    "SALES": {"root_type": "Income", "account_type": "Sales"},
    "TERMLIAB": {"root_type": "Liability", "account_type": "Liability"},
}

# Reverse mapping: ERPNext (root_type, account_type) -> Xero Type
# Order matters - more specific mappings should come first
ERPNEXT_TO_XERO_TYPE_MAP = {
    # Bank accounts
    ("Asset", "Bank"): "BANK",
    
    # Assets - specific types first
    ("Asset", "Receivable"): "CURRENT",
    ("Asset", "Accumulated Depreciation"): "DEPRECIATN",
    ("Asset", "Fixed Asset"): "FIXED",
    ("Asset", "Stock"): "INVENTORY",
    ("Asset", "Prepaid Expense"): "PREPAYMENT",
    ("Asset", "Asset"): "NONCURRENT",  # Generic non-current asset
    
    # Liabilities
    ("Liability", "Payable"): "CURRLIAB",
    ("Liability", "Liability"): "TERMLIAB",  # Long-term liability
    
    # Equity
    ("Equity", "Equity"): "EQUITY",
    
    # Income
    ("Income", "Income Account"): "REVENUE",
    ("Income", "Sales"): "SALES",
    ("Income", "Other Income"): "OTHERINCOME",
    
    # Expenses
    ("Expense", "Direct Expense"): "DIRECTCOSTS",
    ("Expense", "Expense Account"): "EXPENSE",
    ("Expense", "Indirect Expense"): "OVERHEADS",
    ("Expense", "Cost of Goods Sold"): "DIRECTCOSTS",
    
    # Receivable/Payable can be Asset or Liability
    ("Asset", "Payable"): "CURRLIAB",  # Unusual but possible
    ("Liability", "Receivable"): "CURRENT",  # Unusual but possible
}

# System accounts that should not be synced
XERO_SYSTEM_ACCOUNTS = ["DEBTORS", "CREDITORS", "BANKCURRENCYGAIN", "GST", "TAX", "HISTORICAL"]


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_account_code(code):
    """
    Validate and sanitize account code for Xero.
    - Max 10 characters
    - Alphanumeric only
    
    Returns sanitized code or raises ValueError.
    """
    if not code:
        raise ValueError("Account code is required for Xero sync")
    
    # Convert to string and truncate to 10 chars
    code = str(code)[:10]
    
    # Remove invalid characters (keep alphanumeric)
    code = re.sub(r'[^a-zA-Z0-9]', '', code)
    
    if not code:
        raise ValueError("Account code must contain alphanumeric characters after sanitization")
    
    return code


def validate_account_name(name):
    """
    Validate and sanitize account name for Xero.
    - Max 150 characters
    - No special restrictions per Xero docs
    
    Returns sanitized name or raises ValueError.
    """
    if not name:
        raise ValueError("Account name is required for Xero sync")
    
    # Truncate to 150 chars and strip whitespace
    return str(name)[:150].strip()


def get_xero_type_from_erpnext(root_type, account_type):
    """
    Map ERPNext account types to Xero account type.
    
    Args:
        root_type: ERPNext root_type (Asset, Liability, Equity, Income, Expense)
        account_type: ERPNext account_type (Bank, Receivable, etc.)
    
    Returns:
        Xero account type string or None if no mapping found
    """
    # Try exact match first
    xero_type = ERPNEXT_TO_XERO_TYPE_MAP.get((root_type, account_type))
    
    if xero_type:
        return xero_type
    
    # Try with just root_type
    for (rt, at), xt in ERPNEXT_TO_XERO_TYPE_MAP.items():
        if rt == root_type and at == account_type:
            return xt
    
    # Fallback based on root_type
    if root_type == "Asset":
        return "CURRENT"
    elif root_type == "Liability":
        return "CURRLIAB"
    elif root_type == "Equity":
        return "EQUITY"
    elif root_type == "Income":
        return "REVENUE"
    elif root_type == "Expense":
        return "EXPENSE"
    
    return None


def compute_account_hash(doc):
    """
    Compute MD5 hash of account data for change detection.
    
    This helps avoid unnecessary syncs when nothing has changed.
    """
    # Include key fields that affect Xero sync
    # Use getattr with default to handle missing attributes
    data = "|".join([
        str(doc.account_number or ""),
        str(doc.account_name or ""),
        str(doc.root_type or ""),
        str(doc.account_type or ""),
        str(getattr(doc, 'currency', '') or ""),
        str(doc.disabled or 0),
        str(getattr(doc, 'bank_account_no', '') or ""),  # For bank accounts
    ])
    return hashlib.md5(data.encode()).hexdigest()


def account_data_changed(doc):
    """
    Check if account data has changed since last sync.
    
    Returns True if:
    - No hash exists (never synced)
    - Hash doesn't match (data changed)
    """
    if not doc.xero_data_hash:
        return True
    return compute_account_hash(doc) != doc.xero_data_hash


# =============================================================================
# OUTBOUND SYNC (ERPNext → Xero)
# =============================================================================

@frappe.whitelist()
def enqueue_sync_account(doc, method=None):
    """
    Enqueue account sync to Xero when Account is updated.
    Called via doc_events hook on Account.on_update.
    
    Args:
        doc: Account document (can be string for whitelisted call)
        method: Hook method name (unused, for hook compatibility)
    """
    # Handle string input from whitelisted calls
    if isinstance(doc, str):
        doc = frappe.get_doc("Account", doc)
    
    settings = get_xero_settings()
    
    # Check master switch
    if not settings or not settings.enable_xero_sync:
        return
    
    # Check directional toggle
    if not settings.enable_sync_to_xero:
        return
    
    # Skip group accounts (only sync ledger accounts)
    if doc.is_group:
        return
    
    # Skip if no changes since last sync
    if doc.xero_sync_status == "Synced" and not account_data_changed(doc):
        return
    
    # Enqueue the actual sync
    frappe.enqueue(
        "xero.api.xero_accounts.sync_account_to_xero",
        queue="short",
        account_name=doc.name
    )


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_account_to_xero(account_name):
    """
    Sync a single ERPNext Account to Xero.
    Creates new account or updates existing one.
    
    Args:
        account_name: Name of the ERPNext Account to sync
    """
    doc = frappe.get_doc("Account", account_name)
    settings = get_xero_settings()
    
    if not settings or not settings.enable_xero_sync:
        return
    
    if not settings.enable_sync_to_xero:
        return
    
    # Skip group accounts
    if doc.is_group:
        log_xero_error(
            message=f"Skipping group account {doc.name} - only ledger accounts can sync to Xero",
            status="Info",
            erpnext_doc_type="Account",
            erpnext_doc_name=doc.name
        )
        return
    
    try:
        # Build Xero payload
        payload = build_xero_account_payload(doc, settings)
        
        if doc.xero_account_id:
            # Update existing - use POST with AccountID in URL
            response = xero_request(
                "POST",
                f"Accounts/{doc.xero_account_id}",
                data={"Accounts": [payload]}
            )
            action = "Updated"
        else:
            # Create new - use PUT
            response = xero_request(
                "PUT",
                "Accounts",
                data={"Accounts": [payload]}
            )
            action = "Created"
        
        # Process response
        if response and response.get("Accounts"):
            xero_account = response["Accounts"][0]
            xero_account_id = xero_account.get("AccountID")
            
            # Update ERPNext record with Xero data
            doc.db_set({
                "xero_account_id": xero_account_id,
                "xero_sync_status": "Synced",
                "xero_data_hash": compute_account_hash(doc),
                "xero_last_account_sync": now_datetime()
            })
            
            log_xero_error(
                message=f"{action} Account {doc.name} in Xero (ID: {xero_account_id})",
                status="Success",
                erpnext_doc_type="Account",
                erpnext_doc_name=doc.name,
                xero_entity_id=xero_account_id,
                xero_entity_type="Account",
                direction="ERPNext to Xero"
            )
        else:
            raise Exception("No account returned in Xero response")
            
    except ValueError as e:
        # Validation error - mark as skipped
        doc.db_set("xero_sync_status", "Skipped")
        log_xero_error(
            message=f"Validation error syncing Account {doc.name}: {str(e)}",
            status="Warning",
            erpnext_doc_type="Account",
            erpnext_doc_name=doc.name,
            direction="ERPNext to Xero"
        )
        
    except Exception as e:
        # API or other error - mark as error
        doc.db_set("xero_sync_status", "Error")
        log_xero_error(
            message=f"Failed to sync Account {doc.name} to Xero: {str(e)}",
            status="Error",
            erpnext_doc_type="Account",
            erpnext_doc_name=doc.name,
            direction="ERPNext to Xero",
            error_details=frappe.get_traceback()
        )


def build_xero_account_payload(doc, settings):
    """
    Build Xero API payload from ERPNext Account.
    Validates required fields and maps types.
    
    Args:
        doc: ERPNext Account document
        settings: Xero Settings document
    
    Returns:
        dict: Payload for Xero API
    
    Raises:
        ValueError: If required fields are missing or invalid
    """
    # Get Xero Type
    xero_type = get_xero_type_from_erpnext(doc.root_type, doc.account_type)
    if not xero_type:
        raise ValueError(f"Cannot map ERPNext account type ({doc.root_type}, {doc.account_type}) to Xero")
    
    # Validate and get code
    try:
        code = validate_account_code(doc.account_number or doc.name)
    except ValueError:
        # Try using just the first 10 alphanumeric chars of name
        code = validate_account_code(doc.name)
    
    # Validate name
    name = validate_account_name(doc.account_name)
    
    payload = {
        "Code": code,
        "Name": name,
        "Type": xero_type,
    }
    
    # Add AccountID for updates (required by Xero POST)
    if doc.xero_account_id:
        payload["AccountID"] = doc.xero_account_id
    
    # Map Status (disabled in ERPNext = ARCHIVED in Xero)
    if doc.disabled:
        payload["Status"] = "ARCHIVED"
    else:
        payload["Status"] = "ACTIVE"
    
    # Bank account specific fields
    if xero_type == "BANK":
        bank_account_no = getattr(doc, 'bank_account_no', None)
        if bank_account_no:
            payload["BankAccountNumber"] = bank_account_no
        else:
            # Bank accounts require BankAccountNumber
            raise ValueError(f"Bank account {doc.name} requires Bank Account Number for Xero sync")
        
        currency = getattr(doc, 'currency', None)
        if currency:
            payload["CurrencyCode"] = currency
    
    # Description (optional, not valid for bank accounts)
    description = getattr(doc, 'description', None)
    if xero_type != "BANK" and description:
        payload["Description"] = str(description)[:4000]
    
    return payload


def sync_accounts_to_xero():
    """
    Sync all pending ERPNext Accounts to Xero.
    Called from scheduled tasks or manual trigger.
    """
    settings = get_xero_settings()
    
    if not settings or not settings.enable_xero_sync:
        return
    
    if not settings.enable_sync_to_xero:
        log_xero_error(
            message="Sync to Xero is disabled. Skipping accounts outbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    # Get all accounts that need syncing
    pending_accounts = frappe.get_all(
        "Account",
        filters={
            "is_group": 0,
            "xero_sync_status": ["in", ["Pending", "Error"]],
            "disabled": 0  # Only active accounts
        },
        fields=["name"],
        limit=100  # Process in batches
    )
    
    synced_count = 0
    error_count = 0
    
    for account in pending_accounts:
        try:
            sync_account_to_xero(account.name)
            synced_count += 1
        except Exception as e:
            error_count += 1
            log_xero_error(
                message=f"Error in batch sync for Account {account.name}",
                error_details=str(e)
            )
    
    log_xero_error(
        message=f"Batch account sync completed: {synced_count} synced, {error_count} errors",
        status="Info"
    )
    
    return {"synced": synced_count, "errors": error_count}


# =============================================================================
# INBOUND SYNC (Xero → ERPNext)
# =============================================================================

def sync_accounts_from_xero():
    """
    Fetches the Chart of Accounts from Xero and creates/updates
    corresponding Accounts in ERPNext for the default company.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return
    
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping accounts inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.sync_chart_of_accounts:
        return
    
    company = frappe.defaults.get_user_default("company")
    if not company:
        frappe.throw(_("Default Company not set for user {0}").format(frappe.session.user))
    
    try:
        frappe.logger().info("Starting Chart of Accounts sync from Xero", "Xero Sync")
        response = xero_request("GET", "Accounts")
        
        if not response or not response.get("Accounts"):
            log_xero_error(message="No accounts found or error fetching accounts from Xero.", status="Info")
            return
        
        accounts = response["Accounts"]
        processed_count = 0
        
        for account in accounts:
            try:
                # Skip system accounts
                if account.get("SystemAccount") in XERO_SYSTEM_ACCOUNTS:
                    continue
                
                # Skip archived accounts (optional - can be configured)
                if account.get("Status") == "ARCHIVED":
                    continue
                
                # Skip accounts without proper type mapping
                if account.get("Type") not in XERO_ACCOUNT_TYPE_MAP:
                    continue
                
                process_xero_account(account, company)
                processed_count += 1
                
            except Exception as e:
                log_xero_error(
                    message=f"Failed to process Xero Account ID {account.get('AccountID')}",
                    xero_entity_id=account.get('AccountID'),
                    xero_entity_type="Account",
                    error_details=frappe.get_traceback()
                )
        
        log_xero_error(
            message=f"Finished syncing Chart of Accounts from Xero. Processed {processed_count} accounts.",
            status="Info"
        )
        
    except Exception as e:
        log_xero_error(
            message="Error during sync_accounts_from_xero",
            error_details=frappe.get_traceback()
        )


def find_matching_erpnext_account(xero_account_id, xero_code, xero_name, company):
    """
    Find matching ERPNext account using multiple strategies.
    Priority: xero_account_id > account_number > account_name
    
    Returns:
        tuple: (account_name, match_type) or (None, None)
    """
    # 1. Try exact match by xero_account_id (highest priority)
    if xero_account_id:
        match = frappe.db.get_value(
            "Account",
            {"xero_account_id": xero_account_id, "company": company},
            "name"
        )
        if match:
            return match, "id"
    
    # 2. Try match by account_number (Xero Code)
    if xero_code:
        match = frappe.db.get_value(
            "Account",
            {"account_number": xero_code, "company": company},
            "name"
        )
        if match:
            return match, "code"
    
    # 3. Try match by constructed name
    constructed_name = f"{xero_code} - {xero_name}"[:140] if xero_code else xero_name[:140]
    match = frappe.db.get_value(
        "Account",
        {"account_name": constructed_name, "company": company},
        "name"
    )
    if match:
        return match, "name"
    
    # 4. Try match by just the Xero name
    if xero_name:
        match = frappe.db.get_value(
            "Account",
            {"account_name": xero_name[:140], "company": company},
            "name"
        )
        if match:
            return match, "name_only"
    
    return None, None


def process_xero_account(xero_account_data, company):
    """
    Creates or updates an ERPNext Account from Xero account data.
    
    Uses improved matching logic that prioritizes xero_account_id.
    """
    xero_account_id = xero_account_data.get("AccountID")
    xero_code = xero_account_data.get("Code")
    xero_name = xero_account_data.get("Name")
    xero_type = xero_account_data.get("Type")
    xero_status = xero_account_data.get("Status", "ACTIVE")
    
    if not xero_account_id or not xero_name or not xero_type:
        log_xero_error(
            message=f"Skipping Xero account due to missing ID, Name, or Type: {xero_account_data}",
            status="Info"
        )
        return
    
    # Map Xero Type to ERPNext Type
    erpnext_type_info = XERO_ACCOUNT_TYPE_MAP.get(xero_type)
    if not erpnext_type_info:
        log_xero_error(
            message=f"Skipping Xero account '{xero_name}' ({xero_code}) - Unmapped Xero Type: {xero_type}",
            status="Info"
        )
        return
    
    # Find matching ERPNext account
    erpnext_doc_name, match_type = find_matching_erpnext_account(
        xero_account_id, xero_code, xero_name, company
    )
    
    # Construct account name
    erpnext_account_name = f"{xero_code} - {xero_name}" if xero_code else xero_name
    erpnext_account_name = erpnext_account_name[:140]
    
    # Prepare ERPNext data
    erpnext_data = {
        "account_name": erpnext_account_name,
        "account_number": xero_code,
        "account_type": erpnext_type_info["account_type"],
        "root_type": erpnext_type_info["root_type"],
        "company": company,
        "currency": xero_account_data.get("CurrencyCode") or frappe.get_cached_value('Company', company, 'default_currency'),
        "report_type": "Balance Sheet" if erpnext_type_info["root_type"] in ["Asset", "Liability", "Equity"] else "Profit and Loss",
        "is_group": 0,
        "disabled": 1 if xero_status == "ARCHIVED" else 0,
        "xero_account_id": xero_account_id,
        "xero_sync_status": "Synced",
    }
    
    try:
        if erpnext_doc_name:
            # Update existing account
            doc = frappe.get_doc("Account", erpnext_doc_name)
            
            # Only update if matched by ID or code (more reliable)
            # If matched by name, be more conservative
            if match_type in ["id", "code"]:
                doc.account_number = erpnext_data["account_number"]
                doc.currency = erpnext_data["currency"]
                doc.disabled = erpnext_data["disabled"]
            
            # Always update the Xero ID if we found a match
            doc.xero_account_id = xero_account_id
            doc.xero_sync_status = "Synced"
            doc.xero_data_hash = compute_account_hash(doc)
            doc.xero_last_account_sync = now_datetime()
            
            doc.flags.ignore_mandatory = True
            doc.save(ignore_permissions=True)
            log_message = f"Updated Account {erpnext_doc_name} from Xero Account {xero_account_id} (matched by {match_type})"
        else:
            # Create new account
            doc = frappe.new_doc("Account")
            doc.update(erpnext_data)
            
            # Set parent account based on root type
            parent_account = f"{erpnext_data['root_type']} - {frappe.get_cached_value('Company', company, 'abbr')}"
            if frappe.db.exists("Account", parent_account):
                doc.parent_account = parent_account
            else:
                # Try to find existing root
                existing_root = frappe.db.get_value(
                    "Account",
                    {"root_type": erpnext_data['root_type'], "company": company, "is_group": 1},
                    "name"
                )
                if existing_root:
                    doc.parent_account = existing_root
                else:
                    log_xero_error(
                        f"Could not find root account for '{erpnext_account_name}'. Account creation may fail.",
                        status="Warning"
                    )
            
            doc.xero_data_hash = compute_account_hash(doc)
            doc.xero_last_account_sync = now_datetime()
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
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_account_id,
            xero_entity_type="Account",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )


# =============================================================================
# WHITELISTED UI FUNCTIONS
# =============================================================================

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
            if account.get("SystemAccount") in XERO_SYSTEM_ACCOUNTS:
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
            if account.get("SystemAccount") in XERO_SYSTEM_ACCOUNTS:
                continue
            
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
        
        frappe.msgprint(f"Successfully fetched {len(formatted_accounts)} accounts from Xero. You can now manually create account mappings.")
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
            if tax_rate.get("Status") != "ACTIVE":
                continue
            
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
        
        frappe.msgprint(f"Successfully fetched {len(formatted_tax_rates)} tax rates from Xero.")
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
        
        unique_options = {opt["value"]: opt for opt in options}.values()
        return sorted(unique_options, key=lambda x: x["value"])
        
    except Exception as e:
        frappe.log_error(f"Error fetching Xero tax type options: {str(e)}")
        return []
