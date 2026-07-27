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
from ..utils.transactions import commit_checkpoint, commit_external_outcome

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
    frappe.db.set_single_value("Xero Settings", "mapping_status", new_status)

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
            payload.pop("AccountID", None)
            response = xero_request(
                "PUT", "Accounts",
                data={"Accounts": [payload]},
                idempotency_key=f"Account:{acc_name}:create",
            )

            if response and response.get("Accounts"):
                xero_acc  = response["Accounts"][0]
                xero_id   = xero_acc.get("AccountID")
                xero_code = xero_acc.get("Code")

                frappe.db.set_value("Account", acc_name, "xero_account_id", xero_id, update_modified=False)
                # The account now exists in Xero; its linkage must survive a
                # failure later in this loop or a re-push would duplicate it.
                commit_external_outcome()

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


@frappe.whitelist()
def get_unmapped_accounts_for_resolution():
    """
    Power the "Resolve Unmapped Accounts" picker.

    Returns every ERPNext leaf account that has NO mapping row yet, each with a
    suggested *existing* Xero account (best fuzzy match, if any) so the user can
    decide map-vs-create with full information, plus the full live Xero chart for
    the dropdown. Accounts referenced by recent mapping-error logs are flagged
    and sorted first so the failing ones are immediately actionable.

    Shape:
      {
        "unmapped": [{erpnext_account, account_name, root_type, account_type,
                      account_number, is_tax, has_recent_error,
                      suggested: {code, name, confidence} | None}, ...],
        "xero_accounts": [{code, name, type, account_id}, ...],
        "company": str,
      }
    """
    from .xero_client import require_xero_manager
    require_xero_manager()

    settings = get_xero_settings()
    if not settings.access_token or not settings.tenant_id:
        frappe.throw("Xero connection not configured. Connect to Xero first.")

    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1, pluck="name")[0]

    # Only ACTIVE Xero accounts are valid map targets / creation duplicates check
    xero_accounts = _fetch_xero_accounts(include_archived=False)
    erpnext_accounts = _fetch_erpnext_accounts(company)
    _mapped_codes, mapped_erpnext, _rows = _load_existing_mappings(settings)

    xero_list = sorted(
        [
            {
                "code":       a.get("Code", ""),
                "name":       a.get("Name", ""),
                "type":       a.get("Type", ""),
                "account_id": a.get("AccountID", ""),
            }
            for a in xero_accounts if a.get("Code")
        ],
        key=lambda x: (x["code"] or ""),
    )

    error_accounts = _recent_mapping_error_accounts()

    unmapped = []
    for acc in erpnext_accounts:
        if acc["name"] in mapped_erpnext:
            continue
        suggestion = _find_best_xero_match(acc, xero_accounts)
        unmapped.append({
            "erpnext_account":  acc["name"],
            "account_name":     acc.get("account_name") or acc["name"],
            "root_type":        acc.get("root_type", ""),
            "account_type":     acc.get("account_type", ""),
            "account_number":   acc.get("account_number", ""),
            "is_tax":           1 if acc.get("account_type") == "Tax" else 0,
            "has_recent_error": 1 if acc["name"] in error_accounts else 0,
            "suggested":        suggestion,
        })

    # Failing accounts first, then by type/name
    unmapped.sort(key=lambda x: (-x["has_recent_error"], x["root_type"], x["account_name"]))
    return {"unmapped": unmapped, "xero_accounts": xero_list, "company": company}


@frappe.whitelist()
def resolve_unmapped_accounts(resolutions):
    """
    Apply the picker's decisions (create-in-Xero or map-to-existing).

    Map-only batches run inline for instant feedback. Any batch that creates
    accounts in Xero is handed to a background job (queue="long") so it does not
    block the request and so the shared rate limiter can pace the POSTs; on
    completion the job fires a `xero_resolve_done` realtime event with the summary.

    resolutions: JSON list of
      {erpnext_account, action: "create"|"map"|"skip",
       xero_account_code?, xero_account_name?, xero_account_id?}
    """
    from .xero_client import require_xero_manager
    require_xero_manager()
    import json

    if isinstance(resolutions, str):
        resolutions = json.loads(resolutions)

    resolutions = [
        r for r in resolutions
        if r.get("erpnext_account") and r.get("action") in ("create", "map")
    ]
    if not resolutions:
        return {"queued": False, "created": [], "mapped": [], "errors": [], "total_mapped": None}

    has_create = any(r["action"] == "create" for r in resolutions)

    # Creating accounts writes to Xero, so it must respect the outbound master
    # gate. Mapping/skip are local-only and always allowed.
    if has_create and not get_xero_settings().enable_sync_to_xero:
        frappe.throw(
            "Outbound sync to Xero is disabled (Xero Settings → Enable Sync TO Xero). "
            "Enable it before creating accounts in Xero, or choose Map/Skip instead."
        )

    if not has_create:
        # Pure remap — no external calls, return the result immediately.
        return _process_resolutions(resolutions)

    frappe.enqueue(
        "xero.utils.account_mapper._process_resolutions",
        queue="long",
        timeout=2400,
        job_name="xero_resolve_unmapped_accounts",
        resolutions=resolutions,
        user=frappe.session.user,
    )
    return {"queued": True, "count": len(resolutions)}


def _process_resolutions(resolutions, user=None):
    """Worker: create-or-link / map each resolution, write mapping rows, report a summary."""
    settings = get_xero_settings()
    existing_erpnext = {r.erpnext_account for r in settings.account_mapping if r.erpnext_account}

    created, mapped, errors = [], [], []

    # Build the full Xero account index ONCE (active + archived + system) so we can
    # link onto existing accounts and guarantee unique codes for genuine creates.
    has_create = any(r.get("action") == "create" for r in resolutions)
    xindex, used_codes = None, None
    if has_create:
        xindex = _build_xero_index(_fetch_xero_accounts_raw(include_system=True))
        used_codes = set(xindex["by_code"].keys())

    for r in resolutions:
        ea     = r.get("erpnext_account")
        action = r.get("action")
        if not ea or action not in ("create", "map"):
            continue
        if ea in existing_erpnext:
            errors.append(f"{ea}: already mapped — skipped")
            continue
        try:
            if action == "create":
                if not settings.enable_sync_to_xero:
                    errors.append(f"{ea}: skipped — outbound sync to Xero is disabled")
                    continue
                outcome = _create_or_link_to_xero(
                    ea, settings, xindex, used_codes, existing_erpnext)
                if outcome["status"] == "created":
                    created.append(outcome["row"])
                elif outcome["status"] == "linked":
                    mapped.append(outcome["row"])
                else:
                    errors.append(outcome["error"])
            else:  # map
                code = r.get("xero_account_code")
                name = r.get("xero_account_name") or ""
                xid  = r.get("xero_account_id") or None
                if not code:
                    errors.append(f"{ea}: no Xero account selected to map to")
                    continue
                _append_mapping_row(settings, ea, code, name, existing_erpnext)
                if xid:
                    frappe.db.set_value("Account", ea, "xero_account_id", xid, update_modified=False)
                mapped.append({"erpnext_account": ea, "xero_code": code, "xero_name": name})
        except Exception as e:
            errors.append(f"{ea}: {e}")

    settings.flags.ignore_version = True
    settings.save(ignore_permissions=True)
    # The loop above created/linked accounts in Xero; persist that linkage
    # before any later step in this request can fail and roll it back.
    commit_external_outcome()
    _refresh_mapping_status(settings)
    # Bust the cached single so any read later (e.g. a manual sync triggered
    # right after) sees the new mapping rows immediately.
    frappe.clear_document_cache("Xero Settings", "Xero Settings")

    result = {
        "created":      created,
        "mapped":       mapped,
        "errors":       errors,
        "total_mapped": len(settings.account_mapping),
    }
    if user:
        frappe.publish_realtime("xero_resolve_done", result, user=user)
    return result


# ---------------------------------------------------------------------------
# Reconciliation engine — create-or-link, idempotent, collision-free
# ---------------------------------------------------------------------------

def _normalize_name(s):
    import re as _re
    return _re.sub(r"\s+", " ", (s or "").strip()).lower()


def _fetch_xero_accounts_raw(include_system=True):
    """
    Fetch the FULL Xero chart for indexing — active + archived + (optionally)
    system accounts. Unlike _fetch_xero_accounts this does NOT filter system
    accounts or non-mappable types, so we can both link onto and avoid colliding
    with accounts like the built-in VAT.
    """
    response = xero_request("GET", "Accounts")
    if not response or not response.get("Accounts"):
        return []
    out = []
    for acc in response["Accounts"]:
        if not include_system and acc.get("SystemAccount") in XERO_SYSTEM_ACCOUNTS:
            continue
        out.append(acc)
    return out


def _build_xero_index(raw_accounts):
    """Index raw Xero accounts by Code and by normalized Name (first wins)."""
    by_code, by_name = {}, {}
    for a in raw_accounts:
        code = (a.get("Code") or "").strip()
        if code:
            by_code.setdefault(code, a)
        name = _normalize_name(a.get("Name"))
        if name:
            by_name.setdefault(name, a)
    return {"by_code": by_code, "by_name": by_name}


def _existing_xero_match(doc, xindex):
    """Return the existing Xero account dict to link onto, or None.
    Matches by account_number == Code, then by exact normalized Name."""
    num = str(doc.get("account_number") or "").strip()
    if num and num in xindex["by_code"]:
        return xindex["by_code"][num]
    nm = _normalize_name(doc.get("account_name"))
    if nm and nm in xindex["by_name"]:
        return xindex["by_name"][nm]
    return None


def _xero_code_for(doc, used_codes):
    """
    A unique Xero account code (<=10 alphanumerics). Prefers the ERPNext
    account_number; otherwise derives from the name. Appends a numeric suffix on
    collision with codes already in Xero or reserved earlier in this batch.
    """
    from ..api.xero_accounts import validate_account_code
    base = doc.get("account_number") or doc.get("account_name") or doc.name
    try:
        code = validate_account_code(base)
    except ValueError:
        code = validate_account_code(doc.name)
    if code not in used_codes:
        return code
    for i in range(2, 1000):
        suffix = str(i)
        cand = code[:10 - len(suffix)] + suffix
        if cand not in used_codes:
            return cand
    return code  # extremely unlikely


def _create_or_link_to_xero(ea, settings, xindex, used_codes, existing_erpnext):
    """
    Reconcile one ERPNext account to Xero (never blind-create):
      1. exact Code/Name already in Xero  → LINK onto it
      2. account_type == "Tax"            → refuse (belongs in Tax mapping)
      3. otherwise                        → CREATE with a unique code
      4. if the create still hits a uniqueness error → self-heal by linking
    Returns {"status": "created"|"linked"|"error", "row"/"error": ...}.
    """
    from ..api.xero_accounts import build_xero_account_payload

    doc = frappe.get_doc("Account", ea)

    # 1. Link onto an existing Xero account (e.g. VAT → Xero's built-in VAT).
    #    This is what protects VAT-style accounts from duplicate-name errors. We
    #    deliberately do NOT hard-refuse account_type == "Tax" here: ZA statutory
    #    liabilities (UIF/SDL/PAYE) are often typed "Tax" yet are real GL accounts
    #    that must exist in Xero. The UI steers genuine VAT control accounts to
    #    Skip (defaulted) so nothing tax-like is created blindly.
    existing = _existing_xero_match(doc, xindex)
    if existing:
        return _link(ea, existing, settings, existing_erpnext)

    # 2. Create with a guaranteed-unique code
    payload = build_xero_account_payload(doc, settings)
    payload.pop("AccountID", None)
    code = _xero_code_for(doc, used_codes)
    payload["Code"] = code
    used_codes.add(code)
    try:
        response = xero_request(
            "PUT", "Accounts",
            data={"Accounts": [payload]},
            idempotency_key=f"Account:{ea}:create",
        )
    except Exception as put_err:
        # 4. Self-heal: a uniqueness clash means it already exists → link to it
        match = _existing_xero_match(doc, _build_xero_index(_fetch_xero_accounts_raw(include_system=True)))
        if match:
            return _link(ea, match, settings, existing_erpnext)
        return {"status": "error", "error": f"{ea}: {put_err}"}

    if not (response and response.get("Accounts")):
        return {"status": "error", "error": f"{ea}: no valid response from Xero"}
    xa = response["Accounts"][0]
    if xa.get("AccountID"):
        frappe.db.set_value("Account", ea, "xero_account_id", xa["AccountID"], update_modified=False)
        xindex["by_code"][xa.get("Code", "")] = xa
        xindex["by_name"][_normalize_name(xa.get("Name"))] = xa
    _append_mapping_row(settings, ea, xa.get("Code"), xa.get("Name"), existing_erpnext)
    return {"status": "created",
            "row": {"erpnext_account": ea, "xero_code": xa.get("Code"), "xero_name": xa.get("Name")}}


def _link(ea, xero_acc, settings, existing_erpnext):
    """Link an ERPNext account onto an existing Xero account (no create)."""
    if xero_acc.get("AccountID"):
        frappe.db.set_value("Account", ea, "xero_account_id", xero_acc["AccountID"], update_modified=False)
    _append_mapping_row(settings, ea, xero_acc.get("Code"), xero_acc.get("Name"), existing_erpnext)
    return {"status": "linked",
            "row": {"erpnext_account": ea, "xero_code": xero_acc.get("Code"),
                    "xero_name": xero_acc.get("Name"), "linked": True}}


# ===========================================================================
# Unified mapping workspace — one wizard over both directions + tax
# ===========================================================================

@frappe.whitelist()
def get_mapping_workspace():
    """
    One payload powering the unified "Account & Tax Mapping" wizard.

    Includes only the sections whose sync direction is enabled:
      • accounts_from_xero  (Xero → ERPNext)  when enable_sync_from_xero
      • accounts_to_xero    (ERPNext → Xero)  when enable_sync_to_xero
      • tax                 (always)          unmapped ERPNext Item Tax Templates
    plus the dropdown lists (xero_accounts, erpnext_accounts, xero_tax_rates)
    and a summary. Reuses the existing inbound/outbound matchers.
    """
    from .xero_client import require_xero_manager
    require_xero_manager()

    settings = get_xero_settings()
    if not settings.access_token or not settings.tenant_id:
        frappe.throw("Xero connection not configured. Connect to Xero first.")

    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1, pluck="name")[0]
    to_xero   = bool(settings.enable_sync_to_xero)
    from_xero = bool(settings.enable_sync_from_xero)

    xero_accounts    = _fetch_xero_accounts(include_archived=False)
    erpnext_accounts = _fetch_erpnext_accounts(company)
    mapped_codes, mapped_erpnext, _rows = _load_existing_mappings(settings)

    # Full Xero index (incl. system/archived) for exact-match / link detection.
    xindex = _build_xero_index(_fetch_xero_accounts_raw(include_system=True))

    # ---- Section B: ERPNext → Xero (reconciled) ----
    accounts_to_xero = []
    if to_xero:
        error_accounts = _recent_mapping_error_accounts()
        for acc in erpnext_accounts:
            if acc["name"] in mapped_erpnext:
                continue
            doc_like = {
                "account_number": acc.get("account_number"),
                "account_name":   acc.get("account_name") or acc["name"],
            }
            is_tax = acc.get("account_type") == "Tax"
            exact  = _existing_xero_match(doc_like, xindex)
            # Status drives the page's default action:
            #   exact → link (auto)  | tax → skip (opt-in)  | fuzzy → review  | else → create
            # Tax takes precedence over a fuzzy match so a VAT/tax account is never
            # suggested onto an unrelated GL account (e.g. a bank).
            if exact:
                status, fuzzy = "exact", None
            elif is_tax:
                status, fuzzy = "tax", None
            else:
                fuzzy = _find_best_xero_match(acc, xero_accounts)
                status = "fuzzy" if fuzzy else "create"
            accounts_to_xero.append({
                "erpnext_account":  acc["name"],
                "account_name":     acc.get("account_name") or acc["name"],
                "root_type":        acc.get("root_type", ""),
                "account_type":     acc.get("account_type", ""),
                "is_tax":           1 if is_tax else 0,
                "has_recent_error": 1 if acc["name"] in error_accounts else 0,
                "status":           status,
                "exact":            ({"code": exact.get("Code"), "name": exact.get("Name"),
                                      "account_id": exact.get("AccountID")} if exact else None),
                "suggested":        fuzzy,
            })
        # exact matches first (easy wins), then failing, then by type/name
        _order = {"exact": 0, "fuzzy": 1, "create": 2, "tax": 3}
        accounts_to_xero.sort(key=lambda x: (_order.get(x["status"], 9), -x["has_recent_error"],
                                             x["root_type"], x["account_name"]))

    # ---- Section A: Xero → ERPNext (unmapped Xero accounts) ----
    accounts_from_xero = []
    if from_xero:
        claimed = set(mapped_erpnext)
        for x in xero_accounts:
            code = x.get("Code", "")
            if code and code in mapped_codes:
                continue
            ename, conf = _find_best_erpnext_match(
                x.get("AccountID", ""), code, x.get("Name", ""), x.get("Type", ""),
                erpnext_accounts, claimed, company,
            )
            if ename:
                claimed.add(ename)
            accounts_from_xero.append({
                "xero_account_id":   x.get("AccountID", ""),
                "xero_code":         code,
                "xero_name":         x.get("Name", ""),
                "xero_type":         x.get("Type", ""),
                "suggested_erpnext": ename,
                "confidence":        conf,
            })
        accounts_from_xero.sort(key=lambda r: (r["xero_code"] or ""))

    # ---- Section C: tax (unmapped ERPNext Item Tax Templates) ----
    xero_tax_rates = _fetch_xero_tax_rates()
    mapped_tax = {r.erpnext_tax_template for r in settings.tax_mapping if r.erpnext_tax_template}
    tax = []
    for tmpl in frappe.get_all("Item Tax Template", pluck="name"):
        if tmpl in mapped_tax:
            continue
        tax.append({
            "erpnext_tax_template": tmpl,
            "erpnext_rate":         _erpnext_tax_template_rate(tmpl),
            "suggested":            _find_best_xero_tax_match(tmpl, xero_tax_rates),
        })

    # Already-configured mappings (for the collapsible "Mapped" section in the UI)
    mapped_accounts = [
        {
            "erpnext_account":   r.erpnext_account,
            "xero_account_code": r.xero_account_code,
            "xero_account_name": r.xero_account_name,
        }
        for r in settings.account_mapping
        if r.erpnext_account and r.xero_account_code
    ]
    mapped_tax_rows = [
        {
            "erpnext_tax_template": r.erpnext_tax_template,
            "xero_tax_type_code":   r.xero_tax_type_code,
            "xero_tax_type_name":   r.xero_tax_type_name,
            "xero_tax_rate":        r.xero_tax_rate,
        }
        for r in settings.tax_mapping
        if r.erpnext_tax_template
    ]

    return {
        "directions":         {"to_xero": to_xero, "from_xero": from_xero},
        "accounts_to_xero":   accounts_to_xero,
        "accounts_from_xero": accounts_from_xero,
        "tax":                tax,
        "mapped_accounts":    mapped_accounts,
        "mapped_tax_rows":    mapped_tax_rows,
        "xero_accounts":      sorted(
            [{"code": a.get("Code", ""), "name": a.get("Name", ""),
              "type": a.get("Type", ""), "account_id": a.get("AccountID", "")}
             for a in xero_accounts if a.get("Code")],
            key=lambda x: (x["code"] or "")),
        "erpnext_accounts":   [{"name": a["name"], "label": a.get("account_name") or a["name"]}
                               for a in erpnext_accounts],
        "xero_tax_rates":     xero_tax_rates,
        "summary": {
            "mapped_accounts":  len([r for r in settings.account_mapping
                                     if r.erpnext_account and r.xero_account_code]),
            "mapped_tax":       len(mapped_tax),
            "need_to_xero":     len(accounts_to_xero),
            "need_from_xero":   len(accounts_from_xero),
            "need_tax":         len(tax),
        },
    }


@frappe.whitelist()
def apply_mapping_workspace(decisions):
    """
    Apply all wizard decisions in one pass.

    decisions: JSON {
      "to_xero":   [ {erpnext_account, action: create|map|skip, xero_account_code?, ...} ],
      "from_xero": [ {xero_account_id, xero_code, xero_name, xero_type,
                      action: create|map|skip, erpnext_account?} ],
      "tax":       [ {erpnext_tax_template, action: map|skip,
                      xero_tax_type_code?, xero_tax_type_name?, xero_tax_rate?} ]
    }

    - ERPNext→Xero creates reuse _process_resolutions (background enqueue, gate,
      PUT-create). Everything else (maps, ERPNext-side creates, tax) is local and
      applied inline. Returns a unified summary; if any outbound create was
      queued, its result arrives later via the `xero_resolve_done` realtime event.
    """
    from .xero_client import require_xero_manager
    require_xero_manager()
    import json

    if isinstance(decisions, str):
        decisions = json.loads(decisions)

    to_xero_d   = decisions.get("to_xero", []) or []
    from_xero_d = decisions.get("from_xero", []) or []
    tax_d       = decisions.get("tax", []) or []

    settings = get_xero_settings()
    company = frappe.db.get_default("company") or frappe.get_all("Company", limit=1, pluck="name")[0]
    existing_erpnext = {r.erpnext_account for r in settings.account_mapping if r.erpnext_account}
    existing_tax     = {r.erpnext_tax_template for r in settings.tax_mapping if r.erpnext_tax_template}

    created_erpnext, mapped, tax_mapped, errors = [], [], [], []

    # ---- Inbound (Xero → ERPNext): create-in-ERPNext or map ----
    for d in from_xero_d:
        action = d.get("action")
        if action not in ("create", "map"):
            continue
        try:
            if action == "create":
                ename = _create_erpnext_account_from_xero(d, company)
                if not ename:
                    errors.append(f"{d.get('xero_name')}: could not create ERPNext account")
                    continue
                if _append_mapping_row(settings, ename, d.get("xero_code"), d.get("xero_name"), existing_erpnext):
                    created_erpnext.append({"erpnext_account": ename, "xero_code": d.get("xero_code")})
            else:  # map to an existing ERPNext account the user picked
                ename = d.get("erpnext_account")
                if not ename:
                    errors.append(f"{d.get('xero_name')}: no ERPNext account selected")
                    continue
                if _append_mapping_row(settings, ename, d.get("xero_code"), d.get("xero_name"), existing_erpnext):
                    mapped.append({"erpnext_account": ename, "xero_code": d.get("xero_code")})
        except Exception as e:
            errors.append(f"{d.get('xero_name')}: {e}")

    # ---- Tax: map ERPNext Item Tax Template → Xero tax type ----
    for d in tax_d:
        if d.get("action") != "map":
            continue
        tmpl = d.get("erpnext_tax_template")
        code = d.get("xero_tax_type_code")
        if not tmpl or not code or tmpl in existing_tax:
            continue
        settings.append("tax_mapping", {
            "erpnext_tax_template": tmpl,
            "xero_tax_type_code":   code,
            "xero_tax_type_name":   d.get("xero_tax_type_name") or "",
            "xero_tax_rate":        d.get("xero_tax_rate") or 0,
        })
        existing_tax.add(tmpl)
        tax_mapped.append({"erpnext_tax_template": tmpl, "xero_tax_type_code": code})

    settings.flags.ignore_version = True
    settings.save(ignore_permissions=True)
    # Persist the applied inbound decisions before the outbound phase below
    # makes external Xero calls that can fail mid-way.
    commit_checkpoint()
    _refresh_mapping_status(settings)
    frappe.clear_document_cache("Xero Settings", "Xero Settings")

    # ---- Outbound (ERPNext → Xero): hand to the existing resolver ----
    outbound = [d for d in to_xero_d if d.get("action") in ("create", "map")]
    outbound_result = None
    if outbound:
        outbound_result = resolve_unmapped_accounts(json.dumps(outbound))

    return {
        "created_erpnext": created_erpnext,
        "mapped":          mapped,
        "tax_mapped":      tax_mapped,
        "errors":          errors,
        "outbound":        outbound_result,
    }


def _fetch_xero_tax_rates():
    """Active Xero tax rates → [{tax_type, name, rate}], rate = summed components."""
    response = xero_request("GET", "TaxRates")
    if not response or not response.get("TaxRates"):
        return []
    rates = []
    for tr in response["TaxRates"]:
        if tr.get("Status") != "ACTIVE":
            continue
        total = sum(float(c.get("Rate", 0)) for c in tr.get("TaxComponents", []))
        rates.append({
            "tax_type": tr.get("TaxType", ""),
            "name":     tr.get("Name", ""),
            "rate":     total,
        })
    return rates


def _erpnext_tax_template_rate(template_name):
    """Representative rate for an ERPNext Item Tax Template (max child rate)."""
    try:
        rows = frappe.get_all(
            "Item Tax Template Detail",
            filters={"parent": template_name}, fields=["tax_rate"])
        return max([float(r.tax_rate) for r in rows], default=0.0)
    except Exception:
        return 0.0


def _find_best_xero_tax_match(template_name, xero_tax_rates):
    """Best Xero tax rate for an ERPNext Item Tax Template. {tax_type,name,rate,confidence} or None."""
    name = (template_name or "").lower()
    erate = _erpnext_tax_template_rate(template_name)
    best, best_sim = None, 0.0
    for tr in xero_tax_rates:
        # Exact rate match is a strong signal
        if erate and abs(float(tr["rate"]) - erate) < 0.01:
            return {**tr, "confidence": CONFIDENCE_HIGH}
        sim = SequenceMatcher(None, name, (tr["name"] or "").lower()).ratio()
        if sim >= SIMILARITY_THRESHOLD and sim > best_sim:
            best_sim = sim
            best = {**tr, "confidence": CONFIDENCE_MEDIUM}
    return best


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


def _find_best_xero_match(erpnext_acc, xero_accounts):
    """
    Reverse of _find_best_erpnext_match: given an ERPNext account, find the best
    *existing* Xero account to map it to. Returns {code, name, confidence} or None.
    Only High/Medium suggestions are returned — a Low (type-only) guess would be
    misleading in a picker, so we leave those for the user to choose.
    """
    ea_number = str(erpnext_acc.get("account_number") or "").strip()
    ea_name   = (erpnext_acc.get("account_name") or "").lower().strip()
    ea_root   = erpnext_acc.get("root_type", "")
    ea_xid    = erpnext_acc.get("xero_account_id")

    best     = None
    best_sim = 0.0

    for x in xero_accounts:
        x_code = x.get("Code", "")
        x_name = x.get("Name", "") or ""
        x_type = x.get("Type", "")
        x_id   = x.get("AccountID", "")
        x_root = XERO_ACCOUNT_TYPE_MAP.get(x_type, {}).get("root_type", "")
        x_name_l = x_name.lower().strip()
        x_leaf   = x_name.split(":")[-1].strip().lower()

        # 1. xero_account_id already stored on the ERPNext account
        if ea_xid and x_id == ea_xid:
            return {"code": x_code, "name": x_name, "confidence": CONFIDENCE_HIGH}
        # 2. account_number == Xero code
        if ea_number and x_code and ea_number == str(x_code).strip():
            return {"code": x_code, "name": x_name, "confidence": CONFIDENCE_HIGH}
        # 3. Exact name match (full or leaf segment)
        if ea_name and (ea_name == x_name_l or ea_name == x_leaf):
            return {"code": x_code, "name": x_name, "confidence": CONFIDENCE_HIGH}
        # 4. Same root_type + fuzzy name
        if ea_root and x_root == ea_root and ea_name:
            sim = max(
                SequenceMatcher(None, ea_name, x_name_l).ratio(),
                SequenceMatcher(None, ea_name, x_leaf).ratio(),
            )
            if sim >= SIMILARITY_THRESHOLD and sim > best_sim:
                best_sim = sim
                best = {"code": x_code, "name": x_name, "confidence": CONFIDENCE_MEDIUM}

    return best


def _append_mapping_row(settings, ea, code, name, existing_erpnext):
    """
    Append an account_mapping row. Idempotent on erpnext_account ONLY — several
    ERPNext accounts may legitimately map to the same Xero code (e.g. all payroll
    expense accounts → one Xero "Wages" account), so we do not dedupe on code.
    Returns True if a row was appended, False if it already existed.
    """
    if ea in existing_erpnext:
        return False
    xero_account_doc = frappe.db.get_value("Xero Account", {"account_code": code}, "name")
    settings.append("account_mapping", {
        "erpnext_account":   ea,
        "xero_account":      xero_account_doc or None,
        "xero_account_code": code,
        "xero_account_name": name or "",
    })
    existing_erpnext.add(ea)
    return True


def _recent_mapping_error_accounts(days=30):
    """
    Return a set of ERPNext account names referenced by recent mapping-error logs,
    parsed from the log message text ("... for ERPNext Account: X" /
    "... for Tax/Charge Account: X"). Best-effort — used only to flag/sort.
    """
    import re
    accounts = set()
    try:
        rows = frappe.get_all(
            "Xero Log",
            filters={
                "status": "Error",
                "category": "Mapping Errors",
                "timestamp": [">=", frappe.utils.add_days(frappe.utils.nowdate(), -days)],
            },
            fields=["message"],
            limit=2000,
        )
    except Exception:
        return accounts

    pattern = re.compile(r"(?:ERPNext Account|Tax/Charge Account):\s*([^(]+?)(?:\s*\(|\.\s*Add it|$)")
    for row in rows:
        m = pattern.search(row.get("message") or "")
        if m:
            accounts.add(m.group(1).strip())
    return accounts


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
            # Checkpoint each created group so a failure deeper in the tree
            # keeps the levels already built (recreation is duplicate-guarded).
            commit_checkpoint()
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
    # Checkpoint per imported account so one bad account later in the batch
    # does not roll back the mirrors already created for real Xero accounts.
    commit_checkpoint()

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

    return added


def _update_mapping_status(unmatched_xero, unmatched_erpnext, matched):
    """Set mapping_status on Xero Settings based on what's still unresolved."""
    if unmatched_xero or unmatched_erpnext:
        new_status = "Review Required"
    elif matched:
        new_status = "In Progress"
    else:
        new_status = "Not Started"

    frappe.db.set_single_value("Xero Settings", "mapping_status", new_status)


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

        frappe.db.set_single_value("Xero Settings", "mapping_status", new_status)
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
