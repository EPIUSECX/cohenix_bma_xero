# Long Description

**FC requirements:** covers usage, features, and app details; must **not**
contain installation instructions; must not duplicate the summary; screenshots
are uploaded separately (folder `05_screenshots/`), not embedded here.
Markdown supported.

Paste everything below the line as-is.

---

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
Items, Invoices, Bills, Credit Notes, Payments, and Bank Transactions.

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
