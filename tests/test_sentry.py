from __future__ import annotations

from unittest.mock import patch
from tunapi.sentry import DEFAULT_SENTRY_DSN, init_sentry


def test_init_sentry_default() -> None:
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        mock_init.assert_called_once_with(
            dsn=DEFAULT_SENTRY_DSN,
            send_default_pii=True,
        )


def test_init_sentry_custom_dsn() -> None:
    custom = "https://custom@sentry.io/123"
    with patch("sentry_sdk.init") as mock_init:
        init_sentry(dsn=custom)
        mock_init.assert_called_once_with(
            dsn=custom,
            send_default_pii=True,
        )


def test_init_sentry_env_var(monkeypatch) -> None:
    env_dsn = "https://env@sentry.io/456"
    monkeypatch.setenv("SENTRY_DSN", env_dsn)
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        mock_init.assert_called_once_with(
            dsn=env_dsn,
            send_default_pii=True,
        )
