# Xero Integration Codebase — Critical Knowledge for Future Tasks

> **Purpose**: This document captures essential knowledge to avoid misunderstandings when working on the Xero Integration codebase. Read this before making any changes.

---

## ⚠️ Critical Gotchas & Common Pitfalls

### 1. Double-Trigger Guard is Required for Contacts

**Problem**: The `on_update` hook fires when `xero_contact_id` is set back to the document, causing infinite loops.

**Solution**: Check `xero_sync_status == "Synced"` before enqueueing:
```python
# xero_contacts.py:26-29
xero_status = frappe.db.get_value(doc_type, doc_name, "xero_sync_status")
if xero_status == "Synced":
    return  # Already synced, skip re-trigger
```

**Remember**: Any change to contact sync logic must preserve this guard.

---

### 2. Xero Requires Non-Empty Description on Line Items

**Problem**: ERPNext stores HTML in `description` field. Xero requires plain text and non-empty description.

**Solution**: Strip HTML and fallback to `item_name` or `item_code`:
```python
# xero_invoices.py:193-201
description = (item.description or "").strip()
if description and "<" in description:
    import re
    description = re.sub(r'<[^>]+>', '', description).strip()
if not description:
    description = item.item_name or item.item_code or "Item"
```

**Remember**: Any new sync that includes description fields must handle HTML stripping.

---

### 3. Xero's IsCustomer/IsSupplier Are Read-Only API Fields

**Problem**: Xero only sets `IsCustomer`/`IsSupplier` when a contact is used on a transaction. New contacts from API have neither flag set.

**Solution**: Default to Customer when neither flag is set:
```python
# xero_contacts.py:493-501
if not is_customer and not is_supplier:
    log_xero_error(
        message=f"Xero Contact {contact_name} ({xero_contact_id}) has no Customer/Supplier flag set. Creating as Customer by default.",
        status="Info"
    )
    sync_xero_contact_to_erpnext(xero_contact_data, "Customer")
```

**Remember**: Contact type may change on "round-trip" — Suppliers might become Customers on inbound sync.

---

### 4. Cannot Update Submitted ERPNext Documents from Xero

**Problem**: ERPNext prevents modification of submitted documents. Inbound sync for existing submitted invoices will fail.

**Solution**: Inbound sync creates documents as Draft:
```python
# xero_invoices.py:844
erpnext_data["docstatus"] = 0  # Always create as Draft
```

**Remember**: Inbound invoice sync can only CREATE new documents, not update existing submitted ones.

---

### 5. Account Mapping is Required for All Invoice/Payment Syncs

**Problem**: Every line item needs a Xero AccountCode. Missing mappings cause immediate sync failure.

**Solution**: Check mapping before building payload:
```python
# xero_invoices.py:188-191
xero_account_code = get_xero_account_code(erpnext_account, settings)
if not xero_account_code:
    raise Exception(f"Xero Account Code mapping not found in Xero Settings for ERPNext Account: {erpnext_account}")
```

**Remember**: New account mappings must be added to Xero Settings before syncing invoices that use those accounts.

---

### 6. Sync Functions Are Decorated with Retry Logic

**Problem**: The `@retry_with_exponential_backoff` decorator catches all exceptions and retries.

**Solution**: Be aware that exceptions inside sync functions will trigger retries:
```python
# xero_invoices.py:45
@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_invoice_to_xero(doc_name, doc_type, **kwargs):
```

**Remember**: 
- Don't catch exceptions that should trigger retry
- Do catch exceptions that should NOT trigger retry (e.g., validation errors that won't be fixed by retrying)

---

### 7. Directional Toggles Override Entity-Specific Settings

**Problem**: Even if `sync_invoices` is enabled, sync won't happen if `enable_sync_to_xero` is disabled.

**Solution**: Check directional toggle first:
```python
# xero_invoices.py:57-65
if not settings.enable_sync_to_xero:
    log_xero_error(
        message=f"Sync to Xero is disabled. Skipping {doc_type} {doc_name} outbound sync.",
        status="Info",
        category="System Monitoring"
    )
    return
```

**Remember**: There are THREE levels of toggles:
1. `enable_xero_sync` — Master switch
2. `enable_sync_to_xero` / `enable_sync_from_xero` — Directional switches
3. `sync_invoices`, `sync_contacts`, etc. — Entity-specific switches

---

### 8. Prerequisites Are Auto-Queued, Not Synced Inline

**Problem**: When an invoice's contact isn't synced, the contact sync is queued, but the invoice sync returns immediately.

**Solution**: Invoice is marked as "Pending Prerequisites" and re-queued:
```python
# xero_invoices.py:132-159
frappe.db.set_value(doc_type, doc_name, {
    "xero_sync_status": "Pending Prerequisites"
}, update_modified=False)

# Re-queue this invoice for later
frappe.enqueue(
    "xero.api.xero_invoices.sync_invoice_to_xero",
    queue="short",
    ...
)
```

**Remember**: The prerequisite sync is asynchronous. The invoice will retry after the contact sync completes.

---

### 9. Token Refresh Happens Automatically, But Can Fail

**Problem**: Token refresh failure sends emails to System Managers and invalidates stored tokens.

**Solution**: Check for token issues before sync:
```python
# xero_client.py:119-206
def refresh_access_token():
    # ... retry logic ...
    if e.response.status_code in [400, 401]:
        # Invalid refresh token - notify and invalidate
        settings.refresh_token = None
        settings.access_token = None
        settings.save(ignore_permissions=True)
        notify_admins_token_failure("Invalid refresh token - re-authentication required")
```

**Remember**: If syncs suddenly stop working, check:
1. Xero Settings for valid tokens
2. Error Log for token refresh failures
3. Email notifications to System Managers

---

### 10. Xero API Has Rate Limiting (60 requests/minute/tenant)

**Problem**: Xero returns 429 when rate limit is exceeded.

**Solution**: Exponential backoff with configurable settings:
```python
# xero_client.py:329-353
if e.response.status_code == 429:  # Rate limit error
    retry_count += 1
    wait_time = min(backoff_base ** retry_count, max_delay)
    time.sleep(wait_time)
```

**Remember**: Bulk syncs can hit rate limits. The system handles this automatically, but it causes delays.

---

## 🧠 Mental Model Quick Reference

### Sync Flow (Outbound)

```
User submits document
    ↓
Hook fires (on_submit)
    ↓
enqueue_sync_*() queues background job
    ↓
RQ worker picks up job
    ↓
sync_*_to_xero() with @retry decorator
    ↓
Check settings (master, directional, entity)
    ↓
Check prerequisites (contact, accounts)
    ↓
Build Xero payload
    ↓
xero_request() → Xero API
    ↓
Update ERPNext custom fields
    ↓
Log to Xero Log
```

### Sync Flow (Inbound)

```
Scheduled task fires (daily/hourly)
    ↓
sync_*_from_xero()
    ↓
Paginate through Xero API (100 per page)
    ↓
For each entity:
    ↓
    Check if exists in ERPNext (by xero_*_id)
    ↓
    Create new or update existing
    ↓
    Log to Xero Log
```

### Key Files to Modify For...

| Task | File(s) to Modify |
|------|-------------------|
| Add new entity sync | `hooks.py`, new `xero_*.py` in `api/`, `custom_fields.py` |
| Change sync logic | `xero_*.py` in `api/` |
| Add new settings | `xero_settings.json`, `xero_settings.py` |
| Change retry behavior | `retry_handler.py`, `xero_client.py` |
| Add dashboard feature | `xero_sync_dashboard.py` |
| Fix OAuth issues | `xero_client.py` |
| Add scheduled task | `hooks.py`, `tasks.py` |
| Change logging | `logging.py` |

---

## 📋 Pre-Change Checklist

Before making any changes to this codebase:

1. **Check directional toggles** — Will your change respect `enable_sync_to_xero` and `enable_sync_from_xero`?

2. **Check entity-specific toggles** — Will your change respect `sync_invoices`, `sync_contacts`, etc.?

3. **Consider prerequisites** — Does your sync depend on other entities being synced first?

4. **Handle HTML in description fields** — ERPNext stores HTML, Xero requires plain text.

5. **Handle empty/null values** — Xero API rejects empty strings for required fields.

6. **Add logging** — Every sync operation should log to Xero Log with appropriate category.

7. **Consider retry behavior** — Should errors trigger retries? Use `@retry_with_exponential_backoff` appropriately.

8. **Test both directions** — If changing sync logic, test both outbound (ERPNext → Xero) and inbound (Xero → ERPNext).

9. **Test with missing mappings** — What happens if account/tax mappings aren't configured?

10. **Check for double-trigger** — If modifying contact sync, ensure the guard is preserved.

---

## 🔧 Debugging Tips

### Sync Not Triggering

1. Check `enable_xero_sync` in Xero Settings
2. Check directional toggle (`enable_sync_to_xero` or `enable_sync_from_xero`)
3. Check entity-specific toggle (`sync_invoices`, etc.)
4. Check if document is submitted (`docstatus == 1`)
5. Check Xero Log for "Skipping" messages

### Sync Failing

1. Check Xero Log for error details
2. Check error category for hints:
   - "Validation Errors" → Missing/invalid data
   - "Mapping Errors" → Account/tax mapping missing
   - "Authentication Issues" → Token expired/invalid
   - "Rate Limiting" → Too many requests
   - "Connection Issues" → Network timeout

### Token Issues

1. Check `access_token` and `refresh_token` in Xero Settings
2. Check `token_expiry` — if in past, token needs refresh
3. Check Error Log for "Xero OAuth" errors
4. Re-authenticate from Xero Settings

### Missing Data After Inbound Sync

1. Check if prerequisites are synced first (Contacts before Invoices)
2. Check account mappings — unmapped accounts cause line items to be skipped
3. Check Xero Log for "Skipping" messages
4. Check if documents are being created as Draft (not submitted)


---

## 🏗️ Architecture Decisions

### Why No Official Xero Python SDK?

The codebase uses direct `requests` calls instead of the official Xero SDK. This was a deliberate choice for:
- Simpler dependency management
- Direct control over error handling
- Easier debugging with full request/response access

### Why Separate Files for Each Entity?

Each entity type has its own module (`xero_invoices.py`, `xero_contacts.py`, etc.) because:
- Different entities have different field mappings
- Different prerequisite chains
- Easier to maintain and test individually
- Allows parallel development

### Why Background Jobs Instead of Immediate Sync?

Syncs are queued via `frappe.enqueue()` because:
- Xero API can be slow (network latency, rate limiting)
- Don't block the user's request
- Automatic retry on failure
- Can handle bulk operations without timeout

---

## ⚡ Performance Considerations

1. **Pagination** — Inbound syncs fetch 100 records per API call
2. **Caching** — Account/tax mappings are cached per request
3. **Rate Limiting** — Xero allows 60 requests/minute/tenant
4. **Background Jobs** — Use "short" queue for individual syncs, "long" for bulk
5. **Database Commits** — Each sync commits immediately after success

---

## 🚫 What NOT To Do

1. **Don't sync in the main request thread** — Always use `frappe.enqueue()`
2. **Don't catch exceptions that should retry** — Let them propagate to the retry decorator
3. **Don't modify submitted documents** — Inbound sync creates drafts only
4. **Don't assume Xero IDs are stable** — They can change if data is deleted/recreated
5. **Don't skip the double-trigger guard** — It will cause infinite loops
6. **Don't ignore rate limiting** — Xero will block your app
7. **Don't store sensitive data in logs** — Tokens, secrets should be masked

---

*Last Updated: 2026-02-12*
*Author: AI Assistant (Kilo Code)*
