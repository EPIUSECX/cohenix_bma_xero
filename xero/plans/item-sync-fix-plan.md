# Plan: Robust Item Sync Implementation

## Problem Statement

Item syncs are currently not working bi-directionally. The implementation needs to be fixed to align with Xero Items API requirements and provide rich feedback for validation errors and API limitations.

## Current State Analysis

### Xero Items API Requirements (from official documentation)

| Aspect | Requirement |
|--------|-------------|
| **HTTP Methods** | GET, PUT (create only), POST (create/update), DELETE |
| **Code** | Required, max 30 characters |
| **Name** | Optional, max 50 characters |
| **Description** | Optional, max 4000 characters |
| **PurchaseDescription** | Optional, max 4000 characters |
| **IsSold** | Boolean, defaults to true |
| **IsPurchased** | Boolean, defaults to true |
| **Tracked Items** | Require `InventoryAssetAccountCode` AND `COGSAccountCode` in PurchaseDetails |
| **SalesDetails.AccountCode** | Not applicable to purchase details of tracked items |
| **PurchaseDetails.COGSAccountCode** | Required for tracked items |

### Critical API Method Distinction

| Method | Purpose |
|--------|---------|
| **PUT** | Create NEW items only - fails if item with same Code exists |
| **POST** | Create OR update - if ItemID provided, updates; otherwise creates |

### Issues Found in Current Implementation

#### Issue 1: Wrong HTTP Method for Updates (CRITICAL)

**Current Code (line 179):**
```python
response = xero_request("PUT", "Items", data={"Items": [item_payload]})
```

**Problem:** PUT is for CREATE ONLY. Updates to existing items will fail with "Item already exists" error.

**Solution:** Use POST for updates (when `xero_item_id` exists), PUT for creates.

#### Issue 2: Missing Hook for Item

**Current State:** No `on_update` hook for Item in `hooks.py`.

**Problem:** Items don't sync automatically when created or updated.

**Solution:** Add Item to `doc_events` in hooks.py.

#### Issue 3: Missing xero_data_hash for Change Detection

**Current State:** Item custom fields don't include `xero_data_hash`.

**Problem:** No way to detect if data has changed. Will cause:
- Re-sync loops (sync triggers on update, update triggers sync)
- Unnecessary API calls

**Solution:** Add `xero_data_hash` field and hash computation logic.

#### Issue 4: Missing COGSAccountCode for Tracked Items

**Current Code (lines 152-168):**
```python
if doc.is_stock_item:
    inventory_account_code = get_xero_account_code(inventory_account, settings)
    if inventory_account_code:
        item_payload["InventoryAssetAccountCode"] = inventory_account_code
        item_payload["IsTrackedAsInventory"] = True
```

**Problem:** Xero requires BOTH `InventoryAssetAccountCode` AND `COGSAccountCode` for tracked items. Missing COGSAccountCode will cause API error.

**Solution:** Add COGSAccountCode from ERPNext's expense account for stock items.

#### Issue 5: No Field Length Validation

**Problem:** No validation for:
- Code max 30 chars
- Name max 50 chars
- Description max 4000 chars

**Solution:** Add validation functions with clear error messages.

#### Issue 6: Missing Double-Trigger Guard

**Current State:** No check for `xero_sync_status == "Synced"` before enqueueing.

**Problem:** When sync updates `xero_item_id`, the `on_update` hook fires again, causing infinite loop.

**Solution:** Add guard similar to Contact sync:
```python
xero_status = frappe.db.get_value("Item", item_code, "xero_sync_status")
if xero_status == "Synced":
    return  # Already synced, skip re-trigger
```

#### Issue 7: Missing Rich Error Feedback

**Problem:** Generic error messages don't help users understand:
- Which fields are missing
- Which fields exceed limits
- What API limitation blocked the sync

**Solution:** Add specific validation with clear error messages.

## Proposed Solution

### Phase 1: Custom Fields Update

Add `xero_data_hash` field to Item in `custom_fields.py`:

```python
{
    "fieldname": "xero_data_hash",
    "fieldtype": "Data",
    "label": "Xero Data Hash",
    "length": 32,
    "no_copy": 1,
    "read_only": 1,
    "print_hide": 1,
    "report_hide": 1,
    "hidden": 1,
    "insert_after": "xero_sync_status"
}
```

### Phase 2: Add Item Hook

Update `hooks.py`:

```python
doc_events = {
    # ... existing hooks ...
    "Item": {
        "on_update": "xero.api.xero_items.enqueue_sync_item"
    }
}
```

### Phase 3: Rewrite sync_item_to_xero()

#### 3.1 Add Validation Functions

```python
def validate_item_code(item_code, item_name):
    """Validate item code for Xero API requirements."""
    if not item_code or not str(item_code).strip():
        raise ValueError("Item Code is required for Xero sync")
    if len(str(item_code)) > 30:
        raise ValueError(f"Item Code '{item_code}' exceeds Xero limit of 30 characters (current: {len(str(item_code))})")

def validate_item_name(item_name):
    """Validate item name for Xero API requirements."""
    if item_name and len(str(item_name)) > 50:
        raise ValueError(f"Item Name '{item_name}' exceeds Xero limit of 50 characters (current: {len(str(item_name))})")

def validate_description(description, field_name="Description"):
    """Validate description for Xero API requirements."""
    if description and len(str(description)) > 4000:
        raise ValueError(f"{field_name} exceeds Xero limit of 4000 characters (current: {len(str(description))})")
```

#### 3.2 Add Hash Computation

```python
def compute_item_hash(doc):
    """Compute MD5 hash of item data for change detection."""
    import hashlib
    hash_data = {
        "code": doc.item_code,
        "name": doc.item_name,
        "description": doc.get("description"),
        "purchase_description": doc.get("purchase_description"),
        "is_sold": doc.is_sales_item,
        "is_purchased": doc.is_purchase_item,
        "standard_rate": doc.get("standard_rate"),
        "last_purchase_rate": doc.get("last_purchase_rate"),
    }
    hash_string = str(sorted(hash_data.items()))
    return hashlib.md5(hash_string.encode()).hexdigest()

def item_data_changed(doc):
    """Check if item data has changed since last sync."""
    stored_hash = doc.get("xero_data_hash")
    if not stored_hash:
        return True  # No hash, assume changed
    return compute_item_hash(doc) != stored_hash
```

#### 3.3 Add Double-Trigger Guard

```python
@frappe.whitelist()
def enqueue_sync_item(doc, method=None):
    """Enqueue background job to sync Item to Xero."""
    # Handle both hook call (doc object) and manual call (string)
    if isinstance(doc, str):
        item_code = doc
    else:
        item_code = doc.name
    
    settings = get_xero_settings()
    if not settings.sync_items:
        return
    
    # Double-trigger guard - skip if already synced
    xero_status = frappe.db.get_value("Item", item_code, "xero_sync_status")
    if xero_status == "Synced":
        return  # Already synced, skip re-trigger
    
    frappe.enqueue(
        "xero.api.xero_items.sync_item_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        item_code=item_code
    )
```

#### 3.4 Fix HTTP Method Logic

```python
def sync_item_to_xero(item_code, **kwargs):
    """Syncs an ERPNext Item to Xero."""
    # ... validation and setup ...
    
    # Check if data has changed
    if not item_data_changed(doc):
        log_xero_error(
            message=f"Item {item_code} unchanged since last sync. Skipping.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    # Build payload
    item_payload = build_xero_item_payload(doc, settings)
    
    # Use correct HTTP method
    if doc.xero_item_id:
        # UPDATE existing item - use POST with ItemID
        item_payload["ItemID"] = doc.xero_item_id
        response = xero_request("POST", "Items", data={"Items": [item_payload]})
    else:
        # CREATE new item - use PUT
        response = xero_request("PUT", "Items", data={"Items": [item_payload]})
    
    # ... handle response ...
```

#### 3.5 Add COGSAccountCode for Tracked Items

```python
def build_xero_item_payload(doc, settings):
    """Build Xero item payload from ERPNext Item."""
    payload = {
        "Code": doc.item_code,
        "Name": doc.item_name[:50] if doc.item_name else doc.item_code[:50],
    }
    
    # ... sales and purchase details ...
    
    # Handle tracked inventory items
    if doc.is_stock_item:
        # Get inventory asset account
        inventory_account = get_inventory_account(doc)
        inventory_account_code = get_xero_account_code(inventory_account, settings)
        
        # Get COGS account (expense account for stock items)
        cogs_account = get_cogs_account(doc)
        cogs_account_code = get_xero_account_code(cogs_account, settings)
        
        if inventory_account_code and cogs_account_code:
            payload["InventoryAssetAccountCode"] = inventory_account_code
            payload["IsTrackedAsInventory"] = True
            
            # Add COGSAccountCode to PurchaseDetails
            if "PurchaseDetails" not in payload:
                payload["PurchaseDetails"] = {}
            payload["PurchaseDetails"]["COGSAccountCode"] = cogs_account_code
        else:
            # Cannot sync as tracked - log warning and sync as untracked
            log_xero_error(
                message=f"Item {doc.name}: Missing account mapping for tracked inventory. "
                       f"Inventory Account: {inventory_account} (mapped: {bool(inventory_account_code)}), "
                       f"COGS Account: {cogs_account} (mapped: {bool(cogs_account_code)}). "
                       f"Syncing as untracked item.",
                status="Warning",
                erpnext_doc_type="Item",
                erpnext_doc_name=doc.name,
                category="Mapping Errors"
            )
            payload["IsTrackedAsInventory"] = False
    
    return payload
```

### Phase 4: Improve Inbound Sync

#### 4.1 Handle Tracked Items Properly

```python
def process_xero_item(xero_item_data, settings):
    """Creates or updates an ERPNext Item from Xero item data."""
    # ... existing code ...
    
    # Handle tracked inventory
    if xero_item_data.get("IsTrackedAsInventory"):
        erpnext_data["is_stock_item"] = 1
        
        # Map inventory asset account
        if xero_item_data.get("InventoryAssetAccountCode"):
            erpnext_account = get_erpnext_account_from_xero_code(
                xero_item_data["InventoryAssetAccountCode"], settings
            )
            if erpnext_account:
                erpnext_data["stock_account"] = erpnext_account
        
        # Map COGS account from PurchaseDetails
        if xero_item_data.get("PurchaseDetails", {}).get("COGSAccountCode"):
            cogs_account = get_erpnext_account_from_xero_code(
                xero_item_data["PurchaseDetails"]["COGSAccountCode"], settings
            )
            if cogs_account:
                # Set in item_defaults
                # ...
```

#### 4.2 Add Reverse Account Mapping Helper

```python
def get_erpnext_account_from_xero_code(xero_code, settings):
    """Find ERPNext account name from Xero account code using mapping table."""
    for mapping in settings.account_mapping:
        if mapping.xero_account_code == xero_code:
            return mapping.erpnext_account
    return None
```

### Phase 5: Add Rich Error Feedback

#### 5.1 Validation Error Messages

| Scenario | Error Message |
|----------|---------------|
| Code missing | "Item Code is required for Xero sync" |
| Code > 30 chars | "Item Code 'XXX...' exceeds Xero limit of 30 characters (current: 35)" |
| Name > 50 chars | "Item Name 'XXX...' exceeds Xero limit of 50 characters (current: 65)" |
| Description > 4000 chars | "Description exceeds Xero limit of 4000 characters (current: 4500)" |
| Missing inventory account mapping | "Missing Xero account mapping for Inventory Account 'Stock In Hand - C'. Item will sync as untracked." |
| Missing COGS account mapping | "Missing Xero account mapping for COGS Account 'Cost of Goods Sold - C'. Item will sync as untracked." |
| Item already exists | "Item with code 'XXX' already exists in Xero. Use existing item or change code." |

#### 5.2 Pre-Sync Validation

```python
def validate_item_for_xero(doc, settings):
    """
    Validate item before sync and return list of issues.
    Returns: (is_valid, issues_list)
    """
    issues = []
    
    # Required field
    if not doc.item_code:
        issues.append("Item Code is required")
    elif len(doc.item_code) > 30:
        issues.append(f"Item Code exceeds 30 characters ({len(doc.item_code)} chars)")
    
    # Optional fields with limits
    if doc.item_name and len(doc.item_name) > 50:
        issues.append(f"Item Name exceeds 50 characters ({len(doc.item_name)} chars)")
    
    if doc.description and len(doc.description) > 4000:
        issues.append(f"Description exceeds 4000 characters ({len(doc.description)} chars)")
    
    if doc.purchase_description and len(doc.purchase_description) > 4000:
        issues.append(f"Purchase Description exceeds 4000 characters ({len(doc.purchase_description)} chars)")
    
    # Tracked inventory requirements
    if doc.is_stock_item:
        inventory_account = get_inventory_account(doc)
        cogs_account = get_cogs_account(doc)
        
        if inventory_account and not get_xero_account_code(inventory_account, settings):
            issues.append(f"Inventory Account '{inventory_account}' not mapped to Xero")
        
        if cogs_account and not get_xero_account_code(cogs_account, settings):
            issues.append(f"COGS Account '{cogs_account}' not mapped to Xero")
    
    return len(issues) == 0, issues
```

## Implementation Checklist

### Phase 1: Infrastructure
- [ ] Add `xero_data_hash` field to Item in `custom_fields.py`
- [ ] Add Item to `doc_events` in `hooks.py`

### Phase 2: Outbound Sync (ERPNext → Xero)
- [ ] Add `validate_item_code()` function
- [ ] Add `validate_item_name()` function
- [ ] Add `validate_description()` function
- [ ] Add `compute_item_hash()` function
- [ ] Add `item_data_changed()` function
- [ ] Add double-trigger guard to `enqueue_sync_item()`
- [ ] Fix HTTP method logic (PUT for create, POST for update)
- [ ] Add `get_inventory_account()` helper
- [ ] Add `get_cogs_account()` helper
- [ ] Add COGSAccountCode to tracked item payload
- [ ] Add `validate_item_for_xero()` pre-sync validation
- [ ] Update `sync_item_to_xero()` with all fixes

### Phase 3: Inbound Sync (Xero → ERPNext)
- [ ] Add `get_erpnext_account_from_xero_code()` helper
- [ ] Update `process_xero_item()` to handle tracked items
- [ ] Map inventory and COGS accounts on inbound

### Phase 4: Testing
- [ ] Test outbound sync for new item (PUT)
- [ ] Test outbound sync for existing item (POST)
- [ ] Test validation errors for field length limits
- [ ] Test tracked item sync with proper accounts
- [ ] Test tracked item sync with missing account mappings
- [ ] Test inbound sync for tracked items
- [ ] Test double-trigger guard
- [ ] Test change detection (hash)

## API Limitations to Document

1. **Code is immutable after creation** - Cannot change Code after item is created in Xero
2. **Tracked items require both accounts** - Both InventoryAssetAccountCode and COGSAccountCode must be set
3. **QuantityOnHand is read-only** - Cannot set quantity via API; must use transactions
4. **TotalCostPool is read-only** - Cannot set value via API
5. **IsSold/IsPurchased affect details** - Setting to false nulls related description and details

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Existing items with long codes | Truncate with warning in log |
| Missing account mappings | Sync as untracked with warning |
| Double-trigger infinite loop | Guard with status check |
| API rate limiting | Use background jobs |
| Data loss on inbound | Create as draft, don't overwrite submitted |

## Files to Modify

| File | Changes |
|------|---------|
| `xero/setup/custom_fields.py` | Add `xero_data_hash` field |
| `xero/hooks.py` | Add Item to `doc_events` |
| `xero/api/xero_items.py` | Major rewrite with all fixes |
