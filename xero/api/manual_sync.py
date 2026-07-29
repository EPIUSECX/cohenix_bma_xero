# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Single entry point for the desk "Sync to Xero" form buttons.

The buttons used to call the doc_event handlers directly. Those handlers take
(doc, method) — a real Document plus the hook name — which a browser cannot
supply, so every button failed: passing a name string raised TypeError and
passing the serialised form doc raised AttributeError ('dict' has no attribute
'name'). Resolving the document server-side and handing the handler the real
object fixes that, and means a manual sync goes through exactly the same
settings toggles, echo-loop guards and double-trigger guards as an automatic
one rather than a parallel code path that can drift.

Bank Transaction is deliberately absent: outbound sync for it is disabled by
design (see the note in xero_bank_transactions.py) because the Payment Entry
and Journal Entry it reconciles against already move the Xero bank balance.
"""

import frappe
from frappe import _

from ..utils.xero_client import get_xero_settings, require_xero_manager

# DocType -> the doc_event handler that already owns the enable/guard logic.
# Sales and Purchase Invoice route through the _or_return wrapper so a return
# (is_return=1) is sent to Xero as a credit note rather than an invoice.
SYNC_HANDLERS = {
    "Sales Invoice": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
    "Purchase Invoice": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
    "Journal Entry": "xero.api.xero_journals.enqueue_sync_journal",
    "Payment Entry": "xero.api.xero_payments.enqueue_sync_payment",
    "Quotation": "xero.api.xero_quotes.enqueue_sync_quotation",
    "Item": "xero.api.xero_items.enqueue_sync_item",
}


@frappe.whitelist()
def sync_document_to_xero(doctype, docname):
    """Queue an outbound sync for one document, as if its submit hook had fired."""
    require_xero_manager()

    # Frappe deserialises request args, so a "string" parameter can arrive as a
    # dict or list. That matters here: frappe.get_doc(doctype, {"docstatus": 1})
    # treats the dict as FILTERS and loads whichever document matches, while
    # has_permission() only resolves str/int into a document — so the doc that
    # was permission-checked would not be the doc that got synced. Reject
    # anything that is not a plain string before either call.
    if not isinstance(doctype, str) or not isinstance(docname, str):
        frappe.throw(_("Invalid document reference."), frappe.PermissionError)

    handler_path = SYNC_HANDLERS.get(doctype)
    if not handler_path:
        frappe.throw(_("{0} cannot be synced to Xero.").format(_(doctype)))

    frappe.has_permission(doctype, "write", docname, throw=True)

    if not get_xero_settings().enable_xero_sync:
        frappe.throw(_("Xero sync is disabled. Enable it in Xero Settings first."))

    doc = frappe.get_doc(doctype, docname)
    frappe.get_attr(handler_path)(doc, "manual_sync")

    # Don't claim the job was queued: the handlers drop the request without
    # raising (and, for Journal Entry and Quotation, without logging) when the
    # entity's own toggle is off, so point at the setting as well as the log.
    return _(
        "Sync to Xero requested for {0}. If nothing appears in the Xero Log,"
        " check that this entity's sync toggle is enabled in Xero Settings."
    ).format(docname)
