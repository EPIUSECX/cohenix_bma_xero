# Copyright (c) 2026, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Shared exception types for the Xero integration.

Kept free of any xero.* imports so both xero_client and logging can use them
without import cycles.
"""


class XeroApiError(Exception):
    """A non-retryable HTTP error returned by the Xero API (4xx).

    Carries the parsed validation detail so callers can log the SPECIFIC
    reason Xero rejected the request (e.g. "Organisation is not subscribed
    to currency USD") instead of the generic outer "A validation exception
    occurred", and can attach the full response body to the Xero Log row.
    """

    def __init__(self, message, status_code=None, response_body=None, validation_messages=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.validation_messages = validation_messages or []

    @property
    def is_permanent(self):
        """True when retrying the identical request can never succeed.

        Xero 4xx responses (except auth/timeout/rate-limit) mean the payload
        itself was rejected; a document that hits one should reach a terminal
        state instead of being re-queued hourly forever.
        """
        if self.status_code is None:
            return False
        return 400 <= self.status_code < 500 and self.status_code not in (401, 408, 429)


class TaxRepresentationError(Exception):
    """The ERPNext tax structure cannot be represented faithfully in Xero.

    Raised by the outbound line builder BEFORE anything is sent, so a payload
    whose Total/TotalTax would not reconcile with the ERPNext document is
    never written to Xero. The message must be operator-actionable.
    """


def extract_xero_validation_messages(error_data):
    """Collect every ValidationErrors message from a Xero error body.

    Xero nests the actionable reason in Elements[].ValidationErrors[].Message
    (and sometimes a root-level ValidationErrors array); the outer "Message"
    is always the generic "A validation exception occurred". Returns the
    specific messages, deduplicated, in document order.
    """
    if not isinstance(error_data, dict):
        return []

    messages = []

    def _collect(container):
        for err in container.get("ValidationErrors") or []:
            msg = (err or {}).get("Message")
            if msg and msg not in messages:
                messages.append(msg)

    for element in error_data.get("Elements") or []:
        if isinstance(element, dict):
            _collect(element)
    _collect(error_data)

    return messages
