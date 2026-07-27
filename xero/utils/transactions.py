"""Single choke point for mid-transaction commits.

Frappe commits automatically at the end of every successful request,
background job, and scheduled job, and rolls back on failure. Never call
frappe.db.commit() directly anywhere in this app — route through one of the
helpers below so every mid-transaction commit states why it is allowed to
exist. The marketplace semgrep audit (frappe-manual-commit) gates publishing
on this; the app's one suppressed commit lives at the bottom of this module.
"""

import frappe


def commit_external_outcome():
    """A write to Xero (or an OAuth token rotation) just succeeded. The stored
    id/status/token is the only thing preventing a retried job from repeating
    the external write, so it must survive any later rollback."""
    _commit()


def commit_checkpoint():
    """Per-document progress checkpoint in a bulk or inbound sync loop. A
    failure later in the loop must not undo documents already imported or
    watermarks already earned."""
    _commit()


def commit_error_state():
    """Terminal sync status or an Error/Warning Xero Log row written on a
    failure path. The surrounding transaction is about to roll back; the
    error trail must survive it."""
    _commit()


def _commit():
    # The one deliberate mid-transaction commit in the app; each public
    # helper above documents the only situations that may reach it.
    frappe.db.commit()  # nosemgrep
