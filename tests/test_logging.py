"""The bot token must never appear in logs.

httpx logs every request URL at INFO level, and Telegram URLs contain
the token (https://api.telegram.org/bot<TOKEN>/...). So httpx must log
at WARNING or above.
"""

import logging

import travelkaki.main  # noqa: F401  (importing sets up logging)


def test_httpx_does_not_log_request_urls():
    # Check the level set on the httpx logger itself. (Effective level is unreliable
    # under pytest, which adds its own log handlers.)
    assert logging.getLogger("httpx").level >= logging.WARNING
