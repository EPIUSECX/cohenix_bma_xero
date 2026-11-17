# Review: tax mapping per side and zero-rated lines

- Date: 2026-11-17
- Branch: `fix/tax-direction-and-zero-rate`
- Reviewer: an independent reviewer that did not write the change
- Checklist: the `frappe-code-review` checklist of the bench kit
- Sources checked: this app, Frappe `version-16`, ERPNext `version-16`

## What the branch changes

1. Each tax mapping row has an Applies To field: Both, Sales or Purchases. A Sales and a Purchase Taxes and Charges Template can share a name, and one tax account can serve both sides. Xero needs a tax type per side.
2. A line that ERPNext rates at 0% keeps its mapped Xero tax type with a tax amount of 0. Before, every line without tax was sent as `NONE`.
3. The token refresh test follows the direct token store that `main` already has.

## First pass (commits 511d0d3 to 6a2e6b0): fix first

| Id | Severity | Finding | Result |
| --- | --- | --- | --- |
| C1 | Critical | `_resolve_zero_rated_tax_type` fell back to the mapping of the tax account. One account carries several rates. A 0% line was sent with the standard-rate type, and with a sales type on a bill. | Fixed in e50bf94 |
| m1 | Minor | The mapping wizard and the fetch button dedupe on the name only. They cannot create or show a row per side. | Documented in the README. The wizard writes Both rows. A row per side is added in the Tax Mapping table. |
| m2 | Minor | An Item Tax Template for another tax account, or with the rate `"N/A"`, counted as zero-rated. | Fixed in e50bf94 |
| m3 | Minor | A line with an Item Tax Template and no rates was always `NONE` on a zero-rated document. | Fixed in e50bf94. The line follows the document. |
| m4 | Minor | Test gaps: account fallback, credit notes, purchase orders, the real `get_tax_map`, the inbound fallback to a Both row. | Tests added in e50bf94 |
| m5 | Minor | The refresh test mocks `_store_tokens`, so the store had no test. | Test added in e50bf94 |

Nits not changed, with the reason:

- `direction_of` returns Sales for an unknown doctype. No caller passes one.
- A row with an Applies To value outside the three options is ignored. The Select field prevents it through the form.
- The evidence manifest lists screenshots that git ignores. The screenshots show site data and stay local.
- The new messages are not wrapped in `_()`. The file does not translate its messages.

## Second pass (commits c0316dc and e50bf94): ship

The reviewer confirmed C1 and m1 to m5 as resolved. It found no new critical or major finding, and two smaller ones:

| Id | Severity | Finding | Result |
| --- | --- | --- | --- |
| N1 | Minor | A template with 0% rows that is mapped to a rated Xero type still gave that type on a document without tax. | Fixed. A row that records a Xero Tax Rate above 0 never serves a line without tax. The README states the rule. |
| N2 | Nit | A line with one 0% account and one `"N/A"` account was sent as `NONE`. | Fixed. `"N/A"` is not a rate and is ignored. |

Tests: `test_template_mapped_to_a_rated_type_is_not_used_on_an_untaxed_document` (N1), `test_zero_rated_only_leaves_out_rows_with_a_rate` (N1), `test_rate_and_not_applicable_account_together_are_zero_rated` (N2).

Limit of the N1 guard: it reads the Xero Tax Rate of the mapping row. A row typed by hand without a rate has no guard.

## The rule after the fix

A line without tax keeps a Xero tax type only when a mapping proves a 0% rate:

- its Item Tax Template rates every tax account of the document at 0%, and that template is mapped, or
- every tax row of the document is 0%, no line carries tax, and the document's template is mapped.

Every other line without tax is sent as `NONE`. The mapping of a tax account serves taxed lines only.

## Regression tests

`xero/tests/test_tax_mapping.py`:

- `TestZeroTaxLinesNeverBorrowARatedMapping` covers C1 and m2.
- `test_item_template_without_rates_follows_the_document` covers m3.
- `test_zero_rated_credit_note_keeps_its_mapped_type`, `test_zero_rated_purchase_order_keeps_its_mapped_type` and `test_inbound_lookup_falls_back_to_a_both_row` cover m4.

`xero/tests/test_xero_client.py`: `test_store_tokens_writes_the_pair_encrypted_and_masks_the_fields` covers m5.

## Checks against a Xero demo company

The Xero Demo Company (Global) has no South African tax rates. Three rates with the South African names were created for the check. The real South African tax type codes were not tested.

- Xero rejects a sales-only tax type on a bill, and a purchases-only tax type on a sales invoice.
- Xero accepts a rated tax type with a tax amount of 0. This is why a 0% line must not borrow a rated mapping.
- Five documents synced through the app after the fix. Each had the expected tax type, and the Xero totals matched ERPNext: sales 15% exclusive, sales 15% inclusive, sales 0% export, purchase 15% exclusive, purchase without VAT.
