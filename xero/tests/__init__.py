# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

"""Offline test suite for the Xero integration.

Every test here runs without a live Xero connection or network access: the
Xero HTTP layer is mocked and any documents created are rolled back.

Run with:
    bench run-tests --app xero --site your-site
"""
