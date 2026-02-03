# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from ..utils.xero_client import xero_request, get_xero_settings
from ..utils.logging import log_xero_error
from frappe.utils import getdate

@frappe.whitelist()
def enqueue_sync_sales_order(doc, method):
    """Enqueue background job to sync a Sales Order to Xero."""
    settings = get_xero_settings()
    if not settings.enable_xero_sync or not settings.get("sync_sales_orders"): # Assume a new setting
        return

    frappe.enqueue(
        "xero.api.xero_sales_orders.sync_sales_order_to_xero",
        queue="short",
        doc_name=doc.name,
        doc_type=doc.doctype
    )
    frappe.logger().info(f"Queued sync for {doc.doctype} {doc.name} to Xero.", "Xero Sync")


def sync_sales_order_to_xero(doc_name, doc_type):
    """
    Syncs a submitted ERPNext Sales Order to Xero as a Sales Order.
    Ref: https://developer.xero.com/documentation/api/accounting/purchaseorders
    Note: Xero uses the same endpoint for Sales Orders and Purchase Orders.
    """
    try:
        doc = frappe.get_doc(doc_type, doc_name)
        settings = get_xero_settings()
        
        if not settings.enable_xero_sync:
            return
        
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
        
        if not settings.get("sync_sales_orders"):
            return
        
        xero_so_id = doc.get("xero_sales_order_id")

        if doc.docstatus != 1:
            return

        # 1. Get Xero Contact ID
        xero_contact_id = frappe.db.get_value("Customer", doc.customer, "xero_contact_id")
        if not xero_contact_id:
            raise Exception(f"Xero Contact ID not found for Customer: {doc.customer}.")

        # 2. Map Line Items
        line_items = []
        for item in doc.items:
            line_items.append({
                "Description": item.description,
                "Quantity": item.qty,
                "UnitAmount": item.rate,
                "ItemCode": item.item_code,
                "LineAmount": item.amount,
            })

        # 3. Construct Sales Order Payload
        so_payload = {
            "Contact": { "ContactID": xero_contact_id },
            "Date": getdate(doc.transaction_date).isoformat(),
            "DeliveryDate": getdate(doc.delivery_date).isoformat() if doc.delivery_date else None,
            "LineItems": line_items,
            "OrderNumber": doc.name,
            "Status": "DRAFT", # Start as Draft in Xero, can be approved there
        }

        if xero_so_id:
            so_payload["PurchaseOrderID"] = xero_so_id

        # 4. Make API Call (Xero uses PurchaseOrders endpoint for Sales Orders)
        response = xero_request("PUT", "PurchaseOrders", data={"PurchaseOrders": [so_payload]})

        # 5. Process response
        if response and response.get("PurchaseOrders"):
            new_xero_id = response["PurchaseOrders"][0].get("PurchaseOrderID")
            frappe.db.set_value(doc_type, doc_name, "xero_sales_order_id", new_xero_id, update_modified=False)
            frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Synced", update_modified=False)
            frappe.db.commit()
            log_xero_error(
                message=f"Successfully synced {doc_type} {doc.name} to Xero.",
                status="Success",
                erpnext_doc_type=doc_type,
                erpnext_doc_name=doc.name,
                xero_entity_id=new_xero_id,
                xero_entity_type="SalesOrder"
            )
        else:
            raise Exception("Invalid response from Xero PurchaseOrders API.")

    except Exception as e:
        frappe.db.set_value(doc_type, doc_name, "xero_sync_status", "Error", update_modified=False)
        frappe.db.commit()
        log_xero_error(
            message=f"Failed to sync {doc_type} {doc_name} to Xero.",
            erpnext_doc_type=doc_type,
            erpnext_doc_name=doc_name,
            error_details=frappe.get_traceback()
        )


# --- Sales Order Sync (Xero to ERPNext) ---

def sync_sales_orders_from_xero(modified_since=None):
    """
    Fetches sales orders from Xero and creates/updates corresponding
    Sales Orders in ERPNext.
    
    Args:
        modified_since: ISO date string to fetch only recent orders
    """
    settings = get_xero_settings()
    if not settings.enable_xero_sync: return
    
    # Check directional toggle for inbound sync
    if not settings.enable_sync_from_xero:
        log_xero_error(
            message="Sync from Xero is disabled. Skipping sales orders inbound sync.",
            status="Info",
            category="System Monitoring"
        )
        return
    
    if not settings.get("sync_sales_orders"): return
    
    try:
        page = 1
        params = {"page": page}
        
        if modified_since:
            params["ModifiedSince"] = modified_since
        
        while True:
            frappe.logger().info(f"Fetching Xero Sales Orders page {page}", "Xero Sync")
            response = xero_request("GET", "PurchaseOrders", params=params)
            
            if not response or not response.get("PurchaseOrders"):
                break
            
            orders = response["PurchaseOrders"]
            if not orders:
                break
            
            # Filter for sales orders only (Xero uses same endpoint for both)
            for order_data in orders:
                try:
                    # Check if this is a sales order (has customer contact)
                    contact_id = order_data.get("Contact", {}).get("ContactID")
                    if contact_id:
                        # Check if contact is a customer
                        is_customer = frappe.db.exists("Customer", {"xero_contact_id": contact_id})
                        if is_customer:
                            process_xero_sales_order(order_data, settings)
                except Exception as e:
                    log_xero_error(
                        message=f"Failed to process Xero Sales Order ID {order_data.get('PurchaseOrderID')}",
                        xero_entity_id=order_data.get('PurchaseOrderID'),
                        xero_entity_type="SalesOrder",
                        error_details=frappe.get_traceback()
                    )
            
            if len(orders) < 100:
                break
            page += 1
            params["page"] = page
        
        log_xero_error(message="Finished syncing sales orders from Xero.", status="Info")
    
    except Exception as e:
        log_xero_error(
            message="Error during sync_sales_orders_from_xero",
            error_details=frappe.get_traceback()
        )


def process_xero_sales_order(xero_order_data, settings):
    """Creates or updates an ERPNext Sales Order from Xero order data."""
    from .xero_invoices import parse_xero_date, get_or_create_item_from_xero_code
    
    xero_order_id = xero_order_data.get("PurchaseOrderID")  # Xero uses PurchaseOrderID for both
    order_number = xero_order_data.get("PurchaseOrderNumber")
    
    if not xero_order_id:
        log_xero_error(message=f"Skipping Xero order due to missing ID", status="Info")
        return
    
    # Check if order already exists
    erpnext_doc_name = frappe.db.get_value("Sales Order", {"xero_sales_order_id": xero_order_id}, "name")
    
    # Get contact information
    xero_contact_id = xero_order_data.get("Contact", {}).get("ContactID")
    if not xero_contact_id:
        log_xero_error(message=f"Skipping Xero order {order_number}: No contact information", status="Info")
        return
    
    # Find corresponding ERPNext customer
    customer_name = frappe.db.get_value("Customer", {"xero_contact_id": xero_contact_id}, "name")
    
    if not customer_name:
        log_xero_error(
            message=f"Skipping Xero order {order_number}: Customer not found for Xero Contact {xero_contact_id}",
            status="Info",
            xero_entity_id=xero_order_id,
            xero_entity_type="SalesOrder"
        )
        return
    
    try:
        # Get company
        company = frappe.defaults.get_global_default("company")
        if not company:
            company = frappe.get_all("Company", limit=1, pluck="name")[0]
        
        # Map header fields
        erpnext_data = {
            "xero_sales_order_id": xero_order_id,
            "xero_sync_status": "Synced",
            "customer": customer_name,
            "customer_name": xero_order_data.get("Contact", {}).get("Name"),
            "company": company,
            "transaction_date": parse_xero_date(xero_order_data.get("Date")),
            "delivery_date": parse_xero_date(xero_order_data.get("DeliveryDate")),
            "currency": xero_order_data.get("CurrencyCode", "USD"),
            "conversion_rate": frappe.utils.flt(xero_order_data.get("CurrencyRate", 1.0)),
        }
        
        # Store Xero order number in remarks
        if order_number:
            erpnext_data["remarks"] = f"Xero Order: {order_number}"
        
        # Create or update order
        if erpnext_doc_name:
            # Update existing
            doc = frappe.get_doc("Sales Order", erpnext_doc_name)
            doc.update(erpnext_data)
            doc.save(ignore_permissions=True)
            log_message = f"Updated Sales Order {erpnext_doc_name} from Xero Order {xero_order_id}"
        else:
            # Create new
            doc = frappe.new_doc("Sales Order")
            doc.update(erpnext_data)
            
            # Add line items
            line_items = xero_order_data.get("LineItems", [])
            for line in line_items:
                item_code = get_or_create_item_from_xero_code(line.get("ItemCode"), line.get("Description"), settings)
                
                item_dict = {
                    "description": line.get("Description", "Item from Xero"),
                    "qty": frappe.utils.flt(line.get("Quantity", 1)),
                    "rate": frappe.utils.flt(line.get("UnitAmount", 0)),
                    "amount": frappe.utils.flt(line.get("LineAmount", 0)),
                }
                
                if item_code:
                    item_dict["item_code"] = item_code
                    item_dict["item_name"] = line.get("Description")
                else:
                    item_dict["item_name"] = line.get("Description", "Xero Item")
                
                doc.append("items", item_dict)
            
            if not doc.items:
                log_xero_error(
                    message=f"Skipping Xero order {order_number}: No line items",
                    status="Warning",
                    xero_entity_id=xero_order_id,
                    xero_entity_type="SalesOrder"
                )
                return
            
            doc.insert(ignore_permissions=True)
            erpnext_doc_name = doc.name
            log_message = f"Created Sales Order {erpnext_doc_name} from Xero Order {xero_order_id} ({order_number})"
        
        frappe.db.commit()
        log_xero_error(
            message=log_message,
            status="Success",
            erpnext_doc_type="Sales Order",
            erpnext_doc_name=erpnext_doc_name,
            xero_entity_id=xero_order_id,
            xero_entity_type="SalesOrder",
            direction="Xero to ERPNext"
        )
    
    except Exception as e:
        sync_status = "Error"
        if erpnext_doc_name:
            frappe.db.set_value("Sales Order", erpnext_doc_name, "xero_sync_status", sync_status, update_modified=False)
            frappe.db.commit()
        
        log_xero_error(
            message=f"Failed to sync Xero Sales Order {xero_order_id} ({order_number}) to ERPNext",
            erpnext_doc_type="Sales Order",
            erpnext_doc_name=erpnext_doc_name if 'erpnext_doc_name' in locals() else None,
            xero_entity_id=xero_order_id,
            xero_entity_type="SalesOrder",
            direction="Xero to ERPNext",
            error_details=frappe.get_traceback()
        )