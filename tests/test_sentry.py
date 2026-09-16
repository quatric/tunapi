from __future__ import annotations

from unittest.mock import patch
from tunapi.sentry import DEFAULT_SENTRY_DSN, before_send, init_sentry


def test_init_sentry_default() -> None:
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        mock_init.assert_called_once_with(
            dsn=DEFAULT_SENTRY_DSN,
            send_default_pii=True,
            before_send=before_send,
        )


def test_init_sentry_custom_dsn() -> None:
    custom = "https://custom@sentry.io/123"
    with patch("sentry_sdk.init") as mock_init:
        init_sentry(dsn=custom)
        mock_init.assert_called_once_with(
            dsn=custom,
            send_default_pii=True,
            before_send=before_send,
        )


def test_init_sentry_env_var(monkeypatch) -> None:
    env_dsn = "https://env@sentry.io/456"
    monkeypatch.setenv("SENTRY_DSN", env_dsn)
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        mock_init.assert_called_once_with(
            dsn=env_dsn,
            send_default_pii=True,
            before_send=before_send,
        )


def test_before_send_filters_transient_discord_errors() -> None:
    class WSServerHandshakeError(Exception):
        pass

    class DiscordServerError(Exception):
        pass

    event = {"event_id": "123"}

    # WSServerHandshakeError is dropped
    assert before_send(event, {"exc_info": (WSServerHandshakeError, WSServerHandshakeError("Invalid response status"), None)}) is None

    # DiscordServerError is dropped
    assert before_send(event, {"exc_info": (DiscordServerError, DiscordServerError("500 Internal Server Error"), None)}) is None

    # Generic exception with matching message is dropped
    assert before_send(event, {"exc_info": (RuntimeError, RuntimeError("Failed with 500 Internal Server Error (error code: 0)"), None)}) is None

    # Chained exception is dropped
    cause_exc = DiscordServerError("500 Internal Server Error")
    wrapper_exc = RuntimeError("Wrapped error")
    wrapper_exc.__cause__ = cause_exc
    assert before_send(event, {"exc_info": (RuntimeError, wrapper_exc, None)}) is None

    # Normal application exceptions are preserved
    assert before_send(event, {"exc_info": (ValueError, ValueError("invalid input"), None)}) == event
    assert before_send(event, {}) == event
