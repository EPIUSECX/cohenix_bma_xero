# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""CR-2: Move previously plaintext Xero OAuth tokens into Frappe's encrypted
password store.

`access_token` and `refresh_token` were stored as Small Text (plaintext in
`tabSingles`). Their fieldtype is now `Password`, so values must live encrypted
in the `__Auth` table and be read via `get_password()`. This patch runs once
after the model sync: it reads any plaintext value still sitting in the Singles
column, writes it to the encrypted store, and masks the Singles value.

Idempotent: a value already masked ("*****") or empty is skipped, so re-running
migrate is safe.
"""

import frappe
from frappe.utils.password import set_encrypted_password

DOCTYPE = "Xero Settings"
TOKEN_FIELDS = ("access_token", "refresh_token")
MASK = "*****"


def execute():
    for field in TOKEN_FIELDS:
        try:
            raw = frappe.db.get_single_value(DOCTYPE, field)
        except Exception:
            raw = None

        if not raw or raw == MASK:
            continue

        # Persist the plaintext value into the encrypted (__Auth) store...
        set_encrypted_password(DOCTYPE, DOCTYPE, raw, field)
        # ...and replace the plaintext in tabSingles with the masked placeholder.
        frappe.db.set_single_value(DOCTYPE, field, MASK)

    frappe.db.commit()
