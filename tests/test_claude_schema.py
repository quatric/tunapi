from __future__ import annotations

from pathlib import Path

import pytest

from tunapi.schemas import claude as claude_schema


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / name


def _decode_fixture(name: str) -> list[str]:
    path = _fixture_path(name)
    errors: list[str] = []

    for lineno, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        try:
            decoded = claude_schema.decode_stream_json_line(line)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"line {lineno}: {exc.__class__.__name__}: {exc}")
            continue

        _ = decoded

    return errors


@pytest.mark.parametrize(
    "fixture",
    [
        "claude_stream_json_session.jsonl",
        "claude_rate_limit_event.jsonl",
    ],
)
def test_claude_schema_parses_fixture(fixture: str) -> None:
    errors = _decode_fixture(fixture)

    assert not errors, f"{fixture} had {len(errors)} errors: " + "; ".join(errors[:5])


def test_claude_schema_parses_tool_progress_event() -> None:
    event = claude_schema.decode_stream_json_line(
        b'{"type":"tool_progress","tool_use_id":"toolu_123",'
        b'"tool_name":"Bash","elapsed_time_seconds":30.0,'
        b'"uuid":"uuid","session_id":"session","unexpected":"ignored"}'
    )

    assert isinstance(event, claude_schema.StreamToolProgressMessage)
    assert event.tool_use_id == "toolu_123"
    assert event.elapsed_time_seconds == 30.0
