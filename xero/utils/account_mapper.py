# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""
Xero ↔ ERPNext Account Auto-Mapper
====================================
Provides intelligent, confidence-scored matching between ERPNext and Xero
charts of accounts, removing the need for manual mapping at deployment time.

Two deployment topologies are supported:

  Topology A — Xero as Source of Truth
      Client runs Xero and is adopting ERPNext.  On first sync, pull the Xero
      chart of accounts and create / match ERPNext accounts automatically.
      Account mapping is 1:1 after confirmation.

  Topology B — ERPNext as Source of Truth
      Client runs ERPNext and is adopting Xero as the new accounting provider.
      Auto-match ERPNext accounts to Xero accounts by type and name.  Flag
      gaps for manual review.  Never create Xero accounts without explicit
      consultant confirmation.

Public API
----------
  run_auto_mapping(dry_run=False)   → result dict (see below)
  confirm_mapping(suggestions)      → writes confirmed rows to account_mapping
  push_accounts_to_xero(account_names) → creates ERPNext accounts in Xero

Result dict shape:
  {
    "matched":            [{erpnext_account, xero_account_id, xero_code, xero_name, confidence}, ...],
    "unmatched_xero":     [{xero_account_id, xero_code, xero_name, xero_type}, ...],
    "unmatched_erpnext":  [{erpnext_account, root_type, account_type, account_number}, ...],
    "already_mapped":     [{erpnext_account, xero_code}, ...],
    "created_accounts":   [{erpnext_account, xero_account_id}, ...],   # Topology A only
    "errors":             [str, ...],
    "summary": {
        "total_xero": int,
        "total_erpnext": int,
        "matched": int,
        "unmatched_xero": int,
        "unmatched_erpnext": int,
        "already_mapped": int,
        "created": int,
    }
  }
"""

import frappe
from difflib import SequenceMatcher
from ..api.xero_accounts import XERO_ACCOUNT_TYPE_MAP, XERO_SYSTEM_ACCOUNTS
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error

# ---------------------------------------------------------------------------
# Confidence constants
# ---------------------------------------------------------------------------
CONFIDENCE_HIGH   = "High"    # Code or name exact match — safe to auto-apply
CONFIDENCE_MEDIUM = "Medium"  # Type + fuzzy name match — review recommended
CONFIDENCE_LOW    = "Low"     # Type match only — manual confirmation required

SIMILARITY_THRESHOLD = 0.80   # Minimum SequenceMatcher ratio for Medium confidence


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_auto_mapping(dry_run=True):
    """
    Main entry point.  Fetches accounts from both sides and runs matching.

    dry_run=True  → analyse only, write nothing.
    dry_run=False → for Topology A (Xero as Source), also create missing ERPNext
                    accounts.  Never writes to Xero.

    Returns the result dict described in the module docstring.
    """
    dry_run = frappe.utils.cint(dry_run)
    settings = get_xero_settings()
    errors = []

    if not settings.access_token or not settings.tenant_id:
        frappe.throw("Xero connection not configured. Connect to Xero first.")

    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1, pluck="name")[0]

    # --- 1. Fetch Xero accounts ---
    try:
        xero_accounts = _fetch_xero_accounts()
    except Exception as e:
        frappe.throw(f"Failed to fetch Xero accounts: {e}")

    # --- 2. Fetch ERPNext accounts (leaf nodes only, for the active company) ---
    erpnext_accounts = _fetch_erpnext_accounts(company)

    # --- 3. Build lookup structures ---
    # Xero keyed by AccountID
    xero_by_id   = {a["AccountID"]: a for a in xero_accounts}
    # ERPNext keyed by name (the full "Code - Name - Abbr" string)
    erpnext_by_name = {a["name"]: a for a in erpnext_accounts}

    # --- 4. Find rows that are already in the mapping table ---
    already_mapped_xero_codes = set()
    already_mapped_erpnext    = set()
    already_mapped_rows       = []

    for row in settings.account_mapping:
        if row.xero_account_code:
            already_mapped_xero_codes.add(row.xero_account_code)
        if row.erpnext_account:
            already_mapped_erpnext.add(row.erpnext_account)
            already_mapped_rows.append({
                "erpnext_account": row.erpnext_account,
                "xero_code":       row.xero_account_code,
                "xero_name":       row.xero_account_name,
            })

    # --- 5. Run matching ---
    matched           = []
    unmatched_xero    = []
    unmatched_erpnext = []
    created_accounts  = []

    # Track which ERPNext accounts have been claimed by a match
    claimed_erpnext = set(already_mapped_erpnext)

    for xero_acc in xero_accounts:
        xero_id   = xero_acc["AccountID"]
        xero_code = xero_acc.get("Code", "")
        xero_name = xero_acc.get("Name", "")
        xero_type = xero_acc.get("Type", "")

        # Skip if this Xero code is already in the mapping table
        if xero_code and xero_code in already_mapped_xero_codes:
            continue

        erpnext_name, confidence = _find_best_erpnext_match(
            xero_id, xero_code, xero_name, xero_type,
            erpnext_accounts, claimed_erpnext, company
        )

        if erpnext_name:
            claimed_erpnext.add(erpnext_name)
            matched.append({
                "erpnext_account": erpnext_name,
                "xero_account_id": xero_id,
                "xero_code":       xero_code,
                "xero_name":       xero_name,
                "xero_type":       xero_type,
                "confidence":      confidence,
            })
        else:
            unmatched_xero.append({
                "xero_account_id": xero_id,
                "xero_code":       xero_code,
                "xero_name":       xero_name,
                "xero_type":       xero_type,
            })

    # Unmatched ERPNext accounts
    for acc in erpnext_accounts:
        if acc["name"] not in claimed_erpnext:
            unmatched_erpnext.append({
                "erpnext_account": acc["name"],
                "root_type":       acc.get("root_type", ""),
                "account_type":    acc.get("account_type", ""),
                "account_number":  acc.get("account_number", ""),
            })

    # --- 6. Topology A: create ERPNext accounts for unmatched Xero accounts ---
    if not dry_run and settings.get("setup_mode") == "Xero as Source":
        for xero_acc in unmatched_xero[:]:   # iterate copy — we modify the list
            try:
                erpnext_name = _create_erpnext_account_from_xero(xero_acc, company)
                if erpnext_name:
                    created_accounts.append({
                        "erpnext_account": erpnext_name,
                        "xero_account_id": xero_acc["xero_account_id"],
                        "xero_code":       xero_acc["xero_code"],
                        "xero_name":       xero_acc["xero_name"],
                    })
                    # Move from unmatched to matched with High confidence
                    matched.append({
                        "erpnext_account": erpnext_name,
                        "xero_account_id": xero_acc["xero_account_id"],
                        "xero_code":       xero_acc["xero_code"],
                        "xero_name":       xero_acc["xero_name"],
                        "xero_type":       xero_acc["xero_type"],
                        "confidence":      CONFIDENCE_HIGH,
                    })
                    unmatched_xero.remove(xero_acc)
            except Exception as e:
                errors.append(f"Failed to create ERPNext account for Xero '{xero_acc.get('xero_name')}': {e}")

    # --- 7. Update mapping_status on settings ---
    if not dry_run:
        if unmatched_xero or unmatched_erpnext:
            new_status = "Review Required"
        elif matched:
            new_status = "In Progress"
        else:
            new_status = "Not Started"

        frappe.db.set_value("Xero Settings", "Xero Settings", "mapping_status", new_status)
        frappe.db.commit()

    result = {
        "matched":            matched,
        "unmatched_xero":     unmatched_xero,
        "unmatched_erpnext":  unmatched_erpnext,
        "already_mapped":     already_mapped_rows,
        "created_accounts":   created_accounts,
        "errors":             errors,
        "summary": {
            "total_xero":         len(xero_accounts),
            "total_erpnext":      len(erpnext_accounts),
            "matched":            len(matched),
            "unmatched_xero":     len(unmatched_xero),
            "unmatched_erpnext":  len(unmatched_erpnext),
            "already_mapped":     len(already_mapped_rows),
            "created":            len(created_accounts),
        }
    }

    log_xero_error(
        message=(
            f"Auto-mapping {'analysis' if dry_run else 'run'} complete: "
            f"{result['summary']['matched']} matched, "
            f"{result['summary']['unmatched_xero']} unmatched Xero, "
            f"{result['summary']['unmatched_erpnext']} unmatched ERPNext, "
            f"{result['summary']['created']} created."
        ),
        status="Info",
        category="System Monitoring",
    )

    return result


@frappe.whitelist()
def confirm_mapping(suggestions):
    """
    Write confirmed mapping rows to the Xero Settings account_mapping table.

    suggestions: JSON list of {erpnext_account, xero_code, xero_name, xero_account_id}
    Rows already present (same erpnext_account OR same xero_code) are skipped.
    """
    import json
    if isinstance(suggestions, str):
        suggestions = json.loads(suggestions)

    settings = get_xero_settings()
    existing_erpnext = {r.erpnext_account for r in settings.account_mapping if r.erpnext_account}
    existing_codes   = {r.xero_account_code for r in settings.account_mapping if r.xero_account_code}

    added = 0
    for s in suggestions:
        ea   = s.get("erpnext_account")
        code = s.get("xero_code") or s.get("xero_account_code")
        name = s.get("xero_name") or s.get("xero_account_name")

        if not ea or not code:
            continue
        if ea in existing_erpnext or code in existing_codes:
            continue

        # Try to resolve the Xero Account DocType record (optional link).
        # The Xero Account doctype field is `account_code`, not `xero_code`.
        xero_account_doc = frappe.db.get_value("Xero Account", {"account_code": code}, "name")

        settings.append("account_mapping", {
            "erpnext_account":   ea,
            "xero_account":      xero_account_doc or None,
            "xero_account_code": code,
            "xero_account_name": name or "",
        })
        existing_erpnext.add(ea)
        existing_codes.add(code)
        added += 1

    settings.save(ignore_permissions=True)
    frappe.db.commit()

    # Set status to Complete if nothing is left unmatched
    _refresh_mapping_status(settings)

    return {"added": added, "total_mapped": len(settings.account_mapping)}


@frappe.whitelist()
def push_accounts_to_xero(account_names):
    """
    Topology B helper: create unmatched ERPNext accounts in Xero.
    account_names: JSON list of ERPNext account names.

    Returns list of {erpnext_account, xero_account_id, xero_code} for successes.
    """
    import json
    from ..api.xero_accounts import build_xero_account_payload, validate_account_code

    if isinstance(account_names, str):
        account_names = json.loads(account_names)

    settings = get_xero_settings()
    created = []
    errors  = []

    for acc_name in account_names:
        try:
            doc = frappe.get_doc("Account", acc_name)
            payload = build_xero_account_payload(doc, settings)
            response = xero_request("POST", "Accounts", data={"Accounts": [payload]})

            if response and response.get("Accounts"):
                xero_acc    = response["Accounts"][0]
                xero_id     = xero_acc.get("AccountID")
                xero_code   = xero_acc.get("Code")

                frappe.db.set_value("Account", acc_name, "xero_account_id", xero_id, update_modified=False)
                frappe.db.commit()

                created.append({
                    "erpnext_account": acc_name,
                    "xero_account_id": xero_id,
                    "xero_code":       xero_code,
                    "xero_name":       xero_acc.get("Name"),
                })
            else:
                errors.append(f"No valid response for {acc_name}")

        except Exception as e:
            errors.append(f"{acc_name}: {e}")

    return {"created": created, "errors": errors}


@frappe.whitelist()
def get_mapping_status():
    """Return current mapping status and a quick summary for the UI."""
    settings = get_xero_settings()
    return {
        "setup_mode":     settings.get("setup_mode") or "Manual",
        "mapping_status": settings.get("mapping_status") or "Not Started",
        "mapped_count":   len([r for r in settings.account_mapping if r.erpnext_account and r.xero_account_code]),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_xero_accounts():
    """Fetch all non-system, active Xero accounts via API."""
    response = xero_request("GET", "Accounts")
    if not response or not response.get("Accounts"):
        return []

    accounts = []
    for acc in response["Accounts"]:
        if acc.get("Status") != "ACTIVE":
            continue
        if acc.get("SystemAccount") in XERO_SYSTEM_ACCOUNTS:
            continue
        if acc.get("Type") not in XERO_ACCOUNT_TYPE_MAP:
            continue
        accounts.append(acc)
    return accounts


def _fetch_erpnext_accounts(company):
    """Fetch all leaf (non-group) accounts for the given company."""
    return frappe.get_all(
        "Account",
        filters={"company": company, "is_group": 0},
        fields=["name", "account_name", "account_number", "root_type", "account_type", "xero_account_id"],
    )


def _find_best_erpnext_match(xero_id, xero_code, xero_name, xero_type, erpnext_accounts, claimed, company):
    """
    Return (erpnext_account_name, confidence) for the best match, or (None, None).

    Priority:
    1. xero_account_id already stored on the ERPNext Account   → High
    2. account_number exactly equals xero_code                 → High
    3. account_name exactly equals xero_name (case-insensitive)→ High
    4. Same root_type + name similarity >= threshold            → Medium
    5. Same root_type only (first unclaimed)                    → Low
    """
    target_type_info = XERO_ACCOUNT_TYPE_MAP.get(xero_type, {})
    target_root      = target_type_info.get("root_type", "")

    best_name       = None
    best_confidence = None
    best_similarity = 0.0

    xero_name_lower = (xero_name or "").lower().strip()

    for acc in erpnext_accounts:
        if acc["name"] in claimed:
            continue

        # 1. xero_account_id match
        if xero_id and acc.get("xero_account_id") == xero_id:
            return acc["name"], CONFIDENCE_HIGH

        # 2. account_number == xero_code
        if xero_code and acc.get("account_number") and str(acc["account_number"]).strip() == str(xero_code).strip():
            return acc["name"], CONFIDENCE_HIGH

        # 3. Exact name match
        acc_name_lower = (acc.get("account_name") or "").lower().strip()
        if xero_name_lower and acc_name_lower == xero_name_lower:
            return acc["name"], CONFIDENCE_HIGH

        # 4 & 5. Type-based matching
        if target_root and acc.get("root_type") == target_root:
            similarity = SequenceMatcher(None, xero_name_lower, acc_name_lower).ratio()
            if similarity >= SIMILARITY_THRESHOLD and similarity > best_similarity:
                best_similarity = similarity
                best_name       = acc["name"]
                best_confidence = CONFIDENCE_MEDIUM
            elif best_confidence not in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM):
                # Keep the first Low candidate
                if best_name is None:
                    best_name       = acc["name"]
                    best_confidence = CONFIDENCE_LOW

    return best_name, best_confidence


def _create_erpnext_account_from_xero(xero_acc, company):
    """
    Topology A: create an ERPNext Account stub for a Xero account that has
    no matching ERPNext account.  Returns the new account's name, or None.
    """
    xero_type  = xero_acc.get("xero_type") or xero_acc.get("Type", "")
    xero_name  = xero_acc.get("xero_name") or xero_acc.get("Name", "")
    xero_code  = xero_acc.get("xero_code") or xero_acc.get("Code", "")
    xero_id    = xero_acc.get("xero_account_id") or xero_acc.get("AccountID", "")

    type_info  = XERO_ACCOUNT_TYPE_MAP.get(xero_type)
    if not type_info or not xero_name:
        return None

    root_type    = type_info["root_type"]
    account_type = type_info["account_type"]

    # Find parent account: first non-group account under the matching root
    parent = frappe.db.get_value(
        "Account",
        {"root_type": root_type, "is_group": 1, "company": company},
        "name",
        order_by="lft asc",
    )
    if not parent:
        return None

    # Build a unique account name
    base_name = xero_name[:140]
    acc_name  = base_name
    suffix    = 1
    while frappe.db.exists("Account", {"account_name": acc_name, "company": company}):
        acc_name = f"{base_name} ({suffix})"
        suffix  += 1

    doc = frappe.new_doc("Account")
    doc.account_name   = acc_name
    doc.account_number = (xero_code or "")[:20]
    doc.parent_account = parent
    doc.root_type      = root_type
    doc.account_type   = account_type
    doc.company        = company
    doc.xero_account_id = xero_id
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return doc.name


def _refresh_mapping_status(settings):
    """Set mapping_status to Complete if every Xero account has a mapping."""
    try:
        xero_accounts = _fetch_xero_accounts()
        xero_codes    = {a.get("Code") for a in xero_accounts if a.get("Code")}
        mapped_codes  = {r.xero_account_code for r in settings.account_mapping if r.xero_account_code}

        if xero_codes and xero_codes.issubset(mapped_codes):
            new_status = "Complete"
        elif mapped_codes:
            new_status = "In Progress"
        else:
            new_status = "Not Started"

        frappe.db.set_value("Xero Settings", "Xero Settings", "mapping_status", new_status)
        frappe.db.commit()
    except Exception:
        pass  # Don't let a status refresh crash a confirm operation
