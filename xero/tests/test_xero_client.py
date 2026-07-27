# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline unit tests for the auth- and money-critical paths of the Xero client.

These tests mock the Xero HTTP layer (``requests``) and the Frappe cache so they
run without a live Xero connection or network access:

  * token refresh — success, refresh-token rotation, 400/401 invalidation
  * concurrent-refresh lock — token reuse instead of a second rotation
  * webhook HMAC signature — accept valid, reject invalid/missing (security)
  * webhook responses — wire-level HTTP status, post-dedup queued count
  * 429 and 5xx retry with backoff
  * Idempotency-Key propagation on mutating calls
  * inbound invoice mutex release + refetch_invoice recovery endpoint

Run: bench run-tests --app xero --module xero.tests.test_xero_client
"""

import base64
import hashlib
import hmac
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from frappe.utils import add_to_date, now_datetime

import xero.utils.xero_client as xc
import xero.utils.webhook_handler as wh


class FakeResponse:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, status_code=200, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.text = text
        self.reason = "Error" if status_code >= 400 else "OK"

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"{self.status_code}")
            err.response = self
            raise err


def _fake_settings(**overrides):
    """A settings double with sane numeric retry config and a get_password map."""
    base = SimpleNamespace(
        client_id="cid",
        tenant_id="tenant-123",
        refresh_token="rt-encrypted",
        access_token="at-encrypted",
        token_expiry=add_to_date(now_datetime(), seconds=-10),  # expired
        last_token_refresh=None,
        max_retry_attempts=3,
        api_timeout=30,
        rate_limit_backoff_base=2,
        rate_limit_max_delay=5,
        enable_rate_limit_tracking=False,
        rate_limit_per_minute=0,  # disable throttle in tests
    )
    for k, v in overrides.items():
        setattr(base, k, v)

    secrets = {"client_secret": "secret", "refresh_token": "rt-plain", "access_token": "at-plain"}
    base.get_password = MagicMock(side_effect=lambda f: secrets.get(f))
    base.save = MagicMock()
    return base


class FakeCache:
    """In-memory cache supporting the SET NX EX / delete used by the lock."""

    def __init__(self, set_returns=True):
        self.store = {}
        self.set_returns = set_returns

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return self.set_returns

    def delete(self, key):
        self.store.pop(key, None)

    def get_value(self, key):
        return self.store.get(key)

    def set_value(self, key, value, expires_in_sec=None):
        self.store[key] = value

    def delete_value(self, key):
        self.store.pop(key, None)

    # Defensive no-ops so any incidental cache use during a test doesn't blow up.
    def hget(self, *a, **k):
        return None

    def hset(self, *a, **k):
        return None

    def incr(self, *a, **k):
        return 1

    def expire(self, *a, **k):
        return None


# ---------------------------------------------------------------------------
# Webhook signature (security)
# ---------------------------------------------------------------------------
class TestWebhookSignature(unittest.TestCase):
    def _sign(self, key, payload):
        digest = hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def test_valid_signature_accepted(self):
        key, payload = "whsec", '{"events":[]}'
        self.assertTrue(wh.verify_signature(key, payload, self._sign(key, payload)))

    def test_invalid_signature_rejected(self):
        self.assertFalse(wh.verify_signature("whsec", '{"events":[]}', "not-a-sig"))

    def test_tampered_payload_rejected(self):
        key = "whsec"
        sig = self._sign(key, '{"events":[]}')
        self.assertFalse(wh.verify_signature(key, '{"events":[{"x":1}]}', sig))


# ---------------------------------------------------------------------------
# Token freshness helper
# ---------------------------------------------------------------------------
class TestTokenFreshness(unittest.TestCase):
    def test_expired_token_not_fresh(self):
        s = _fake_settings(token_expiry=add_to_date(now_datetime(), minutes=1))
        # within the 5-minute buffer -> must refresh
        self.assertFalse(xc._token_is_fresh(s))

    def test_valid_token_is_fresh(self):
        s = _fake_settings(token_expiry=add_to_date(now_datetime(), minutes=30))
        self.assertTrue(xc._token_is_fresh(s))

    def test_missing_token_not_fresh(self):
        s = _fake_settings(access_token=None)
        self.assertFalse(xc._token_is_fresh(s))


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------
class TestRefreshAccessToken(unittest.TestCase):
    # The token-save commit is routed through xero.utils.transactions; patch the
    # underlying frappe.db.commit there so tests never persist anything.
    @patch("xero.utils.transactions.frappe.db.commit", MagicMock())
    def test_successful_refresh_returns_plaintext_and_saves(self):
        settings = _fake_settings()
        cache = FakeCache()
        token_json = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 1800,
        }
        # log_xero_error is imported function-locally, so patch it at its source.
        with patch("xero.utils.xero_client.get_xero_settings", return_value=settings), \
             patch("xero.utils.xero_client.frappe.cache", return_value=cache), \
             patch("xero.utils.xero_client.requests.post",
                   return_value=FakeResponse(200, token_json)) as post, \
             patch("xero.utils.logging.log_xero_error", MagicMock()):
            result = xc.refresh_access_token()

        self.assertEqual(result, "new-access")  # plaintext, not the encrypted attr
        self.assertEqual(settings.access_token, "new-access")
        self.assertEqual(settings.refresh_token, "new-refresh")
        settings.save.assert_called()
        post.assert_called_once()

    @patch("xero.utils.transactions.frappe.db.commit", MagicMock())
    def test_invalid_refresh_token_invalidates_and_throws(self):
        settings = _fake_settings()
        cache = FakeCache()
        with patch("xero.utils.xero_client.get_xero_settings", return_value=settings), \
             patch("xero.utils.xero_client.frappe.cache", return_value=cache), \
             patch("xero.utils.xero_client.notify_admins_token_failure", MagicMock()), \
             patch("xero.utils.logging.log_xero_error", MagicMock()), \
             patch("xero.utils.xero_client.requests.post",
                   return_value=FakeResponse(400, {"error": "invalid_grant"})):
            with self.assertRaises(Exception):
                xc.refresh_access_token()

        # Tokens cleared so the next call forces re-authentication.
        self.assertIsNone(settings.access_token)
        self.assertIsNone(settings.refresh_token)

    def test_concurrent_refresh_reuses_fresh_token(self):
        """If another worker already refreshed (token fresh once we hold the
        lock), we must reuse it and NOT burn the rotated refresh token."""
        settings = _fake_settings(token_expiry=add_to_date(now_datetime(), minutes=30))
        cache = FakeCache()
        with patch("xero.utils.xero_client.get_xero_settings", return_value=settings), \
             patch("xero.utils.xero_client.frappe.cache", return_value=cache), \
             patch("xero.utils.xero_client.requests.post") as post:
            result = xc.refresh_access_token()

        self.assertEqual(result, "at-plain")   # decrypted existing token
        post.assert_not_called()               # no rotation performed


# ---------------------------------------------------------------------------
# xero_request retry / idempotency
# ---------------------------------------------------------------------------
class TestXeroRequestRetry(unittest.TestCase):
    def setUp(self):
        self.settings = _fake_settings()

    def _common_patches(self):
        return [
            patch("xero.utils.xero_client.get_xero_settings", return_value=self.settings),
            patch("xero.utils.xero_client.get_xero_client", return_value={"Authorization": "Bearer x"}),
            patch("xero.utils.xero_client._throttle_xero_call", MagicMock()),
            patch("time.sleep", MagicMock()),  # function-local `import time`
            patch("xero.utils.logging.log_xero_error", MagicMock()),
            patch("xero.utils.xero_client.frappe.log_error", MagicMock()),
        ]

    def test_429_then_success_retries(self):
        responses = [
            FakeResponse(429, headers={"Retry-After": "0"}),
            FakeResponse(200, {"Invoices": []}),
        ]
        patches = self._common_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        with patch("xero.utils.xero_client.requests.get", side_effect=responses) as get:
            out = xc.xero_request("GET", "Invoices")
        self.assertEqual(out, {"Invoices": []})
        self.assertEqual(get.call_count, 2)

    def test_503_then_success_retries(self):
        responses = [FakeResponse(503), FakeResponse(200, {"ok": 1})]
        patches = self._common_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        with patch("xero.utils.xero_client.requests.get", side_effect=responses) as get:
            out = xc.xero_request("GET", "Organisation")
        self.assertEqual(out, {"ok": 1})
        self.assertEqual(get.call_count, 2)

    def test_idempotency_key_sent_on_put(self):
        patches = self._common_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        with patch("xero.utils.xero_client.requests.put",
                   return_value=FakeResponse(200, {"Invoices": []})) as put:
            xc.xero_request("PUT", "Invoices", data={"Invoices": [{}]},
                            idempotency_key="SI-001:create-invoice")
        sent_headers = put.call_args.kwargs["headers"]
        self.assertEqual(sent_headers.get("Idempotency-Key"), "SI-001:create-invoice")

    def test_no_idempotency_key_when_not_provided(self):
        patches = self._common_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        with patch("xero.utils.xero_client.requests.get",
                   return_value=FakeResponse(200, {"ok": 1})) as get:
            xc.xero_request("GET", "Invoices")
        self.assertNotIn("Idempotency-Key", get.call_args.kwargs["headers"])


# ---------------------------------------------------------------------------
# Webhook handler — wire status + queued count
# ---------------------------------------------------------------------------
class TestWebhookHandler(unittest.TestCase):
    """handle_webhook must set the HTTP status frappe actually reads
    (frappe.local.response["http_status_code"]) and report the post-dedup
    queued count, not the raw event count."""

    KEY = "whsec"

    def setUp(self):
        import frappe
        self._request = getattr(frappe.local, "request", None)
        self._response = getattr(frappe.local, "response", None)
        self.addCleanup(self._restore)

    def _restore(self):
        import frappe
        frappe.local.request = self._request
        frappe.local.response = self._response

    def _sign(self, payload):
        digest = hmac.new(self.KEY.encode(), payload.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def _call(self, payload, signature, seen=None, webhook_key="whsec"):
        import frappe
        frappe.local.request = SimpleNamespace(
            headers={"X-Xero-Signature": signature} if signature else {},
            get_data=lambda as_text=True: payload,
        )
        frappe.local.response = frappe._dict()
        enqueued = []
        with patch.object(wh, "get_webhook_key", return_value=webhook_key), \
             patch.object(wh, "log_xero_error") as log, \
             patch.object(wh, "_webhook_event_already_seen",
                          side_effect=seen or (lambda e: False)), \
             patch.object(wh.frappe, "enqueue",
                          side_effect=lambda *a, **k: enqueued.append(k)):
            result = wh.handle_webhook()
        return result, frappe.local.response, log, enqueued

    def test_invalid_signature_sets_wire_401(self):
        result, response, log, enqueued = self._call('{"events":[]}', "not-a-sig")
        self.assertEqual(result["status"], "error")
        self.assertEqual(response.get("http_status_code"), 401)
        self.assertEqual(enqueued, [])
        # The rejection must still be recorded in Xero Log
        self.assertTrue(any(
            call.kwargs.get("status") == "Error" for call in log.call_args_list
        ))

    def test_missing_webhook_key_sets_wire_401(self):
        result, response, log, enqueued = self._call(
            '{"events":[]}', "sig", webhook_key=None
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(response.get("http_status_code"), 401)

    def test_invalid_json_sets_wire_400(self):
        payload = "not-json"
        result, response, log, enqueued = self._call(payload, self._sign(payload))
        self.assertEqual(result["status"], "error")
        self.assertEqual(response.get("http_status_code"), 400)

    def test_queued_count_excludes_replayed_events(self):
        payload = ('{"events": ['
                   '{"resourceId": "a"}, {"resourceId": "dup"}, {"resourceId": "b"}'
                   ']}')
        result, response, log, enqueued = self._call(
            payload, self._sign(payload),
            seen=lambda e: e.get("resourceId") == "dup",
        )
        self.assertEqual(result["status"], "success")
        self.assertNotIn("http_status_code", response)
        self.assertEqual(len(enqueued), 2)
        self.assertIn("2 of 3", result["message"])


# ---------------------------------------------------------------------------
# Inbound invoice mutex + refetch recovery
# ---------------------------------------------------------------------------
class TestInvoiceLockRelease(unittest.TestCase):
    """The per-invoice mutex must be released on every exit path — a leaked
    lock blocks retries of that invoice for the full 2-minute TTL."""

    def test_lock_released_on_skip_inside_locked_section(self):
        import xero.api.xero_invoices as xi
        cache = FakeCache()
        settings = SimpleNamespace(get=lambda k, d=None: 1)
        # No Contact → the skip return fires inside the locked section
        payload = {"InvoiceID": "inv-1", "Type": "ACCREC", "Status": "AUTHORISED"}
        with patch.object(xi.frappe, "cache", return_value=cache), \
             patch.object(xi.frappe.db, "get_value", return_value=None), \
             patch.object(xi, "log_xero_error"):
            outcome = xi.process_xero_invoice(payload, settings)
        self.assertEqual(outcome, "skipped")
        self.assertNotIn("xero_inbound_lock_inv-1", cache.store)

    def test_busy_lock_skips_without_stealing(self):
        import xero.api.xero_invoices as xi
        cache = FakeCache()
        cache.store["xero_inbound_lock_inv-1"] = True  # held by another worker
        settings = SimpleNamespace(get=lambda k, d=None: 1)
        payload = {"InvoiceID": "inv-1", "Type": "ACCREC", "Status": "AUTHORISED"}
        with patch.object(xi.frappe, "cache", return_value=cache), \
             patch.object(xi, "log_xero_error"):
            outcome = xi.process_xero_invoice(payload, settings)
        self.assertEqual(outcome, "skipped")
        self.assertIn("xero_inbound_lock_inv-1", cache.store)


class TestRefetchInvoice(unittest.TestCase):
    """refetch_invoice recovers one skipped invoice without ever moving the
    incremental watermark."""

    VALID_ID = "12345678-1234-1234-1234-123456789abc"

    def _patches(self, xi, xero_response):
        return [
            patch("xero.utils.xero_client.require_xero_manager"),
            patch("xero.utils.xero_client.commit_watermark"),
            patch.object(xi, "get_xero_settings",
                         return_value=SimpleNamespace(enable_xero_sync=1)),
            patch.object(xi, "xero_request", return_value=xero_response),
            patch.object(xi, "process_xero_invoice", return_value="synced"),
        ]

    def test_processes_invoice_without_touching_watermark(self):
        import xero.api.xero_invoices as xi
        invoice = {"InvoiceID": self.VALID_ID, "Type": "ACCREC"}
        patches = self._patches(xi, {"Invoices": [invoice]})
        mocks = [p.start() for p in patches]
        self.addCleanup(lambda: [p.stop() for p in patches])

        out = xi.refetch_invoice(self.VALID_ID)

        self.assertEqual(out, {"invoice_id": self.VALID_ID, "outcome": "synced"})
        mocks[4].assert_called_once()
        self.assertIs(mocks[4].call_args.args[0], invoice)
        mocks[1].assert_not_called()  # commit_watermark
        mocks[3].assert_called_once_with("GET", f"Invoices/{self.VALID_ID}")

    def test_rejects_malformed_invoice_id(self):
        import frappe
        import xero.api.xero_invoices as xi
        with patch("xero.utils.xero_client.require_xero_manager"):
            with self.assertRaises(frappe.ValidationError):
                xi.refetch_invoice("../Contacts")

    def test_throws_when_invoice_not_in_xero(self):
        import frappe
        import xero.api.xero_invoices as xi
        patches = self._patches(xi, {"Invoices": []})
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        with self.assertRaises(frappe.ValidationError):
            xi.refetch_invoice(self.VALID_ID)


if __name__ == "__main__":
    unittest.main()
