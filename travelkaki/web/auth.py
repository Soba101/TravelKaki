"""Check the `initData` Telegram gives a mini app (M3, #23).

Telegram signs initData with our bot token. If the signature is right,
we can trust the user id inside it. Steps (from Telegram's docs):
  secret = HMAC_SHA256(key="WebAppData", msg=bot_token)
  hash   = hex(HMAC_SHA256(key=secret, msg=data_check_string))
data_check_string = every field except `hash`, as "key=value", sorted, joined by "\n".
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_AGE = 24 * 3600  # initData older than this is rejected (stops replaying old links)


class AuthError(Exception):
    """initData is missing, forged, too old or has no user."""


def check_init_data(raw: str, token: str, now: float | None = None) -> tuple[int, str | None]:
    """Return (user_id, start_param) if `raw` is real, fresh initData. Else raise AuthError.

    `now` is only passed by tests, so they don't depend on the clock.
    """
    fields = dict(parse_qsl(raw, keep_blank_values=True))
    given = fields.pop("hash", None)
    if not given:
        raise AuthError("no hash")

    # Rebuild the string Telegram signed, and sign it ourselves.
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    # compare_digest takes the same time whatever matches, so it leaks nothing.
    if not hmac.compare_digest(expected, given):
        raise AuthError("bad signature")

    # A real signature can still be old (e.g. copied from logs). Reject stale data.
    now = time.time() if now is None else now
    try:
        auth_date = int(fields.get("auth_date", ""))
    except ValueError as e:
        raise AuthError("bad auth_date") from e
    if now - auth_date > MAX_AGE:
        raise AuthError("too old")

    try:
        user_id = int(json.loads(fields["user"])["id"])
    except (KeyError, ValueError, TypeError) as e:
        raise AuthError("no user") from e
    return user_id, fields.get("start_param")
