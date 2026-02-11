# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_fullname
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error # We'll create this logging utility next
from ..utils.retry_handler import retry_with_exponential_backoff

@frappe.whitelist()
def enqueue_sync_contact(doc_name, doc_type=None):
    """Enqueue background job to sync contact to Xero with one retry.
    Accepts either (doc_name, doc_type) or (doc, method) when called from Frappe hooks (doc is Customer/Supplier).
    """
    # When called from Frappe hook: (doc, method) with doc = Customer/Supplier document
    if hasattr(doc_name, "name") and hasattr(doc_name, "doctype"):
        doc = doc_name
        doc_name = doc.name
        doc_type = doc.doctype
    elif not doc_type or doc_type in ("on_update", "manual_trigger"):
        # Second arg was method name; doc_name might be a string identifier
        frappe.throw(_("enqueue_sync_contact requires (doc_name, doc_type) or a document as first argument."))
    frappe.enqueue(
        "xero.api.xero_contacts.sync_contact_to_xero",
        queue="short",
        timeout=600,
        retry=1,
        doc_name=doc_name,
        doc_type=doc_type
    )
    frappe.msgprint(_("Contact sync to Xero queued."))

@retry_with_exponential_backoff(max_retries=3, base_delay=1)
def sync_contact_to_xero(doc_name, doc_type, **kwargs):
    """
    Syncs an ERPNext Customer or Supplier to Xero Contacts.
    Uses PUT for both create and update as per Xero API recommendation.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync:
        # Log only once if master switch is off? Or not at all?
        # frappe.logger().info("Xero Sync master switch is disabled.", "Xero Info")
        return # Master switch disabled
    
    # Check directional toggle for outbound sync
    if not settings.enable_sync_to_xero:
        log_xero_error(
            message=f"Sync to Xero is disabled. Skipping {doc_type} {doc_name} outbound sync.",
            status="Info",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            category="System Monitoring"
        )
        return
    
    if not settings.sync_contacts:
        return # Contact sync specifically disabled

    try:
        doc = frappe.get_doc(doc_type, doc_name)
        xero_contact_id = doc.get("xero_contact_id")

        # --- Validate Name (required by Xero for create; recommended for update) ---
        raw_name = doc.get("customer_name") or doc.get("supplier_name")
        name = (raw_name or "").strip()
        if not name:
            log_xero_error(
                message=f"Contact sync skipped: {doc_type} name is required. Document: {doc_name}.",
                status="Warning",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                category="Validation"
            )
            frappe.db.set_value(doc_type, doc_name, {"xero_sync_status": "Error"}, update_modified=False)
            frappe.db.commit()
            return

        # --- Map ERPNext Data to Xero Contact Format ---
        primary_contact_details = get_primary_contact_details(doc_type, doc_name)

        # Build contact payload. Name is required; FirstName/LastName optional (from linked Contact or omitted for company-only).
        contact_payload = {
            "Name": name,
            "IsCustomer": True if doc_type == "Customer" else False,
            "IsSupplier": True if doc_type == "Supplier" else False,
            "ContactStatus": "ARCHIVED" if doc.get("disabled") else "ACTIVE",
        }
        # Set FirstName/LastName only when we have them from linked Contact; for company-only, omit (Name is sufficient).
        first_name = (primary_contact_details.get("first_name") or "").strip()
        last_name = (primary_contact_details.get("last_name") or "").strip()
        if first_name:
            contact_payload["FirstName"] = first_name
        if last_name:
            contact_payload["LastName"] = last_name
        if not first_name and not last_name:
            # Optional: use first word of organisation name as FirstName for display (safe: name is non-empty here).
            words = name.split()
            if words:
                contact_payload["FirstName"] = words[0]
        
        # Add EmailAddress if available from contact details
        if primary_contact_details.get("email_id") and str(primary_contact_details.get("email_id")).strip():
            contact_payload["EmailAddress"] = str(primary_contact_details.get("email_id")).strip()
        
        # Add Phones - include all phones that have values
        phones = []
        if primary_contact_details.get("phone") and str(primary_contact_details.get("phone")).strip():
            phones.append({"PhoneType": "DEFAULT", "PhoneNumber": str(primary_contact_details.get("phone")).strip()})
        if primary_contact_details.get("mobile_no") and str(primary_contact_details.get("mobile_no")).strip():
            phones.append({"PhoneType": "MOBILE", "PhoneNumber": str(primary_contact_details.get("mobile_no")).strip()})
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
        if primary_address and (primary_address.get("AddressLine1") or primary_address.get("Country")):
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
                if primary_contact_person.get("IncludeInEmails") and not primary_contact_person.get("EmailAddress"):
                    primary_contact_person.pop("IncludeInEmails", None)
                contact_payload["ContactPersons"] = [primary_contact_person]

                # If main contact has no email but ContactPerson has email, use it as main EmailAddress
                if not has_main_email and has_contact_person_email:
                    contact_payload["EmailAddress"] = primary_contact_person.get("EmailAddress")
            else:
                # No email available - skip ContactPersons to avoid Xero validation error
                # Log a warning so users know contact person data was not synced
                frappe.log_error(
                    message=f"Skipping ContactPerson data for {doc_type} '{doc_name}' - no email address available. "
                            f"Contact person ({primary_contact_person.get('FirstName', '')} {primary_contact_person.get('LastName', '')}) "
                            f"will not be synced to Xero. Add an email to the contact to include this data.",
                    title="Xero Sync: ContactPerson Skipped"
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
        # Ensure Name is always present (Xero requirement); never let clean_dict remove it.
        contact_payload["Name"] = name
        if xero_contact_id:
            contact_payload["ContactID"] = xero_contact_id

        # --- Make API Call ---
        # Xero API uses PUT for creating contacts if no ID is provided, or updating if ID is provided.
        # It can also update based on ContactNumber if provided and unique. We use ContactID for reliability.
        response = xero_request("PUT", "Contacts", data={"Contacts": [contact_payload]})

        if response and response.get("Contacts"):
            updated_contact = response["Contacts"][0]
            new_xero_contact_id = updated_contact.get("ContactID")

            # --- Update ERPNext Document ---
            if new_xero_contact_id:
                frappe.db.set_value(doc_type, doc_name, {
                    "xero_contact_id": new_xero_contact_id,
                    "xero_sync_status": "Synced"
                }, update_modified=False)
                frappe.db.commit() # Commit changes immediately

                log_xero_error(
                    message=f"Successfully synced {doc_type} {doc_name} to Xero.",
                    status="Success",
                    erpnext_doc_type=doc_type,
                    erpnext_doc_name=doc_name,
                    xero_entity_id=new_xero_contact_id,
                    xero_entity_type="Contact"
                )
            else:
                raise Exception("Xero API response did not contain a ContactID.")

        else:
             raise Exception("Invalid response received from Xero Contacts API.")

    except Exception as e:
        frappe.db.set_value(doc_type, doc_name, {"xero_sync_status": "Error"}, update_modified=False)
        frappe.db.commit()
        log_xero_error(
            message=f"Failed to sync {doc_type} {doc_name} to Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )
        # Optionally re-raise the exception if needed elsewhere
        # raise e


def sync_contacts_to_xero(filters=None, sync_type="full", **kwargs):
    """
    Batch sync: sync multiple Customers and/or Suppliers to Xero.
    Called from the Sync Dashboard for entity types Customer and Supplier.
    filters: optional Frappe filters (e.g. {"name": "..."} or {} for all).
    sync_type: "full" or optional; when "pending" only syncs docs with xero_sync_status in ("Pending", "Error") if filters allow.
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.enable_sync_to_xero or not settings.sync_contacts:
        return

    filters = filters or {}
    doc_filters = {k: v for k, v in filters.items() if k != "entity_type"}
    entity_type = filters.get("entity_type") or kwargs.get("entity_type")

    to_sync = []
    if not entity_type or entity_type == "Customer":
        if sync_type == "pending":
            doc_filters_customer = dict(doc_filters)
            doc_filters_customer["xero_sync_status"] = ["in", ["Pending", "Error"]]
            to_sync.extend([("Customer", n) for n in frappe.get_all("Customer", filters=doc_filters_customer, pluck="name")])
        else:
            to_sync.extend([("Customer", n) for n in frappe.get_all("Customer", filters=doc_filters, pluck="name")])
    if not entity_type or entity_type == "Supplier":
        if sync_type == "pending":
            doc_filters_supplier = dict(doc_filters)
            doc_filters_supplier["xero_sync_status"] = ["in", ["Pending", "Error"]]
            to_sync.extend([("Supplier", n) for n in frappe.get_all("Supplier", filters=doc_filters_supplier, pluck="name")])
        else:
            to_sync.extend([("Supplier", n) for n in frappe.get_all("Supplier", filters=doc_filters, pluck="name")])

    for doc_type, doc_name in to_sync:
        try:
            sync_contact_to_xero(doc_name, doc_type)
        except Exception as e:
            log_xero_error(
                message=f"Batch contact sync failed for {doc_type} {doc_name}: {e}",
                status="Error",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc_name,
                error_details=frappe.get_traceback()
            )


def get_primary_address(parent_doctype, parent_name):
    """Helper to get primary address details formatted for Xero."""
    # Find the primary address linked to the Customer/Supplier
    # Query using Dynamic Link child table properly
    # Prioritize by address_type (Billing), then Shipping, then any Primary
    address_result = frappe.db.sql("""
        SELECT a.name
        FROM `tabAddress` a
        INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name AND dl.parenttype = 'Address'
        WHERE dl.link_doctype = %s AND dl.link_name = %s 
        AND (a.address_type = 'Billing' OR a.is_primary_address = 1)
        ORDER BY CASE WHEN a.address_type = 'Billing' THEN 1 WHEN a.is_primary_address = 1 THEN 2 ELSE 3 END
        LIMIT 1
    """, (parent_doctype, parent_name), as_dict=True)
    
    if not address_result:
        # Fallback: get any address linked to this customer
        address_result = frappe.db.sql("""
            SELECT a.name
            FROM `tabAddress` a
            INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name AND dl.parenttype = 'Address'
            WHERE dl.link_doctype = %s AND dl.link_name = %s
            LIMIT 1
        """, (parent_doctype, parent_name), as_dict=True)

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
        "Country": address_doc.country # Ensure country name/code matches Xero's expectations if needed
    }
    # Remove None and empty string values, but keep all fields that have data
    # This allows syncing sparse addresses (e.g., just City, or just PostalCode)
    xero_address = {k: v for k, v in xero_address.items() 
                    if v is not None and str(v).strip() != ""}
    
    # Return address if it has ANY meaningful data (any field with a value)
    # This syncs all available address data while preventing completely empty objects
    if not xero_address:
        return None
    
    return xero_address

def get_primary_contact_details(parent_doctype, parent_name):
    """Helper to get primary contact person details (email, phone)."""
    # Find the primary Contact linked to the Customer/Supplier
    # Query using Dynamic Link child table properly
    contact_result = frappe.db.sql("""
        SELECT c.name
        FROM `tabContact` c
        INNER JOIN `tabDynamic Link` dl ON dl.parent = c.name AND dl.parenttype = 'Contact'
        WHERE dl.link_doctype = %s AND dl.link_name = %s AND c.is_primary_contact = 1
        LIMIT 1
    """, (parent_doctype, parent_name), as_dict=True)
    
    if not contact_result:
        return {}

    contact_doc = frappe.get_doc("Contact", contact_result[0].name)
    details = {
        "first_name": contact_doc.first_name,
        "last_name": contact_doc.last_name,
        "email_id": contact_doc.email_id,
        "phone": contact_doc.phone,
        "mobile_no": contact_doc.mobile_no
    }
    return {k: v for k, v in details.items() if v} # Return dict with non-empty values

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
        "IncludeInEmails": True # Default? Or based on ERPNext setting?
    }
    # Remove None and empty string values, but keep all fields that have data
    # This allows syncing sparse contact person data (e.g., just email, or just name)
    xero_contact_person = {k: v for k, v in xero_contact_person.items() 
                          if v is not None and str(v).strip() != ""}
    
    # Return contact person if it has ANY meaningful data (FirstName, LastName, or EmailAddress)
    # This syncs all available contact person data while preventing completely empty objects
    if not xero_contact_person:
        return None
    
    # If IncludeInEmails is True but no EmailAddress, remove IncludeInEmails
    # Xero requires EmailAddress when IncludeInEmails is True
    if xero_contact_person.get("IncludeInEmails") and not xero_contact_person.get("EmailAddress"):
        xero_contact_person.pop("IncludeInEmails", None)
    
    return xero_contact_person


def sync_contacts_from_xero():
    """
    Fetches contacts from Xero and creates/updates corresponding
    Customers/Suppliers in ERPNext.
    (Consider potential for duplicates and mapping challenges)
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return # Master switch disabled
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping contacts inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.sync_contacts: return # Contact sync specifically disabled

    try:
        page = 1
        while True:
            frappe.logger().info(f"Fetching Xero Contacts page {page}", "Xero Sync")
            response = xero_request("GET", "Contacts", params={"page": page})

            if not response or not response.get("Contacts"):
                break # No more contacts or error

            contacts = response["Contacts"]
            if not contacts:
                break # Empty page, end of contacts

            for contact in contacts:
                try:
                    process_xero_contact(contact)
                except Exception as e:
                     log_xero_error(
                        message=f"Failed to process Xero Contact ID {contact.get('ContactID')}",
                        xero_entity_id=contact.get('ContactID'),
                        xero_entity_type="Contact",
                        error_details=frappe.get_traceback()
                    )

            # Check if it was the last page (Xero doesn't explicitly tell you,
            # so we assume if we received less than 100, it's the last page,
            # or if the response was empty/invalid)
            # Xero default page size is 100
            if len(contacts) < 100:
                break
            page += 1

        log_xero_error(message="Finished syncing contacts from Xero.", status="Info")

    except Exception as e:
        log_xero_error(
            message="Error during sync_contacts_from_xero",
            error_details=frappe.get_traceback()
        )

def process_xero_contact(xero_contact_data):
    """Creates or updates an ERPNext Customer/Supplier from Xero contact data."""
    xero_contact_id = xero_contact_data.get("ContactID")
    contact_name = xero_contact_data.get("Name")

    if not xero_contact_id or not contact_name:
        log_xero_error(message=f"Skipping Xero contact due to missing ID or Name: {xero_contact_data}", status="Info")
        return

    # Determine if Customer or Supplier (Xero has IsSupplier/IsCustomer flags)
    is_customer = xero_contact_data.get("IsCustomer", False)
    is_supplier = xero_contact_data.get("IsSupplier", False)

    # Decide which ERPNext DocType(s) to create/update
    # Simple approach: Create both if flags are true? Or prioritize one?
    # Or require manual mapping/selection? For now, let's try creating based on flags.

    if is_customer:
        sync_xero_contact_to_erpnext(xero_contact_data, "Customer")
    if is_supplier:
        sync_xero_contact_to_erpnext(xero_contact_data, "Supplier")

    if not is_customer and not is_supplier:
         log_xero_error(message=f"Xero Contact {contact_name} ({xero_contact_id}) is neither Customer nor Supplier.", status="Info")


def sync_xero_contact_to_erpnext(xero_contact_data, target_doctype):
    """Syncs a single Xero contact to the specified ERPNext DocType (Customer or Supplier)."""
    xero_contact_id = xero_contact_data.get("ContactID")
    contact_name = xero_contact_data.get("Name")
    erpnext_doc_name = None
    sync_status = "Synced" # Assume success unless error occurs

    # 1. Check if ERPNext doc already exists linked by xero_contact_id
    erpnext_doc_name = frappe.db.get_value(target_doctype, {"xero_contact_id": xero_contact_id}, "name")

    # 2. If not found by ID, check by name (potential for duplicates!)
    if not erpnext_doc_name:
        field_name = "customer_name" if target_doctype == "Customer" else "supplier_name"
        erpnext_doc_name = frappe.db.get_value(target_doctype, {field_name: contact_name}, "name")
        # If found by name, update its xero_contact_id
        if erpnext_doc_name:
            frappe.db.set_value(target_doctype, erpnext_doc_name, "xero_contact_id", xero_contact_id, update_modified=False)

    # --- Map Xero Data to ERPNext Fields ---
    erpnext_data = {
        "xero_contact_id": xero_contact_id,
        "xero_sync_status": sync_status,
        "tax_id": xero_contact_data.get("TaxNumber"),
        "website": xero_contact_data.get("Website"),
    }
    
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
        erpnext_data["customer_group"] = frappe.db.get_default("customer_group") or "All Customer Groups" # Default group
        erpnext_data["territory"] = frappe.db.get_default("territory") or "All Territories" # Default territory
    else: # Supplier
        erpnext_data["supplier_name"] = contact_name
        erpnext_data["supplier_group"] = frappe.db.get_default("supplier_group") or "All Supplier Groups" # Default group

    # --- Create or Update ERPNext Document ---
    try:
        if erpnext_doc_name:
            # Update existing document
            doc = frappe.get_doc(target_doctype, erpnext_doc_name)
            doc.update(erpnext_data)
            # TODO: Update addresses and contact persons if needed
            doc.save(ignore_permissions=True) # Use ignore_permissions carefully
            log_message = f"Updated {target_doctype} {erpnext_doc_name} from Xero Contact {xero_contact_id}"
        else:
            # Create new document
            doc = frappe.new_doc(target_doctype)
            doc.update(erpnext_data)
            # TODO: Create addresses and contact persons if needed
            doc.insert(ignore_permissions=True) # Use ignore_permissions carefully
            erpnext_doc_name = doc.name
            log_message = f"Created {target_doctype} {erpnext_doc_name} from Xero Contact {xero_contact_id}"

        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type=target_doctype,
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            direction="Xero to ERPNext"
        )
        
        # --- Sync Contact Persons (NEW IMPLEMENTATION) ---
        # After successfully creating/updating the Customer/Supplier, sync contact persons
        
        # First, sync the primary contact (FirstName, EmailAddress, Phones on the Contact itself)
        # Xero stores primary contact info directly on the Contact object
        primary_first_name = xero_contact_data.get("FirstName")
        primary_email = xero_contact_data.get("EmailAddress")
        primary_phones = xero_contact_data.get("Phones", [])
        
        if primary_first_name or primary_email:
            # Create a pseudo ContactPerson dict from primary contact fields
            primary_person_data = {}
            if primary_first_name:
                primary_person_data["FirstName"] = primary_first_name
            if primary_email:
                primary_person_data["EmailAddress"] = primary_email
            if primary_phones:
                primary_person_data["Phones"] = primary_phones
            primary_person_data["IncludeInEmails"] = True  # Primary contact should be included
            
            try:
                sync_contact_person_to_erpnext(primary_person_data, target_doctype, erpnext_doc_name, xero_contact_id)
            except Exception as person_error:
                # Log error but continue
                log_xero_error(
                    message=f"Failed to sync primary contact for {target_doctype} {erpnext_doc_name}",
                    erpnext_doc_type="Contact",
                    xero_entity_id=xero_contact_id,
                    error_details=str(person_error)
                )
        
        # Then, sync additional contact persons from ContactPersons array
        contact_persons = xero_contact_data.get("ContactPersons", [])
        if contact_persons:
            for person in contact_persons:
                try:
                    sync_contact_person_to_erpnext(person, target_doctype, erpnext_doc_name, xero_contact_id)
                except Exception as person_error:
                    # Log error but continue with other contact persons
                    log_xero_error(
                        message=f"Failed to sync ContactPerson for {target_doctype} {erpnext_doc_name}",
                        erpnext_doc_type="Contact",
                        xero_entity_id=xero_contact_id,
                        error_details=str(person_error)
                    )
        
        # --- Sync Addresses (NEW IMPLEMENTATION) ---
        # Sync addresses from Xero to ERPNext Address DocType
        addresses = xero_contact_data.get("Addresses", [])
        if addresses:
            for address_data in addresses:
                try:
                    sync_xero_address_to_erpnext(address_data, target_doctype, erpnext_doc_name, xero_contact_id)
                except Exception as address_error:
                    # Log error but continue with other addresses
                    log_xero_error(
                        message=f"Failed to sync Address for {target_doctype} {erpnext_doc_name}",
                        erpnext_doc_type="Address",
                        xero_entity_id=xero_contact_id,
                        error_details=str(address_error)
                    )

    except Exception as e:
        # Log error, but don't stop processing other contacts
        sync_status = "Error"
        if erpnext_doc_name: # If update failed after finding doc
             frappe.db.set_value(target_doctype, erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
             frappe.db.commit()

        log_xero_error(
            message=f"Failed to sync Xero Contact {xero_contact_id} to ERPNext {target_doctype}",
            erpnext_doc_type=target_doctype,
            erpnext_doc_name=erpnext_doc_name, # Might be None if creation failed early
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )


def sync_contact_person_to_erpnext(person_data, parent_doctype, parent_name, xero_contact_id):
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
    
    # Strategy 1: Find by email if available (most reliable unique identifier)
    if email:
        contact_name = frappe.db.get_value("Contact", {"email_id": email}, "name")
    
    # Strategy 2: Find by name linked to this specific customer/supplier
    if not contact_name and first_name and last_name:
        contact_result = frappe.db.sql("""
            SELECT c.name
            FROM `tabContact` c
            INNER JOIN `tabDynamic Link` dl ON dl.parent = c.name AND dl.parenttype = 'Contact'
            WHERE c.first_name = %s AND c.last_name = %s
            AND dl.link_doctype = %s AND dl.link_name = %s
            LIMIT 1
        """, (first_name, last_name, parent_doctype, parent_name), as_dict=True)
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
            
            # Update email in child table if provided
            if email:
                # Check if email already exists in email_ids child table
                email_exists = False
                for email_row in contact.email_ids:
                    if email_row.email_id == email:
                        email_exists = True
                        email_row.is_primary = 1
                        break
                
                if not email_exists:
                    # Add new email to child table
                    contact.append("email_ids", {
                        "email_id": email,
                        "is_primary": 1
                    })
            
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
                                contact.append("phone_nos", {
                                    "phone": phone_number,
                                    "is_primary_phone": 1 if phone_type == "DEFAULT" else 0,
                                    "is_primary_mobile_no": 1 if phone_type == "MOBILE" else 0
                                })
                        except:
                            # Skip invalid phone numbers silently
                            pass
            
            # Ensure link to parent exists
            link_exists = False
            for link in contact.links:
                if link.link_doctype == parent_doctype and link.link_name == parent_name:
                    link_exists = True
                    break
            
            if not link_exists:
                contact.append("links", {
                    "link_doctype": parent_doctype,
                    "link_name": parent_name
                })
            
            contact.save(ignore_permissions=True)
            action = "Updated"
        else:
            # Create new contact
            contact = frappe.new_doc("Contact")
            contact.update(contact_data)
            
            # Add email to child table if provided
            if email:
                contact.append("email_ids", {
                    "email_id": email,
                    "is_primary": 1
                })
            
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
                            contact.append("phone_nos", {
                                "phone": phone_number,
                                "is_primary_phone": 1 if phone_type == "DEFAULT" else 0,
                                "is_primary_mobile_no": 1 if phone_type == "MOBILE" else 0
                            })
                        except:
                            # Skip invalid phone numbers
                            pass
            
            # Link to parent Customer/Supplier
            contact.append("links", {
                "link_doctype": parent_doctype,
                "link_name": parent_name
            })
            
            contact.insert(ignore_permissions=True)
            action = "Created"
        
        frappe.db.commit()
        
        # Log success
        full_name = f"{first_name or ''} {last_name or ''}".strip() or email or "Unknown"
        log_xero_error(
            message=f"{action} Contact Person '{full_name}' for {parent_doctype} {parent_name} from Xero",
            status="Success",
            erpnext_doc_type="Contact",
            erpnext_doc_name=contact.name,
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            direction="Xero to ERPNext"
        )
        
    except Exception as e:
        # Log error for this specific contact person
        full_name = f"{first_name or ''} {last_name or ''}".strip() or email or "Unknown"
        log_xero_error(
            message=f"Failed to sync Contact Person '{full_name}' for {parent_doctype} {parent_name}",
            erpnext_doc_type="Contact",
            xero_entity_id=xero_contact_id,
            xero_entity_type="Contact",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )
        # Don't re-raise - allow other contact persons to be processed


def sync_xero_address_to_erpnext(address_data, parent_doctype, parent_name, xero_contact_id):
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
    
    # Map Xero AddressType to ERPNext address_type
    # STREET → Billing, POBOX → Postal
    erpnext_address_type = "Billing" if address_type == "STREET" else "Postal"
    
    # Try to find existing address
    # Strategy: Find by address_line1 + city linked to this customer/supplier
    address_name = None
    if address_line1 and city:
        address_result = frappe.db.sql("""
            SELECT a.name
            FROM `tabAddress` a
            INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name AND dl.parenttype = 'Address'
            WHERE a.address_line1 = %s AND a.city = %s
            AND dl.link_doctype = %s AND dl.link_name = %s
            LIMIT 1
        """, (address_line1, city, parent_doctype, parent_name), as_dict=True)
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
        address_data_dict["country"] = country
    
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
                if link.link_doctype == parent_doctype and link.link_name == parent_name:
                    link_exists = True
                    break
            
            if not link_exists:
                address.append("links", {
                    "link_doctype": parent_doctype,
                    "link_name": parent_name
                })
            
            address.save(ignore_permissions=True)
            action = "Updated"
        else:
            # Create new address
            address = frappe.new_doc("Address")
            
            # Set address title
            address.address_title = f"{parent_name} - {erpnext_address_type}"
            address.update(address_data_dict)
            
            # Link to parent Customer/Supplier
            address.append("links", {
                "link_doctype": parent_doctype,
                "link_name": parent_name
            })
            
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
            direction="Xero to ERPNext"
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
            error_details=frappe.get_traceback()
        )
        # Don't re-raise - allow other addresses to be processed
