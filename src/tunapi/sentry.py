from __future__ import annotations

import os
import sentry_sdk

DEFAULT_SENTRY_DSN = (
    "https://4cc6afb1660f14e2d91eedc3ae6b4a8d@o107347.ingest.us.sentry.io/4512040254111744"
)


def init_sentry(*, dsn: str | None = None) -> None:
    target_dsn = (
        dsn
        or os.environ.get("SENTRY_DSN")
        or DEFAULT_SENTRY_DSN
    )
    sentry_sdk.init(
        dsn=target_dsn,
        send_default_pii=True,
    )
