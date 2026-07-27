# Marketplace Submission Package — Xero Integration

Everything the Frappe Cloud Marketplace listing needs, one folder per field.
Fill the TODOs, drop the image assets into `04_logo/` and `05_screenshots/`,
then zip this `marketplace/` directory and hand it to the app lister. Every
field is entered on the **Frappe Cloud dashboard** (Marketplace → app →
listing/overview tab) — nothing in this package is read by the app itself.

The last audit failed three listing checks — **Missing Long Description**,
**No Screenshots**, **Missing Links** — all resolved by completing this package
on the dashboard.

## Contents & status

| Folder | Field | FC requirement | Status |
| --- | --- | --- | --- |
| `01_app_title/` | App title | Max 255 chars | ✅ Ready |
| `02_summary/` | Short description | One sentence, 40–80 chars, only proper nouns capitalized | ✅ Ready (two options) |
| `03_long_description/` | Long description | Usage + features; **no installation instructions** | ✅ Ready (Markdown) |
| `04_logo/` | Logo | ≥ 200×200 px, square, **no text in image** | ⬜ TODO — add `logo.png` |
| `05_screenshots/` | Screenshots | Uploaded separately from description | ⬜ TODO — 6 shots listed |
| `06_category/` | Category | Closest match to primary functionality | ✅ Suggested |
| `07_links/` | Website / Documentation / Support / Privacy Policy / ToS URLs | Support + Privacy Policy are required | ⬜ TODO — URLs to confirm |

Also recommended by FC (optional, not in this package): a short **demo video**
showing the app in use, and valid contact info on the FC publisher profile.

## Publisher identity

Standardized 2026-07-27 to **EPI-USE Global Services** (support@epiuse.com) —
now consistent across `hooks.py`, `pyproject.toml`, and the repo copyright.
The FC publisher account used for submission must match this identity.

## Publishing steps (after the release PR merges to `main`)

1. FC dashboard → Marketplace → app → complete every field from this package;
   upload the logo and screenshots.
2. Create a new release from the latest `main` commit and submit for review —
   the review/audit (including semgrep) re-runs against that release. Reviews
   take up to ~10 days.
3. If the audit reports listing items again, re-check this package's TODOs first.

References: [Publishing an app](https://docs.frappe.io/cloud/marketplace/publishing-an-app-to-marketplace) ·
[Marketplace guidelines](https://docs.frappe.io/cloud/marketplace/marketplace-guidelines)
