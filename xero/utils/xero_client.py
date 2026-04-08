# Copyright (c) 2024, Your Name and contributors
# For license information, please see license.txt

import frappe
import requests
from frappe.utils import get_site_url, now_datetime, add_to_date
from json import dumps, loads
from urllib.parse import urlencode

XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"
XERO_API_BASE_URL = "https://api.xero.com/api.xro/2.0"


def get_xero_settings():
    """Returns the Xero Settings document."""
    # Consider multi-company scenarios if applicable
    return frappe.get_single("Xero Settings")


def get_redirect_uri():
    """Returns the OAuth2 redirect URI from settings or default."""
    settings = get_xero_settings()
    if settings.redirect_url:
        return settings.redirect_url
    # Fallback to default if not configured
    return f"{get_site_url(frappe.local.site)}/api/method/xero.utils.xero_client.handle_oauth_callback"


@frappe.whitelist()
def get_auth_url():
    """Generates the Xero authorization URL."""
    settings = get_xero_settings()
    if not settings.client_id:
        frappe.throw("Xero Client ID not set in Xero Settings.")

    state_token = frappe.generate_hash(length=20)
    # Encode the current user into the state so the guest callback can retrieve it
    state = f"{frappe.session.user}:{state_token}"
    # Store state token in cache keyed by user for CSRF verification
    frappe.cache().hset("xero_oauth_state", frappe.session.user, state_token)

    params = {
        "response_type": "code",
        "client_id": settings.client_id,
        "redirect_uri": get_redirect_uri(),
        "scope": "openid profile email accounting.transactions accounting.contacts accounting.settings offline_access",
        "state": state,
    }
    return f"{XERO_AUTH_URL}?{urlencode(params)}"


@frappe.whitelist(allow_guest=True)
def handle_oauth_callback(code=None, state=None, error=None):
    """Handles the OAuth2 callback from Xero."""
    if error:
        frappe.throw(f"Xero OAuth Error: {error}")

    # State is encoded as "{user}:{token}" so the guest callback can resolve the initiating user
    if not state or ":" not in state:
        frappe.throw("Invalid OAuth state. Please try connecting again.")
    initiating_user, state_token = state.split(":", 1)
    cached_state = frappe.cache().hget("xero_oauth_state", initiating_user)
    if not cached_state or state_token != cached_state:
        frappe.throw("Invalid OAuth state. Please try connecting again.")
    # Clear the used state token to prevent replay attacks
    frappe.cache().hdel("xero_oauth_state", initiating_user)

    if not code:
        frappe.throw("Missing authorization code from Xero.")

    try:
        settings = get_xero_settings()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "authorization_code",
            "client_id": settings.client_id,
            "client_secret": settings.get_password("client_secret"),
            "code": code,
            "redirect_uri": get_redirect_uri(),
        }

        response = requests.post(XERO_TOKEN_URL, headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()

        # Get Tenant ID
        tenant_id = get_tenant_id(token_data["access_token"])

        # Save tokens and tenant ID
        settings.access_token = token_data["access_token"]
        settings.refresh_token = token_data["refresh_token"]
        settings.token_expiry = add_to_date(
            now_datetime(), seconds=token_data["expires_in"]
        )
        settings.tenant_id = tenant_id
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = (
            "/app/xero-settings"  # Redirect back to settings page
        )
        frappe.msgprint("Xero connection successful!")

    except requests.exceptions.RequestException as e:
        frappe.log_error(f"Xero OAuth Token Request Failed: {e}", "Xero Auth Error")
        frappe.throw("Failed to get access token from Xero.")
    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback(), title="Xero OAuth Callback Error"
        )
        frappe.throw("An error occurred during Xero authentication.")


def get_tenant_id(access_token):
    """Fetches the Tenant ID from Xero Connections API."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(XERO_CONNECTIONS_URL, headers=headers)
        response.raise_for_status()
        connections = response.json()
        if connections and len(connections) > 0:
            # Assuming the first tenant is the one we want
            return connections[0]["tenantId"]
        else:
            frappe.throw("No Xero tenants found for this connection.")
    except requests.exceptions.RequestException as e:
        frappe.log_error(f"Xero Get Tenant ID Failed: {e}", "Xero API Error")
        frappe.throw("Failed to retrieve Tenant ID from Xero.")


def refresh_access_token():
    """Refreshes the Xero access token using the refresh token with retry logic."""
    import time
    from ..utils.logging import log_xero_error

    settings = get_xero_settings()
    if not settings.refresh_token:
        notify_admins_token_failure("No refresh token found")
        frappe.throw("Xero Refresh Token not found. Please re-authenticate.")

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "client_id": settings.client_id,
        "client_secret": settings.get_password("client_secret"),
        "refresh_token": settings.refresh_token,
    }

    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            response = requests.post(
                XERO_TOKEN_URL, headers=headers, data=data, timeout=30
            )
            response.raise_for_status()
            token_data = response.json()

            settings.access_token = token_data["access_token"]
            settings.refresh_token = token_data[
                "refresh_token"
            ]  # Xero might issue a new refresh token
            settings.token_expiry = add_to_date(
                now_datetime(), seconds=token_data["expires_in"]
            )
            settings.last_token_refresh = now_datetime()
            settings.save(ignore_permissions=True)
            frappe.db.commit()

            log_xero_error(
                message="Xero access token refreshed successfully",
                status="Success",
                category="Authentication Issues",
            )

            return settings.access_token

        except requests.exceptions.RequestException as e:
            retry_count += 1
            error_msg = str(e)

            # Check if it's a permanent failure (invalid refresh token)
            if hasattr(e, "response") and e.response is not None:
                if e.response.status_code in [400, 401]:
                    # Invalid refresh token - notify and invalidate
                    log_xero_error(
                        message=f"Token refresh failed permanently: {error_msg}",
                        status="Error",
                        category="Authentication Issues",
                        error_details=frappe.get_traceback(),
                        retry_count=retry_count,
                    )

                    settings.refresh_token = None
                    settings.access_token = None
                    settings.save(ignore_permissions=True)
                    frappe.db.commit()

                    notify_admins_token_failure(
                        "Invalid refresh token - re-authentication required"
                    )
                    frappe.throw(
                        "Xero refresh token is invalid. Please re-authenticate in Xero Settings."
                    )

            if retry_count >= max_retries:
                # Final failure after all retries
                log_xero_error(
                    message=f"Token refresh failed after {max_retries} attempts: {error_msg}",
                    status="Error",
                    category="Authentication Issues",
                    error_details=frappe.get_traceback(),
                    retry_count=retry_count,
                )
                notify_admins_token_failure(
                    f"Token refresh failed after {max_retries} attempts"
                )
                frappe.throw(
                    "Failed to refresh Xero access token after multiple attempts. Please check Xero Settings."
                )

            # Wait before retry (exponential backoff)
            wait_time = 2**retry_count
            log_xero_error(
                message=f"Token refresh failed (attempt {retry_count}/{max_retries}), retrying in {wait_time}s",
                status="Warning",
                category="Authentication Issues",
                retry_count=retry_count,
            )
            time.sleep(wait_time)


def notify_admins_token_failure(reason):
    """Send notification to system managers about token refresh failure."""
    try:
        # Get all users with System Manager role
        system_managers = frappe.get_all(
            "Has Role",
            filters={"role": "System Manager", "parenttype": "User"},
            fields=["parent"],
        )

        if system_managers:
            recipients = [sm.parent for sm in system_managers]

            # Send email notification
            frappe.sendmail(
                recipients=recipients,
                subject="Xero Integration: Token Refresh Failed",
                message=f"""
                    <p>The Xero integration token refresh has failed.</p>
                    <p><strong>Reason:</strong> {reason}</p>
                    <p>Please log in to ERPNext and re-authenticate with Xero in the Xero Settings page.</p>
                    <p>Until this is resolved, Xero synchronization will not function.</p>
                """,
                delayed=False,
            )

            # Also create a notification in the system
            for user in recipients[:5]:  # Limit to first 5 to avoid spam
                try:
                    notification = frappe.get_doc(
                        {
                            "doctype": "Notification Log",
                            "subject": "Xero Token Refresh Failed",
                            "for_user": user,
                            "type": "Alert",
                            "document_type": "Xero Settings",
                            "document_name": "Xero Settings",
                            "email_content": f"Xero token refresh failed: {reason}. Please re-authenticate.",
                        }
                    )
                    notification.insert(ignore_permissions=True)
                except Exception:
                    pass  # Don't fail if notification creation fails

    except Exception as e:
        frappe.log_error(
            f"Failed to notify admins about token failure: {str(e)}",
            "Xero Notification Error",
        )


def get_xero_client():
    """
    Initializes and returns a configured Xero API client (using requests).
    Handles token expiry and refresh.
    """
    settings = get_xero_settings()
    if not settings.access_token or not settings.tenant_id:
        frappe.throw(
            "Xero connection not configured or access token missing. Please connect in Xero Settings."
        )

    # Check if token is expired or close to expiring (e.g., within 5 minutes)
    from frappe.utils import get_datetime

    token_expiry_dt = (
        get_datetime(settings.token_expiry) if settings.token_expiry else None
    )

    if not token_expiry_dt or now_datetime() >= add_to_date(
        token_expiry_dt, minutes=-5
    ):
        access_token = refresh_access_token()
    else:
        access_token = settings.access_token

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Xero-Tenant-Id": settings.tenant_id,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return headers  # Return headers for direct requests usage


# --- Wrapper functions for API calls ---


def xero_request(method, endpoint, data=None, params=None):
    """Makes a request to the Xero API, handling authentication and errors."""
    import time

    settings = get_xero_settings()
    headers = get_xero_client()  # Gets headers with valid token
    url = f"{XERO_API_BASE_URL}/{endpoint}"

    # Get configurable settings
    max_retries = getattr(settings, "max_retry_attempts", 5)
    api_timeout = getattr(settings, "api_timeout", 30)
    backoff_base = getattr(settings, "rate_limit_backoff_base", 2)
    max_delay = getattr(settings, "rate_limit_max_delay", 60)
    track_rate_limits = getattr(settings, "enable_rate_limit_tracking", True)

    retry_count = 0
    response = None
    start_time = time.time()

    while retry_count < max_retries:
        try:
            if method.upper() == "GET":
                response = requests.get(
                    url, headers=headers, params=params, timeout=api_timeout
                )
            elif method.upper() == "POST":
                response = requests.post(
                    url,
                    headers=headers,
                    data=dumps(data) if data else None,
                    params=params,
                    timeout=api_timeout,
                )
            elif method.upper() == "PUT":
                response = requests.put(
                    url,
                    headers=headers,
                    data=dumps(data) if data else None,
                    params=params,
                    timeout=api_timeout,
                )
            else:
                frappe.throw(f"Unsupported HTTP method: {method}")

            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

            # Track successful API call timing
            processing_time = time.time() - start_time
            if track_rate_limits:
                from ..utils.logging import log_xero_error

                log_xero_error(
                    message=f"Successful API call: {method} {endpoint}",
                    status="Info",
                    category="System Monitoring",
                    processing_time=processing_time,
                )

            # Handle potential empty response body for certain successful calls (e.g., 204 No Content)
            if response.status_code == 204:
                return None
            return response.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limit error
                retry_count += 1

                # Extract rate limit headers if available
                rate_limit_remaining = e.response.headers.get(
                    "X-Rate-Limit-Remaining", "unknown"
                )
                rate_limit_reset = e.response.headers.get(
                    "X-Rate-Limit-Reset", "unknown"
                )

                if track_rate_limits:
                    from ..utils.logging import log_xero_error

                    log_xero_error(
                        message=f"Rate limit hit on {method} {endpoint}. Remaining: {rate_limit_remaining}, Reset: {rate_limit_reset}",
                        status="Warning",
                        category="Rate Limiting",
                        retry_count=retry_count,
                    )

                if retry_count >= max_retries:
                    # Log final failure and re-raise
                    frappe.log_error(
                        f"Xero API rate limit exceeded after {max_retries} retries. Remaining: {rate_limit_remaining}",
                        "Xero API Error",
                    )
                    raise e

                # Exponential backoff with configurable base and max delay
                wait_time = min(backoff_base**retry_count, max_delay)
                frappe.log_warning(
                    f"Xero rate limit hit. Retrying in {wait_time} seconds... (Attempt {retry_count}/{max_retries})",
                    "Xero API Error",
                )
                time.sleep(wait_time)
            else:
                # For other HTTP errors, log details and re-raise
                error_details = ""
                try:
                    error_data = e.response.json()
                    error_details = dumps(error_data, indent=2)
                except Exception:
                    error_details = e.response.text or ""

                # Log to frappe error log
                frappe.log_error(
                    message=f"Xero API Error ({e.response.status_code}) on {method} {url}:\n{error_details}",
                    title="Xero API Error",
                )

                # Also log to Xero Log for visibility in the dashboard
                from ..utils.logging import log_xero_error

                log_xero_error(
                    message=f"Xero API Error ({e.response.status_code}) on {method} {endpoint}: {error_details[:500]}",
                    status="Error",
                    category="Validation Errors",
                    error_details=error_details,
                )

                # Include response body in the thrown error so callers can see it
                frappe.throw(
                    f"Xero API request failed: {e.response.reason} ({e.response.status_code})\nDetails: {error_details[:1000]}"
                )

        except requests.exceptions.RequestException as e:
            # Network errors, timeouts, etc.
            frappe.log_error(
                message=f"Xero Network Error on {method} {url}: {e}",
                title="Xero Network Error",
            )
            frappe.throw(f"Network error communicating with Xero: {e}")

        except Exception as e:
            frappe.log_error(
                message=frappe.get_traceback(), title="Xero Client Unexpected Error"
            )
            frappe.throw("An unexpected error occurred in the Xero client.")

    # This part should not be reached if the loop completes, but as a fallback:
    frappe.throw("Failed to get a valid response from Xero after multiple retries.")


def check_xero_entity_exists(entity_type, entity_id):
    """
    Check if an entity exists in Xero by its ID.

    :param entity_type: Type of entity (e.g., 'Invoices', 'Contacts', 'Items')
    :param entity_id: Xero entity ID (GUID)
    :return: Boolean indicating if entity exists
    """
    try:
        # Try to get the entity from Xero
        response = xero_request("GET", f"{entity_type}/{entity_id}")
        return response is not None
    except Exception as e:
        # If 404 or other error, entity doesn't exist
        error_str = str(e).lower()
        if "404" in error_str or "not found" in error_str:
            return False
        # For other errors, log but assume it might exist (cautious approach)
        frappe.log_error(
            f"Error checking if {entity_type} {entity_id} exists: {str(e)}",
            "Xero Entity Check",
        )
        return True  # Assume exists to avoid duplicates


def get_xero_entity_by_number(entity_type, number_field, number_value):
    """
    Search for an entity in Xero by a unique number/code.

    :param entity_type: Type of entity (e.g., 'Invoices', 'Contacts')
    :param number_field: Field name to search (e.g., 'InvoiceNumber', 'ContactNumber')
    :param number_value: Value to search for
    :return: Entity data if found, None otherwise
    """
    try:
        # Use where clause to search
        response = xero_request(
            "GET", entity_type, params={"where": f'{number_field}=="{number_value}"'}
        )

        if response and entity_type in response and len(response[entity_type]) > 0:
            return response[entity_type][0]
        return None
    except Exception as e:
        frappe.log_error(
            f"Error searching {entity_type} by {number_field}={number_value}: {str(e)}",
            "Xero Search Error",
        )
        return None


# Example Usage (to be called from api modules):
# def get_accounts():
#     return xero_request("GET", "Accounts")
#
# def create_invoice(invoice_data):
#     # Xero API expects data often wrapped, e.g., {"Invoices": [invoice_data]}
#     return xero_request("PUT", "Invoices", data={"Invoices": [invoice_data]})
