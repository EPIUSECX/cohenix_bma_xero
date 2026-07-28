# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Shared sync-status transition for failed sync attempts.

Every sync worker's generic except-block funnels through mark_sync_failure so
the Failed/Error decision, the status write, and the Xero Log row stay
consistent across entities and directions.
"""

import frappe

from .logging import build_error_details, format_sync_error_message, log_xero_error
from .transactions import commit_error_state


def mark_sync_failure(
    doctype,
    name,
    exception,
    direction,
    source_type=None,
    source_id=None,
    source_display=None,
    xero_entity_id=None,
    xero_entity_type=None,
    traceback_text=None,
    extra_message="",
):
    """Record a failed sync attempt: status field + Xero Log row.

    Permanent Xero rejections (4xx validation — see XeroApiError.is_permanent)
    go terminal ("Failed") so the hourly retry sweep stops re-queuing a
    document that can never sync unchanged; the operator fixes the cause and
    retries explicitly. Everything else stays "Error" and is retried.

    doctype/name identify the ERPNext document (either may be None when the
    failure happened before a document existed — only the log row is written).
    source_type/source_id/source_display describe the failing entity for the
    operator-facing message; they default to the ERPNext document, and inbound
    callers pass the Xero entity instead.

    Returns the sync status written ("Failed" or "Error").
    """
    sync_status = "Failed" if getattr(exception, "is_permanent", False) else "Error"

    if doctype and name:
        frappe.db.set_value(
            doctype, name, {"xero_sync_status": sync_status}, update_modified=False
        )
        commit_error_state()

    message = format_sync_error_message(
        source_type or doctype,
        source_id or name,
        source_display or source_id or name,
        direction,
        exception,
    )
    if extra_message:
        message += " " + extra_message

    log_xero_error(
        message=message,
        erpnext_doc_type=doctype,
        erpnext_doc_name=name,
        xero_entity_id=xero_entity_id,
        xero_entity_type=xero_entity_type,
        direction=direction,
        error_details=build_error_details(
            exception, traceback_text or frappe.get_traceback()
        ),
    )
    return sync_status
