"""Tests for the Telegram initData check (M3, #23).

We sign test data the same way Telegram does, so no network is needed.
"""

import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from travelkaki.web.auth import AuthError, check_init_data

TOKEN = "123:fake-token"
NOW = 1_800_000_000  # a fixed "now" (unix seconds) so tests never depend on the clock


def sign(fields: dict, token: str = TOKEN) -> str:
    """Build an initData string signed like Telegram signs it."""
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()}
    return urlencode(fields)


def good_fields(**extra) -> dict:
    user = json.dumps({"id": 42, "first_name": "Don"})
    return {"auth_date": str(NOW - 60), "user": user, "start_param": "7", **extra}


def test_valid_data_gives_user_and_start_param():
    assert check_init_data(sign(good_fields()), TOKEN, now=NOW) == (42, "7")


def test_missing_start_param_is_none():
    fields = good_fields()
    del fields["start_param"]
    assert check_init_data(sign(fields), TOKEN, now=NOW) == (42, None)


def test_wrong_token_is_rejected():
    with pytest.raises(AuthError):
        check_init_data(sign(good_fields(), token="999:other"), TOKEN, now=NOW)


def test_tampered_field_is_rejected():
    raw = sign(good_fields()).replace("start_param=7", "start_param=8")
    with pytest.raises(AuthError):
        check_init_data(raw, TOKEN, now=NOW)


@pytest.mark.parametrize("raw", ["", "user=x", "hash=abc&auth_date=1"])
def test_missing_or_broken_data_is_rejected(raw):
    with pytest.raises(AuthError):
        check_init_data(raw, TOKEN, now=NOW)


def test_old_data_is_rejected():
    fields = good_fields(auth_date=str(NOW - 25 * 3600))  # older than 24 h
    with pytest.raises(AuthError):
        check_init_data(sign(fields), TOKEN, now=NOW)


def test_signed_data_without_user_is_rejected():
    fields = good_fields()
    del fields["user"]
    with pytest.raises(AuthError):
        check_init_data(sign(fields), TOKEN, now=NOW)
