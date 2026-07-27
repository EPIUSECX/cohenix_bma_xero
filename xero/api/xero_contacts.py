# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_fullname
import hashlib
import re
from ..utils.xero_client import xero_request, get_xero_settings, require_xero_manager
from ..utils.logging import log_xero_error, get_leaf_doctype_value
from ..utils.retry_handler import retry_with_exponential_backoff


# =============================================================================
# CONSTANTS
# =============================================================================

# Xero API limits
XERO_MAX_CONTACT_PERSONS = 5  # Xero allows max 5 ContactPersons per contact




# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def validate_and_sanitize_name(name, doc_type, doc_name):
    """Validate and sanitize contact name for Xero API.

    Xero requirements:
    - Max 255 characters
    - No angle brackets
    - No leading/trailing whitespace
    - No repeating spaces

    Returns: tuple (sanitized_name, error_message or None)
    """
    if not name or not str(name).strip():
        return None, f"Contact name is required for {doc_type} {doc_name}"

    name = str(name).strip()

    # Check for angle brackets and remove them
    if "<" in name or ">" in name:
        name = name.replace("<", "").replace(">", "").strip()
        if not name:
            return (
                None,
                f"Contact name for {doc_type} {doc_name} contains only invalid characters (< >)",
            )

    # Collapse multiple spaces into single space
    name = re.sub(r"\s+", " ", name)

    # Check length
    if len(name) > 255:
        return (
            None,
            f"Contact name for {doc_type} {doc_name} exceeds 255 characters (current: {len(name)})",
        )

    return name, None


def compute_data_hash(doc):
    """Compute hash of relevant fields to detect changes.

    This is used to prevent unnecessary re-syncs when data hasn't changed.

    HI-3: The hash MUST cover every field the outbound sync actually pushes to
    Xero, otherwise an edit to (for example) email or address is silently
    skipped by enqueue_sync_contact's hash short-circuit. We therefore include
    the primary contact email/phone/mobile, the primary contact person name and
    the primary address fields, resolved via the SAME getter helpers the sync
    uses. The components are normalised (stripped) and assembled in a stable,
    sorted order so the digest is deterministic.
    """
    name_field = "customer_name" if doc.doctype == "Customer" else "supplier_name"

    # Primary contact person details (email, phone, mobile, name) — same source
    # the outbound payload uses.
    contact_details = get_primary_contact_details(doc.doctype, doc.name) or {}
    # Primary address fields — same source the outbound payload uses.
    address = get_primary_address(doc.doctype, doc.name) or {}

    components = {
        "name": str(doc.get(name_field) or "").strip(),
        "tax_id": str(doc.get("tax_id") or "").strip(),
        "website": str(doc.get("website") or "").strip(),
        "disabled": str(doc.get("disabled") or 0),
        "email": str(contact_details.get("email_id") or "").strip(),
        "phone": str(contact_details.get("phone") or "").strip(),
        "mobile_no": str(contact_details.get("mobile_no") or "").strip(),
        "contact_first_name": str(contact_details.get("first_name") or "").strip(),
        "contact_last_name": str(contact_details.get("last_name") or "").strip(),
        "addr_line1": str(address.get("AddressLine1") or "").strip(),
        "addr_city": str(address.get("City") or "").strip(),
        "addr_state": str(address.get("Region") or "").strip(),
        "addr_pincode": str(address.get("PostalCode") or "").strip(),
        "addr_country": str(address.get("Country") or "").strip(),
    }
    # Sorted items -> stable, order-independent serialisation.
    data = "|".join(f"{k}={components[k]}" for k in sorted(components))
    return hashlib.md5(data.encode()).hexdigest()


def parse_erpnext_reference(contact_number):
    """Parse ERPNext reference from Xero ContactNumber.

    Format: "ERP:{type_code}:{doc_name}"
    Example: "ERP:C:CUST-001" for Customer, "ERP:S:SUPP-001" for Supplier

    Returns: tuple (doc_type, doc_name) or (None, None) if not found
    """
    if not contact_number or not str(contact_number).startswith("ERP:"):
        return None, None

    parts = str(contact_number).split(":")
    if len(parts) != 3:
        return None, None

    type_code, doc_name = parts[1], parts[2]
    doc_type = (
        "Customer" if type_code == "C" else "Supplier" if type_code == "S" else None
    )
    return doc_type, doc_name


def build_contact_number(doc_type, doc_name):
    """Build ContactNumber for Xero contact.

    Format: "ERP:{type_code}:{doc_name}"
    """
    type_code = "C" if doc_type == "Customer" else "S"
    return f"ERP:{type_code}:{doc_name}"


# =============================================================================
# SYNC FUNCTIONS
# =============================================================================


@frappe.whitelist()
def enqueue_sync_contact(doc_name, doc_type=None):
    """Enqueue background job to sync contact to Xero with one retry.
    Accepts either (doc_name, doc_type) or (doc, method) when called from Frappe hooks (doc is Customer/Supplier).
    """
    # When called from Frappe hook: (doc, method) with doc = Customer/Supplier document
    if hasattr(doc_name, "name") and hasattr(doc_name, "doctype"):
        doc = doc_name
        # HI-4: The inbound (Xero -> ERPNext) sync sets this flag before saving the
        # Customer/Supplier so the on_update hook does NOT re-fire an outbound sync,
        # which would otherwise loop indefinitely.
        if getattr(doc.flags, "ignore_xero_sync", False):
            return
        doc_name = doc.name
        doc_type = doc.doctype
    elif not doc_type or doc_type in ("on_update", "manual_trigger"):
        # Second arg was method name; doc_name might be a string identifier
        frappe.throw(
            _(
                "enqueue_sync_contact requires (doc_name, doc_type) or a document as first argument."
            )
        )

    # Improved guard against double-trigger from on_update hook
    # Check if sync should be skipped based on status and data changes
    sync_status = frappe.db.get_value(doc_type, doc_name, "xero_sync_status")

    # Allow re-sync if status is Error or Pending
    if sync_status in ("Error", "Pending"):
        pass  # Continue to sync
    elif sync_status == "Synced":
        # Check if data has changed since last sync
        doc = frappe.get_doc(doc_type, doc_name)
        current_hash = compute_data_hash(doc)
        stored_hash = frappe.db.get_value(doc_type, doc_name, "xero_data_hash") or ""

        if current_hash == stored_hash:
            # No changes since last sync, skip
            return

    frappe.enqueue(
        "xero.api.xero_contacts.sync_contact_to_xero",
        queue="short",
        timeout=600,
        doc_name=doc_name,
        doc_type=doc_type,
    )
    frappe.publish_realtime("show_alert", {"message": _("Contact sync to Xero queued."), "indicator": "blue"}, user=frappe.session.user)


@retry_with_exponential_backoff(max_retries=3, base_delay=1)
def sync_contact_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs an ERPNext Customer or Supplier to Xero Contacts.

    CRITICAL: Uses POST for updates (when ContactID is known) and PUT for creates.
    This is because PUT errors if ContactName matches an existing contact.

    NOTE: IsCustomer/IsSupplier are NOT sent - they are read-only fields in Xero API.
    Xero sets these automatically when invoices are created against the contact.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return  # Master switch disabled

    # Check per-entity directional toggle for outbound sync
    if not settings.get("sync_contacts_to_xero"):
        log_xero_error(
            message=f"Contact outbound sync is disabled. Skipping {doc_type} {doc_name}.",
            status="Info",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            category="System Monitoring",
        )
        return

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_contact_id = doc.get("xero_contact_id")

        # --- Validate and Sanitize Name (required by Xero) ---
        raw_name = doc.get("customer_name") or doc.get("supplier_name")
        name, error = validate_and_sanitize_name(raw_name, doc_type, doc_name)

        if error:
            log_xero_error(
                message=error,
                status="Warning",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="Validation",
            )
            frappe.db.set_value(
                doc_type, doc_name, {"xero_sync_status": "Error"}, update_modified=False
            )
            frappe.db.commit()
            return

        # --- Map ERPNext Data to Xero Contact Format ---
        primary_contact_details = get_primary_contact_details(doc_type, doc_name)

        # Build contact payload
        # NOTE: IsCustomer/IsSupplier are READ-ONLY in Xero API - do NOT send them
        # Xero sets these automatically when invoices are created against the contact
        contact_payload = {
            "Name": name,
            # ContactNumber stores ERPNext reference for reliable matching on inbound sync
            # Format: "ERP:{C|S}:{doc_name}" where C=Customer, S=Supplier
            "ContactNumber": build_contact_number(doc_type, doc_name),
            "ContactStatus": "ARCHIVED" if doc.get("disabled") else "ACTIVE",
        }
        # Set FirstName/LastName only when we have them from linked Contact; for company-only, omit (Name is sufficient).
        first_name = (primary_contact_details.get("first_name") or "").strip()
        last_name = (primary_contact_details.get("last_name") or "").strip()
        if first_name:
            contact_payload["FirstName"] = first_name
        if last_name:
            contact_payload["LastName"] = last_name
        # No fallback for company-only parties: inventing FirstName from the
        # organisation name round-trips badly — inbound sees it on the Xero
        # contact and materialises a bogus ERP Contact person for the party.

        # Add EmailAddress if available from contact details
        if (
            primary_contact_details.get("email_id")
            and str(primary_contact_details.get("email_id")).strip()
        ):
            contact_payload["EmailAddress"] = str(
                primary_contact_details.get("email_id")
            ).strip()

        # Add Phones - include all phones that have values
        phones = []
        if (
            primary_contact_details.get("phone")
            and str(primary_contact_details.get("phone")).strip()
        ):
            phones.append(
                {
                    "PhoneType": "DEFAULT",
                    "PhoneNumber": str(primary_contact_details.get("phone")).strip(),
                }
            )
        if (
            primary_contact_details.get("mobile_no")
            and str(primary_contact_details.get("mobile_no")).strip()
        ):
            phones.append(
                {
                    "PhoneType": "MOBILE",
                    "PhoneNumber": str(
                        primary_contact_details.get("mobile_no")
                    ).strip(),
                }
            )
        if phones:
            contact_payload["Phones"] = phones

        # Add TaxNumber if available
        if doc.get("tax_id") and str(doc.get("tax_id")).strip():
            contact_payload["TaxNumber"] = str(doc.get("tax_id")).strip()

        # Add Website if available
        if doc.get("website") and str(doc.get("website")).strip():
            contact_payload["Website"] = str(doc.get("website")).strip()

        # Add primary address only when it has at least AddressLine1 or Country (Xero dependency)
        primary_address = get_primary_address(doc_type, doc_name)
        if primary_address and (
            primary_address.get("AddressLine1") or primary_address.get("Country")
        ):
            contact_payload["Addresses"] = [primary_address]

        # Add primary contact person if available
        # IMPORTANT: Xero requires EmailAddress on main contact if ContactPersons are added
        # If no email is available anywhere, skip ContactPersons to ensure sync succeeds
        primary_contact_person = get_primary_contact(doc_type, doc_name)
        if primary_contact_person:
            # Check if we have an email anywhere (main contact or contact person)
            has_main_email = bool(contact_payload.get("EmailAddress"))
            has_contact_person_email = bool(primary_contact_person.get("EmailAddress"))

            if has_main_email or has_contact_person_email:
                # Xero requires EmailAddress when IncludeInEmails is True; ensure we never send invalid combination
                if primary_contact_person.get(
                    "IncludeInEmails"
                ) and not primary_contact_person.get("EmailAddress"):
                    primary_contact_person.pop("IncludeInEmails", None)
                contact_payload["ContactPersons"] = [primary_contact_person]

                # If main contact has no email but ContactPerson has email, use it as main EmailAddress
                if not has_main_email and has_contact_person_email:
                    contact_payload["EmailAddress"] = primary_contact_person.get(
                        "EmailAddress"
                    )
            else:
                # No email available - skip ContactPersons to avoid Xero validation error
                # Log a warning so users know contact person data was not synced
                frappe.log_error(
                    message=f"Skipping ContactPerson data for {doc_type} '{doc_name}' - no email address available. "
                    f"Contact person ({primary_contact_person.get('FirstName', '')} {primary_contact_person.get('LastName', '')}) "
                    f"will not be synced to Xero. Add an email to the contact to include this data.",
                    title="Xero Sync: ContactPerson Skipped",
                )

        # If updating an existing contact, include the ID
        if xero_contact_id:
            contact_payload["ContactID"] = xero_contact_id

        # Final cleanup: Remove any None, empty string, or empty array values
        # This ensures we never send empty/null data to Xero
        # Only include fields with actual values
        def is_empty_value(v):
            """Check if a value is empty (None, empty string, empty list, empty dict)"""
            if v is None:
                return True
            if isinstance(v, str) and not v.strip():
                return True
            if isinstance(v, list):
                return len(v) == 0
            if isinstance(v, dict):
                return len(v) == 0
            return False

        def clean_dict(d):
            """Recursively clean a dictionary, removing empty values"""
            cleaned = {}
            for k, v in d.items():
                if isinstance(v, dict):
                    cleaned_dict = clean_dict(v)
                    if cleaned_dict:  # Only add if dict has values
                        cleaned[k] = cleaned_dict
                elif isinstance(v, list):
                    cleaned_list = []
                    for item in v:
                        if isinstance(item, dict):
                            cleaned_item = clean_dict(item)
                            if cleaned_item:  # Only add if item has values
                                cleaned_list.append(cleaned_item)
                        elif not is_empty_value(item):
                            cleaned_list.append(item)
                    if cleaned_list:  # Only add if list has items
                        cleaned[k] = cleaned_list
                elif not is_empty_value(v):
                    cleaned[k] = v
            return cleaned

        contact_payload = clean_dict(contact_payload)
        # Ensure Name and ContactNumber are always present (Xero requirement); never let clean_dict remove them.
        contact_payload["Name"] = name
        contact_payload["ContactNumber"] = build_contact_number(doc_type, doc_name)
        if xero_contact_id:
            contact_payload["ContactID"] = xero_contact_id

        # --- Make API Call ---
        # CRITICAL: Use POST for updates (when ContactID is known), PUT for creates only.
        # PUT errors if ContactName matches an existing contact, POST creates or updates.
        method = "POST" if xero_contact_id else "PUT"
        # Pass a stable idempotency key on CREATE (PUT) so a retry after a network
        # timeout where Xero actually created the contact does not duplicate it.
        idempotency_key = (
            None if xero_contact_id else f"{doc_type}:{doc_name}:create"
        )
        response = xero_request(
            method,
            "Contacts",
            data={"Contacts": [contact_payload]},
            idempotency_key=idempotency_key,
        )

        if response and response.get("Contacts"):
            updated_contact = response["Contacts"][0]
            new_xero_contact_id = updated_contact.get("ContactID")

            # --- Update ERPNext Document ---
            if new_xero_contact_id:
                # Compute and store data hash for change detection
                data_hash = compute_data_hash(doc)
                frappe.db.set_value(
                    doc_type,
                    doc_name,
                    {
                        "xero_contact_id": new_xero_contact_id,
                        "xero_sync_status": "Synced",
                        "xero_data_hash": data_hash,
                    },
                    update_modified=False,
                )
                frappe.db.commit()  # Commit changes immediately

                log_xero_error(
                    message=f"Successfully synced {doc_type} {doc_name} to Xero.",
                    status="Success",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=new_xero_contact_id,
                    xero_entity_type="Contact",
                )
            else:
                raise Exception("Xero API response did not contain a ContactID.")

        else:
            raise Exception("Invalid response received from Xero Contacts API.")

    except Exception as e:
        from ..utils.logging import is_already_exists_error

        error_traceback = frappe.get_traceback()

        # Check if this is an "already exists" type error from Xero API
        if is_already_exists_error(str(e), error_traceback):
            frappe.db.set_value(
                doc_type,
                doc_name,
                {"xero_sync_status": "Synced"},
                update_modified=False,
            )
            frappe.db.commit()

            log_xero_error(
                message=f"{doc_type} {doc_name} already exists in Xero. No action needed.",
                status="Info",
                category="Duplicate Entity",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                direction="ERPNext to Xero",
            )
        else:
            from ..utils.logging import build_error_details, format_sync_error_message

            # Permanent Xero rejections (duplicate name, archived contact, ...)
            # go terminal ("Failed") so the hourly retry task stops re-queuing
            # a contact that can never sync unchanged.
            sync_status = "Failed" if getattr(e, "is_permanent", False) else "Error"
            frappe.db.set_value(
                doc_type, doc_name, {"xero_sync_status": sync_status}, update_modified=False
            )
            frappe.db.commit()
            user_message = format_sync_error_message(
                doc_type, doc_name, doc_name, "ERPNext to Xero", e
            )
            # M4: archived contacts cannot be edited OR unarchived through the
            # Xero API (verified even for a minimal ContactStatus-only update),
            # so point the operator at the one action that works.
            if "archived contact" in str(e).lower():
                user_message += (
                    " Unarchive the contact in the Xero web UI first, then use "
                    "Retry — the API cannot modify archived contacts."
                )
            log_xero_error(
                message=user_message,
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                error_details=build_error_details(e, error_traceback),
                direction="ERPNext to Xero",
            )


def sync_contacts_to_xero(filters=None, sync_type="full", **kwargs):
    """
    Batch sync: sync multiple Customers and/or Suppliers to Xero.
    Called from the Sync Dashboard for entity types Customer and Supplier.
    filters: optional Frappe filters (e.g. {"name": "..."} or {} for all).
    sync_type: "full" or optional; when "pending" only syncs docs with xero_sync_status in ("Pending", "Error") if filters allow.
    """
    settings = get_xero_settings()
    if (
        not settings.enable_xero_sync
        or not settings.enable_sync_to_xero
        or not settings.sync_contacts
    ):
        return

    filters = filters or {}
    doc_filters = {k: v for k, v in filters.items() if k != "entity_type"}
    entity_type = filters.get("entity_type") or kwargs.get("entity_type")

    to_sync = []
    if not entity_type or entity_type == "Customer":
        if sync_type == "pending":
            doc_filters_customer = dict(doc_filters)
            doc_filters_customer["xero_sync_status"] = ["in", ["Pending", "Error"]]
            to_sync.extend(
                [
                    ("Customer", n)
                    for n in frappe.get_all(
                        "Customer", filters=doc_filters_customer, pluck="name"
                    )
                ]
            )
        else:
            to_sync.extend(
                [
                    ("Customer", n)
                    for n in frappe.get_all(
                        "Customer", filters=doc_filters, pluck="name"
                    )
                ]
            )
    if not entity_type or entity_type == "Supplier":
        if sync_type == "pending":
            doc_filters_supplier = dict(doc_filters)
            doc_filters_supplier["xero_sync_status"] = ["in", ["Pending", "Error"]]
            to_sync.extend(
                [
                    ("Supplier", n)
                    for n in frappe.get_all(
                        "Supplier", filters=doc_filters_supplier, pluck="name"
                    )
                ]
            )
        else:
            to_sync.extend(
                [
                    ("Supplier", n)
                    for n in frappe.get_all(
                        "Supplier", filters=doc_filters, pluck="name"
                    )
                ]
            )

    for doc_type, doc_name in to_sync:
        try:
            sync_contact_to_xero(doc_name, doc_type)
        except Exception as e:
            log_xero_error(
                message=f"Batch contact sync failed for {doc_type} {doc_name}: {e}",
                status="Error",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                error_details=frappe.get_traceback(),
            )


def get_primary_address(parent_doctype, parent_name):
    """Helper to get primary address details formatted for Xero."""
    # Find the primary address linked to the Customer/Supplier
    # Query using Dynamic Link child table properly
    # Prioritize by address_type (Billing), then Shipping, then any Primary
    address_result = frappe.db.sql(
        """
        SELECT a.name
        FROM `tabAddress` a
        INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name AND dl.parenttype = 'Address'
        WHERE dl.link_doctype = %s AND dl.link_name = %s 
        AND (a.address_type = 'Billing' OR a.is_primary_address = 1)
        ORDER BY CASE WHEN a.address_type = 'Billing' THEN 1 WHEN a.is_primary_address = 1 THEN 2 ELSE 3 END
        LIMIT 1
    """,
        (parent_doctype, parent_name),
        as_dict=True,
    )

    if not address_result:
        # Fallback: get any address linked to this customer
        address_result = frappe.db.sql(
            """
            SELECT a.name
            FROM `tabAddress` a
            INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name AND dl.parenttype = 'Address'
            WHERE dl.link_doctype = %s AND dl.link_name = %s
            LIMIT 1
        """,
            (parent_doctype, parent_name),
            as_dict=True,
        )

    if not address_result:
        return None

    address_name = address_result[0].name

    address_doc = frappe.get_doc("Address", address_name)
    # Map ERPNext Address fields to Xero Address structure
    # See: https://developer.xero.com/documentation/api/accounting/contacts#addresses
    xero_address = {
        # Use STREET type for physical addresses, POBOX if address_type indicates it
        "AddressType": "STREET" if address_doc.address_type != "Postal" else "POBOX",
        "AddressLine1": address_doc.address_line1,
        "AddressLine2": address_doc.address_line2,
        "City": address_doc.city,
        "Region": address_doc.state,
        "PostalCode": address_doc.pincode,
        "Country": address_doc.country,  # Ensure country name/code matches Xero's expectations if needed
    }
    # Remove None and empty string values, but keep all fields that have data
    # This allows syncing sparse addresses (e.g., just City, or just PostalCode)
    xero_address = {
        k: v for k, v in xero_address.items() if v is not None and str(v).strip() != ""
    }

    # Return address if it has ANY meaningful data (any field with a value)
    # This syncs all available address data while preventing completely empty objects
    if not xero_address:
        return None

    return xero_address


def get_primary_contact_details(parent_doctype, parent_name):
    """Helper to get primary contact person details (email, phone)."""
    # Find the primary Contact linked to the Customer/Supplier
    # Query using Dynamic Link child table properly
    contact_result = frappe.db.sql(
        """
        SELECT c.name
        FROM `tabContact` c
        INNER JOIN `tabDynamic Link` dl ON dl.parent = c.name AND dl.parenttype = 'Contact'
        WHERE dl.link_doctype = %s AND dl.link_name = %s AND c.is_primary_contact = 1
        LIMIT 1
    """,
        (parent_doctype, parent_name),
        as_dict=True,
    )

    if not contact_result:
        return {}

    contact_doc = frappe.get_doc("Contact", contact_result[0].name)
    details = {
        "first_name": contact_doc.first_name,
        "last_name": contact_doc.last_name,
        "email_id": contact_doc.email_id,
        "phone": contact_doc.phone,
        "mobile_no": contact_doc.mobile_no,
    }
    return {k: v for k, v in details.items() if v}  # Return dict with non-empty values


def get_primary_contact(parent_doctype, parent_name):
    """Helper to get primary contact person details formatted for Xero ContactPersons."""
    details = get_primary_contact_details(parent_doctype, parent_name)
    if not details:
        return None

    # Map ERPNext Contact fields to Xero ContactPerson structure
    # See: https://developer.xero.com/documentation/api/accounting/contacts#contact-persons
    xero_contact_person = {
        "FirstName": details.get("first_name"),
        "LastName": details.get("last_name"),
        "EmailAddress": details.get("email_id"),
        "IncludeInEmails": True,  # Default? Or based on ERPNext setting?
    }
    # Remove None and empty string values, but keep all fields that have data
    # This allows syncing sparse contact person data (e.g., just email, or just name)
    xero_contact_person = {
        k: v
        for k, v in xero_contact_person.items()
        if v is not None and str(v).strip() != ""
    }

    # Return contact person if it has ANY meaningful data (FirstName, LastName, or EmailAddress)
    # This syncs all available contact person data while preventing completely empty objects
    if not xero_contact_person:
        return None

    # If IncludeInEmails is True but no EmailAddress, remove IncludeInEmails
    # Xero requires EmailAddress when IncludeInEmails is True
    if xero_contact_person.get("IncludeInEmails") and not xero_contact_person.get(
        "EmailAddress"
    ):
        xero_contact_person.pop("IncludeInEmails", None)

    return xero_contact_person


def sync_contacts_from_xero():
    """
    Fetches contacts from Xero and creates/updates corresponding
    Customers/Suppliers in ERPNext.
    (Consider potential for duplicates and mapping challenges)
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        return  # Master switch disabled

    # Check per-entity directional toggle for inbound sync
    if not settings.get("sync_contacts_from_xero"):
        log_xero_error(
            message="Contact inbound sync is disabled. Skipping contacts from Xero.",
            status="Info",
            category="System Monitoring",
        )
        return

    from ..utils.xero_client import (
        incremental_since,
        commit_watermark,
        start_incremental_run,
    )

    watermark_key = "contacts"
    run_started_at = start_incremental_run()
    if_modified_since = incremental_since(watermark_key)

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Contacts page {page}", "Xero Sync")
            response = xero_request(
                "GET",
                "Contacts",
                params={"page": page},
                modified_since=if_modified_since,
            )

            if not response or not response.get("Contacts"):
                break  # No more contacts or error

            contacts = response["Contacts"]
            if not contacts:
                break  # Empty page, end of contacts

            for contact in contacts:
                try:
                    process_xero_contact(contact)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Contact ID {contact.get('ContactID')}",
                        xero_entity_id=contact.get("ContactID"),
                        xero_entity_type="Contact",
                        error_details=frappe.get_traceback(),
                    )

            # Check if it was the last page (Xero doesn't explicitly tell you,
            # so we assume if we received less than 100, it's the last page,
            # or if the response was empty/invalid)
            # Xero default page size is 100
            if len(contacts) < 100:
                break
            page += 1

        # Only advance the watermark after a fully successful sweep — if an
        # exception aborted the loop, the next run re-fetches from the old
        # watermark so nothing is missed.
        commit_watermark(watermark_key, run_started_at)
        log_xero_error(message="Finished syncing contacts from Xero.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_contacts_from_xero",
            error_details=frappe.get_traceback(),
        )


def process_xero_contact(xero_contact_data):
    """Creates or updates an ERPNext Customer/Supplier from Xero contact data.

    Priority for determining DocType:
    1. ContactNumber field (if it contains ERP: prefix)
    2. IsCustomer/IsSupplier flags (only set after invoices are created)
    3. Skip with warning if no type information available
    """
    xero_contact_id = xero_contact_data.get("ContactID")
    contact_name = xero_contact_data.get("Name")
    contact_number = xero_contact_data.get("ContactNumber")

    if not xero_contact_id or not contact_name:
        log_xero_error(
            message=f"Skipping Xero contact due to missing ID or Name: {xero_contact_data}",
            status="Info",
        )
        return

    # Priority 1: Check ContactNumber for ERPNext reference
    # This is the most reliable way to determine the correct DocType
    doc_type, doc_name = parse_erpnext_reference(contact_number)
    if doc_type and doc_name:
        # Found ERPNext reference - sync to correct DocType
        log_xero_error(
            message=f"Xero Contact {contact_name} ({xero_contact_id}) has ContactNumber '{contact_number}' - syncing as {doc_type}",
            status="Info",
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
        )
        sync_xero_contact_to_erpnext(xero_contact_data, doc_type)
        return

    # Priority 2: Check IsCustomer/IsSupplier flags
    # NOTE: These are only set after invoices are created against the contact
    is_customer = xero_contact_data.get("IsCustomer", False)
    is_supplier = xero_contact_data.get("IsSupplier", False)

    if is_customer:
        sync_xero_contact_to_erpnext(xero_contact_data, "Customer")
    if is_supplier:
        sync_xero_contact_to_erpnext(xero_contact_data, "Supplier")

    # Priority 3: No type information available
    if not is_customer and not is_supplier:
        # Contact has no type information - this happens for:
        # - New contacts created via API that haven't been used on invoices
        # - Contacts created manually in Xero without transactions
        #
        # We skip these contacts with a warning instead of defaulting to Customer
        # to prevent incorrect type assignment on round-trip syncs
        log_xero_error(
            message=f"Xero Contact {contact_name} ({xero_contact_id}) has no type information. "
            f"IsCustomer={is_customer}, IsSupplier={is_supplier}, ContactNumber={contact_number}. "
            f"Skipping - cannot determine if Customer or Supplier. "
            f"This contact will be synced when it's used on an invoice.",
            status="Warning",
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            category="Sync Skipped",
        )


def _contact_email_matches(target_doctype, party_name, xero_contact_data):
    """True when the Xero contact's email matches an email already on the
    candidate ERPNext party (via a linked Contact). Used as a second signal to
    gate auto-linking on an otherwise-unsafe bare-name match."""
    xero_email = (xero_contact_data.get("EmailAddress") or "").strip().lower()
    if not xero_email:
        return False
    linked_contacts = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": target_doctype,
            "link_name": party_name,
            "parenttype": "Contact",
        },
        pluck="parent",
    )
    for contact in linked_contacts:
        emails = frappe.get_all(
            "Contact Email", filters={"parent": contact}, pluck="email_id"
        )
        if any((e or "").strip().lower() == xero_email for e in emails):
            return True
    return False


def sync_xero_contact_to_erpnext(xero_contact_data, target_doctype):
    """Syncs a single Xero contact to the specified ERPNext DocType (Customer or Supplier)."""
    xero_contact_id = xero_contact_data.get("ContactID")
    contact_name = xero_contact_data.get("Name")
    erpnext_doc_name = None
    sync_status = "Synced"  # Assume success unless error occurs

    # 1. Check if ERPNext doc already exists linked by xero_contact_id
    erpnext_doc_name = frappe.db.get_value(
        target_doctype, {"xero_contact_id": xero_contact_id}, "name"
    )

    # 2. If not found by ID, consider a name match — but a bare name match is
    #    unsafe: two unrelated parties can share a name, and blindly binding the
    #    Xero id then overwriting fields silently corrupts the wrong master
    #    record. Only auto-link when (a) the candidate is not already linked to a
    #    DIFFERENT Xero contact, and (b) a second signal (email) corroborates.
    #    Otherwise skip and flag for a human to link manually.
    if not erpnext_doc_name:
        field_name = (
            "customer_name" if target_doctype == "Customer" else "supplier_name"
        )
        name_match = frappe.db.get_value(
            target_doctype, {field_name: contact_name},
            ["name", "xero_contact_id"], as_dict=True,
        )
        if name_match:
            existing_xid = name_match.get("xero_contact_id")
            if existing_xid and existing_xid != xero_contact_id:
                log_xero_error(
                    message=(
                        f"Xero Contact {xero_contact_id} ({contact_name}) name-matches "
                        f"{target_doctype} {name_match.name}, already linked to a DIFFERENT "
                        f"Xero contact ({existing_xid}). Skipping to avoid a wrong merge."
                    ),
                    status="Warning",
                    category="Duplicate Entity",
                    xero_entity_id=xero_contact_id,
                    xero_entity_type="Contact",
                    erpnext_doc_type=target_doctype,
                    erpnext_doc_name=name_match.name,
                    direction="Xero to ERPNext",
                )
                return
            if _contact_email_matches(target_doctype, name_match.name, xero_contact_data):
                # Name + email corroborate: safe to link this existing record.
                erpnext_doc_name = name_match.name
            else:
                log_xero_error(
                    message=(
                        f"Xero Contact {xero_contact_id} ({contact_name}) name-matches "
                        f"{target_doctype} {name_match.name}, but no corroborating email. "
                        f"Skipping auto-link to avoid a wrong merge; link manually if correct."
                    ),
                    status="Warning",
                    category="Duplicate Entity",
                    xero_entity_id=xero_contact_id,
                    xero_entity_type="Contact",
                    erpnext_doc_type=target_doctype,
                    erpnext_doc_name=name_match.name,
                    direction="Xero to ERPNext",
                )
                return

    # --- Map Xero Data to ERPNext Fields ---
    # Only carry non-empty Xero values so a blank Xero field never wipes an
    # existing ERPNext value on an update.
    erpnext_data = {
        "xero_contact_id": xero_contact_id,
        "xero_sync_status": sync_status,
    }
    if xero_contact_data.get("TaxNumber"):
        erpnext_data["tax_id"] = xero_contact_data.get("TaxNumber")
    if xero_contact_data.get("Website"):
        erpnext_data["website"] = xero_contact_data.get("Website")

    # Map ContactStatus to disabled field
    # ACTIVE → disabled=0, ARCHIVED/GDPRREQUEST → disabled=1
    contact_status = xero_contact_data.get("ContactStatus", "ACTIVE")
    erpnext_data["disabled"] = 0 if contact_status == "ACTIVE" else 1

    # Map DefaultCurrency if available
    default_currency = xero_contact_data.get("DefaultCurrency")
    if default_currency:
        erpnext_data["default_currency"] = default_currency

    if target_doctype == "Customer":
        erpnext_data["customer_name"] = contact_name
        erpnext_data["customer_group"] = get_leaf_doctype_value(
            "Customer Group", frappe.db.get_default("customer_group")
        )
        erpnext_data["territory"] = get_leaf_doctype_value(
            "Territory", frappe.db.get_default("territory")
        )
    else:  # Supplier
        erpnext_data["supplier_name"] = contact_name
        erpnext_data["supplier_group"] = get_leaf_doctype_value(
            "Supplier Group", frappe.db.get_default("supplier_group")
        )

    # --- Create or Update ERPNext Document ---
    try:
        if erpnext_doc_name:
            # Update existing document
            doc = frappe.get_doc(target_doctype, erpnext_doc_name)
            doc.update(erpnext_data)
            # HI-4: suppress the outbound on_update->enqueue hook for this
            # inbound write so we don't bounce the same data straight back to Xero.
            doc.flags.ignore_xero_sync = True
            # TODO: Update addresses and contact persons if needed
            doc.save(ignore_permissions=True)  # Use ignore_permissions carefully
            log_message = f"Updated {target_doctype} {erpnext_doc_name} from Xero Contact {xero_contact_id}"
        else:
            # Create new document
            doc = frappe.new_doc(target_doctype)
            doc.update(erpnext_data)
            # HI-4: suppress the outbound on_update->enqueue hook (see above).
            doc.flags.ignore_xero_sync = True
            # TODO: Create addresses and contact persons if needed
            doc.insert(ignore_permissions=True)  # Use ignore_permissions carefully
            erpnext_doc_name = doc.name
            log_message = f"Created {target_doctype} {erpnext_doc_name} from Xero Contact {xero_contact_id}"

        # HI-4: persist the freshly-computed data hash on the inbound path so a
        # LATER genuine ERPNext edit is correctly detected (and not short-circuited
        # by enqueue_sync_contact comparing against a stale/empty hash). Computed
        # after save so address/contact relations resolved above are reflected.
        try:
            frappe.db.set_value(
                target_doctype,
                erpnext_doc_name,
                "xero_data_hash",
                compute_data_hash(doc),
                update_modified=False,
            )
        except Exception:
            # Hash is an optimisation only; never let it break the inbound sync.
            log_xero_error(
                message=f"Could not store xero_data_hash for {target_doctype} {erpnext_doc_name}",
                status="Warning",
                erpnext_doc_type=target_doctype,
                erpnext_doc_name=erpnext_doc_name,
                category="System Monitoring",
                error_details=frappe.get_traceback(),
            )

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type=target_doctype,
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            direction="Xero to ERPNext",
        )

        # --- Sync Contact Persons ---
        # Order matters: process the ContactPersons array FIRST and the
        # Contact-level primary fields (FirstName/EmailAddress/Phones) LAST.
        # Xero mirrors the primary person into ContactPersons, so after a
        # Contact-level email change the array still echoes the OLD address —
        # whichever block runs last decides the primary email, and that must
        # be the authoritative Contact-level one.
        # NOTE: Xero allows max 5 ContactPersons per contact
        contact_persons = xero_contact_data.get("ContactPersons", [])
        if contact_persons:
            # Limit to XERO_MAX_CONTACT_PERSONS to avoid API errors
            contact_persons = contact_persons[:XERO_MAX_CONTACT_PERSONS]
            if (
                len(xero_contact_data.get("ContactPersons", []))
                > XERO_MAX_CONTACT_PERSONS
            ):
                log_xero_error(
                    message=f"Xero Contact {contact_name} has {len(xero_contact_data.get('ContactPersons', []))} ContactPersons. "
                    f"Only syncing first {XERO_MAX_CONTACT_PERSONS}.",
                    status="Warning",
                    xero_entity_id=xero_contact_id,
                    xero_entity_type="Contact",
                )

            for person in contact_persons:
                try:
                    sync_contact_person_to_erpnext(
                        person, target_doctype, erpnext_doc_name, xero_contact_id
                    )
                except Exception as person_error:
                    # Log error but continue with other contact persons
                    log_xero_error(
                        message=f"Failed to sync ContactPerson for {target_doctype} {erpnext_doc_name}",
                        erpnext_doc_type="Contact",
                        xero_entity_id=xero_contact_id,
                        error_details=str(person_error),
                    )

        # The primary contact lives directly on the Xero Contact object;
        # processed last so it wins over any stale ContactPersons echo.
        primary_first_name = xero_contact_data.get("FirstName")
        primary_email = xero_contact_data.get("EmailAddress")
        primary_phones = xero_contact_data.get("Phones", [])

        if primary_first_name or primary_email:
            # Pseudo ContactPerson from the primary fields. LastName MUST be
            # carried too: without it the person-matcher cannot find the
            # existing "First Last" Contact and creates a duplicate per amend.
            primary_person_data = {}
            if primary_first_name:
                primary_person_data["FirstName"] = primary_first_name
            if xero_contact_data.get("LastName"):
                primary_person_data["LastName"] = xero_contact_data.get("LastName")
            if primary_email:
                primary_person_data["EmailAddress"] = primary_email
            if primary_phones:
                primary_person_data["Phones"] = primary_phones
            # The primary contact is always included in emails.
            primary_person_data["IncludeInEmails"] = True

            try:
                sync_contact_person_to_erpnext(
                    primary_person_data,
                    target_doctype,
                    erpnext_doc_name,
                    xero_contact_id,
                )
            except Exception as person_error:
                # Log error but continue
                log_xero_error(
                    message=f"Failed to sync primary contact for {target_doctype} {erpnext_doc_name}",
                    erpnext_doc_type="Contact",
                    xero_entity_id=xero_contact_id,
                    error_details=str(person_error),
                )

        # --- Sync Addresses (NEW IMPLEMENTATION) ---
        # Sync addresses from Xero to ERPNext Address DocType
        addresses = xero_contact_data.get("Addresses", [])
        if addresses:
            for address_data in addresses:
                try:
                    sync_xero_address_to_erpnext(
                        address_data, target_doctype, erpnext_doc_name, xero_contact_id
                    )
                except Exception as address_error:
                    # Log error but continue with other addresses
                    log_xero_error(
                        message=f"Failed to sync Address for {target_doctype} {erpnext_doc_name}",
                        erpnext_doc_type="Address",
                        xero_entity_id=xero_contact_id,
                        error_details=str(address_error),
                    )

    except Exception as e:
        # Log error, but don't stop processing other contacts
        sync_status = "Error"
        if erpnext_doc_name:  # If update failed after finding doc
            frappe.db.set_value(
                target_doctype,
                erpnext_doc_name,
                "xero_sync_status",
                sync_status,
                update_modified=False,
            )
            frappe.db.commit()

        log_xero_error(
            message=f"Failed to sync Xero Contact {xero_contact_id} to ERPNext {target_doctype}",
            erpnext_doc_type=target_doctype,
            erpnext_doc_name=erpnext_doc_name,  # Might be None if creation failed early
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback(),
        )


def sync_contact_person_to_erpnext(
    person_data, parent_doctype, parent_name, xero_contact_id
):
    """
    Creates or updates an ERPNext Contact from Xero ContactPerson data or primary contact fields.
    Links the contact to the parent Customer/Supplier via Dynamic Link.

    Args:
        person_data: Dictionary containing Xero ContactPerson data (or primary contact fields)
        parent_doctype: "Customer" or "Supplier"
        parent_name: Name of the parent Customer/Supplier document
        xero_contact_id: Xero Contact ID (for logging purposes)
    """
    first_name = person_data.get("FirstName")
    last_name = person_data.get("LastName")
    email = person_data.get("EmailAddress")

    # Extract phone numbers if available (from Xero Phones array)
    phones = person_data.get("Phones", [])

    # Skip if no meaningful data
    if not first_name and not last_name and not email:
        return

    # Try to find existing contact
    contact_name = None

    # Strategy 1: Find by email, but SCOPED to this party's own linked Contacts
    # only (LO-2). A global email lookup cross-links unrelated Customers/Suppliers
    # that happen to share a mailbox (e.g. info@). We therefore require the Contact
    # to already carry a Dynamic Link to this parent Customer/Supplier.
    if email:
        scoped = frappe.db.sql(
            """
            SELECT c.name
            FROM `tabContact` c
            INNER JOIN `tabContact Email` ce ON ce.parent = c.name AND ce.parenttype = 'Contact'
            INNER JOIN `tabDynamic Link` dl ON dl.parent = c.name AND dl.parenttype = 'Contact'
            WHERE ce.email_id = %s
            AND dl.link_doctype = %s AND dl.link_name = %s
            LIMIT 1
        """,
            (email, parent_doctype, parent_name),
            as_dict=True,
        )
        if scoped:
            contact_name = scoped[0].name

    # Strategy 2: Find by name linked to this specific customer/supplier.
    # last_name is legitimately empty for company-only contacts, so match it
    # as an empty string instead of requiring both parts (requiring both made
    # every amend of a last-name-less contact create a duplicate).
    if not contact_name and first_name:
        contact_result = frappe.db.sql(
            """
            SELECT c.name
            FROM `tabContact` c
            INNER JOIN `tabDynamic Link` dl ON dl.parent = c.name AND dl.parenttype = 'Contact'
            WHERE c.first_name = %s AND COALESCE(c.last_name, '') = %s
            AND dl.link_doctype = %s AND dl.link_name = %s
            LIMIT 1
        """,
            (first_name, last_name or "", parent_doctype, parent_name),
            as_dict=True,
        )
        if contact_result:
            contact_name = contact_result[0].name

    # Prepare contact data - only include fields with values
    contact_data = {}
    if first_name:
        contact_data["first_name"] = first_name
    if last_name:
        contact_data["last_name"] = last_name

    # Set primary contact flag based on IncludeInEmails
    contact_data["is_primary_contact"] = 1 if person_data.get("IncludeInEmails") else 0

    try:
        if contact_name:
            # Update existing contact
            contact = frappe.get_doc("Contact", contact_name)
            contact.update(contact_data)

            # Update email in child table if provided. Xero's EmailAddress is
            # THE address, so it becomes the only primary row — leaving an old
            # row primary alongside it makes the effective email_id ambiguous.
            if email:
                email_exists = False
                for email_row in contact.email_ids:
                    email_row.is_primary = 1 if email_row.email_id == email else 0
                    if email_row.email_id == email:
                        email_exists = True

                if not email_exists:
                    contact.append("email_ids", {"email_id": email, "is_primary": 1})

            # Update phone numbers in child table if provided
            if phones:
                for phone_data in phones:
                    phone_number = phone_data.get("PhoneNumber")
                    phone_type = phone_data.get("PhoneType", "Phone")
                    if phone_number and str(phone_number).strip():
                        # Validate phone number format before adding
                        try:
                            from frappe.utils import validate_phone_number

                            validate_phone_number(phone_number, throw=True)

                            # Check if phone already exists
                            phone_exists = False
                            for phone_row in contact.phone_nos:
                                if phone_row.phone == phone_number:
                                    phone_exists = True
                                    break

                            if not phone_exists:
                                contact.append(
                                    "phone_nos",
                                    {
                                        "phone": phone_number,
                                        "is_primary_phone": 1
                                        if phone_type == "DEFAULT"
                                        else 0,
                                        "is_primary_mobile_no": 1
                                        if phone_type == "MOBILE"
                                        else 0,
                                    },
                                )
                        except Exception:
                            # Skip invalid phone numbers but log for visibility (LO-2).
                            frappe.log_error(
                                message=f"Skipping invalid phone '{phone_number}' on Contact {contact_name} (Xero {xero_contact_id})",
                                title="Xero Sync: Invalid Phone Skipped",
                            )

            # Ensure link to parent exists
            link_exists = False
            for link in contact.links:
                if (
                    link.link_doctype == parent_doctype
                    and link.link_name == parent_name
                ):
                    link_exists = True
                    break

            if not link_exists:
                contact.append(
                    "links", {"link_doctype": parent_doctype, "link_name": parent_name}
                )

            contact.save(ignore_permissions=True)
            action = "Updated"
        else:
            # Create new contact
            contact = frappe.new_doc("Contact")
            contact.update(contact_data)

            # Add email to child table if provided
            if email:
                contact.append("email_ids", {"email_id": email, "is_primary": 1})

            # Add phone numbers to child table if provided
            if phones:
                for phone_data in phones:
                    phone_number = phone_data.get("PhoneNumber")
                    phone_type = phone_data.get("PhoneType", "Phone")
                    if phone_number and str(phone_number).strip():
                        # Validate phone number format before adding
                        try:
                            from frappe.utils import validate_phone_number

                            validate_phone_number(phone_number, throw=True)
                            contact.append(
                                "phone_nos",
                                {
                                    "phone": phone_number,
                                    "is_primary_phone": 1
                                    if phone_type == "DEFAULT"
                                    else 0,
                                    "is_primary_mobile_no": 1
                                    if phone_type == "MOBILE"
                                    else 0,
                                },
                            )
                        except Exception:
                            # Skip invalid phone numbers but log for visibility (LO-2).
                            frappe.log_error(
                                message=f"Skipping invalid phone '{phone_number}' for new Contact linked to {parent_doctype} {parent_name} (Xero {xero_contact_id})",
                                title="Xero Sync: Invalid Phone Skipped",
                            )

            # Link to parent Customer/Supplier
            contact.append(
                "links", {"link_doctype": parent_doctype, "link_name": parent_name}
            )

            contact.insert(ignore_permissions=True)
            action = "Created"

        frappe.db.commit()

        # Log success
        full_name = (
            f"{first_name or ''} {last_name or ''}".strip() or email or "Unknown"
        )
        log_xero_error(
            message=f"{action} Contact Person '{full_name}' for {parent_doctype} {parent_name} from Xero",
            status="Success",
            erpnext_doc_type="Contact",
            erpnext_doc_name=contact.name,
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            direction="Xero to ERPNext",
        )

    except Exception as e:
        # Log error for this specific contact person
        full_name = (
            f"{first_name or ''} {last_name or ''}".strip() or email or "Unknown"
        )
        log_xero_error(
            message=f"Failed to sync Contact Person '{full_name}' for {parent_doctype} {parent_name}",
            erpnext_doc_type="Contact",
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback(),
        )
        # Don't re-raise - allow other contact persons to be processed


def sync_xero_address_to_erpnext(
    address_data, parent_doctype, parent_name, xero_contact_id
):
    """
    Creates or updates an ERPNext Address from Xero Address data.
    Links the address to the parent Customer/Supplier via Dynamic Link.

    Args:
        address_data: Dictionary containing Xero Address data
        parent_doctype: "Customer" or "Supplier"
        parent_name: Name of the parent Customer/Supplier document
        xero_contact_id: Xero Contact ID (for logging purposes)
    """
    address_type = address_data.get("AddressType", "STREET")
    address_line1 = address_data.get("AddressLine1")
    address_line2 = address_data.get("AddressLine2")
    city = address_data.get("City")
    region = address_data.get("Region")
    postal_code = address_data.get("PostalCode")
    country = address_data.get("Country")

    # Skip if no meaningful address data
    if not address_line1 and not city and not postal_code:
        return

    # ERPNext Address.city is mandatory. Xero contacts (especially PO Box type)
    # often omit the city. Fall back through available fields to avoid MandatoryError.
    if not city:
        city = region or postal_code or address_line1 or "-"

    # ERPNext Address.address_line1 is also mandatory. Partial / PO-Box Xero
    # addresses can omit it; fall back so the insert doesn't MandatoryError.
    if not address_line1:
        address_line1 = city or postal_code or address_line2 or "-"

    # Map Xero AddressType to ERPNext address_type
    # STREET → Billing, POBOX → Postal
    erpnext_address_type = "Billing" if address_type == "STREET" else "Postal"

    # Try to find existing address
    # Strategy: Find by address_line1 + city linked to this customer/supplier
    address_name = None
    if address_line1 and city:
        address_result = frappe.db.sql(
            """
            SELECT a.name
            FROM `tabAddress` a
            INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name AND dl.parenttype = 'Address'
            WHERE a.address_line1 = %s AND a.city = %s
            AND dl.link_doctype = %s AND dl.link_name = %s
            LIMIT 1
        """,
            (address_line1, city, parent_doctype, parent_name),
            as_dict=True,
        )
        if address_result:
            address_name = address_result[0].name

    # Prepare address data - only include fields with values
    address_data_dict = {
        "address_type": erpnext_address_type,
    }

    if address_line1:
        address_data_dict["address_line1"] = address_line1
    if address_line2:
        address_data_dict["address_line2"] = address_line2
    if city:
        address_data_dict["city"] = city
    if region:
        address_data_dict["state"] = region
    if postal_code:
        address_data_dict["pincode"] = postal_code
    if country:
        # Xero's address "Country" field is free text and frequently holds a
        # town / region (e.g. "Caledon", "Onrus") rather than a real country,
        # which fails ERPNext's Country link validation. Use it only when it's a
        # valid Country; otherwise fall back to the company's country and never
        # block the address insert over it.
        if frappe.db.exists("Country", country):
            address_data_dict["country"] = country
        else:
            _default_country = frappe.db.get_value(
                "Company", frappe.defaults.get_global_default("company"), "country"
            )
            if _default_country:
                address_data_dict["country"] = _default_country

    # Set as primary address if it's a STREET/Billing address
    if address_type == "STREET":
        address_data_dict["is_primary_address"] = 1

    try:
        if address_name:
            # Update existing address
            address = frappe.get_doc("Address", address_name)
            address.update(address_data_dict)

            # Ensure link to parent exists
            link_exists = False
            for link in address.links:
                if (
                    link.link_doctype == parent_doctype
                    and link.link_name == parent_name
                ):
                    link_exists = True
                    break

            if not link_exists:
                address.append(
                    "links", {"link_doctype": parent_doctype, "link_name": parent_name}
                )

            address.save(ignore_permissions=True)
            action = "Updated"
        else:
            # Create new address
            address = frappe.new_doc("Address")

            # Set address title
            address.address_title = f"{parent_name} - {erpnext_address_type}"
            address.update(address_data_dict)

            # Link to parent Customer/Supplier
            address.append(
                "links", {"link_doctype": parent_doctype, "link_name": parent_name}
            )

            address.insert(ignore_permissions=True)
            action = "Created"

        frappe.db.commit()

        # Log success
        address_summary = f"{address_line1 or ''}, {city or ''}".strip(", ")
        log_xero_error(
            message=f"{action} Address '{address_summary}' ({erpnext_address_type}) for {parent_doctype} {parent_name} from Xero",
            status="Success",
            erpnext_doc_type="Address",
            erpnext_doc_name=address.name,
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            direction="Xero to ERPNext",
        )

    except Exception as e:
        # Log error for this specific address
        address_summary = f"{address_line1 or ''}, {city or ''}".strip(", ")
        log_xero_error(
            message=f"Failed to sync Address '{address_summary}' for {parent_doctype} {parent_name}",
            erpnext_doc_type="Address",
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback(),
        )
        # Don't re-raise - allow other addresses to be processed


# ---------------------------------------------------------------------------
# Xero Contact History & Notes  ->  ERPNext timeline Comments
# ---------------------------------------------------------------------------
# Xero keeps free-text notes on a contact under a SEPARATE endpoint
# (GET /Contacts/{ContactID}/History) that is NOT part of the Contact payload,
# so the normal contact sync never sees them. These helpers pull those notes and
# mirror them onto the linked ERPNext Customer/Supplier as timeline Comments.
# Because it costs one extra API call per contact, the sync is batched via a
# rolling cursor and is meant to run as a throttled scheduled job.

XERO_NOTE_MARKER = "[Xero Note"


def fetch_contact_notes(xero_contact_id):
    """Return the manual Notes for a Xero contact (history records where Changes == 'Note')."""
    from .xero_invoices import parse_xero_date

    response = xero_request("GET", f"Contacts/{xero_contact_id}/History")
    records = (response or {}).get("HistoryRecords") or []
    notes = []
    for rec in records:
        if (rec.get("Changes") or "").strip().lower() != "note":
            continue
        details = (rec.get("Details") or "").strip()
        if not details:
            continue
        note_date = parse_xero_date(rec.get("DateUTC")) or rec.get("DateUTCString") or ""
        notes.append({
            "details": details,
            "date": str(note_date).strip(),
            "user": (rec.get("User") or "").strip(),
        })
    return notes


def store_contact_notes(party_doctype, party_name, notes):
    """Write the given Xero notes onto an ERPNext party as timeline Comments, deduped."""
    added = 0
    for n in notes:
        meta = " · ".join(part for part in [n.get("date", ""), n.get("user", "")] if part)
        content = f"{XERO_NOTE_MARKER}{(' ' + meta) if meta else ''}] {n['details']}"

        # Dedupe on the exact rendered content already attached to this party so
        # re-runs never create duplicate comments.
        if frappe.db.exists("Comment", {
            "comment_type": "Comment",
            "reference_doctype": party_doctype,
            "reference_name": party_name,
            "content": content,
        }):
            continue

        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Comment",
            "reference_doctype": party_doctype,
            "reference_name": party_name,
            "content": content,
        }).insert(ignore_permissions=True)
        added += 1

    if added:
        frappe.db.commit()
    return added


def get_contact_notes_progress():
    """Return (total_linked, synced, never_synced) contact-notes coverage counts
    across Customers + Suppliers, for the dashboard and the sync job."""
    total = synced = 0
    for dt in ("Customer", "Supplier"):
        if not frappe.db.has_column(dt, "xero_notes_last_sync"):
            continue
        total += frappe.db.count(dt, {"xero_contact_id": ["is", "set"]})
        synced += frappe.db.count(
            dt, {"xero_contact_id": ["is", "set"], "xero_notes_last_sync": ["is", "set"]}
        )
    return total, synced, total - synced


@frappe.whitelist()
def sync_contact_notes_from_xero(batch_size=50, refresh_days=7, call_delay=0.4):
    """
    Mirror Xero contact History & Notes onto the linked ERPNext Customers/Suppliers
    as timeline Comments.

    Rate-limit safe by design:
      * Each contact carries a `xero_notes_last_sync` marker. Only contacts that
        have NEVER been notes-synced, or whose marker is older than `refresh_days`
        (to pick up newly added notes), are fetched. So once the initial backlog
        is drained the job idles to a trickle — it does NOT re-poll every contact
        on every run (which is what made the old cursor version burn the rate
        limit continuously).
      * At most `batch_size` contacts per run, globally oldest-marker first.
      * `call_delay` seconds between Xero calls so a single run never bursts past
        Xero's 60-calls/minute limit; xero_request's 429 back-off is the final
        safety net.

    Gated by enable_sync_from_xero + the sync_contact_notes toggle.
    """
    require_xero_manager()
    import time
    from datetime import datetime

    batch_size = frappe.utils.cint(batch_size) or 50
    refresh_days = frappe.utils.cint(refresh_days)
    try:
        call_delay = float(call_delay)
    except (TypeError, ValueError):
        call_delay = 0.4

    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.enable_sync_from_xero:
        return {"skipped": "sync disabled"}
    if not settings.get("sync_contact_notes"):
        return {"skipped": "sync_contact_notes disabled"}

    cutoff = (
        frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-refresh_days)
        if refresh_days > 0
        else None
    )

    # Collect the contacts due a notes sync (marker NULL, or older than cutoff),
    # then globally order oldest-marker-first and cap at batch_size for this run.
    candidates = []
    for dt in ("Customer", "Supplier"):
        if not frappe.db.has_column(dt, "xero_notes_last_sync"):
            continue
        if cutoff is not None:
            rows = frappe.get_all(
                dt,
                filters={"xero_contact_id": ["is", "set"]},
                or_filters=[
                    ["xero_notes_last_sync", "is", "not set"],
                    ["xero_notes_last_sync", "<", cutoff],
                ],
                fields=["name", "xero_contact_id", "xero_notes_last_sync"],
                order_by="xero_notes_last_sync asc",
                limit=batch_size,
            )
        else:
            rows = frappe.get_all(
                dt,
                filters={"xero_contact_id": ["is", "set"], "xero_notes_last_sync": ["is", "not set"]},
                fields=["name", "xero_contact_id", "xero_notes_last_sync"],
                order_by="name asc",
                limit=batch_size,
            )
        for r in rows:
            candidates.append((r.xero_notes_last_sync or datetime.min, dt, r.name, r.xero_contact_id))

    candidates.sort(key=lambda x: x[0])
    due = candidates[:batch_size]

    if not due:
        total, synced, never = get_contact_notes_progress()
        return {"processed": 0, "notes_added": 0, "never_synced_remaining": never, "synced": synced, "total": total}

    processed = 0
    notes_added = 0
    now = frappe.utils.now_datetime()
    for i, (_marker, dt, name, cid) in enumerate(due):
        try:
            notes_added += store_contact_notes(dt, name, fetch_contact_notes(cid))
            # Stamp the marker even when there were no notes, so an empty contact
            # is not re-polled until the refresh window elapses.
            frappe.db.set_value(dt, name, "xero_notes_last_sync", now, update_modified=False)
            processed += 1
        except Exception:
            log_xero_error(
                message=f"Failed to sync notes for {dt} {name} (Xero {cid})",
                status="Warning",
                erpnext_doc_type=dt,
                erpnext_doc_name=name,
                xero_entity_id=cid,
                xero_entity_type="Contact",
                direction="Xero to ERPNext",
                category="System Monitoring",
                error_details=frappe.get_traceback(),
            )
        # Pace between Xero calls to stay under the per-minute rate limit.
        if call_delay and i < len(due) - 1:
            time.sleep(call_delay)

    frappe.db.commit()
    total, synced, never = get_contact_notes_progress()

    log_xero_error(
        message=(
            f"Contact notes sync: processed {processed} contact(s), "
            f"{notes_added} new note(s) added. Coverage {synced}/{total} "
            f"({never} never-synced remaining)."
        ),
        status="Info",
        category="System Monitoring",
        direction="Xero to ERPNext",
    )
    return {
        "processed": processed,
        "notes_added": notes_added,
        "never_synced_remaining": never,
        "synced": synced,
        "total": total,
    }
