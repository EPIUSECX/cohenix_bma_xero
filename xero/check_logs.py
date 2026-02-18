"""Check recent Xero logs for errors."""

def check_logs():
    import frappe
    logs = frappe.get_all("Xero Log", fields=["name", "message", "error_details", "creation"], order_by="creation desc", limit=5)
    for log in logs:
        print(f"\n--- Log: {log.name} ({log.creation}) ---")
        print(f"Message: {log.message[:300] if log.message else None}")
        if log.error_details:
            print(f"Error: {log.error_details[:800]}")
