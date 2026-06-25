# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""
Xero Items Sync Module

This module handles bidirectional sync of Items between ERPNext and Xero.

Key Xero API Constraints:
- PUT: Create NEW items only (fails if Code already exists)
- POST: Create OR update items (if ItemID provided, updates; otherwise creates)
- Code: Required, max 30 characters
- Name: Optional, max 50 characters
- Description: Optional, max 4000 characters
- Tracked items require BOTH InventoryAssetAccountCode AND COGSAccountCode

Reference: https://developer.xero.com/documentation/api/accounting/items
"""

import frappe
from frappe import _
from frappe.utils import flt
import hashlib
import re
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error, get_leaf_doctype_value
from ..utils.retry_handler import retry_with_exponential_backoff
from .xero_invoices import get_xero_account_code  # Reuse account mapping

# --- Xero API Field Limits ---
XERO_ITEM_CODE_MAX_LENGTH = 30
XERO_ITEM_NAME_MAX_LENGTH = 50
XERO_DESCRIPTION_MAX_LENGTH = 4000


def get_or_create_item_for_xero_line(item_code, description, settings=None, is_sales=False, is_purchase=False):
    """
    Resolve an ERPNext Item for an INBOUND Xero line that REQUIRES an item_code
    (Purchase Order and Quotation both mandate item_code on their rows, unlike
    Sales/Purchase Invoice which accept description-only rows).

    Resolution order:
      1. Existing Item whose code matches the Xero ItemCode.
      2. Existing Item already linked to this Xero code via xero_item_id.
      3. Otherwise create a minimal non-stock ("service") Item and return it.

    Always returns a usable item_code (str); never returns None.
    """
    code = (item_code or "").strip()

    # 1. Existing item by code
    if code and frappe.db.exists("Item", code):
        return code

    # 2. Existing item linked by Xero item id (outbound stores the ItemCode)
    if code:
        linked = frappe.db.get_value("Item", {"xero_item_id": code}, "name")
        if linked:
            return linked

    # 3. Create a minimal non-stock item
    if not code:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", (description or "Item")).strip("-")
        code = (f"XERO-{slug}" if slug else "XERO-ITEM")[:140]
    base, n = code, 1
    while frappe.db.exists("Item", code):
        code = f"{base[:135]}-{n}"
        n += 1

    item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
    doc = frappe.new_doc("Item")
    doc.item_code = code
    doc.item_name = (description or code)[:140]
    doc.item_group = item_group
    doc.stock_uom = "Nos"
    doc.is_stock_item = 0
    doc.is_sales_item = 1 if is_sales else 0
    doc.is_purchase_item = 1 if is_purchase else 0
    doc.description = description or code
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)
    log_xero_error(
        message=f"Auto-created ERPNext Item '{code}' from an inbound Xero line (no matching item existed).",
        status="Info",
        category="System Monitoring",
        direction="Xero to ERPNext",
    )
    return code


# --- Validation Functions ---


def validate_item_code(item_code):
    """
    Validate item code for Xero API requirements.

    Args:
        item_code: The item code to validate

    Raises:
        ValueError: If validation fails with specific error message
    """
    if not item_code or not str(item_code).strip():
        raise ValueError("Item Code is required for Xero sync")

    code_str = str(item_code).strip()
    if len(code_str) > XERO_ITEM_CODE_MAX_LENGTH:
        raise ValueError(
            f"Item Code '{code_str[:20]}...' exceeds Xero limit of {XERO_ITEM_CODE_MAX_LENGTH} characters "
            f"(current: {len(code_str)} chars). Please shorten the Item Code."
        )


def validate_item_name(item_name):
    """
    Validate item name for Xero API requirements.

    Args:
        item_name: The item name to validate

    Raises:
        ValueError: If validation fails with specific error message
    """
    if item_name:
        name_str = str(item_name).strip()
        if len(name_str) > XERO_ITEM_NAME_MAX_LENGTH:
            raise ValueError(
                f"Item Name '{name_str[:20]}...' exceeds Xero limit of {XERO_ITEM_NAME_MAX_LENGTH} characters "
                f"(current: {len(name_str)} chars). Please shorten the Item Name."
            )


def validate_description(description, field_name="Description"):
    """
    Validate description for Xero API requirements.

    Args:
        description: The description text to validate
        field_name: Name of the field for error message

    Raises:
        ValueError: If validation fails with specific error message
    """
    if description:
        desc_str = str(description).strip()
        if len(desc_str) > XERO_DESCRIPTION_MAX_LENGTH:
            raise ValueError(
                f"{field_name} exceeds Xero limit of {XERO_DESCRIPTION_MAX_LENGTH} characters "
                f"(current: {len(desc_str)} chars). Please shorten the {field_name}."
            )


def validate_item_for_xero(doc, settings):
    """
    Comprehensive pre-sync validation for Item.

    Args:
        doc: ERPNext Item document
        settings: Xero Settings document

    Returns:
        tuple: (is_valid: bool, issues: list of error messages)
    """
    issues = []

    # Required field validation
    try:
        validate_item_code(doc.item_code)
    except ValueError as e:
        issues.append(str(e))

    # Optional field limits
    try:
        validate_item_name(doc.item_name)
    except ValueError as e:
        issues.append(str(e))

    try:
        validate_description(doc.get("description"), "Description")
    except ValueError as e:
        issues.append(str(e))

    try:
        validate_description(doc.get("purchase_description"), "Purchase Description")
    except ValueError as e:
        issues.append(str(e))

    # Tracked inventory requirements
    if doc.is_stock_item:
        inventory_account = get_inventory_account(doc)
        cogs_account = get_cogs_account(doc)

        if inventory_account:
            inventory_code = get_xero_account_code(inventory_account, settings)
            if not inventory_code:
                issues.append(
                    f"Inventory Account '{inventory_account}' is not mapped to Xero. "
                    f"Item will sync as untracked (non-inventory)."
                )

        if cogs_account:
            cogs_code = get_xero_account_code(cogs_account, settings)
            if not cogs_code:
                issues.append(
                    f"COGS Account '{cogs_account}' is not mapped to Xero. "
                    f"Item will sync as untracked (non-inventory)."
                )

    return len(issues) == 0, issues


# --- Helper Functions ---


def clean_item_payload(payload):
    """
    Recursively removes None values, empty strings, and empty dictionaries from payload.
    This ensures only valid data is sent to Xero API.
    """
    cleaned = {}
    for k, v in payload.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, dict):
            cleaned_dict = clean_item_payload(v)
            if cleaned_dict:  # Only add if dict has content
                cleaned[k] = cleaned_dict
        else:
            cleaned[k] = v
    return cleaned


def strip_html(text):
    """
    Strip HTML tags from text for Xero compatibility.
    Xero requires plain text descriptions.
    """
    if not text:
        return ""
    text = str(text).strip()
    if "<" in text:
        text = re.sub(r"<[^>]+>", "", text).strip()
    return text


def get_inventory_account(doc):
    """
    Get the inventory asset account for a stock item.

    Args:
        doc: ERPNext Item document

    Returns:
        str: Account name or None
    """
    # Try to get from item_defaults
    company = frappe.db.get_default("company")

    if hasattr(doc, "item_defaults") and doc.item_defaults:
        for id_row in doc.item_defaults:
            if id_row.company == company:
                # Check for default warehouse and get stock account
                if id_row.default_warehouse:
                    stock_account = frappe.db.get_value(
                        "Warehouse", id_row.default_warehouse, "account"
                    )
                    if stock_account:
                        return stock_account

    # HI-12: Fall back to the company's DEFAULT INVENTORY account, not the
    # stock_adjustment_account. Using stock_adjustment_account here made the
    # Inventory and COGS resolvers return the same account, so tracked items got
    # identical Inventory/COGS codes in Xero.
    if company:
        inventory_account = frappe.get_cached_value(
            "Company", company, "default_inventory_account"
        )
        if inventory_account:
            return inventory_account

    return None


def get_cogs_account(doc):
    """
    Get the Cost of Goods Sold (COGS) account for a stock item.

    Args:
        doc: ERPNext Item document

    Returns:
        str: Account name or None
    """
    # Try to get from item_defaults
    company = frappe.db.get_default("company")

    if hasattr(doc, "item_defaults") and doc.item_defaults:
        for id_row in doc.item_defaults:
            if id_row.company == company:
                if id_row.expense_account:
                    return id_row.expense_account

    # HI-12: Fall back to the company's DEFAULT COST OF GOODS SOLD account, not
    # the stock_adjustment_account (which is the inventory fallback). This keeps
    # Inventory and COGS distinct for tracked items.
    if company:
        cogs_account = frappe.get_cached_value(
            "Company", company, "default_cost_of_goods_sold_account"
        )
        if cogs_account:
            return cogs_account

    return None


def get_sales_account(doc):
    """
    Get the sales/income account for an item.

    Args:
        doc: ERPNext Item document

    Returns:
        str: Account name or None
    """
    company = frappe.db.get_default("company")

    if hasattr(doc, "item_defaults") and doc.item_defaults:
        for id_row in doc.item_defaults:
            if id_row.company == company:
                if id_row.income_account:
                    return id_row.income_account

    return None


def get_purchase_account(doc):
    """
    Get the purchase/expense account for an item.

    Args:
        doc: ERPNext Item document

    Returns:
        str: Account name or None
    """
    company = frappe.db.get_default("company")

    if hasattr(doc, "item_defaults") and doc.item_defaults:
        for id_row in doc.item_defaults:
            if id_row.company == company:
                if id_row.expense_account:
                    return id_row.expense_account

    return None


def compute_item_hash(doc):
    """
    Compute MD5 hash of item data for change detection.
    This prevents unnecessary syncs and infinite loops.

    Args:
        doc: ERPNext Item document

    Returns:
        str: MD5 hash string
    """
    hash_data = {
        "code": str(doc.item_code or ""),
        "name": str(doc.item_name or ""),
        "description": str(doc.get("description") or ""),
        "purchase_description": str(doc.get("purchase_description") or ""),
        "is_sales_item": int(doc.is_sales_item or 0),
        "is_purchase_item": int(doc.is_purchase_item or 0),
        "is_stock_item": int(doc.is_stock_item or 0),
        "standard_rate": flt(doc.get("standard_rate") or 0),
        "last_purchase_rate": flt(doc.get("last_purchase_rate") or 0),
    }

    # Include account info for stock items
    if doc.is_stock_item:
        hash_data["inventory_account"] = str(get_inventory_account(doc) or "")
        hash_data["cogs_account"] = str(get_cogs_account(doc) or "")

    hash_string = str(sorted(hash_data.items()))
    return hashlib.md5(hash_string.encode()).hexdigest()


def item_data_changed(doc):
    """
    Check if item data has changed since last sync.

    Args:
        doc: ERPNext Item document

    Returns:
        bool: True if data has changed or no hash exists
    """
    stored_hash = doc.get("xero_data_hash")
    if not stored_hash:
        return True  # No hash, assume changed
    return compute_item_hash(doc) != stored_hash


def get_erpnext_account_from_xero_code(xero_code, settings):
    """
    Find ERPNext account name from Xero account code using mapping table.

    Args:
        xero_code: Xero account code
        settings: Xero Settings document

    Returns:
        str: ERPNext account name or None
    """
    if not xero_code:
        return None

    for mapping in settings.account_mapping:
        if mapping.xero_account_code == xero_code:
            return mapping.erpnext_account

    return None


# --- Enqueue Function ---


@frappe.whitelist()
def enqueue_sync_item(doc, method=None):
    """
    Enqueue background job to sync Item to Xero.

    This function handles both:
    1. Hook call (receives doc object with method parameter)
    2. Manual whitelist call (receives item_code string)

    Includes double-trigger guard to prevent infinite loops.
    """
    # Handle both hook call (doc object) and manual call (string)
    if isinstance(doc, str):
        item_code = doc
    else:
        item_code = doc.name

    settings = get_xero_settings()

    # Check master switch
    if not settings.enable_xero_sync:
        log_xero_error(
            message=f"Item sync skipped: Xero sync is disabled",
            status="Info",
            erpnext_doc_type="Item",
            erpnext_doc_name=item_code,
        )
        return

    # Check per-entity directional toggle for outbound sync
    if not settings.get("sync_items_to_xero"):
        log_xero_error(
            message=f"Items outbound sync is disabled. Skipping Item {item_code}.",
            status="Info",
            erpnext_doc_type="Item",
            erpnext_doc_name=item_code,
            category="System Monitoring",
        )
        return

    # HI-4: inbound (Xero -> ERPNext) creation/updates set this flag before
    # saving the Item so this on_update hook does not bounce the data straight
    # back out to Xero in a loop.
    if not isinstance(doc, str) and getattr(doc.flags, "ignore_xero_sync", False):
        return

    # HI-5: Gate the enqueue on whether the item data has ACTUALLY changed rather
    # than on status == "Synced". The old status-only guard meant a later edit to
    # an already-synced item never re-synced (the change was silently dropped).
    # This mirrors the contacts/accounts behaviour. The hash short-circuit in
    # sync_item_to_xero remains the backstop against redundant API calls.
    if isinstance(doc, str):
        doc = frappe.get_doc("Item", item_code)
    if not item_data_changed(doc):
        return

    frappe.enqueue(
        "xero.api.xero_items.sync_item_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        item_code=item_code,
    )


# --- Outbound Sync (ERPNext → Xero) ---


@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_item_to_xero(item_code, **kwargs):
    """
    Syncs an ERPNext Item to Xero Items (Products & Services).

    Uses PUT for creating new items and POST for updating existing items.
    This is critical because Xero's PUT endpoint only creates new items.
    """
    settings = get_xero_settings()

    # Check master switch
    if not settings.enable_xero_sync:
        log_xero_error(
            message=f"Item sync skipped: Xero sync is disabled",
            status="Info",
            erpnext_doc_type="Item",
            erpnext_doc_name=item_code,
        )
        return

    # Check directional toggle for outbound sync
    if not settings.enable_sync_to_xero:
        log_xero_error(
            message=f"Sync to Xero is disabled. Skipping Item {item_code} outbound sync.",
            status="Info",
            erpnext_doc_type="Item",
            erpnext_doc_name=item_code,
            category="System Monitoring",
        )
        return

    # Check entity-specific toggle
    if not settings.sync_items:
        log_xero_error(
            message=f"Item sync skipped: Item sync is disabled in settings",
            status="Info",
            erpnext_doc_type="Item",
            erpnext_doc_name=item_code,
        )
        return

    try:
        doc = frappe.get_doc("Item", item_code)
        xero_item_id = doc.get("xero_item_id")

        # --- Pre-Sync Validation ---
        is_valid, issues = validate_item_for_xero(doc, settings)

        if not is_valid:
            # Log validation issues but continue with sync for warnings
            critical_issues = [
                i for i in issues if "required" in i.lower() or "exceeds" in i.lower()
            ]
            if critical_issues:
                # Critical issues - abort sync
                error_msg = "Item validation failed:\n" + "\n".join(critical_issues)
                frappe.db.set_value(
                    "Item",
                    item_code,
                    "xero_sync_status",
                    "Error",
                    update_modified=False,
                )
                log_xero_error(
                    message=error_msg,
                    status="Error",
                    erpnext_doc_type="Item",
                    erpnext_doc_name=item_code,
                    category="Validation Errors",
                )
                return

            # Non-critical issues - log warning and continue
            log_xero_error(
                message="Item sync warnings:\n" + "\n".join(issues),
                status="Warning",
                erpnext_doc_type="Item",
                erpnext_doc_name=item_code,
                category="Mapping Errors",
            )

        # --- Check if data has changed ---
        if not item_data_changed(doc):
            log_xero_error(
                message=f"Item {item_code} unchanged since last sync. Skipping.",
                status="Info",
                erpnext_doc_type="Item",
                erpnext_doc_name=item_code,
                category="System Monitoring",
            )
            return

        # --- Build Xero Payload ---
        item_payload = build_xero_item_payload(doc, settings)

        # --- Make API Call ---
        # CRITICAL: Use POST for updates, PUT for creates
        if xero_item_id:
            # UPDATE existing item - use POST with ItemID
            item_payload["ItemID"] = xero_item_id
            response = xero_request("POST", "Items", data={"Items": [item_payload]})
        else:
            # CREATE new item - use PUT. Pass a stable idempotency key so a retry
            # after a network timeout does not create a duplicate item in Xero.
            response = xero_request(
                "PUT",
                "Items",
                data={"Items": [item_payload]},
                idempotency_key=f"Item:{item_code}:create",
            )

        # --- Handle Response ---
        if response and response.get("Items"):
            updated_item = response["Items"][0]
            new_xero_item_id = updated_item.get("ItemID")

            if new_xero_item_id:
                # Update ERPNext document
                frappe.db.set_value(
                    "Item",
                    item_code,
                    {
                        "xero_item_id": new_xero_item_id,
                        "xero_sync_status": "Synced",
                        "xero_data_hash": compute_item_hash(doc),
                        "xero_last_item_sync": frappe.utils.now(),
                    },
                    update_modified=False,
                )
                frappe.db.commit()

                log_xero_error(
                    message=f"Successfully synced Item {item_code} to Xero.",
                    status="Success",
                    erpnext_doc_type="Item",
                    erpnext_doc_name=item_code,
                    xero_entity_id=new_xero_item_id,
                    xero_entity_type="Item",
                    direction="ERPNext to Xero",
                )
            else:
                raise Exception("Xero API response did not contain an ItemID.")
        else:
            raise Exception("Invalid response received from Xero Items API.")

    except ValueError as e:
        # Validation errors - don't retry
        frappe.db.set_value(
            "Item", item_code, "xero_sync_status", "Error", update_modified=False
        )
        frappe.db.commit()
        log_xero_error(
            message=f"Validation error syncing Item {item_code}: {str(e)}",
            status="Error",
            erpnext_doc_type="Item",
            erpnext_doc_name=item_code,
            category="Validation Errors",
            error_details=frappe.get_traceback(),
        )

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        if is_already_exists_error(str(e), error_traceback):
            if item_code:
                frappe.db.set_value(
                    "Item",
                    item_code,
                    "xero_sync_status",
                    "Synced",
                    update_modified=False,
                )
                frappe.db.commit()
            log_xero_error(
                message=f"Item {item_code} already exists in Xero. No action needed.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type="Item",
                erpnext_doc_name=item_code,
                direction="ERPNext to Xero",
            )
        else:
            from ..utils.logging import format_sync_error_message

            # Update sync status on error
            if item_code:
                frappe.db.set_value(
                    "Item",
                    item_code,
                    "xero_sync_status",
                    "Error",
                    update_modified=False,
                )
                frappe.db.commit()
            user_message = format_sync_error_message(
                "Item", item_code, item_code, "ERPNext to Xero", e
            )
            log_xero_error(
                message=user_message,
                erpnext_doc_type="Item",
                erpnext_doc_name=item_code,
                error_details=error_traceback,
                direction="ERPNext to Xero",
            )
            raise  # Re-raise for retry decorator


def build_xero_item_payload(doc, settings):
    """
    Build Xero item payload from ERPNext Item document.

    Handles:
    - Field length limits (truncation with warning)
    - Tracked inventory items (COGS + Inventory accounts)
    - Sales and purchase details

    Args:
        doc: ERPNext Item document
        settings: Xero Settings document

    Returns:
        dict: Xero-compatible item payload
    """
    payload = {}

    # --- Code (Required, max 30 chars) ---
    code = str(doc.item_code).strip()[:XERO_ITEM_CODE_MAX_LENGTH]
    if len(str(doc.item_code)) > XERO_ITEM_CODE_MAX_LENGTH:
        log_xero_error(
            message=f"Item Code truncated from {len(str(doc.item_code))} to {XERO_ITEM_CODE_MAX_LENGTH} chars",
            status="Warning",
            erpnext_doc_type="Item",
            erpnext_doc_name=doc.name,
        )
    payload["Code"] = code

    # --- Name (Optional, max 50 chars) ---
    if doc.item_name:
        name = str(doc.item_name).strip()[:XERO_ITEM_NAME_MAX_LENGTH]
        if len(str(doc.item_name)) > XERO_ITEM_NAME_MAX_LENGTH:
            log_xero_error(
                message=f"Item Name truncated from {len(str(doc.item_name))} to {XERO_ITEM_NAME_MAX_LENGTH} chars",
                status="Warning",
                erpnext_doc_type="Item",
                erpnext_doc_name=doc.name,
            )
        payload["Name"] = name

    # --- Description (Sales, max 4000 chars) ---
    # Xero's "Description" is the SALES description and is only valid when the
    # item IsSold. Sending it while IsSold=False makes Xero reject the whole item
    # ("IsSold cannot be set to false when SalesDetails or Description values are
    # provided"), so gate it on is_sales_item.
    if doc.is_sales_item and doc.get("description"):
        description = strip_html(doc.description)
        if len(description) > XERO_DESCRIPTION_MAX_LENGTH:
            description = description[:XERO_DESCRIPTION_MAX_LENGTH]
            log_xero_error(
                message="Description truncated to 4000 chars",
                status="Warning",
                erpnext_doc_type="Item",
                erpnext_doc_name=doc.name,
            )
        payload["Description"] = description

    # --- Purchase Description (max 4000 chars) ---
    # Symmetric to Description above: PurchaseDescription is only valid when the
    # item IsPurchased, otherwise Xero rejects it.
    if doc.is_purchase_item and doc.get("purchase_description"):
        purchase_desc = strip_html(doc.purchase_description)
        if len(purchase_desc) > XERO_DESCRIPTION_MAX_LENGTH:
            purchase_desc = purchase_desc[:XERO_DESCRIPTION_MAX_LENGTH]
            log_xero_error(
                message="Purchase Description truncated to 4000 chars",
                status="Warning",
                erpnext_doc_type="Item",
                erpnext_doc_name=doc.name,
            )
        payload["PurchaseDescription"] = purchase_desc

    # --- Sales Details ---
    if doc.is_sales_item:
        payload["IsSold"] = True
        sales_details = {}

        # Unit Price
        if doc.get("standard_rate"):
            sales_details["UnitPrice"] = flt(doc.standard_rate)

        # Account Code
        sales_account = get_sales_account(doc)
        if sales_account:
            sales_code = get_xero_account_code(sales_account, settings)
            if sales_code:
                sales_details["AccountCode"] = sales_code

        if sales_details:
            payload["SalesDetails"] = sales_details
    else:
        payload["IsSold"] = False

    # --- Purchase Details ---
    if doc.is_purchase_item:
        payload["IsPurchased"] = True
        purchase_details = {}

        # Unit Price
        if doc.get("last_purchase_rate"):
            purchase_details["UnitPrice"] = flt(doc.last_purchase_rate)

        # Account Code (not for tracked items - use COGSAccountCode instead)
        if not doc.is_stock_item:
            purchase_account = get_purchase_account(doc)
            if purchase_account:
                purchase_code = get_xero_account_code(purchase_account, settings)
                if purchase_code:
                    purchase_details["AccountCode"] = purchase_code

        if purchase_details:
            payload["PurchaseDetails"] = purchase_details
    else:
        payload["IsPurchased"] = False

    # --- Tracked Inventory ---
    if doc.is_stock_item:
        inventory_account = get_inventory_account(doc)
        cogs_account = get_cogs_account(doc)

        # HI-12: Xero requires DISTINCT Inventory and COGS accounts for a tracked
        # item. If resolution collapses to the same account (e.g. company defaults
        # not configured), do NOT sync as tracked — log a Warning and fall through
        # to untracked treatment so we never push an invalid identical Inventory ==
        # COGS pairing to Xero.
        if (
            inventory_account
            and cogs_account
            and inventory_account == cogs_account
        ):
            log_xero_error(
                message=f"Item {doc.name}: resolved Inventory account and COGS account are identical "
                f"('{inventory_account}'). Xero requires distinct accounts for tracked items. "
                f"Syncing as untracked. Configure the company's Default Inventory Account and "
                f"Default Cost of Goods Sold Account (or the item's defaults) to enable tracking.",
                status="Warning",
                erpnext_doc_type="Item",
                erpnext_doc_name=doc.name,
                category="Mapping Errors",
            )
            payload["IsTrackedAsInventory"] = False
            payload = clean_item_payload(payload)
            return payload

        inventory_code = None
        cogs_code = None

        if inventory_account:
            inventory_code = get_xero_account_code(inventory_account, settings)

        if cogs_account:
            cogs_code = get_xero_account_code(cogs_account, settings)

        # Both accounts required for tracked items
        if inventory_code and cogs_code:
            payload["InventoryAssetAccountCode"] = inventory_code
            payload["IsTrackedAsInventory"] = True

            # Add COGSAccountCode to PurchaseDetails
            if "PurchaseDetails" not in payload:
                payload["PurchaseDetails"] = {}
            payload["PurchaseDetails"]["COGSAccountCode"] = cogs_code

            # Ensure IsPurchased is true for tracked items
            payload["IsPurchased"] = True
        else:
            # Cannot sync as tracked - log warning and sync as untracked
            missing = []
            if not inventory_code:
                missing.append(f"Inventory Account '{inventory_account}'")
            if not cogs_code:
                missing.append(f"COGS Account '{cogs_account}'")

            log_xero_error(
                message=f"Item {doc.name}: Missing Xero account mapping for tracked inventory. "
                f"Missing: {', '.join(missing)}. Syncing as untracked item.",
                status="Warning",
                erpnext_doc_type="Item",
                erpnext_doc_name=doc.name,
                category="Mapping Errors",
            )
            payload["IsTrackedAsInventory"] = False

    # --- Clean payload (remove empty values) ---
    payload = clean_item_payload(payload)

    return payload


# --- Inbound Sync (Xero → ERPNext) ---


def sync_items_from_xero():
    """
    Fetches items from Xero and creates/updates corresponding Items in ERPNext.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return

    # Check per-entity directional toggle for inbound sync
    if not settings.get("sync_items_from_xero"):
        log_xero_error(
            message="Items inbound sync is disabled. Skipping items from Xero.",
            status="Info",
            category="System Monitoring",
        )
        return

    if not settings.sync_items:
        return

    from ..utils.xero_client import (
        incremental_since,
        commit_watermark,
        start_incremental_run,
    )

    watermark_key = "items"
    run_started_at = start_incremental_run()
    if_modified_since = incremental_since(watermark_key)

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Items page {page}", "Xero Sync")
            response = xero_request(
                "GET", "Items", params={"page": page}, modified_since=if_modified_since
            )

            if not response or not response.get("Items"):
                break

            items = response["Items"]
            if not items:
                break

            for item_data in items:
                try:
                    process_xero_item(item_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Item ID {item_data.get('ItemID')}: {str(e)}",
                        xero_entity_id=item_data.get("ItemID"),
                        xero_entity_type="Item",
                        error_details=frappe.get_traceback(),
                    )

            if len(items) < 100:  # Default page size
                break
            page += 1

        # Only advance the watermark after a fully successful sweep — if an
        # exception aborted the loop, the next run re-fetches from the old
        # watermark so nothing is missed.
        commit_watermark(watermark_key, run_started_at)
        log_xero_error(message="Finished syncing items from Xero.", status="Info")

    except Exception as e:
        log_xero_error(
            message=f"Error during sync_items_from_xero: {str(e)}",
            error_details=frappe.get_traceback(),
        )


def process_xero_item(xero_item_data, settings):
    """
    Creates or updates an ERPNext Item from Xero item data.

    Args:
        xero_item_data: Item data from Xero API
        settings: Xero Settings document
    """
    xero_item_id = xero_item_data.get("ItemID")
    item_code = xero_item_data.get("Code")

    if not xero_item_id or not item_code:
        log_xero_error(
            message=f"Skipping Xero item due to missing ID or Code: {xero_item_data}",
            status="Info",
        )
        return

    # --- Check if ERPNext Item Exists ---
    # First check by xero_item_id
    erpnext_doc_name = frappe.db.get_value(
        "Item", {"xero_item_id": xero_item_id}, "name"
    )

    # If not found, check by item_code
    if not erpnext_doc_name:
        erpnext_doc_name = frappe.db.get_value("Item", {"item_code": item_code}, "name")

    # --- Map Xero Data to ERPNext Fields ---
    erpnext_data = {
        "item_code": item_code,
        "item_name": xero_item_data.get("Name", item_code)[:140],  # ERPNext limit
        "item_group": get_leaf_doctype_value("Item Group", frappe.db.get_default("item_group")),
        "stock_uom": frappe.db.get_default("stock_uom") or "Nos",
        "description": strip_html(xero_item_data.get("Description")),
        "purchase_description": strip_html(xero_item_data.get("PurchaseDescription")),
        "xero_item_id": xero_item_id,
        "xero_sync_status": "Synced",
        "is_stock_item": 1 if xero_item_data.get("IsTrackedAsInventory") else 0,
        "is_sales_item": 1 if xero_item_data.get("IsSold") else 0,
        "is_purchase_item": 1 if xero_item_data.get("IsPurchased") else 0,
    }

    # Map Sales Details
    if xero_item_data.get("SalesDetails"):
        sales_details = xero_item_data["SalesDetails"]
        erpnext_data["standard_rate"] = sales_details.get("UnitPrice")

        # Map Account Code back to ERPNext
        if sales_details.get("AccountCode"):
            income_account = get_erpnext_account_from_xero_code(
                sales_details["AccountCode"], settings
            )
            if income_account:
                erpnext_data["income_account"] = income_account

    # Map Purchase Details
    if xero_item_data.get("PurchaseDetails"):
        purchase_details = xero_item_data["PurchaseDetails"]
        erpnext_data["last_purchase_rate"] = purchase_details.get("UnitPrice")

        # Map COGS Account for tracked items
        if purchase_details.get("COGSAccountCode"):
            expense_account = get_erpnext_account_from_xero_code(
                purchase_details["COGSAccountCode"], settings
            )
            if expense_account:
                erpnext_data["expense_account"] = expense_account
        elif purchase_details.get("AccountCode"):
            expense_account = get_erpnext_account_from_xero_code(
                purchase_details["AccountCode"], settings
            )
            if expense_account:
                erpnext_data["expense_account"] = expense_account

    # Map Inventory Asset Account for tracked items
    if xero_item_data.get("IsTrackedAsInventory"):
        if xero_item_data.get("InventoryAssetAccountCode"):
            stock_account = get_erpnext_account_from_xero_code(
                xero_item_data["InventoryAssetAccountCode"], settings
            )
            if stock_account:
                erpnext_data["stock_account"] = stock_account

    # --- Create or Update ERPNext Item ---
    try:
        if erpnext_doc_name:
            # Update existing item
            doc = frappe.get_doc("Item", erpnext_doc_name)

            # Only update specific fields to avoid overwriting user data
            doc.update(
                {
                    "item_name": erpnext_data["item_name"],
                    "description": erpnext_data["description"],
                    "purchase_description": erpnext_data["purchase_description"],
                    "standard_rate": erpnext_data.get("standard_rate"),
                    "last_purchase_rate": erpnext_data.get("last_purchase_rate"),
                    "xero_item_id": xero_item_id,
                    "xero_sync_status": "Synced",
                    "xero_data_hash": compute_item_hash(doc),
                }
            )
            # HI-4: suppress the outbound on_update->enqueue_sync_item hook for
            # this inbound write so we don't loop the data straight back to Xero.
            doc.flags.ignore_xero_sync = True
            doc.save(ignore_permissions=True)
            log_message = (
                f"Updated Item {erpnext_doc_name} from Xero Item {xero_item_id}"
            )
        else:
            # Create new item
            doc = frappe.new_doc("Item")
            doc.update(erpnext_data)
            # HI-4: suppress the outbound on_update->enqueue_sync_item hook (above).
            doc.flags.ignore_xero_sync = True
            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = (
                f"Created Item {erpnext_doc_name} from Xero Item {xero_item_id}"
            )

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type="Item",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_item_id,
            xero_entity_type="Item",
            direction="Xero to ERPNext",
        )

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        if is_already_exists_error(str(e), error_traceback):
            if erpnext_doc_name:
                frappe.db.set_value(
                    "Item",
                    erpnext_doc_name,
                    "xero_sync_status",
                    "Synced",
                    update_modified=False,
                )
                frappe.db.commit()

            log_xero_error(
                message=f"Xero Item {xero_item_id} already exists in ERPNext as {erpnext_doc_name or 'existing item'}. Skipping update.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type="Item",
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_item_id,
                xero_entity_type="Item",
                direction="Xero to ERPNext",
            )
        else:
            from ..utils.logging import format_sync_error_message

            if erpnext_doc_name:
                frappe.db.set_value(
                    "Item",
                    erpnext_doc_name,
                    "xero_sync_status",
                    "Error",
                    update_modified=False,
                )
                frappe.db.commit()

            user_message = format_sync_error_message(
                "Xero Item", xero_item_id, item_code, "Xero to ERPNext", e
            )

            log_xero_error(
                message=user_message,
                erpnext_doc_type="Item",
                erpnext_doc_name=erpnext_doc_name,
                xero_entity_id=xero_item_id,
                xero_entity_type="Item",
                direction="Xero to ERPNext",
                error_details=error_traceback,
            )
