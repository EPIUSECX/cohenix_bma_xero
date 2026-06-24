# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class XeroSettings(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING, List

    if TYPE_CHECKING:
        from frappe.types import DF
        from .xero_account_mapping import XeroAccountMapping
        from .xero_tax_mapping import XeroTaxMapping

        access_token: DF.Password | None
        account_mapping: DF.Table[XeroAccountMapping]
        mapping_status: DF.Literal["Not Started", "In Progress", "Review Required", "Complete"] | None
        setup_mode: DF.Literal["Manual", "Xero as Source", "ERPNext as Source"] | None
        api_timeout: DF.Int
        auto_submit_inbound: DF.Check
        enable_incremental_sync: DF.Check
        sync_watermarks: DF.LongText | None
        backoff_base: DF.Int  # alias kept for compatibility
        client_id: DF.Data | None
        client_secret: DF.Password | None
        connection_status: DF.Data | None
        create_payment_entry_on_sync: DF.Check
        default_bank_account: DF.Link | None
        enable_auto_sync: DF.Check
        enable_rate_limit_tracking: DF.Check
        enable_sync_from_xero: DF.Check
        enable_sync_to_xero: DF.Check
        enable_webhooks: DF.Check
        enable_xero_sync: DF.Check
        last_sync_time: DF.Datetime | None
        last_token_refresh: DF.Datetime | None
        log_retention_days: DF.Int
        max_retry_attempts: DF.Int
        rate_limit_backoff_base: DF.Int
        rate_limit_max_delay: DF.Int
        redirect_url: DF.Data | None
        refresh_token: DF.Password | None
        sync_bank_transactions: DF.Check
        sync_bills_from_xero: DF.Check
        sync_bills_to_xero: DF.Check
        sync_chart_of_accounts: DF.Check
        sync_contacts: DF.Check
        sync_contacts_from_xero: DF.Check
        sync_contacts_to_xero: DF.Check
        sync_credit_notes: DF.Check
        sync_credit_notes_from_xero: DF.Check
        sync_credit_notes_to_xero: DF.Check
        sync_financial_reports: DF.Check
        sync_frequency: DF.Literal["Hourly", "Daily", "Weekly"] | None
        sync_invoices: DF.Check
        sync_invoices_from_xero: DF.Check
        sync_invoices_to_xero: DF.Check
        sync_items: DF.Check
        sync_items_from_xero: DF.Check
        sync_items_to_xero: DF.Check
        sync_journal_entries: DF.Check
        sync_payments: DF.Check
        sync_payments_from_xero: DF.Check
        sync_payments_standalone: DF.Check
        sync_payments_to_xero: DF.Check
        sync_purchase_orders: DF.Check
        sync_quotes: DF.Check
        tax_mapping: DF.Table[XeroTaxMapping]
        tenant_id: DF.Data | None
        tenant_name: DF.Data | None
        token_expiry: DF.Datetime | None
        webhook_secret: DF.Password | None
    # end: auto-generated types

    def validate(self):
        """
        Cascade validation for sync toggles:
        1. Derive legacy entity-existence flags from per-entity directional toggles
           (backward compat with modules that check e.g. settings.sync_invoices)
        2. Clear sub-toggles when their parent direction switch is disabled
        3. Clear everything when the master switch is disabled

        No entities are forcibly disabled — all toggles are respected as set.
        Operators control exactly what syncs via the settings UI.
        """
        # --- Derive aggregate entity flags from directional sub-toggles ---
        # These maintain backward compatibility with sync modules that check
        # the old-style single flag (e.g. settings.sync_invoices).
        self.sync_contacts = (
            1 if (self.sync_contacts_to_xero or self.sync_contacts_from_xero) else 0
        )
        self.sync_invoices = (
            1
            if (
                self.sync_invoices_to_xero
                or self.sync_invoices_from_xero
                or self.get("sync_bills_to_xero")
                or self.get("sync_bills_from_xero")
            )
            else 0
        )
        self.sync_credit_notes = (
            1
            if (self.sync_credit_notes_to_xero or self.sync_credit_notes_from_xero)
            else 0
        )
        self.sync_payments = (
            1 if (self.sync_payments_to_xero or self.sync_payments_from_xero) else 0
        )
        self.sync_items = (
            1
            if (self.get("sync_items_to_xero") or self.get("sync_items_from_xero"))
            else 0
        )

        # --- Cascade: clear outbound sub-toggles if outbound master is OFF ---
        if not self.enable_sync_to_xero:
            self.sync_contacts_to_xero = 0
            self.sync_items_to_xero = 0
            self.sync_invoices_to_xero = 0
            self.sync_bills_to_xero = 0
            self.sync_credit_notes_to_xero = 0
            self.sync_payments_to_xero = 0
            # Extended entities (outbound only)
            self.sync_journal_entries = 0
            self.sync_bank_transactions = 0
            self.sync_purchase_orders = 0
            self.sync_quotes = 0

        # --- Cascade: clear inbound sub-toggles if inbound master is OFF ---
        if not self.enable_sync_from_xero:
            self.sync_contacts_from_xero = 0
            self.sync_items_from_xero = 0
            self.sync_invoices_from_xero = 0
            self.sync_bills_from_xero = 0
            self.sync_credit_notes_from_xero = 0
            self.sync_payments_from_xero = 0
            # Extended entities (inbound only)
            self.sync_financial_reports = 0
            self.sync_chart_of_accounts = 0

        # --- Cascade: clear direction masters and auto-sync if global switch is OFF ---
        if not self.enable_xero_sync:
            self.enable_sync_to_xero = 0
            self.enable_sync_from_xero = 0
            self.enable_auto_sync = 0
            self.enable_webhooks = 0

    # Add custom methods if needed, e.g., to fetch mappings easily
    def get_account_map(self):
        """Returns a dictionary mapping ERPNext accounts to Xero codes."""
        mapping = {}
        for row in self.account_mapping:
            if row.erpnext_account and row.xero_account_code:
                mapping[row.erpnext_account] = row.xero_account_code
        return mapping

    def get_tax_map(self):
        """Returns a dictionary mapping ERPNext tax templates to Xero tax types."""
        mapping = {}
        for row in self.tax_mapping:
            if row.erpnext_tax_template and row.xero_tax_type_code:
                mapping[row.erpnext_tax_template] = row.xero_tax_type_code
        return mapping

    @frappe.whitelist()
    def check_xero_connection(self):
        """Attempts to connect to Xero API (e.g., fetch Organisation) to verify credentials and token."""
        if not self.enable_xero_sync or not self.access_token or not self.tenant_id:
            self.connection_status = "Disabled or Not Configured"
            self.save(ignore_permissions=True)
            return {"status": self.connection_status}

        from xero.utils.xero_client import xero_request  # Avoid circular import at top

        status = "Error"
        try:
            # Make a simple API call to check connectivity, e.g., get Organisation details
            response = xero_request("GET", "Organisation")
            if response and response.get("Organisations"):
                status = "Active"
            else:
                status = "Error (Invalid Response)"
        except Exception as e:
            status = f"Error ({e})"  # Include error message

        self.connection_status = status
        self.save(ignore_permissions=True)
        frappe.db.commit()
        return {"status": status}

    @frappe.whitelist()
    def disconnect_xero(self):
        """Clears Xero tokens and tenant ID."""
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        self.tenant_id = None
        self.connection_status = "Disconnected"
        self.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.msgprint("Disconnected from Xero. Tokens have been cleared.")

    @frappe.whitelist()
    def fetch_and_update_account_mapping(self):
        """Fetches accounts from Xero and ERPNext, populates mapping table."""
        if not self.enable_xero_sync or not self.tenant_id:
            frappe.throw("Xero sync must be enabled and connected.")

        doc = frappe.get_doc("Xero Settings", self.name)  # Explicitly reload

        from xero.api.xero_accounts import (
            sync_accounts_from_xero,
        )  # Fetch Xero accounts
        from xero.utils.xero_client import xero_request

        # 1. Fetch Xero Accounts (ensure they are created/updated in ERPNext first)
        try:
            xero_accounts_response = xero_request("GET", "Accounts")
            xero_accounts = (
                xero_accounts_response.get("Accounts", [])
                if xero_accounts_response
                else []
            )
        except Exception as e:
            frappe.throw(f"Failed to fetch accounts from Xero: {e}")

        # 2. Get relevant ERPNext Accounts (e.g., non-group accounts for the default company)
        erpnext_accounts = frappe.get_all(
            "Account", filters={"is_group": 0}, fields=["name", "account_number"]
        )

        # 3. Prepare Xero data lookup (by code and ID)
        xero_lookup_by_code = {
            acc.get("Code"): acc for acc in xero_accounts if acc.get("Code")
        }
        xero_lookup_by_id = {
            acc.get("AccountID"): acc for acc in xero_accounts if acc.get("AccountID")
        }

        # 4. Update mapping table
        account_mapping_table = doc.get("account_mapping") or []
        existing_erp_accounts_in_map = {
            row.erpnext_account for row in account_mapping_table
        }
        updated = 0
        added = 0

        for erp_acc in erpnext_accounts:
            erp_acc_name = erp_acc["name"]
            erp_acc_number = erp_acc["account_number"]
            xero_match = None

            # Try matching via ERPNext Account Number == Xero Code
            if erp_acc_number and erp_acc_number in xero_lookup_by_code:
                xero_match = xero_lookup_by_code[erp_acc_number]

            # Find existing row or create new one
            existing_row = next(
                (
                    row
                    for row in doc.account_mapping
                    if row.erpnext_account == erp_acc_name
                ),
                None,
            )

            if existing_row:
                # Update existing row if match found and code is missing/different
                if xero_match and existing_row.xero_account_code != xero_match.get(
                    "Code"
                ):
                    existing_row.xero_account_code = xero_match.get("Code")
                    existing_row.xero_account_id = xero_match.get("AccountID")
                    existing_row.xero_account_name = xero_match.get("Name")
                    updated += 1
            elif erp_acc_name not in existing_erp_accounts_in_map:
                # Add new row only if a match was found in Xero
                if xero_match:
                    doc.append(
                        "account_mapping",
                        {
                            "erpnext_account": erp_acc_name,
                            "xero_account_code": xero_match.get("Code"),
                            "xero_account_id": xero_match.get("AccountID"),
                            "xero_account_name": xero_match.get("Name"),
                        },
                    )
                    added += 1

        doc.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.msgprint(
            f"Account mapping updated: {added} added, {updated} updated. Please review and fill any missing Xero Account Codes manually."
        )

    @frappe.whitelist()
    def fetch_and_update_tax_mapping(self):
        """Fetches tax rates/types from Xero and populates mapping table."""
        if not self.enable_xero_sync or not self.tenant_id:
            frappe.throw("Xero sync must be enabled and connected.")

        doc = frappe.get_doc("Xero Settings", self.name)  # Explicitly reload

        from xero.api.xero_accounts import (
            get_xero_tax_rates,
        )  # Use the existing function

        # 1. Fetch Xero Tax Rates
        xero_tax_rates = get_xero_tax_rates()
        if not xero_tax_rates:
            frappe.msgprint("Could not fetch Tax Rates from Xero, or none exist.")
            return

        # 2. Get ERPNext Item Tax Templates
        erpnext_templates = frappe.get_all("Item Tax Template", fields=["name"])

        # 3. Update mapping table (simple add - requires manual code entry)
        tax_mapping_table = doc.get("tax_mapping") or []
        existing_erp_templates_in_map = {
            row.erpnext_tax_template for row in tax_mapping_table
        }
        added = 0

        if not doc.get("tax_mapping"):
            doc.set("tax_mapping", [])

        for template in erpnext_templates:
            if template.name not in existing_erp_templates_in_map:
                # Add template, user needs to fill in the Xero code
                doc.append(
                    "tax_mapping",
                    {
                        "erpnext_tax_template": template.name,
                        "xero_tax_type_code": None,  # User must fill this
                    },
                )
                added += 1

        doc.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.msgprint(
            f"Tax mapping updated: {added} ERPNext templates added. Please review and enter the corresponding Xero TaxType Codes."
        )

    @frappe.whitelist()
    def quick_map_accounts(self, mappings, auto_retry=False):
        """
        Quickly map multiple Xero accounts to ERPNext accounts.

        Args:
                mappings: JSON string or list of dicts with {xero_code, erpnext_account}
                auto_retry: Boolean to trigger retry of failed syncs after mapping

        Returns:
                Dict with success status, mappings added, and retry results
        """
        import json

        if isinstance(mappings, str):
            mappings = json.loads(mappings)

        if not isinstance(mappings, list):
            frappe.throw(
                "Mappings must be a list of {xero_code, erpnext_account} objects"
            )

        doc = frappe.get_doc("Xero Settings", self.name)
        mappings_added = 0
        mappings_updated = 0

        for mapping in mappings:
            xero_code = mapping.get("xero_code")
            erpnext_account = mapping.get("erpnext_account")

            if not xero_code or not erpnext_account:
                continue

            # Validate ERPNext account exists
            if not frappe.db.exists("Account", erpnext_account):
                frappe.throw(f"ERPNext Account '{erpnext_account}' does not exist")

            # Get Xero Account details
            xero_account = frappe.db.get_value(
                "Xero Account",
                {"account_code": xero_code},
                ["name", "account_id", "account_name"],
                as_dict=True,
            )

            if not xero_account:
                frappe.throw(
                    f"Xero Account with code '{xero_code}' not found. Please sync Xero Accounts first."
                )

            # Check if mapping already exists
            existing_row = next(
                (
                    row
                    for row in doc.account_mapping
                    if row.xero_account_code == xero_code
                ),
                None,
            )

            if existing_row:
                # Update existing mapping
                existing_row.erpnext_account = erpnext_account
                existing_row.xero_account = xero_account.name
                existing_row.xero_account_id = xero_account.account_id
                existing_row.xero_account_name = xero_account.account_name
                mappings_updated += 1
            else:
                # Add new mapping
                doc.append(
                    "account_mapping",
                    {
                        "erpnext_account": erpnext_account,
                        "xero_account": xero_account.name,
                        "xero_account_code": xero_code,
                        "xero_account_id": xero_account.account_id,
                        "xero_account_name": xero_account.account_name,
                    },
                )
                mappings_added += 1

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Clear cache to ensure new mappings are used immediately
        frappe.cache().delete_value("xero_account_map")

        result = {
            "success": True,
            "mappings_added": mappings_added,
            "mappings_updated": mappings_updated,
            "total_processed": mappings_added + mappings_updated,
        }

        # Optionally retry failed syncs
        if auto_retry:
            retry_results = self.retry_failed_syncs_with_account_errors()
            result["retry_results"] = retry_results

        return result

    # ------------------------------------------------------------------
    # Account Mapping Setup helpers (delegate to account_mapper module)
    # ------------------------------------------------------------------

    @frappe.whitelist()
    def run_account_auto_mapping(self, dry_run=1):
        """Run the auto-mapping engine. dry_run=1 analyses only; 0 also creates accounts (Xero-as-Source)."""
        from xero.utils.account_mapper import run_auto_mapping
        return run_auto_mapping(dry_run=frappe.utils.cint(dry_run))

    @frappe.whitelist()
    def confirm_account_mapping(self, suggestions):
        """Write a confirmed list of mapping suggestions to the account_mapping table."""
        from xero.utils.account_mapper import confirm_mapping
        return confirm_mapping(suggestions)

    @frappe.whitelist()
    def push_unmatched_to_xero(self, account_names):
        """Topology B: create listed ERPNext accounts in Xero."""
        from xero.utils.account_mapper import push_accounts_to_xero
        return push_accounts_to_xero(account_names)

    @frappe.whitelist()
    def run_full_account_auto_map(self):
        """One-shot: match all, create missing ERPNext accounts (with hierarchy), write mapping table."""
        from xero.utils.account_mapper import run_full_auto_map
        return run_full_auto_map()

    def retry_failed_syncs_with_account_errors(self):
        """
        Finds and retries syncs that failed due to account mapping errors.
        Returns count of retried syncs.
        """
        try:
            # Find recent failed syncs due to account mapping
            failed_syncs = frappe.db.sql(
                """
				SELECT DISTINCT
					erpnext_doc_type,
					erpnext_doc_name
				FROM `tabXero Log`
				WHERE status IN ('Error', 'Warning')
				AND (message LIKE '%%No account mapping%%'
					 OR message LIKE '%%Account Code mapping not found%%'
					 OR message LIKE '%%No valid line items%%')
				AND timestamp >= DATE_SUB(NOW(), INTERVAL 1 DAY)
				AND erpnext_doc_type IS NOT NULL
				AND erpnext_doc_name IS NOT NULL
				AND erpnext_doc_type != 'Unknown'
				AND erpnext_doc_name != 'Unknown'
				ORDER BY timestamp DESC
				LIMIT 50
			""",
                as_dict=True,
            )

            retry_count = 0
            for sync in failed_syncs:
                try:
                    # Check if document still exists
                    if not frappe.db.exists(
                        sync.erpnext_doc_type, sync.erpnext_doc_name
                    ):
                        continue

                    # Re-queue the sync
                    doc = frappe.get_doc(sync.erpnext_doc_type, sync.erpnext_doc_name)

                    # Determine which sync function to call
                    sync_function_map = {
                        "Sales Invoice": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
                        "Purchase Invoice": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
                        "Payment Entry": "xero.api.xero_payments.enqueue_sync_payment",
                        "Customer": "xero.api.xero_contacts.enqueue_sync_contact",
                        "Supplier": "xero.api.xero_contacts.enqueue_sync_contact",
                    }

                    function_path = sync_function_map.get(sync.erpnext_doc_type)
                    if function_path:
                        sync_function = frappe.get_attr(function_path)
                        sync_function(doc, "retry_after_mapping")
                        retry_count += 1

                except Exception as e:
                    frappe.log_error(
                        f"Failed to retry {sync.erpnext_doc_type} {sync.erpnext_doc_name}: {str(e)}"
                    )
                    continue

            return {
                "success": True,
                "retried_count": retry_count,
                "total_found": len(failed_syncs),
            }

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Retry Failed Syncs Error")
            return {"success": False, "error": str(e), "retried_count": 0}


# ---------------------------------------------------------------------------
# Module-level whitelisted wrappers
# ---------------------------------------------------------------------------
# The Account Mapping Setup buttons call these via `frm.call({ method: '...' })`
# with a bare method name, which Frappe resolves against this controller MODULE
# (xero.xero.doctype.xero_settings.xero_settings.<name>) — i.e. it expects a
# module-level function, not a Document class method. The class methods above
# are kept for direct/server use; these thin wrappers make the form buttons work.


@frappe.whitelist()
def run_account_auto_mapping(dry_run=1):
    """Run the auto-mapping engine. dry_run=1 analyses only; 0 also creates accounts (Xero-as-Source)."""
    from xero.utils.account_mapper import run_auto_mapping

    return run_auto_mapping(dry_run=frappe.utils.cint(dry_run))


@frappe.whitelist()
def confirm_account_mapping(suggestions):
    """Write a confirmed list of mapping suggestions to the account_mapping table."""
    from xero.utils.account_mapper import confirm_mapping

    return confirm_mapping(suggestions)


@frappe.whitelist()
def push_unmatched_to_xero(account_names):
    """Topology B: create the listed ERPNext accounts in Xero."""
    from xero.utils.account_mapper import push_accounts_to_xero

    return push_accounts_to_xero(account_names)


@frappe.whitelist()
def run_full_account_auto_map():
    """One-shot: match all, create missing ERPNext accounts (with hierarchy), write mapping table."""
    from xero.utils.account_mapper import run_full_auto_map

    return run_full_auto_map()


@frappe.whitelist()
def get_unmapped_accounts_for_resolution():
    """List ERPNext-only accounts (with suggested Xero matches) for the resolve picker."""
    from xero.utils.account_mapper import get_unmapped_accounts_for_resolution as _impl

    return _impl()


@frappe.whitelist()
def resolve_unmapped_accounts(resolutions):
    """Apply picker decisions: create-in-Xero or map-to-existing, then write mapping rows."""
    from xero.utils.account_mapper import resolve_unmapped_accounts as _impl

    return _impl(resolutions)
