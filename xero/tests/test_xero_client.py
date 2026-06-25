# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline unit tests for the auth- and money-critical paths of the Xero client.

These tests mock the Xero HTTP layer (``requests``) and the Frappe cache so they
run without a live Xero connection or network access:

  * token refresh — success, refresh-token rotation, 400/401 invalidation
  * concurrent-refresh lock — token reuse instead of a second rotation (CR-3)
  * webhook HMAC signature — accept valid, reject invalid/missing (security)
  * 429 and 5xx retry with backoff (HI-6)
  * Idempotency-Key propagation on mutating calls (HI-7)

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
    @patch("xero.utils.xero_client.frappe.db.commit", MagicMock())
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

    @patch("xero.utils.xero_client.frappe.db.commit", MagicMock())
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
        """CR-3: if another worker already refreshed (token fresh once we hold the
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


if __name__ == "__main__":
    unittest.main()
