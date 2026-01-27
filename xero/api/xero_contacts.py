# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_fullname
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error # We'll create this logging utility next
from ..utils.retry_handler import retry_with_exponential_backoff

@frappe.whitelist()
def enqueue_sync_contact(doc_name, doc_type):
    """Enqueue background job to sync contact to Xero with one retry."""
    frappe.enqueue(
        "xero.api.xero_contacts.sync_contact_to_xero",
        queue="short",
        timeout=600, # 10 minutes timeout
        retry=1, # Retry once on failure
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

        # --- Map ERPNext Data to Xero Contact Format ---
        # --- Map ERPNext Data to Xero Contact Format ---
        # Fetch primary contact email/phone if available
        primary_contact_details = get_primary_contact_details(doc_type, doc_name)

        # Build contact payload - include ALL available data from ERPNext
        # Sync everything that exists, even if sparse with empty fields
        contact_payload = {
            "Name": doc.get("customer_name") or doc.get("supplier_name"),
            "FirstName": (doc.get("customer_name") or doc.get("supplier_name")).split()[0],
            # Set flags based on doctype
            "IsCustomer": True if doc_type == "Customer" else False,
            "IsSupplier": True if doc_type == "Supplier" else False,
        }
        
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

        # Add primary address if available (even if partial)
        primary_address = get_primary_address(doc_type, doc_name)
        if primary_address:
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
                # We have an email somewhere - safe to add ContactPersons
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
        # TODO: Map addresses, phones, contact persons back to ERPNext
        # This is complex: requires creating/updating linked Address/Contact docs.
        # For now, only mapping basic fields.
    }
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

# TODO: Implement Address and Contact Person syncing logic within sync_xero_contact_to_erpnext
