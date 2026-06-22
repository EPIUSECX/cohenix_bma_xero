# Xero Integration — End-to-End Test Plan

**App:** `xero` (ERPNext ↔ Xero Accounting)  
**Environment required:** ERPNext sandbox site + Xero Demo Company (or dedicated test tenant)  
**Prerequisite:** Xero Developer account, OAuth2 app configured with the correct redirect URI

---

## Pre-flight Setup

| Step | Action | Expected |
|------|--------|----------|
| S1 | Navigate to **Xero Settings** | Form loads, all sections visible |
| S2 | Enter Client ID, Client Secret, Redirect URL | Fields save without error |
| S3 | Enable Xero Synchronization | All direction and entity toggles appear |
| S4 | Click **Connect to Xero** | Browser redirects to Xero login |
| S5 | Authorise the app in Xero | Redirect back; `tenant_id`, `tenant_name`, `access_token` populated |
| S6 | Click **Check Connection** | Status shows `Active` |
| S7 | If multiple Xero orgs: click **Switch Organisation** | Picker shows all tenants; switching updates `tenant_id` |

---

## Phase 1 — Master Data / Contacts

### 1.1 Outbound: Customer → Xero Contact
| ID | Steps | Expected |
|----|-------|---------|
| C-OUT-01 | Enable `Contacts → Xero`. Create/save a new Customer | Xero Contact created; `xero_contact_id` populated on Customer |
| C-OUT-02 | Edit Customer name, save | Xero Contact updated (POST with ContactID) |
| C-OUT-03 | Create Customer with special characters (`< > &`) in name | Name sanitised, contact syncs without 400 error |
| C-OUT-04 | Create Supplier, save | Xero Contact created with Supplier type markers |
| C-OUT-05 | Disable `Contacts → Xero`, save a Customer | No Xero log entry created; Xero Contact NOT updated |

### 1.2 Inbound: Xero Contact → ERPNext
| ID | Steps | Expected |
|----|-------|---------|
| C-IN-01 | Enable `Contacts ← Xero`. Run daily sync task manually | Contacts without `xero_contact_id` created in ERPNext |
| C-IN-02 | Run sync twice (simulate overlap via two manual triggers) | No duplicate contacts; idempotency preserved |

---

## Phase 2 — Items

### 2.1 Outbound
| ID | Steps | Expected |
|----|-------|---------|
| I-OUT-01 | Enable `Items → Xero`. Create/save an Item with Sales and Purchase prices | Xero Item created; `xero_item_id` populated |
| I-OUT-02 | Edit Item description, save | Xero Item updated |

### 2.2 Inbound
| ID | Steps | Expected |
|----|-------|---------|
| I-IN-01 | Enable `Items ← Xero`. Run daily sync | Items from Xero created in ERPNext |

---

## Phase 3 — Chart of Accounts

| ID | Steps | Expected |
|----|-------|---------|
| A-01 | Enable `Chart of Accounts ← Xero`. Run daily sync | Xero Accounts created as `Xero Account` DocType; account mapping helper populated |
| A-02 | Navigate to Xero Settings → Mappings → **Sync Xero Accounts** | Account Mapping table pre-filled with matched codes |
| A-03 | Use Quick Map Accounts (via JS dialog) to map two Xero codes | Mapping saved; `auto_retry` re-queues previously failed syncs |

---

## Phase 4 — Invoices (Core)

### 4.1 Sales Invoice Outbound (ERPNext → Xero)
| ID | Steps | Expected |
|----|-------|---------|
| SI-OUT-01 | Enable `Sales Invoices → Xero`. Submit a Sales Invoice with a mapped item | Xero ACCREC Invoice created; `xero_invoice_id` and `xero_sync_status = Synced` set |
| SI-OUT-02 | Create a Sales Invoice with an unmapped account | Error logged with category `Mapping Errors`; status `Error` |
| SI-OUT-03 | Cancel a synced Sales Invoice | Xero invoice voided (status `VOIDED`) |
| SI-OUT-04 | Disable `Sales Invoices → Xero`, submit invoice | No sync occurs; toggle respected |

### 4.2 Purchase Invoice (Bills) Outbound
| ID | Steps | Expected |
|----|-------|---------|
| PI-OUT-01 | Enable `Bills (Purchase) → Xero`. Submit a Purchase Invoice | Xero ACCPAY Invoice created |
| PI-OUT-02 | Cancel synced Purchase Invoice | Xero invoice voided |

### 4.3 Invoices Inbound (Xero → ERPNext)
| ID | Steps | Expected |
|----|-------|---------|
| INV-IN-01 | Create an ACCREC Invoice in Xero. Enable `Sales Invoices ← Xero`. Run daily sync | ERPNext Sales Invoice created as Draft |
| INV-IN-02 | Run daily sync again for same invoice | No duplicate created; existing record updated |
| INV-IN-03 | Simulate concurrent sync (trigger twice simultaneously) | Cache lock prevents duplicate; second run logs `already in progress` |
| INV-IN-04 | Xero invoice with DueDate before Date | ERPNext invoice created with due_date clamped to posting_date; Warning logged |

---

## Phase 5 — Credit Notes

| ID | Steps | Expected |
|----|-------|---------|
| CN-OUT-01 | Enable `Credit Notes → Xero`. Create a Sales return (credit note) | Xero Credit Note created |
| CN-IN-01 | Enable `Credit Notes ← Xero`. Run daily sync | Xero Credit Notes appear as ERPNext return invoices |

---

## Phase 6 — Payments

| ID | Steps | Expected |
|----|-------|---------|
| PAY-OUT-01 | Enable `Payments → Xero`. Submit a Payment Entry against a synced Sales Invoice | Xero Payment created; `xero_payment_id` set |
| PAY-OUT-02 | Submit a Payment Entry against a non-synced invoice | Error logged: prerequisite contact/invoice not synced |
| PAY-IN-01 | Enable `Payments ← Xero`. Mark a Xero invoice as paid in Xero. Run hourly task | Payment Entry created in ERPNext (or invoice status updated) |
| PAY-IN-02 | Run payment check twice | No duplicate Payment Entry |

---

## Phase 7 — Journal Entries

| ID | Steps | Expected |
|----|-------|---------|
| JE-OUT-01 | Enable `Sync Journal Entries → Xero` (new toggle). Submit a balanced Journal Entry with mapped accounts | Xero Manual Journal created via POST; `xero_manual_journal_id` set |
| JE-OUT-02 | Previously JE-OUT-01 would silently skip (LITE mode). Confirm it now syncs | Sync occurs; no false-positive log about toggle being off |
| JE-OUT-03 | Cancel a synced Journal Entry | Xero Manual Journal voided (status `VOIDED`) via POST |
| JE-OUT-04 | Disable `Journal Entries → Xero`, submit JE | No sync; toggle respected |

---

## Phase 8 — Bank Transactions

| ID | Steps | Expected |
|----|-------|---------|
| BT-OUT-01 | Enable `Bank Transactions → Xero`. Submit a Bank Transaction | Xero Bank Transaction created via POST (not PUT); `xero_bank_transaction_id` set |
| BT-OUT-02 | Re-sync the same Bank Transaction (simulate update) | POST with BankTransactionID in payload; Xero record updated |

---

## Phase 9 — Purchase Orders

| ID | Steps | Expected |
|----|-------|---------|
| PO-OUT-01 | Enable `Purchase Orders → Xero`. Submit a Purchase Order | Xero Purchase Order created via POST; `xero_purchase_order_id` set |
| PO-OUT-02 | Re-sync the same PO after amending | POST with PurchaseOrderID in payload; Xero PO updated |

---

## Phase 10 — Quotations

| ID | Steps | Expected |
|----|-------|---------|
| Q-OUT-01 | Enable `Quotations → Xero`. Submit a Quotation to a Customer | Xero Quote created via POST; `xero_quote_id` set |
| Q-OUT-02 | Re-sync amended Quotation | POST with QuoteID in payload; Xero Quote updated |

---

## Phase 11 — Multi-Tenant

| ID | Steps | Expected |
|----|-------|---------|
| MT-01 | Connect Xero account with multiple organisations | All tenants stored in cache; Switch Organisation button visible |
| MT-02 | Switch to second organisation | `tenant_id` and `tenant_name` update; subsequent syncs target new org |
| MT-03 | Verify a new sync (e.g. contact) targets the switched org | Xero Contact created in the correct organisation |

---

## Phase 12 — Error Handling & Retry

| ID | Steps | Expected |
|----|-------|---------|
| ERR-01 | Revoke Xero access token manually | Next sync attempt refreshes token; if refresh also fails, admins emailed |
| ERR-02 | Invalidate refresh token | System clears tokens; Notification Log entry created for System Managers |
| ERR-03 | Submit an invoice when Xero API returns 429 | Retry with exponential back-off; succeeds on retry; Warning logged |
| ERR-04 | Submit an invoice with a line item description > 4000 chars | Description truncated; invoice syncs; Warning logged |
| ERR-05 | Submit invoice with no account mapping | Error logged, category `Mapping Errors`; `xero_sync_status = Error` |
| ERR-06 | Fix account mapping, click **Quick Map Accounts** with `auto_retry = true` | Failed invoices re-queued and synced |

---

## Phase 13 — Scheduled Tasks

| ID | Steps | Expected |
|----|-------|---------|
| SCHED-01 | Run `xero.tasks.sync_all_enabled` manually | All enabled inbound entities synced; Success log |
| SCHED-02 | Run `xero.tasks.sync_pending_documents` manually | All outbound Pending/Error docs re-queued for extended entities (JE, BT, PO, Quotes) |
| SCHED-03 | Run `xero.tasks.validate_sync_integrity` | Reports any invoices with Xero IDs but no sync status |
| SCHED-04 | Run `xero.tasks.cleanup_old_logs` | Logs older than `log_retention_days` deleted |
| SCHED-05 | Run `xero.tasks.monitor_sync_health` with >10 errors in last hour | Email alert sent to System Manager users (verified via Has Role, not role_profile_name) |

---

## Phase 14 — Security / OAuth

| ID | Steps | Expected |
|----|-------|---------|
| SEC-01 | Attempt OAuth callback with tampered `state` parameter | `frappe.throw` — invalid state; no token stored |
| SEC-02 | Replay same OAuth callback twice | Second attempt rejected (state cleared after first use) |
| SEC-03 | Non-System-Manager user attempts to access Xero Settings | Permission denied |

---

## Pass / Fail Criteria

- **Pass:** All tests in Phases 1–14 produce expected outcomes with no unhandled exceptions.
- **Conditional pass:** Phase 12 ERR-01/02 require deliberate token manipulation; acceptable to validate via code review if sandbox limitations prevent live test.
- **Fail:** Any duplicate record created (INV-IN-02, INV-IN-03, PAY-IN-02), any wrong HTTP method (BT-OUT-02, PO-OUT-02, Q-OUT-02 must use POST not PUT), or any LITE-mode entity silently skipping when its toggle is ON (JE-OUT-01, BT-OUT-01, PO-OUT-01, Q-OUT-01).

---

## Known Gaps / Future Work

1. **Inbound sync for Journal Entries, Bank Transactions, Purchase Orders, Quotations** — not currently implemented (outbound only). No test cases needed until inbound modules are built.
2. **Webhook real-time sync** — end-to-end test requires a publicly accessible URL; recommend ngrok tunnel for local testing.
3. **Financial Reports inbound** — `xero_reports.py` exists but the `sync_financial_reports_from_xero` entry point needs to be confirmed before adding to test suite.
