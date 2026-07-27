# Frappe Cloud Marketplace — Listing Preparation

Staged copy and checklist for the app's Marketplace listing. Everything below is
filled in on the **Frappe Cloud dashboard** (Marketplace → your app → the
listing/overview tab), not in this repo — this file exists so publishing is a
paste job, and so listing copy is reviewed like code.

The last audit failed three listing checks: **Missing Long Description**,
**No Screenshots**, and **Missing Links**. Those are resolved on the dashboard
using the material below.

## Field checklist

| Field | Requirement (FC guidelines) | Status |
| --- | --- | --- |
| App name | Unique on the marketplace (`xero`) | Set by the app repo |
| App title | Max 255 chars | Ready — see below |
| Short description (summary) | One sentence, 40–80 chars, only proper nouns capitalized, don't repeat the title | Ready — see below |
| Long description | Usage + features; **no installation instructions**; don't duplicate the summary | Ready — paste from below |
| Logo | ≥ 200×200 px, square, centered, **no text in the image** | **TODO — asset needed** |
| Screenshots | Uploaded separately from the description | **TODO — shot list below** |
| Category | Pick the closest match to primary functionality | Suggest **Accounting** (or nearest available, e.g. ERP/Integrations) |
| Website URL | Publisher web page | **TODO — decide URL** |
| Documentation URL | Where users learn to use the app | Suggest the repo README (or a docs site if one exists) |
| Support URL | "The URL of a web page that your customers will go to" for help | Suggest GitHub Issues, or a company support portal |
| Privacy Policy URL | Required — a real, hosted privacy policy page | **TODO — must exist before submission** |
| Terms of Service URL | Publisher terms page | **TODO** |
| Demo video | Recommended (short, shows the app in use) | Optional — decide later |
| Publisher profile | Valid contact info on the FC developer account | Verify before submitting |

> **Open decision — publisher identity.** The repo currently carries two
> identities: `hooks.py` says publisher *EPI-USE Global Services*
> (support@epiuse.com) while `pyproject.toml` says author *Cohenix*
> (info@cohenix.com). The listing, the FC publisher account, and the repo
> metadata should agree before submission.

## App title

```
Xero Integration
```

## Short description (54 chars)

```
Bidirectional accounting sync between ERPNext and Xero
```

Alternative (69 chars):

```
Keep ERPNext and Xero in sync — invoices, payments, contacts and more
```

## Long description (paste as-is, Markdown)

```markdown
Connect ERPNext and Xero and keep both sets of books in step. The integration
synchronizes accounting data in both directions, runs in the background on the
Frappe queue, and gives operators a full dashboard to monitor and control every
sync.

**ERPNext → Xero:** Sales Invoices become Xero Invoices and Purchase Invoices
become Bills — with line items, tax breakdowns, and rounding handled so the
totals reconcile. Payment Entries sync as Payments, Journal Entries as Manual
Journals, and Customers, Suppliers, Items, Accounts, Credit Notes, Quotations,
and Purchase Orders all flow across as their Xero counterparts.

**Xero → ERPNext:** import your Chart of Accounts, Contacts (including notes),
Items, Invoices, Bills, Credit Notes, Payments, and Bank Transactions, plus
Trial Balance, P&L, and Balance Sheet figures for reconciliation.

**Built for real operations:**

- OAuth2 with encrypted token storage and automatic refresh
- Webhooks for near-real-time inbound updates where Xero provides them,
  scheduled and manual syncs for everything else
- Rate limiting, exponential-backoff retries, and idempotency keys so
  transient failures never duplicate documents
- Loop prevention via content hashing — an inbound update never echoes back out
- Account and tax mapping tools, with clear per-document errors when a mapping
  is missing
- A six-tab sync dashboard: health overview, manual and bulk sync triggers,
  per-entity status, analytics, searchable logs with one-click retry, and
  configuration
- A complete audit trail: every sync attempt is logged with direction, linked
  document, and Xero's actual response

**Status: Beta.** This app reads and writes financial records in both systems.
Always test against a non-live Xero organisation (such as the Xero Demo
Company) first, then run inbound-only sync against production data, and only
then enable full bidirectional sync — the staged rollout is documented in the
README, together with the disclaimer of warranty and liability. Keep backups
of both systems. Xero is a trademark of Xero Limited; this app is an
independent integration and is not affiliated with or endorsed by Xero Limited.
```

## Screenshot shot list

Take these on a demo site seeded with realistic (non-real) data. Before
shooting, check every frame for real tenant names, tokens, email addresses, or
customer data. PNG, consistent browser width (≥ 1280 px wide), light theme.

1. **Sync dashboard — Overview tab**: connection healthy, health score, recent stats.
2. **Sync Operations tab**: per-entity manual triggers and bulk actions.
3. **Entity Status tab**: per-doctype synced/pending counts.
4. **Sync Logs tab**: filtered log list showing success and one retryable error.
5. **Xero Settings**: the directional sync toggles (outbound/inbound sections).
6. **Account mapping**: Xero Account Mapping with mapped rows.

## Publishing steps (after the PR merges to `main`)

1. FC dashboard → Marketplace → app → complete every field above; upload logo
   and screenshots.
2. Create a new release from the latest `main` commit and submit for review —
   the review/audit (including semgrep) re-runs against that release. Reviews
   take up to ~10 days.
3. If the audit reports listing items again, re-check this file's TODOs first.

References: [Publishing an app](https://docs.frappe.io/cloud/marketplace/publishing-an-app-to-marketplace) ·
[Marketplace guidelines](https://docs.frappe.io/cloud/marketplace/marketplace-guidelines)
