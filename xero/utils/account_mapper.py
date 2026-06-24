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
  run_auto_mapping(dry_run=True)    → result dict — analyse / apply with review step
  run_full_auto_map()               → result dict — one-shot: match + create + write all
  confirm_mapping(suggestions)      → writes confirmed rows to account_mapping
  push_accounts_to_xero(names)      → creates ERPNext accounts in Xero (Topology B)
  get_mapping_status()              → current status summary

Result dict shape:
  {
    "matched":            [{erpnext_account, xero_account_id, xero_code, xero_name, confidence}, ...],
    "unmatched_xero":     [{xero_account_id, xero_code, xero_name, xero_type}, ...],
    "unmatched_erpnext":  [{erpnext_account, root_type, account_type, account_number}, ...],
    "already_mapped":     [{erpnext_account, xero_code}, ...],
    "created_accounts":   [{erpnext_account, xero_account_id, xero_code, xero_name}, ...],
    "errors":             [str, ...],
    "summary": {
        "total_xero":        int,
        "total_erpnext":     int,
        "matched":           int,
        "unmatched_xero":    int,
        "unmatched_erpnext": int,
        "already_mapped":    int,
        "created":           int,
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
# Public entry points
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_auto_mapping(dry_run=True):
    from .xero_client import require_xero_manager
    require_xero_manager()
    """
    Analyse-and-optionally-apply entry point.

    dry_run=True  → analyse only, write nothing.
    dry_run=False → for Topology A (Xero as Source), also create missing ERPNext
                    accounts.  Returns result for human review / confirm step.

    Returns the result dict described in the module docstring.
    """
    dry_run = frappe.utils.cint(dry_run)
    settings = get_xero_settings()
    errors = []

    if not settings.access_token or not settings.tenant_id:
        frappe.throw("Xero connection not configured. Connect to Xero first.")

    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1, pluck="name")[0]

    # Fetch all accounts — include ARCHIVED so the mapping covers historical GL entries
    try:
        xero_accounts = _fetch_xero_accounts(include_archived=True)
    except Exception as e:
        frappe.throw(f"Failed to fetch Xero accounts: {e}")

    erpnext_accounts = _fetch_erpnext_accounts(company)

    already_mapped_xero_codes, already_mapped_erpnext, already_mapped_rows = \
        _load_existing_mappings(settings)

    matched, unmatched_xero, unmatched_erpnext, created_accounts = \
        _run_matching(
            xero_accounts, erpnext_accounts,
            already_mapped_xero_codes, already_mapped_erpnext,
            company, errors
        )

    # Topology A non-dry-run: create ERPNext accounts for unmatched Xero accounts
    if not dry_run and settings.get("setup_mode") == "Xero as Source":
        _create_missing_accounts(
            unmatched_xero, matched, created_accounts, errors, company
        )

    if not dry_run:
        _update_mapping_status(unmatched_xero, unmatched_erpnext, matched)

    return _build_result(
        matched, unmatched_xero, unmatched_erpnext,
        already_mapped_rows, created_accounts, errors,
        len(xero_accounts), len(erpnext_accounts),
        dry_run=dry_run
    )


@frappe.whitelist()
def run_full_auto_map():
    from .xero_client import require_xero_manager
    require_xero_manager()
    """
    One-shot full mapping for Topology A (Xero as Source).

    1. Fetch ALL Xero accounts (ACTIVE + ARCHIVED).
    2. Auto-match every Xero account to an ERPNext account (all confidence levels).
    3. For every still-unmatched Xero account, create an ERPNext account,
       preserving the Xero colon-separated hierarchy as group/leaf nodes.
       ARCHIVED Xero accounts are created as disabled ERPNext accounts.
    4. Write ALL matched + created rows directly to the account_mapping table.
    5. Set mapping_status = Complete when all ACTIVE Xero accounts are covered.

    This function never pushes to Xero and never modifies existing accounts.
    """
    settings = get_xero_settings()

    if not settings.access_token or not settings.tenant_id:
        frappe.throw("Xero connection not configured. Connect to Xero first.")

    company = frappe.db.get_default("company") or \
        frappe.get_all("Company", limit=1, pluck="name")[0]

    errors = []

    # 1. Fetch all Xero accounts including ARCHIVED
    try:
        xero_accounts = _fetch_xero_accounts(include_archived=True)
    except Exception as e:
        frappe.throw(f"Failed to fetch Xero accounts: {e}")

    erpnext_accounts = _fetch_erpnext_accounts(company)

    already_mapped_xero_codes, already_mapped_erpnext, already_mapped_rows = \
        _load_existing_mappings(settings)

    # 2. Auto-match
    matched, unmatched_xero, unmatched_erpnext, created_accounts = \
        _run_matching(
            xero_accounts, erpnext_accounts,
            already_mapped_xero_codes, already_mapped_erpnext,
            company, errors
        )

    # 3. Create ERPNext accounts for everything still unmatched
    #    Sort by hierarchy depth so parents are always created before children
    unmatched_xero_sorted = sorted(
        unmatched_xero,
        key=lambda a: (a.get("xero_name") or "").count(":")
    )
    _create_missing_accounts(
        unmatched_xero_sorted, matched, created_accounts, errors, company
    )

    # 4. Write all matched + created rows to the mapping table in one bulk save
    all_to_write = matched + created_accounts
    added = _bulk_write_mappings(settings, all_to_write, already_mapped_xero_codes, already_mapped_erpnext)

    # 5. Refresh mapping status
    # Count only ACTIVE Xero accounts for the completeness check
    active_xero_codes = {
        a.get("Code") for a in xero_accounts
        if a.get("Status") == "ACTIVE" and a.get("Code")
    }
    settings_fresh = get_xero_settings()
    mapped_codes = {r.xero_account_code for r in settings_fresh.account_mapping if r.xero_account_code}
    new_status = "Complete" if active_xero_codes.issubset(mapped_codes) else "Review Required"
    frappe.db.set_value("Xero Settings", "Xero Settings", "mapping_status", new_status)
    frappe.db.commit()

    result = _build_result(
        matched, unmatched_xero, unmatched_erpnext,
        already_mapped_rows, created_accounts, errors,
        len(xero_accounts), len(erpnext_accounts),
        dry_run=False
    )
    result["summary"]["written"] = added
    result["summary"]["mapping_status"] = new_status

    log_xero_error(
        message=(
            f"Full auto-map complete: {len(matched)} matched, "
            f"{len(created_accounts)} created, {added} written to mapping table, "
            f"status={new_status}."
        ),
        status="Info",
        category="Account Mapping",
    )

    return result


@frappe.whitelist()
def confirm_mapping(suggestions):
    from .xero_client import require_xero_manager
    require_xero_manager()
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

    settings.flags.ignore_version = True
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    _refresh_mapping_status(settings)

    return {"added": added, "total_mapped": len(settings.account_mapping)}


@frappe.whitelist()
def push_accounts_to_xero(account_names):
    from .xero_client import require_xero_manager
    require_xero_manager()
    """
    Topology B helper: create unmatched ERPNext accounts in Xero.
    account_names: JSON list of ERPNext account names.
    """
    import json
    from ..api.xero_accounts import build_xero_account_payload

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
                xero_acc  = response["Accounts"][0]
                xero_id   = xero_acc.get("AccountID")
                xero_code = xero_acc.get("Code")

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
# Internal helpers — data fetching
# ---------------------------------------------------------------------------

def _fetch_xero_accounts(include_archived=True):
    """
    Fetch Xero accounts via API.

    include_archived=True (default) includes ARCHIVED accounts so they can be
    mapped for historical transaction lookups.  Each returned dict carries a
    'status' key ('ACTIVE' or 'ARCHIVED').
    """
    response = xero_request("GET", "Accounts")
    if not response or not response.get("Accounts"):
        return []

    accounts = []
    for acc in response["Accounts"]:
        status = acc.get("Status", "ACTIVE")
        if status == "ARCHIVED" and not include_archived:
            continue
        if acc.get("SystemAccount") in XERO_SYSTEM_ACCOUNTS:
            continue
        if acc.get("Type") not in XERO_ACCOUNT_TYPE_MAP:
            continue
        acc["status"] = status   # normalise key
        accounts.append(acc)
    return accounts


def _fetch_erpnext_accounts(company):
    """Fetch all leaf (non-group) accounts for the given company."""
    return frappe.get_all(
        "Account",
        filters={"company": company, "is_group": 0},
        fields=["name", "account_name", "account_number", "root_type", "account_type", "xero_account_id"],
    )


def _load_existing_mappings(settings):
    """Return (mapped_xero_codes set, mapped_erpnext_names set, rows list)."""
    mapped_codes   = set()
    mapped_erpnext = set()
    rows           = []
    for row in settings.account_mapping:
        if row.xero_account_code:
            mapped_codes.add(row.xero_account_code)
        if row.erpnext_account:
            mapped_erpnext.add(row.erpnext_account)
            rows.append({
                "erpnext_account": row.erpnext_account,
                "xero_code":       row.xero_account_code,
                "xero_name":       row.xero_account_name,
            })
    return mapped_codes, mapped_erpnext, rows


# ---------------------------------------------------------------------------
# Internal helpers — matching
# ---------------------------------------------------------------------------

def _run_matching(xero_accounts, erpnext_accounts, already_mapped_codes,
                  already_mapped_erpnext, company, errors):
    """
    Core matching loop.  Returns (matched, unmatched_xero, unmatched_erpnext, created_accounts).
    created_accounts is always empty here — creation is a separate step.
    """
    matched           = []
    unmatched_xero    = []
    created_accounts  = []
    claimed_erpnext   = set(already_mapped_erpnext)

    for xero_acc in xero_accounts:
        xero_id   = xero_acc["AccountID"]
        xero_code = xero_acc.get("Code", "")
        xero_name = xero_acc.get("Name", "")
        xero_type = xero_acc.get("Type", "")
        xero_status = xero_acc.get("status", "ACTIVE")

        if xero_code and xero_code in already_mapped_codes:
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
                "xero_status":     xero_status,
                "confidence":      confidence,
            })
        else:
            unmatched_xero.append({
                "xero_account_id": xero_id,
                "xero_code":       xero_code,
                "xero_name":       xero_name,
                "xero_type":       xero_type,
                "xero_status":     xero_status,
            })

    unmatched_erpnext = [
        {
            "erpnext_account": acc["name"],
            "root_type":       acc.get("root_type", ""),
            "account_type":    acc.get("account_type", ""),
            "account_number":  acc.get("account_number", ""),
        }
        for acc in erpnext_accounts
        if acc["name"] not in claimed_erpnext
    ]

    return matched, unmatched_xero, unmatched_erpnext, created_accounts


def _find_best_erpnext_match(xero_id, xero_code, xero_name, xero_type,
                              erpnext_accounts, claimed, company):
    """
    Return (erpnext_account_name, confidence) or (None, None).

    Priority:
    1. xero_account_id already stored on the ERPNext Account   → High
    2. account_number exactly equals xero_code                 → High
    3. account_name exactly equals xero_name (case-insensitive)→ High
       (also checks the leaf segment of colon-separated Xero names)
    4. Same root_type + name similarity >= threshold            → Medium
    5. Same root_type only (first unclaimed)                    → Low
    """
    target_type_info = XERO_ACCOUNT_TYPE_MAP.get(xero_type, {})
    target_root      = target_type_info.get("root_type", "")

    best_name       = None
    best_confidence = None
    best_similarity = 0.0

    # The leaf part of a colon-separated Xero name, e.g. "Brydon" from
    # "Salaries and Wages:Instructor fees:Brydon"
    xero_leaf = (xero_name or "").split(":")[-1].strip().lower()
    xero_name_lower = (xero_name or "").lower().strip()

    for acc in erpnext_accounts:
        if acc["name"] in claimed:
            continue

        # 1. xero_account_id match
        if xero_id and acc.get("xero_account_id") == xero_id:
            return acc["name"], CONFIDENCE_HIGH

        # 2. account_number == xero_code
        if xero_code and acc.get("account_number") and \
                str(acc["account_number"]).strip() == str(xero_code).strip():
            return acc["name"], CONFIDENCE_HIGH

        # 3. Exact name match (full name or leaf segment)
        acc_name_lower = (acc.get("account_name") or "").lower().strip()
        if xero_name_lower and acc_name_lower == xero_name_lower:
            return acc["name"], CONFIDENCE_HIGH
        if xero_leaf and acc_name_lower == xero_leaf:
            return acc["name"], CONFIDENCE_HIGH

        # 4 & 5. Type-based matching
        if target_root and acc.get("root_type") == target_root:
            # Compare against both the full name and the leaf segment
            similarity = max(
                SequenceMatcher(None, xero_name_lower, acc_name_lower).ratio(),
                SequenceMatcher(None, xero_leaf, acc_name_lower).ratio(),
            )
            if similarity >= SIMILARITY_THRESHOLD and similarity > best_similarity:
                best_similarity = similarity
                best_name       = acc["name"]
                best_confidence = CONFIDENCE_MEDIUM
            elif best_confidence not in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM):
                if best_name is None:
                    best_name       = acc["name"]
                    best_confidence = CONFIDENCE_LOW

    return best_name, best_confidence


# ---------------------------------------------------------------------------
# Internal helpers — account creation
# ---------------------------------------------------------------------------

def _parse_xero_name(xero_name):
    """
    Split a Xero account name on ':' into (parent_parts, leaf_name).

    Examples:
      "Salaries and Wages"                    → ([], "Salaries and Wages")
      "Salaries and Wages:UIF"                → (["Salaries and Wages"], "UIF")
      "Salaries and Wages:Instructor fees:Brydon"
                                              → (["Salaries and Wages", "Instructor fees"], "Brydon")
    """
    parts = [p.strip() for p in (xero_name or "").split(":") if p.strip()]
    if not parts:
        return [], xero_name or ""
    return parts[:-1], parts[-1]


def _get_or_create_group_account(path_parts, root_type, company):
    """
    Walk path_parts, finding or creating is_group=1 Account nodes at each level.
    Returns the ERPNext account name of the deepest node, which is used as the
    parent when inserting the leaf account.

    If path_parts is empty, returns the root group for root_type.
    """
    # Find the topmost group for this root_type (lowest lft = closest to root)
    root_group = frappe.db.get_value(
        "Account",
        {"root_type": root_type, "is_group": 1, "company": company},
        "name",
        order_by="lft asc",
    )
    if not root_group:
        return None

    current_parent = root_group

    for part in path_parts:
        # Look for an existing group account with this name under the company
        existing = frappe.db.get_value(
            "Account",
            {"account_name": part, "is_group": 1, "company": company},
            "name",
        )
        if existing:
            current_parent = existing
            continue

        # Create a new group account under current_parent
        try:
            doc = frappe.new_doc("Account")
            doc.account_name   = part[:140]
            doc.parent_account = current_parent
            doc.root_type      = root_type
            doc.is_group       = 1
            doc.company        = company
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            current_parent = doc.name
        except Exception as e:
            # If creation fails (e.g. duplicate), try to find it again
            fallback = frappe.db.get_value(
                "Account",
                {"account_name": part, "company": company},
                "name",
            )
            if fallback:
                current_parent = fallback
            else:
                raise e

    return current_parent


def _create_missing_accounts(unmatched_xero, matched, created_accounts, errors, company):
    """
    For each entry in unmatched_xero, create an ERPNext Account (with proper
    hierarchy from colon-separated Xero names) and move the entry to matched +
    created_accounts.  Modifies all three lists in place.
    """
    for xero_acc in list(unmatched_xero):   # iterate copy — we mutate the list
        try:
            erpnext_name = _create_erpnext_account_from_xero(xero_acc, company)
            if erpnext_name:
                entry = {
                    "erpnext_account": erpnext_name,
                    "xero_account_id": xero_acc["xero_account_id"],
                    "xero_code":       xero_acc["xero_code"],
                    "xero_name":       xero_acc["xero_name"],
                    "xero_type":       xero_acc["xero_type"],
                    "xero_status":     xero_acc.get("xero_status", "ACTIVE"),
                    "confidence":      CONFIDENCE_HIGH,
                }
                matched.append(entry)
                created_accounts.append(entry)
                unmatched_xero.remove(xero_acc)
        except Exception as e:
            errors.append(
                f"Failed to create ERPNext account for Xero '{xero_acc.get('xero_name')}': {e}"
            )


def _create_erpnext_account_from_xero(xero_acc, company):
    """
    Create an ERPNext Account stub for a Xero account that has no match.

    - Parses colon-separated Xero names to build the correct parent hierarchy.
    - ARCHIVED Xero accounts become disabled ERPNext accounts.
    - Returns the new account's ERPNext name, or None on failure.
    """
    xero_type   = xero_acc.get("xero_type") or xero_acc.get("Type", "")
    xero_name   = xero_acc.get("xero_name") or xero_acc.get("Name", "")
    xero_code   = xero_acc.get("xero_code") or xero_acc.get("Code", "")
    xero_id     = xero_acc.get("xero_account_id") or xero_acc.get("AccountID", "")
    xero_status = xero_acc.get("xero_status") or xero_acc.get("Status", "ACTIVE")

    type_info = XERO_ACCOUNT_TYPE_MAP.get(xero_type)
    if not type_info or not xero_name:
        return None

    root_type    = type_info["root_type"]
    account_type = type_info["account_type"]

    # Parse hierarchy
    parent_parts, leaf_name = _parse_xero_name(xero_name)

    # Ensure parent group chain exists
    parent = _get_or_create_group_account(parent_parts, root_type, company)
    if not parent:
        return None

    # Deduplicate the leaf name within the company
    base_name = leaf_name[:140]
    acc_name  = base_name
    suffix    = 1
    while frappe.db.exists("Account", {"account_name": acc_name, "company": company}):
        acc_name = f"{base_name} ({suffix})"
        suffix  += 1

    doc = frappe.new_doc("Account")
    doc.account_name    = acc_name
    doc.account_number  = (xero_code or "")[:20]
    doc.parent_account  = parent
    doc.root_type       = root_type
    doc.account_type    = account_type
    doc.company         = company
    doc.xero_account_id = xero_id
    doc.disabled        = 1 if xero_status == "ARCHIVED" else 0
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return doc.name


# ---------------------------------------------------------------------------
# Internal helpers — writing and status
# ---------------------------------------------------------------------------

def _bulk_write_mappings(settings, rows_to_write, existing_codes, existing_erpnext):
    """
    Append mapping rows to settings.account_mapping and save once.

    Reloads the document immediately before writing so we always have the latest
    modified timestamp — prevents Frappe's concurrent-edit conflict check from
    rejecting the save when account creation has already bumped the doc.
    Returns the number of rows actually added.
    """
    added         = 0
    local_codes   = set(existing_codes)
    local_erpnext = set(existing_erpnext)

    # Collect rows to append before touching the document
    to_append = []
    for row in rows_to_write:
        ea   = row.get("erpnext_account")
        code = row.get("xero_code") or row.get("xero_account_code")
        name = row.get("xero_name") or row.get("xero_account_name", "")

        if not ea or not code:
            continue
        if ea in local_erpnext or code in local_codes:
            continue

        xero_account_doc = frappe.db.get_value("Xero Account", {"account_code": code}, "name")
        to_append.append({
            "erpnext_account":   ea,
            "xero_account":      xero_account_doc or None,
            "xero_account_code": code,
            "xero_account_name": name,
        })
        local_codes.add(code)
        local_erpnext.add(ea)
        added += 1

    if added:
        # Reload fresh to get the current modified timestamp, then bypass version check
        fresh = frappe.get_doc("Xero Settings", "Xero Settings")
        fresh.flags.ignore_version = True

        fresh_codes   = {r.xero_account_code for r in fresh.account_mapping if r.xero_account_code}
        fresh_erpnext = {r.erpnext_account for r in fresh.account_mapping if r.erpnext_account}

        for row in to_append:
            if row["xero_account_code"] in fresh_codes or row["erpnext_account"] in fresh_erpnext:
                continue
            fresh.append("account_mapping", row)
            fresh_codes.add(row["xero_account_code"])
            fresh_erpnext.add(row["erpnext_account"])

        fresh.save(ignore_permissions=True)
        frappe.db.commit()

    return added


def _update_mapping_status(unmatched_xero, unmatched_erpnext, matched):
    """Set mapping_status on Xero Settings based on what's still unresolved."""
    if unmatched_xero or unmatched_erpnext:
        new_status = "Review Required"
    elif matched:
        new_status = "In Progress"
    else:
        new_status = "Not Started"

    frappe.db.set_value("Xero Settings", "Xero Settings", "mapping_status", new_status)
    frappe.db.commit()


def _refresh_mapping_status(settings):
    """Recompute and persist mapping_status after a confirm operation."""
    try:
        xero_accounts = _fetch_xero_accounts(include_archived=False)   # ACTIVE only for completeness check
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
        pass


def _build_result(matched, unmatched_xero, unmatched_erpnext, already_mapped_rows,
                  created_accounts, errors, total_xero, total_erpnext, dry_run=True):
    result = {
        "matched":           matched,
        "unmatched_xero":    unmatched_xero,
        "unmatched_erpnext": unmatched_erpnext,
        "already_mapped":    already_mapped_rows,
        "created_accounts":  created_accounts,
        "errors":            errors,
        "summary": {
            "total_xero":        total_xero,
            "total_erpnext":     total_erpnext,
            "matched":           len(matched),
            "unmatched_xero":    len(unmatched_xero),
            "unmatched_erpnext": len(unmatched_erpnext),
            "already_mapped":    len(already_mapped_rows),
            "created":           len(created_accounts),
        }
    }

    log_xero_error(
        message=(
            f"Account mapping {'analysis' if dry_run else 'run'} complete: "
            f"{result['summary']['matched']} matched, "
            f"{result['summary']['unmatched_xero']} unmatched Xero, "
            f"{result['summary']['unmatched_erpnext']} unmatched ERPNext, "
            f"{result['summary']['created']} created."
        ),
        status="Info",
        category="Account Mapping",
    )

    return result
