# Copyright (c) 2026, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Builds Xero LineItems for outbound Sales/Purchase Invoices, Credit Notes and
Purchase Orders so that Xero's Total AND TotalTax both reconcile with ERPNext.

Tax representation (C1/C2/H1 rework):
- ERPNext percentage tax rows are NEVER sent as extra line items. Each item
  line carries an explicit Xero ``TaxType`` plus a ``TaxAmount`` override equal
  to the tax ERPNext attributed to that line (from the ``item_wise_tax_details``
  breakup table), so Xero's tax subsystem records exactly the ERPNext VAT.
- ``LineAmountTypes`` mirrors ERPNext's included_in_print_rate: Inclusive docs
  keep their gross line amounts (tax inside), Exclusive docs their net ones.
- Flat "Actual" charge rows (e.g. freight) are genuine extra lines, sent with
  TaxType NONE as before. Purchase rows with category "Valuation" don't affect
  the grand total and are omitted entirely.
- When ERPNext's rounded_total differs from grand_total, a rounding line posted
  to the company round-off account makes Xero's Total equal the amount ERPNext
  allocates payments against (H3).

The builder predicts the Total and TotalTax Xero will compute and raises
TaxRepresentationError BEFORE anything is sent if they would not reconcile —
a payload with wrong money in it must never reach Xero.
"""

import re

import frappe
from frappe.utils import cint, flt

from ..utils.exceptions import TaxRepresentationError

# Sub-cent tolerance used when deciding whether an amount is "zero".
EPSILON = 0.005
# Reconciliation tolerance on predicted vs ERPNext totals (matches the ±0.02
# tolerance the verification harness uses).
TOTAL_TOLERANCE = 0.02


def validate_invoice_description(description, item_name=None, item_code=None):
    """Validate and sanitize a line description for Xero (1..4000 chars)."""
    description = (description or "").strip()

    # Strip HTML tags if description contains them
    if description and "<" in description:
        description = re.sub(r"<[^>]+>", "", description).strip()

    if not description:
        description = item_name or item_code or "Item"

    if len(description) > 4000:
        description = description[:3997] + "..."

    return description


def build_xero_lines(doc, doc_type, settings, absolute=False, require_account=True,
                     include_rounding=True):
    """Build the Xero LineItems for an outbound document.

    :param absolute: True for returns (credit notes) — ERPNext stores them with
        negative quantities/amounts, Xero wants positive ones.
    :param require_account: False for Purchase Orders, where Xero treats the
        line AccountCode as optional; unmapped accounts are then omitted
        instead of aborting the sync.
    :param include_rounding: send a rounding line when rounded_total differs
        from grand_total (invoices/credit notes; off for Purchase Orders).
    :returns: frappe._dict(line_items, line_amount_types, target_total, total_tax)
        with target_total/total_tax the doc-currency figures an independent
        Xero read-back must show (already absolute when absolute=True).
    :raises TaxRepresentationError: when the payload could not reconcile.
    """
    account_map = settings.get_account_map()
    tax_map = settings.get_tax_map()
    account_field = "income_account" if doc_type == "Sales Invoice" else "expense_account"

    folded_rows, charge_rows = _split_tax_rows(doc)
    line_tax = _allocate_line_tax(doc, folded_rows)

    inclusive = any(cint(t.included_in_print_rate) for t in folded_rows)
    line_amount_types = "Inclusive" if inclusive else "Exclusive"

    line_items = []
    for item in doc.items:
        erpnext_account = item.get(account_field)
        account_code = account_map.get(erpnext_account) if erpnext_account else None
        if require_account and not account_code:
            raise Exception(
                f"Xero Account Code mapping not found in Xero Settings for ERPNext "
                f"Account: {erpnext_account} (Item: {item.item_code or item.description})"
            )

        line = {
            "Description": validate_invoice_description(
                item.description, item.item_name, item.item_code
            ),
            "Quantity": abs(item.qty) if absolute else item.qty,
            "UnitAmount": item.rate,
            "LineAmount": abs(flt(item.amount)) if absolute else flt(item.amount),
        }
        if account_code:
            line["AccountCode"] = account_code

        tax_amount = flt(line_tax.get(item.name), 2)
        if abs(tax_amount) >= EPSILON:
            tax_type = _resolve_tax_type(item, doc, tax_map, folded_rows)
            if not tax_type:
                raise TaxRepresentationError(_missing_tax_type_message(doc, doc_type, item, folded_rows))
            line["TaxType"] = tax_type
            line["TaxAmount"] = abs(tax_amount) if absolute else tax_amount
        else:
            line["TaxType"] = "NONE"

        # Only reference a Xero item that actually exists there; an unknown
        # ItemCode would make Xero auto-create an item as a side effect.
        if item.item_code and frappe.db.get_value("Item", item.item_code, "xero_item_id"):
            line["ItemCode"] = item.item_code

        line_items.append(line)

    for tax in charge_rows:
        line_items.append(_charge_line(tax, account_map, absolute))

    grand_total = flt(doc.grand_total)
    target_total = grand_total
    rounding_line = _rounding_line(doc, account_map, absolute) if include_rounding else None
    if rounding_line:
        line_items.append(rounding_line)
        target_total = flt(doc.rounded_total)
    if absolute:
        target_total = abs(target_total)

    total_tax = sum(flt(li.get("TaxAmount", 0)) for li in line_items)
    _verify_reconciles(doc, doc_type, line_items, inclusive, target_total)

    return frappe._dict(
        line_items=line_items,
        line_amount_types=line_amount_types,
        target_total=flt(target_total, 2),
        total_tax=flt(total_tax, 2),
    )


# ------------------------------------------------------------------ internals


def _split_tax_rows(doc):
    """Split doc.taxes into rows folded into per-line TaxAmounts vs rows sent
    as separate charge lines. Valuation-only purchase rows (which never reach
    the grand total) are dropped."""
    folded, charges = [], []
    for tax in doc.get("taxes") or []:
        if tax.get("category") == "Valuation":
            continue
        if tax.charge_type == "Actual":
            charges.append(tax)
        else:
            folded.append(tax)
    return folded, charges


def _row_sign(tax):
    return -1 if tax.get("add_deduct_tax") == "Deduct" else 1


def _folded_total(folded_rows):
    return flt(
        sum(_row_sign(t) * flt(t.tax_amount_after_discount_amount) for t in folded_rows), 2
    )


def _allocate_line_tax(doc, folded_rows):
    """Attribute the folded tax rows to item lines, in document currency.

    Primary source is ERPNext's own per-(item row, tax row) breakup table
    ``item_wise_tax_details`` (company currency — divided back by the
    conversion rate). Falls back to proportional-by-amount for documents that
    predate the breakup table. The rounding residual is pinned to the line
    carrying the most tax so the sum equals the tax-row total exactly.
    """
    alloc = {item.name: 0.0 for item in doc.items}
    if not folded_rows:
        return alloc

    folded_names = {t.name for t in folded_rows}
    conversion_rate = flt(doc.get("conversion_rate")) or 1.0
    detail_rows = [
        r for r in (doc.get("item_wise_tax_details") or [])
        if r.tax_row in folded_names and r.item_row in alloc
    ]

    total = _folded_total(folded_rows)
    if detail_rows:
        for r in detail_rows:
            alloc[r.item_row] += flt(r.amount) / conversion_rate
    else:
        base = sum(abs(flt(item.amount)) for item in doc.items)
        for item in doc.items:
            share = abs(flt(item.amount)) / base if base else 1.0 / len(doc.items)
            alloc[item.name] = total * share

    alloc = {k: flt(v, 2) for k, v in alloc.items()}
    residual = flt(total - sum(alloc.values()), 2)
    if residual:
        pin = max(alloc, key=lambda k: abs(alloc[k]))
        alloc[pin] = flt(alloc[pin] + residual, 2)
    return alloc


def _resolve_tax_type(item, doc, tax_map, folded_rows):
    """Resolve the Xero TaxType for a taxed line.

    Most-specific first: the line's Item Tax Template, then the document's
    taxes-and-charges template, then the folded tax rows' account heads. All
    three are looked up in the same Xero Settings tax mapping table.
    """
    itt = item.get("item_tax_template")
    if itt and tax_map.get(itt):
        return tax_map[itt]
    doc_template = doc.get("taxes_and_charges")
    if doc_template and tax_map.get(doc_template):
        return tax_map[doc_template]
    for tax in folded_rows:
        if tax_map.get(tax.account_head):
            return tax_map[tax.account_head]
    return None


def _missing_tax_type_message(doc, doc_type, item, folded_rows):
    candidates = []
    if item.get("item_tax_template"):
        candidates.append(f"Item Tax Template '{item.item_tax_template}'")
    if doc.get("taxes_and_charges"):
        candidates.append(f"tax template '{doc.taxes_and_charges}'")
    for tax in folded_rows:
        candidates.append(f"tax account '{tax.account_head}'")
    candidate_text = " or ".join(dict.fromkeys(candidates)) or "the applicable tax template/account"
    return (
        f"Missing Tax Mapping: cannot represent the tax on {doc_type} {doc.name} "
        f"(line: {item.item_code or item.item_name}) in Xero. Map {candidate_text} "
        f"to a Xero Tax Type under Xero Settings → Mappings, then retry. "
        f"Nothing was sent to Xero."
    )


def _charge_line(tax, account_map, absolute):
    """A flat 'Actual' charge row (e.g. freight) as its own Xero line."""
    account_code = account_map.get(tax.account_head)
    if not account_code:
        raise Exception(
            f"Xero Account Code mapping not found for Tax/Charge Account: {tax.account_head}"
        )
    amount = _row_sign(tax) * flt(tax.tax_amount_after_discount_amount)
    if absolute:
        amount = abs(amount)
    return {
        "Description": validate_invoice_description(tax.description, "Tax/Charge"),
        "Quantity": 1,
        "UnitAmount": flt(amount, 2),
        "LineAmount": flt(amount, 2),
        "AccountCode": account_code,
        "TaxType": "NONE",
    }


def _rounding_line(doc, account_map, absolute):
    """Represent ERPNext's rounding adjustment so Xero's Total equals the
    rounded_total that ERPNext allocates payments against (H3)."""
    if cint(doc.get("disable_rounded_total")):
        return None
    rounded_total, grand_total = flt(doc.get("rounded_total")), flt(doc.grand_total)
    adjustment = flt(
        (abs(rounded_total) - abs(grand_total)) if absolute else (rounded_total - grand_total), 2
    )
    if abs(adjustment) < EPSILON:
        return None

    round_off_account = frappe.get_cached_value("Company", doc.company, "round_off_account")
    account_code = account_map.get(round_off_account) if round_off_account else None
    if not account_code:
        raise TaxRepresentationError(
            f"Missing Account Mapping: {doc.doctype} {doc.name} carries a rounding "
            f"adjustment of {adjustment}, but the company round-off account "
            f"'{round_off_account or '(not set on Company)'}' has no Xero code mapping. "
            f"Map it under Xero Settings → Mappings so the Xero total can match the "
            f"ERPNext rounded total. Nothing was sent to Xero."
        )
    return {
        "Description": "Rounding adjustment (ERPNext rounded total)",
        "Quantity": 1,
        "UnitAmount": adjustment,
        "LineAmount": adjustment,
        "AccountCode": account_code,
        "TaxType": "NONE",
    }


def _verify_reconciles(doc, doc_type, line_items, inclusive, target_total):
    """Abort (never Warn-and-send) when the predicted Xero Total diverges."""
    line_sum = flt(sum(flt(li["LineAmount"]) for li in line_items), 2)
    tax_sum = flt(sum(flt(li.get("TaxAmount", 0)) for li in line_items), 2)
    predicted_total = line_sum if inclusive else flt(line_sum + tax_sum, 2)

    if abs(predicted_total - flt(target_total, 2)) > TOTAL_TOLERANCE:
        raise TaxRepresentationError(
            f"Tax representation mismatch on {doc_type} {doc.name}: the Xero payload "
            f"would total {predicted_total} but ERPNext expects {flt(target_total, 2)} "
            f"(LineAmountTypes={'Inclusive' if inclusive else 'Exclusive'}, "
            f"tax represented {tax_sum}, ERPNext tax "
            f"{flt(doc.get('total_taxes_and_charges'), 2)}). This document uses a tax "
            f"or discount structure the Xero sync cannot represent faithfully. "
            f"Nothing was sent to Xero."
        )


# --- Inbound (Xero -> ERPNext) tax reconstruction ---
# Shared by the invoice, credit note, quotation and purchase order inbound
# processors so every imported document carries the tax Xero holds.


def inbound_line_rate(line, inclusive):
    """Net (tax-exclusive) unit rate for an inbound Xero line.

    ERPNext line rates are tax-exclusive (tax lives in the taxes table), but a
    Xero document with LineAmountTypes=Inclusive carries gross amounts in both
    UnitAmount and LineAmount. Using UnitAmount verbatim on such a document
    counts the tax twice once the taxes row is added.
    """
    qty = flt(line.get("Quantity", 1)) or 1
    if inclusive:
        net_amount = flt(line.get("LineAmount", 0)) - flt(line.get("TaxAmount", 0))
        return flt(net_amount / qty)
    return flt(line.get("UnitAmount", 0))


def resolve_inbound_tax_account(doc):
    """Resolve the ERPNext tax account to post imported Xero tax against.

    Prefers the tax account on a mapped item_tax_template already set on a line.
    Only returns an account the operator has explicitly mapped — never a guess —
    so we never post VAT to a wrong account.
    """
    for item in doc.items:
        tmpl = item.get("item_tax_template")
        if tmpl:
            acc = frappe.db.get_value(
                "Item Tax Template Detail", {"parent": tmpl}, "tax_type"
            )
            if acc:
                return acc
    return None


def apply_inbound_taxes(doc, xero_data, erpnext_doctype, sign=1):
    """Add a single 'Actual' tax charge equal to Xero's total tax so the ERPNext
    grand total matches the Xero Total.

    ``sign=-1`` is for return documents (credit notes): Xero reports TotalTax
    as a positive figure while the ERPNext return carries negative amounts.

    No-op when there is no tax or no mapped tax account can be resolved; the
    caller's total-reconciliation guard then keeps the document a Draft rather
    than posting an under-taxed record.
    """
    total_tax = flt(xero_data.get("TotalTax", 0))
    if total_tax <= 0:
        return
    tax_account = resolve_inbound_tax_account(doc)
    if not tax_account:
        return
    row = {
        "charge_type": "Actual",
        "account_head": tax_account,
        "description": "Tax (imported from Xero)",
        "tax_amount": sign * total_tax,
    }
    # Purchase-side doctypes share the "Purchase Taxes and Charges" child
    # table, which requires category/add_deduct_tax.
    if erpnext_doctype in ("Purchase Invoice", "Purchase Order"):
        row["category"] = "Total"
        row["add_deduct_tax"] = "Add"
    doc.append("taxes", row)
