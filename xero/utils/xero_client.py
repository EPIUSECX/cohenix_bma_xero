# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

import frappe
import requests
from .transactions import commit_checkpoint, commit_error_state, commit_external_outcome
from frappe.utils import get_site_url, now_datetime, add_to_date, get_datetime
from json import dumps, loads
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta

XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"
XERO_API_BASE_URL = "https://api.xero.com/api.xro/2.0"

# Timeout (seconds) applied to every outbound HTTP call to Xero so a hung
# endpoint can never block a worker indefinitely.
XERO_HTTP_TIMEOUT = 30

# HTTP status codes that are safe to retry (transient server-side failures).
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}


def safe_idempotency_key(key):
    """Make an idempotency key legal as an HTTP header value.

    HTTP headers must be Latin-1 encodable; keys are built from ERPNext
    document names, and Customers/Suppliers are named by customer_name /
    supplier_name, so Greek/CJK/emoji names produced a UnicodeEncodeError that
    permanently killed sync for that party (H5). Keys that already encode are
    returned UNCHANGED so every existing key stays stable across this fix;
    non-encodable keys are replaced by their SHA-256 hex digest — deterministic
    (stable per document) and collision-free in practice.
    """
    key = str(key)
    try:
        key.encode("latin-1")
        return key
    except UnicodeEncodeError:
        import hashlib

        return hashlib.sha256(key.encode("utf-8")).hexdigest()


def get_xero_settings():
    """Returns the Xero Settings document."""
    # Consider multi-company scenarios if applicable
    return frappe.get_single("Xero Settings")


# Roles permitted to manage the Xero integration (trigger syncs, change the
# connected organisation, edit mappings, reconcile). System Manager and the
# app's own manager role; Administrator always passes.
XERO_MANAGER_ROLES = ("System Manager", "Xero Integration Manager")


def require_xero_manager():
    """ME-8: Guard whitelisted, state-changing endpoints so any logged-in user
    cannot trigger Xero syncs, switch the connected organisation, or rewrite
    account mappings. Raises PermissionError unless the caller holds a Xero
    management role."""
    if frappe.session.user == "Administrator":
        return
    if not set(XERO_MANAGER_ROLES) & set(frappe.get_roles()):
        frappe.throw(
            "You are not permitted to perform Xero integration actions.",
            frappe.PermissionError,
        )


# ---------------------------------------------------------------------------
# Incremental sync (If-Modified-Since watermarks)
# ---------------------------------------------------------------------------
# Full sweeps of every entity on each run burn through Xero's daily API quota
# (5000/day/tenant) and don't scale to larger orgs. Incremental sync fetches
# only records changed since the last successful run, using Xero's
# `If-Modified-Since` request header (UTC, ISO 8601). We persist a per-entity
# UTC watermark in the Xero Settings `sync_watermarks` JSON field.

# Re-fetch a small overlap window before the last run start to tolerate clock
# skew and records modified mid-run. Cheap insurance against missed updates;
# re-processing an unchanged record is idempotent.
WATERMARK_OVERLAP_MINUTES = 5

# Xero's documented If-Modified-Since format (UTC, no offset suffix).
_IMS_FMT = "%Y-%m-%dT%H:%M:%S"


def _utcnow():
    return datetime.now(timezone.utc)


def _load_watermarks(settings=None):
    raw = (settings or get_xero_settings()).get("sync_watermarks")
    if not raw:
        return {}
    try:
        data = loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_sync_watermark(entity_key, settings=None):
    """Return the stored UTC If-Modified-Since string for an entity, or None."""
    return _load_watermarks(settings).get(entity_key)


def set_sync_watermark(entity_key, value):
    """Persist a watermark for an entity (durably, on the Single doc)."""
    data = _load_watermarks()
    data[entity_key] = value
    frappe.db.set_single_value("Xero Settings", "sync_watermarks", dumps(data))
    # The synced documents behind this watermark are already committed
    # per-document; the watermark must persist with them even if a later
    # entity in the same batch job aborts and rolls back.
    commit_checkpoint()


def incremental_since(entity_key):
    """The If-Modified-Since value to send for this entity's list fetch, or None
    for a full sync (incremental disabled, or first run with no watermark)."""
    settings = get_xero_settings()
    if not settings.get("enable_incremental_sync"):
        return None
    return get_sync_watermark(entity_key, settings)


def start_incremental_run():
    """Capture the run-start instant (UTC) to base the next watermark on.
    Call at the top of an inbound sync, BEFORE fetching."""
    return _utcnow()


def commit_watermark(entity_key, run_started_at):
    """Advance an entity's watermark after a SUCCESSFUL sync. Stores
    (run_start - overlap) so the next run re-checks a small safety window."""
    if not run_started_at:
        return
    if not get_xero_settings().get("enable_incremental_sync"):
        return
    value = (run_started_at - timedelta(minutes=WATERMARK_OVERLAP_MINUTES)).strftime(_IMS_FMT)
    set_sync_watermark(entity_key, value)


@frappe.whitelist()
def reset_xero_sync_watermarks():
    """Clear all incremental watermarks so the next run does a full sync.
    Use after a mapping change or to backfill historical records."""
    require_xero_manager()
    frappe.db.set_single_value("Xero Settings", "sync_watermarks", "")
    return {"status": "ok", "message": "Xero sync watermarks cleared; next sync will be a full sweep."}


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
    require_xero_manager()
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
        # Granular scopes required for apps created on or after 2 March 2026.
        # accounting.transactions is deprecated; replaced by the four scopes below.
        "scope": (
            "openid profile email offline_access "
            "accounting.invoices accounting.payments accounting.banktransactions accounting.manualjournals "
            "accounting.contacts accounting.settings"
        ),
        "state": state,
    }
    return f"{XERO_AUTH_URL}?{urlencode(params)}"


def _redirect_with_error(message):
    """Redirect to Xero Settings with an error message instead of throwing a 500."""
    from urllib.parse import quote
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = (
        f"/app/xero-settings?xero_oauth_error={quote(message)}"
    )


@frappe.whitelist(allow_guest=True)
def handle_oauth_callback(code=None, state=None, error=None):
    """Handles the OAuth2 callback from Xero."""
    if error:
        # Map Xero error codes to actionable messages
        error_messages = {
            "invalid_scope": (
                "Xero rejected the requested permissions (invalid_scope). "
                "Your Xero app was created after 2 March 2026 and uses granular scopes. "
                "The old 'accounting.transactions' scope is no longer valid. "
                "The code has been updated to use the new granular scopes. "
                "If you see this error again, ensure your Xero app in the Developer Portal "
                "is set to 'Web App' (not Custom Connection)."
            ),
            "access_denied": "Access was denied. Please try connecting again and accept the permissions request.",
            "invalid_client": "Invalid Client ID or Client Secret. Check your Xero Settings credentials.",
        }
        # Do not reflect the raw provider `error` back into the redirect — it is
        # attacker-controllable and lands in an HTML-rendering msgprint. Map known
        # codes to friendly text; unknown codes get a generic message, and the raw
        # value is kept in the server log only.
        friendly = error_messages.get(
            error, "Xero returned an authorization error. Please try connecting again."
        )
        frappe.log_error(f"Xero OAuth error param: {error!r}", "Xero OAuth Error")
        _redirect_with_error(friendly)
        return

    # State is encoded as "{user}:{token}" so the guest callback can resolve the initiating user
    if not state or ":" not in state:
        _redirect_with_error("Invalid OAuth state. Please try connecting again.")
        return
    initiating_user, state_token = state.split(":", 1)
    cached_state = frappe.cache().hget("xero_oauth_state", initiating_user)
    if not cached_state or state_token != cached_state:
        _redirect_with_error("Invalid OAuth state. Please try connecting again.")
        return
    # Clear the used state token to prevent replay attacks
    frappe.cache().hdel("xero_oauth_state", initiating_user)

    if not code:
        _redirect_with_error("Missing authorization code from Xero.")
        return

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

        response = requests.post(
            XERO_TOKEN_URL, headers=headers, data=data, timeout=XERO_HTTP_TIMEOUT
        )
        response.raise_for_status()
        token_data = response.json()

        # Get Tenant ID (returns first tenant by default; user can switch via select_tenant)
        tenant_id, tenant_name = get_tenant_id(token_data["access_token"])

        # Save tokens and tenant
        settings.access_token = token_data["access_token"]
        settings.refresh_token = token_data["refresh_token"]
        settings.token_expiry = add_to_date(
            now_datetime(), seconds=token_data["expires_in"]
        )
        settings.tenant_id = tenant_id
        settings.tenant_name = tenant_name
        settings.save(ignore_permissions=True)
        # The authorization code was consumed by the one-shot token exchange
        # above; the tokens must persist even if the rest of this request
        # fails, or the user has to redo the whole OAuth flow.
        commit_external_outcome()

        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = (
            "/app/xero-settings"  # Redirect back to settings page
        )
        frappe.msgprint("Xero connection successful!")

    except requests.exceptions.RequestException as e:
        frappe.log_error(f"Xero OAuth Token Request Failed: {e}", "Xero Auth Error")
        _redirect_with_error("Failed to get access token from Xero. Check your Client ID and Secret.")
    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback(), title="Xero OAuth Callback Error"
        )
        _redirect_with_error("An error occurred during Xero authentication. Check the Error Log for details.")


def get_available_connections(access_token):
    """Returns all Xero tenant connections for the current token."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(
            XERO_CONNECTIONS_URL, headers=headers, timeout=XERO_HTTP_TIMEOUT
        )
        response.raise_for_status()
        return response.json() or []
    except requests.exceptions.RequestException as e:
        frappe.log_error(f"Xero Get Connections Failed: {e}", "Xero API Error")
        frappe.throw("Failed to retrieve Xero tenant connections.")


def get_tenant_id(access_token):
    """
    Fetches the Tenant ID from Xero Connections API.

    If multiple tenants are connected, stores them all in cache for the UI
    to offer a picker, and returns the first one as the default.
    If settings already has a tenant_id set (e.g. user picked one earlier),
    that value is preserved and this function is not called.
    """
    connections = get_available_connections(access_token)
    if not connections:
        frappe.throw("No Xero organisations found for this connection.")

    # Cache the full list so the JS picker can show it
    frappe.cache().set_value(
        "xero_available_tenants",
        [{"id": c["tenantId"], "name": c.get("tenantName", c["tenantId"])} for c in connections],
        expires_in_sec=3600,
    )

    return connections[0]["tenantId"], connections[0].get("tenantName", "")


@frappe.whitelist()
def get_available_tenants():
    """Returns the list of Xero tenants connected to the current OAuth token."""
    require_xero_manager()
    tenants = frappe.cache().get_value("xero_available_tenants")
    if tenants:
        return tenants

    # Re-fetch if cache is cold
    settings = get_xero_settings()
    if not settings.access_token:
        return []
    connections = get_available_connections(settings.get_password("access_token"))
    return [{"id": c["tenantId"], "name": c.get("tenantName", c["tenantId"])} for c in connections]


@frappe.whitelist()
def select_tenant(tenant_id):
    """Allows the user to pick which Xero organisation to sync with."""
    require_xero_manager()
    tenants = get_available_tenants()
    match = next((t for t in tenants if t["id"] == tenant_id), None)
    if not match:
        frappe.throw(f"Tenant {tenant_id} not found in connected organisations.")

    settings = get_xero_settings()
    settings.tenant_id = match["id"]
    settings.tenant_name = match["name"]
    settings.save(ignore_permissions=True)
    frappe.msgprint(f"Xero organisation changed to: {match['name']}")
    return {"tenant_id": match["id"], "tenant_name": match["name"]}


def _token_is_fresh(settings, buffer_minutes=5):
    """True if the stored access token is still valid beyond the safety buffer."""
    if not settings.access_token or not settings.token_expiry:
        return False
    expiry = get_datetime(settings.token_expiry)
    return now_datetime() < add_to_date(expiry, minutes=-buffer_minutes)


def refresh_access_token():
    """Refreshes the Xero access token using the refresh token.

    CR-3: Xero rotates (and invalidates) the refresh token on every use, so two
    workers refreshing concurrently would revoke each other's token and take the
    whole integration offline. We serialise refresh with a short-lived Redis lock
    (SET NX EX) and re-read settings inside the lock — if another worker already
    refreshed, we return the fresh token instead of burning the rotated one.
    Fails open (proceeds without the lock) only if the cache is unavailable.
    """
    import time
    from ..utils.logging import log_xero_error

    cache = frappe.cache()
    site = getattr(frappe.local, "site", "site")
    lock_key = f"xero_token_refresh_lock:{site}"
    lock_ttl = 60  # seconds; longer than the worst-case refresh (3 retries w/ backoff)

    acquired = False
    # Wait up to ~30s for an in-flight refresh by another worker to finish.
    for _ in range(60):
        try:
            acquired = bool(cache.set(lock_key, "1", nx=True, ex=lock_ttl))
        except Exception:
            acquired = True  # cache unavailable -> proceed without coordination
        if acquired:
            break
        time.sleep(0.5)
        fresh = get_xero_settings()
        if _token_is_fresh(fresh):
            return fresh.get_password("access_token")

    try:
        # Re-read the latest token state now that we hold the lock. Another worker
        # may have refreshed in the window between our expiry check and acquiring
        # the lock — if so, reuse its token rather than rotating again.
        settings = get_xero_settings()
        if _token_is_fresh(settings):
            return settings.get_password("access_token")

        if not settings.refresh_token:
            notify_admins_token_failure("No refresh token found")
            frappe.throw("Xero Refresh Token not found. Please re-authenticate.")

        return _do_refresh(settings, log_xero_error, time)
    finally:
        if acquired:
            try:
                cache.delete(lock_key)
            except Exception:
                pass


def _do_refresh(settings, log_xero_error, time):
    """Performs the actual token refresh request with bounded retries.
    Must be called while holding the refresh lock."""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "client_id": settings.client_id,
        "client_secret": settings.get_password("client_secret"),
        "refresh_token": settings.get_password("refresh_token"),
    }

    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            response = requests.post(
                XERO_TOKEN_URL, headers=headers, data=data, timeout=XERO_HTTP_TIMEOUT
            )
            response.raise_for_status()
            token_data = response.json()

            new_access_token = token_data["access_token"]
            settings.access_token = new_access_token
            settings.refresh_token = token_data[
                "refresh_token"
            ]  # Xero rotates the refresh token on every use
            settings.token_expiry = add_to_date(
                now_datetime(), seconds=token_data["expires_in"]
            )
            settings.last_token_refresh = now_datetime()
            settings.save(ignore_permissions=True)
            # Xero rotates the refresh token on every use; if a later failure
            # in the surrounding job rolled this back, the stored (already
            # invalidated) token would permanently break the connection.
            commit_external_outcome()

            log_xero_error(
                message="Xero access token refreshed successfully",
                status="Success",
                category="Authentication Issues",
            )

            # Return the plaintext token directly — after save() the in-memory
            # attribute holds the encrypted Password value, not the bearer token.
            return new_access_token

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
                    # Persist the invalidation before the surrounding job
                    # aborts, or the dead token would be restored on rollback
                    # and every subsequent run would retry it and re-alert.
                    commit_error_state()

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


def get_system_manager_emails():
    """
    Returns email addresses of all enabled System Manager users.
    Uses Has Role (the correct Frappe relationship table) consistently.
    """
    rows = frappe.db.sql(
        """
        SELECT u.email
        FROM `tabUser` u
        INNER JOIN `tabHas Role` hr ON hr.parent = u.name AND hr.parenttype = 'User'
        WHERE hr.role = 'System Manager'
          AND u.enabled = 1
          AND u.email IS NOT NULL
          AND u.email != ''
        """,
        as_dict=True,
    )
    return [r.email for r in rows if r.email]


def notify_admins_token_failure(reason):
    """Send email and in-app notification to System Manager users when token refresh fails."""
    try:
        recipients = get_system_manager_emails()
        if not recipients:
            frappe.log_error("No System Manager users found to notify.", "Xero Notification")
            return

        frappe.sendmail(
            recipients=recipients,
            subject="Xero Integration: Token Refresh Failed",
            message=f"""
                <p>The Xero integration token refresh has failed.</p>
                <p><strong>Reason:</strong> {reason}</p>
                <p>Please log in to ERPNext and re-authenticate with Xero in the
                <a href="/app/xero-settings">Xero Settings</a> page.</p>
                <p>Until this is resolved, Xero synchronisation will not function.</p>
            """,
            delayed=False,
        )

        # In-app Notification Log (cap at 5 to avoid spam)
        for email in recipients[:5]:
            try:
                user = frappe.db.get_value("User", {"email": email}, "name")
                if not user:
                    continue
                frappe.get_doc({
                    "doctype": "Notification Log",
                    "subject": "Xero Token Refresh Failed",
                    "for_user": user,
                    "type": "Alert",
                    "document_type": "Xero Settings",
                    "document_name": "Xero Settings",
                    "email_content": f"Xero token refresh failed: {reason}. Please re-authenticate.",
                }).insert(ignore_permissions=True)
            except Exception:
                pass

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

    # Refresh if the token is missing/expired or within the 5-minute safety buffer.
    if _token_is_fresh(settings):
        access_token = settings.get_password("access_token")
    else:
        access_token = refresh_access_token()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Xero-Tenant-Id": settings.tenant_id,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return headers  # Return headers for direct requests usage


# --- Wrapper functions for API calls ---


def _throttle_xero_call(settings):
    """Distributed, per-tenant rate governor for ALL outbound Xero API calls.

    Every Xero call funnels through xero_request, so enforcing the limit here
    throttles EVERY entity sync at once (invoices, items, payments, contacts,
    journals, ...). Because the counter lives in Redis it coordinates across all
    background workers — something per-function sleeps cannot do. It proactively
    holds calls under Xero's 60/minute/tenant limit (default 55, for headroom)
    instead of only reacting to 429s after the fact.

    Uses a fixed 1-minute window counter (atomic Redis INCR). Fails open if the
    cache is unavailable — the 429 back-off below remains the backstop.
    """
    import time

    limit = frappe.utils.cint(getattr(settings, "rate_limit_per_minute", 0)) or 55
    if limit <= 0:
        return

    cache = frappe.cache()
    tenant = settings.tenant_id or "default"
    site = getattr(frappe.local, "site", "site")
    deadline = time.time() + 30  # never block a single call here for >30s (ME-7)

    while time.time() < deadline:
        bucket = int(time.time() // 60)
        key = f"xero_rl:{site}:{tenant}:{bucket}"
        try:
            count = cache.incr(key)
            if count == 1:
                cache.expire(key, 120)
        except Exception:
            return  # cache unavailable -> fail open
        if count <= limit:
            return
        # Over the per-minute budget — wait into the next minute window.
        time.sleep(min(2.0, max(0.2, 60 - (time.time() % 60))))


def xero_request(method, endpoint, data=None, params=None, idempotency_key=None, modified_since=None):
    """Makes a request to the Xero API, handling authentication and errors.

    :param idempotency_key: Optional stable key sent as the ``Idempotency-Key``
        header. Xero deduplicates mutating requests (POST/PUT) carrying the same
        key for 24h, so a retry after a timeout where Xero actually succeeded
        will NOT create a duplicate record. Callers creating financial documents
        (invoices, payments, credit notes, journals) should always pass one
        (HI-7). When supplied, network/timeout retries on POST/PUT are safe.
    :param modified_since: Optional UTC ISO-8601 string (``YYYY-MM-DDTHH:MM:SS``)
        sent as the ``If-Modified-Since`` header so Xero returns only records
        changed since then (incremental sync). NOTE: this is a HEADER, not a
        query param — the old ``params['ModifiedSince']`` approach was ignored
        by Xero.
    """
    import time

    settings = get_xero_settings()
    headers = dict(get_xero_client())  # Gets headers with valid token (copy to mutate)
    if idempotency_key:
        headers["Idempotency-Key"] = safe_idempotency_key(idempotency_key)
    if modified_since:
        headers["If-Modified-Since"] = str(modified_since)
    url = f"{XERO_API_BASE_URL}/{endpoint}"

    method_upper = method.upper()
    # GET is idempotent by definition; mutating calls are only safe to retry on a
    # network/timeout failure when an Idempotency-Key guarantees server-side dedup.
    safe_to_retry_on_network = method_upper == "GET" or bool(idempotency_key)

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
        # Proactively stay under the per-minute limit before every attempt.
        _throttle_xero_call(settings)
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

            # Handle potential empty response body for certain successful calls (e.g., 204 No Content)
            if response.status_code == 204:
                return None
            return response.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limit error
                retry_count += 1

                # Xero sends X-Rate-Limit-Problem on a 429 telling you WHICH
                # limit tripped (Minute / Daily / Concurrent). X-Rate-Limit-
                # Remaining is only on successful responses, so it's absent here
                # — that's why it always logged "unknown". Retry-After (seconds)
                # is the authoritative wait.
                problem = (e.response.headers.get("X-Rate-Limit-Problem") or "unknown").strip()
                retry_after = e.response.headers.get("Retry-After")

                if track_rate_limits:
                    from ..utils.logging import log_xero_error

                    log_xero_error(
                        message=f"Rate limit hit on {method} {endpoint}. Problem: {problem}, Retry-After: {retry_after or 'n/a'}s",
                        status="Warning",
                        category="Rate Limiting",
                        direction="Xero to ERPNext" if method == "GET" else "ERPNext to Xero",
                        retry_count=retry_count,
                    )

                # Daily limit (5000/day/tenant): retrying within this run is
                # futile — Retry-After can be hours. Abort fast with a clear,
                # actionable error instead of burning every retry slot.
                if "day" in problem.lower():
                    from ..utils.logging import log_xero_error

                    log_xero_error(
                        message=(
                            f"Xero DAILY API limit reached on {method} {endpoint}. "
                            f"Sync cannot continue until the daily quota resets "
                            f"(~{retry_after}s). Re-run after reset."
                        ),
                        status="Error",
                        category="Rate Limiting",
                        direction="Xero to ERPNext" if method == "GET" else "ERPNext to Xero",
                        retry_count=retry_count,
                    )
                    raise e

                if retry_count >= max_retries:
                    # Log final failure and re-raise
                    frappe.log_error(
                        f"Xero API rate limit exceeded after {max_retries} retries on {method} {endpoint}. Problem: {problem}",
                        "Xero API Error",
                    )
                    raise e

                # Honor Xero's Retry-After header when present (it tells you
                # exactly how long the limit lasts); otherwise fall back to
                # exponential backoff. Cap at max_delay so a worker is never
                # blocked indefinitely.
                if retry_after:
                    try:
                        wait_time = min(float(retry_after), max_delay)
                    except (TypeError, ValueError):
                        wait_time = min(backoff_base**retry_count, max_delay)
                else:
                    wait_time = min(backoff_base**retry_count, max_delay)
                frappe.log_error(
                    message=f"Xero rate limit ({problem}). Retrying in {wait_time}s (attempt {retry_count}/{max_retries}).",
                    title="Xero API Rate Limit",
                )
                time.sleep(wait_time)
            elif e.response.status_code in RETRYABLE_STATUS_CODES:
                # HI-6: transient server-side failure (500/502/503/504) — retry
                # with capped exponential backoff before giving up.
                retry_count += 1
                if retry_count >= max_retries:
                    from ..utils.logging import log_xero_error

                    log_xero_error(
                        message=f"Xero API {e.response.status_code} on {method} {endpoint} after {max_retries} retries",
                        status="Error",
                        category="Connection Issues",
                        error_details=(e.response.text or "")[:1000],
                        retry_count=retry_count,
                    )
                    raise e
                wait_time = min(backoff_base**retry_count, max_delay)
                frappe.log_error(
                    message=f"Xero {e.response.status_code} on {method} {endpoint}. Retrying in {wait_time}s (attempt {retry_count}/{max_retries}).",
                    title="Xero API Transient Error",
                )
                time.sleep(wait_time)
            else:
                # Other HTTP errors (4xx): surface the SPECIFIC reason Xero gave.
                # Xero nests it in Elements[].ValidationErrors[].Message; the
                # outer "Message" is always the useless generic one (C4).
                from .exceptions import XeroApiError, extract_xero_validation_messages

                status_code = e.response.status_code
                error_data = None
                try:
                    error_data = e.response.json()
                    error_details = dumps(error_data, indent=2)
                except Exception:
                    error_details = e.response.text or ""

                validation_messages = extract_xero_validation_messages(error_data)
                summary = "; ".join(validation_messages) or (
                    (error_data or {}).get("Message") or e.response.reason or ""
                )

                # Keep the full body in the Frappe Error Log for forensics. The
                # Xero Log row is created by the CALLER (which knows the ERPNext
                # document), so the dashboard row links to the real doc instead
                # of a doc-less "Unknown" entry.
                frappe.log_error(
                    message=f"Xero API Error ({status_code}) on {method} {url}:\n{error_details}",
                    title="Xero API Error",
                )

                raise XeroApiError(
                    f"Xero rejected the request ({status_code}): {summary}",
                    status_code=status_code,
                    response_body=error_details,
                    validation_messages=validation_messages,
                )

        except requests.exceptions.RequestException as e:
            # Network errors, timeouts, connection resets, etc. (HI-6)
            retry_count += 1
            can_retry = safe_to_retry_on_network and retry_count < max_retries
            if can_retry:
                wait_time = min(backoff_base**retry_count, max_delay)
                frappe.log_error(
                    message=f"Xero network error on {method} {endpoint}: {e}. Retrying in {wait_time}s (attempt {retry_count}/{max_retries}).",
                    title="Xero Network Error",
                )
                time.sleep(wait_time)
                continue

            # Non-idempotent call with no idempotency key, or retries exhausted:
            # do NOT silently retry a mutating call that may have already applied.
            frappe.log_error(
                message=f"Xero Network Error on {method} {url}: {e}",
                title="Xero Network Error",
            )
            frappe.throw(f"Network error communicating with Xero: {e}")

        except Exception:
            # Log for forensics but RE-RAISE the original exception: replacing
            # it with "An unexpected error occurred in the Xero client." erased
            # the type and message the operator needed (e.g. the
            # UnicodeEncodeError behind H5) and got miscategorised downstream.
            frappe.log_error(
                message=frappe.get_traceback(), title="Xero Client Unexpected Error"
            )
            raise

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
