from __future__ import annotations

import os
from typing import Any
import sentry_sdk

DEFAULT_SENTRY_DSN = (
    "https://4cc6afb1660f14e2d91eedc3ae6b4a8d@o107347.ingest.us.sentry.io/4512040254111744"
)

IGNORED_EXCEPTION_NAMES = {
    "WSServerHandshakeError",
    "DiscordServerError",
    "ClientOSError",
    "ServerDisconnectedError",
    "ClientConnectorError",
}

IGNORED_PATTERNS = (
    "WSServerHandshakeError",
    "DiscordServerError",
    "500 Internal Server Error",
    "502 Bad Gateway",
    "503 Service Unavailable",
    "504 Gateway Time-out",
    "Invalid response status",
)


def _should_ignore_exception(exc: BaseException | None) -> bool:
    if exc is None:
        return False

    exc_type_name = type(exc).__name__
    if exc_type_name in IGNORED_EXCEPTION_NAMES:
        return True

    msg = str(exc)
    for pattern in IGNORED_PATTERNS:
        if pattern in msg:
            return True

    if exc.__cause__ and _should_ignore_exception(exc.__cause__):
        return True

    if hasattr(exc, "exceptions"):
        for sub_exc in getattr(exc, "exceptions"):
            if _should_ignore_exception(sub_exc):
                return True

    return False


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    if "exc_info" in hint:
        _, exc_value, _ = hint["exc_info"]
        if isinstance(exc_value, BaseException) and _should_ignore_exception(exc_value):
            return None
    return event


def init_sentry(*, dsn: str | None = None) -> None:
    target_dsn = (
        dsn
        or os.environ.get("SENTRY_DSN")
        or DEFAULT_SENTRY_DSN
    )
    sentry_sdk.init(
        dsn=target_dsn,
        send_default_pii=True,
        before_send=before_send,
    )
