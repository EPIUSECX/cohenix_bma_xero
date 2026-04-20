# Xero Integration Codebase Reference Sheet

> **Internal Reference for AI Assistant** — Quick lookup for answering questions about this codebase.

---

## Project Overview

| Attribute | Value |
|-----------|-------|
| **Type** | Frappe App (ERPNext Integration) |
| **Purpose** | Bidirectional sync between ERPNext and Xero Accounting |
| **Location** | `cohenix-bench/apps/xero/xero/` |
| **Version** | 0.0.1 (Production Ready v2.0.0) |
| **Python** | 3.8+ |
| **Framework** | Frappe Framework (v13/v14/v15) |

---

## Directory Structure (Quick Reference)

```
xero/
├── hooks.py                    # ⭐ ENTRY POINT - doc_events, scheduler_events
├── tasks.py                    # Scheduled task implementations
├── api/                        # ⭐ SYNC LOGIC - 11 modules
│   ├── xero_invoices.py        # Sales/Purchase Invoice (964 lines)
│   ├── xero_contacts.py        # Customer/Supplier (970 lines)
│   ├── xero_payments.py        # Payment Entry (607 lines)
│   ├── xero_journals.py        # Journal Entry
│   ├── xero_accounts.py        # Chart of Accounts
│   ├── xero_items.py           # Item/Product
│   ├── xero_quotes.py          # Quotations
│   ├── xero_bank_transactions.py
│   ├── xero_credit_notes.py
│   ├── xero_purchase_orders.py
│   └── xero_reports.py         # Financial reports
├── utils/                      # ⭐ UTILITIES
│   ├── xero_client.py          # OAuth2, API client (445 lines)
│   ├── logging.py              # Xero Log creation
│   ├── retry_handler.py        # Exponential backoff
│   └── webhook_handler.py      # Xero webhooks
├── setup/
│   └── custom_fields.py        # Custom field installation
├── xero/doctype/               # ⭐ DATA MODELS
│   ├── xero_settings/          # Configuration (Single)
│   ├── xero_log/               # Audit trail
│   ├── xero_account_mapping/   # Account map
│   └── xero_tax_mapping/       # Tax map
└── xero/page/xero_sync_dashboard/  # Dashboard (2254 lines)
```

---

## Key Functions by Module

### hooks.py — Entry Points

```python
doc_events = {
    "Sales Invoice": {"on_submit": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
                      "on_cancel": "xero.api.xero_invoices.enqueue_void_invoice"},
    "Purchase Invoice": {"on_submit": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
                         "on_cancel": "xero.api.xero_invoices.enqueue_void_invoice"},
    "Customer": {"on_update": "xero.api.xero_contacts.enqueue_sync_contact"},
    "Supplier": {"on_update": "xero.api.xero_contacts.enqueue_sync_contact"},
    "Payment Entry": {"on_submit": "xero.api.xero_payments.enqueue_sync_payment"},
    "Journal Entry": {"on_submit": "xero.api.xero_journals.enqueue_sync_journal",
                      "on_cancel": "xero.api.xero_journals.delete_journal_from_xero"},
    "Bank Transaction": {"on_submit": "xero.api.xero_bank_transactions.enqueue_sync_bank_transaction"},
    "Quotation": {"on_submit": "xero.api.xero_quotes.enqueue_sync_quotation"},
    "Purchase Order": {"on_submit": "xero.api.xero_purchase_orders.enqueue_sync_purchase_order"}
}

scheduler_events = {
    "daily": ["xero.tasks.sync_all_enabled", "xero.tasks.validate_sync_integrity"],
    "hourly": ["xero.tasks.check_payments", "xero.tasks.monitor_sync_health", "xero.tasks.sync_pending_documents"],
    "weekly": ["xero.tasks.reconcile_all_entities", "xero.tasks.cleanup_old_logs"]
}
```

### xero_client.py — API Layer

| Function | Purpose | Lines |
|----------|---------|-------|
| `get_xero_settings()` | Returns Xero Settings single doc | 15-18 |
| `get_auth_url()` | Generates OAuth2 authorization URL | 28-44 |
| `handle_oauth_callback()` | Processes OAuth callback | 47-96 |
| `refresh_access_token()` | Refreshes OAuth token with retry | 119-206 |
| `get_xero_client()` | Returns headers with valid token | 252-276 |
| `xero_request(method, endpoint, data, params)` | **Main API call function** | 280-391 |

### xero_invoices.py — Invoice Sync

| Function | Purpose | Direction |
|----------|---------|-----------|
| `enqueue_sync_invoice_or_return(doc, method)` | Hook handler, routes to invoice or credit note | — |
| `sync_invoice_to_xero(doc_name, doc_type)` | Syncs SI/PI to Xero | Outbound |
| `sync_invoices_from_xero()` | Fetches all invoices from Xero | Inbound |
| `process_xero_invoice(xero_invoice_data, settings)` | Creates/updates ERPNext invoice | Inbound |
| `get_xero_account_code(erpnext_account, settings)` | Maps ERPNext account to Xero code | Helper |
| `map_erpnext_tax_to_xero(erpnext_tax_template, settings)` | Maps tax template to Xero tax type | Helper |

### xero_contacts.py — Contact Sync

| Function | Purpose | Direction |
|----------|---------|-----------|
| `enqueue_sync_contact(doc_name, doc_type)` | Hook handler with double-trigger guard | — |
| `sync_contact_to_xero(doc_name, doc_type)` | Syncs Customer/Supplier to Xero | Outbound |
| `sync_contacts_from_xero()` | Fetches all contacts from Xero | Inbound |
| `process_xero_contact(xero_contact_data)` | Creates/updates ERPNext contact | Inbound |
| `get_primary_address(parent_doctype, parent_name)` | Gets address for Xero | Helper |
| `get_primary_contact_details(parent_doctype, parent_name)` | Gets contact info | Helper |

### xero_payments.py — Payment Sync

| Function | Purpose | Direction |
|----------|---------|-----------|
| `enqueue_sync_payment(doc, method)` | Hook handler | — |
| `sync_payment_to_xero(doc_name, doc_type)` | Main payment sync | Outbound |
| `sync_invoice_payments(doc, ...)` | Handles invoice-linked payments | Outbound |
| `sync_standalone_payment(doc, ...)` | Handles advance payments | Outbound |
| `sync_payments_from_xero()` | Fetches payments from Xero | Inbound |
| `process_xero_payment(xero_payment_data, settings)` | Creates ERPNext Payment Entry | Inbound |

### logging.py — Audit Trail

```python
def log_xero_error(
    message,                    # Main log message
    status="Error",             # Success/Error/Info/Warning
    erpnext_doc_type=None,      # e.g., "Sales Invoice"
    erpnext_doc_name=None,      # Document name
    xero_entity_type=None,      # e.g., "Invoice", "Contact"
    xero_entity_id=None,        # Xero GUID
    direction=None,             # "ERPNext to Xero" or "Xero to ERPNext"
    error_details=None,         # Full traceback
    category=None,              # Auto-categorized if not provided
    retry_count=0,
    processing_time=None,
    sync_batch_id=None
)
```

### retry_handler.py — Retry Logic

```python
@retry_with_exponential_backoff(max_retries=3, base_delay=1, max_delay=60, backoff_factor=2)
def sync_function(...):
    # If this raises an exception, it will retry with exponential backoff
    pass
```

---

## Data Models (DocTypes)

### Xero Settings (Single)

**Key Fields:**
- `enable_xero_sync` — Master switch
- `enable_sync_to_xero` — Outbound sync toggle
- `enable_sync_from_xero` — Inbound sync toggle
- `client_id`, `client_secret` — OAuth credentials
- `access_token`, `refresh_token`, `token_expiry` — Auto-managed
- `tenant_id`, `tenant_name` — Xero organization
- `sync_invoices`, `sync_contacts`, `sync_payments`, etc. — Entity toggles
- `account_mapping` — Child table (Xero Account Mapping)
- `tax_mapping` — Child table (Xero Tax Mapping)
- `max_retry_attempts` — Default: 5
- `api_timeout` — Default: 30

### Xero Log

**Key Fields:**
- `timestamp` — When sync occurred
- `status` — Success/Error/Info/Warning
- `message` — Main log message
- `erpnext_doc_type`, `erpnext_doc_name` — ERPNext document
- `xero_entity_type`, `xero_entity_id` — Xero entity
- `direction` — "ERPNext to Xero" or "Xero to ERPNext"
- `error_details` — Full traceback
- `category` — Auto-categorized (Connection Issues, Validation Errors, etc.)

### Custom Fields on ERPNext DocTypes

| DocType | Fields |
|---------|--------|
| Sales Invoice | `xero_invoice_id`, `xero_sync_status`, `xero_credit_note_id` |
| Purchase Invoice | `xero_invoice_id`, `xero_sync_status`, `xero_credit_note_id` |
| Payment Entry | `xero_payment_id`, `xero_bank_transaction_id`, `xero_sync_status`, `xero_last_sync`, `xero_payment_data` |
| Customer | `xero_contact_id`, `xero_sync_status`, `xero_last_contact_sync` |
| Supplier | `xero_contact_id`, `xero_sync_status`, `xero_last_contact_sync` |
| Item | `xero_item_id`, `xero_sync_status`, `xero_last_item_sync` |
| Account | `xero_account_id`, `xero_sync_status`, `xero_last_account_sync` |
| Journal Entry | `xero_manual_journal_id`, `xero_sync_status`, `xero_last_sync` |
| Quotation | `xero_quote_id`, `xero_sync_status`, `xero_last_quote_sync` |
| Bank Transaction | `xero_bank_transaction_id`, `xero_sync_status`, `xero_last_bank_sync` |
| Purchase Order | `xero_purchase_order_id`, `xero_sync_status`, `xero_last_purchase_order_sync` |

---

## Sync Status Values

| Status | Meaning |
|--------|---------|
| `Pending` | Document not yet synced |
| `Synced` | Successfully synced to Xero |
| `Error` | Sync failed (check Xero Log) |
| `Skipped` | Intentionally not synced |
| `Pending Prerequisites` | Waiting for contact/account sync |
| `Voided in Xero` | Cancelled in ERPNext, voided in Xero |

---

## Xero API Reference

### Endpoints

| Purpose | URL |
|---------|-----|
| API Base | `https://api.xero.com/api.xro/2.0` |
| OAuth Authorize | `https://login.xero.com/identity/connect/authorize` |
| OAuth Token | `https://identity.xero.com/connect/token` |
| Connections | `https://api.xero.com/connections` |

### Entity Endpoints

| Entity | Endpoint |
|--------|----------|
| Invoices | `/Invoices` |
| Contacts | `/Contacts` |
| Payments | `/Payments` |
| Accounts | `/Accounts` |
| Items | `/Items` |
| Bank Transactions | `/BankTransactions` |
| Manual Journals | `/ManualJournals` |
| Quotes | `/Quotes` |
| Purchase Orders | `/PurchaseOrders` |
| Credit Notes | `/CreditNotes` |

### Rate Limiting

- **Limit**: 60 requests per minute per tenant
- **Response**: 429 status code when exceeded
- **Headers**: `X-Rate-Limit-Remaining`, `X-Rate-Limit-Reset`

---

## Common Patterns

### Enqueue Pattern (All API Modules)

```python
@frappe.whitelist()
def enqueue_sync_*(doc, method):
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_*"):
        return
    
    frappe.enqueue(
        "xero.api.xero_*.sync_*_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        doc_name=doc.name,
        doc_type=doc.doctype
    )
```

### Sync Function Pattern

```python
@retry_with_exponential_backoff(max_retries=3, base_delay=2)
def sync_*_to_xero(doc_name, doc_type, **kwargs):
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return
    
    if not settings.enable_sync_to_xero:
        log_xero_error(message="Sync to Xero is disabled", status="Info", category="System Monitoring")
        return
    
    if not settings.get("sync_*"):
        return
    
    try:
        doc = frappe.get_doc(doc_type, doc_name)
        # ... build payload ...
        response = xero_request("PUT", "Endpoint", data={...})
        # ... update ERPNext ...
        log_xero_error(message="Success", status="Success", ...)
    except Exception as e:
        frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Error")
        log_xero_error(message="Failed", error_details=frappe.get_traceback(), ...)
```

### Inbound Sync Pattern

```python
def sync_*_from_xero():
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.enable_sync_from_xero:
        return
    
    page = 1
    while True:
        response = xero_request("GET", "Endpoint", params={"page": page})
        if not response or not response.get("Endpoint"):
            break
        
        for entity in response["Endpoint"]:
            try:
                process_xero_*(entity, settings)
            except Exception as e:
                log_xero_error(...)
        
        if len(response["Endpoint"]) < 100:
            break
        page += 1
```

---

## Error Categories (Auto-Categorized)

| Category | Trigger Keywords |
|----------|-----------------|
| Connection Issues | connection, timeout, network, refused |
| Validation Errors | validation, required, invalid, must be |
| Authentication Issues | authentication, token, unauthorized, 401, 403 |
| Rate Limiting | rate limit, throttle, 429, too many requests |
| System Monitoring | sync health monitoring, health check |
| Mapping Errors | mapping, account code, tax, not found in settings |
| Other Errors | (default) |

---

## Prerequisite Chain

```
Account (Chart of Accounts)
    ↓
Contact (Customer/Supplier)
    ↓
Invoice (Sales/Purchase)
    ↓
Payment Entry
```

**Rules:**
- Invoices require Contact to be synced first
- Payments require Invoice and Bank Account to be synced first
- Missing prerequisites → "Pending Prerequisites" status → auto-requeue

---

## Quick Debugging

| Issue | Check |
|-------|-------|
| Sync not triggering | `enable_xero_sync`, directional toggles, entity toggles, `docstatus==1` |
| Sync failing | Xero Log → error_details, category |
| Token issues | Xero Settings → `token_expiry`, Error Log for "Xero OAuth" |
| Missing data after inbound | Prerequisites synced? Account mappings? Check for "Skipping" in logs |
| Rate limiting | Xero Log → category="Rate Limiting" |

---

## File Line References (Key Code Locations)

| What | File | Lines |
|------|------|-------|
| Double-trigger guard | `xero_contacts.py` | 26-29 |
| Description HTML stripping | `xero_invoices.py` | 193-201 |
| Default to Customer | `xero_contacts.py` | 493-501 |
| Account mapping check | `xero_invoices.py` | 188-191 |
| Token refresh with retry | `xero_client.py` | 119-206 |
| Rate limit handling | `xero_client.py` | 329-353 |
| Directional toggle check | `xero_invoices.py` | 57-65 |
| Prerequisite re-queue | `xero_invoices.py` | 132-159 |
| Retry decorator | `retry_handler.py` | 10-57 |
| Auto-categorization | `logging.py` | 52-80 |

---

## What NOT To Do

1. ❌ Sync in main request thread — Always use `frappe.enqueue()`
2. ❌ Catch exceptions that should retry — Let them propagate to decorator
3. ❌ Modify submitted documents — Inbound creates drafts only
4. ❌ Assume Xero IDs are stable — They can change on delete/recreate
5. ❌ Skip double-trigger guard — Will cause infinite loops
6. ❌ Ignore rate limiting — Xero will block the app
7. ❌ Store secrets in logs — Mask tokens, passwords

---

*Reference Sheet v1.0 — 2026-02-12*
