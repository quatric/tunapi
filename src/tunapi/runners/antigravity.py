"""Google Antigravity CLI runner."""

from __future__ import annotations

import re
import shutil
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..backends import EngineBackend, EngineConfig
from ..account_pool import looks_exhausted, rotate_account, select_account
from ..config import ConfigError
from ..events import EventFactory
from ..logging import get_logger
from ..model import (
    Action,
    ActionKind,
    CompletedEvent,
    EngineId,
    ResumeToken,
    TunapiEvent,
)
from ..runner import JsonlSubprocessRunner, ResumeTokenMixin, Runner
from .run_options import get_run_options

logger = get_logger(__name__)
ENGINE: EngineId = "antigravity"
_RESUME_RE = re.compile(r"(?im)^\s*`?agy\s+--conversation\s+(?P<token>[^`\s]+)`?\s*$")


@dataclass(slots=True)
class AntigravityStreamState:
    factory: EventFactory = field(default_factory=lambda: EventFactory(ENGINE))
    pending_actions: dict[int, Action] = field(default_factory=dict)
    conversation_id: str | None = None
    answer: str = ""
    saw_result: bool = False
    note_seq: int = 0
    account_home: str | None = None


def _get_account_homes() -> tuple[str, ...]:
    accounts_dir = Path("/var/lib/tunapi-accounts")
    if not accounts_dir.is_dir():
        return ()
    found = sorted(str(p) for p in accounts_dir.iterdir() if p.is_dir() and p.name.startswith("antigravity-"))
    return tuple(found)


_ACCOUNT_MARKER = "/var/lib/tunapi-accounts/antigravity-active"


def _tool_action(step_index: int, update: dict[str, Any]) -> Action:
    tool_info = update.get("tool_info")
    if not isinstance(tool_info, dict):
        tool_info = {}
    tool_name = update.get("tool_name") or tool_info.get("name") or "tool"
    tool_name = str(tool_name)
    params = tool_info.get("parameters")
    if not isinstance(params, dict):
        params = {}

    name = tool_name.lower()
    kind: ActionKind = "tool"
    title = tool_name
    if name in {"run_command", "send_command_input", "command_status"}:
        kind = "command"
        command = params.get("CommandLine") or params.get("command")
        title = str(command or tool_name)
    elif name in {
        "replace_file_content",
        "multi_replace_file_content",
        "write_to_file",
        "notebook_edit",
    }:
        kind = "file_change"
        path = params.get("TargetFile") or params.get("FilePath") or params.get("path")
        title = str(path or tool_name)
    elif name in {"search_web", "read_url_content", "open_browser_url"}:
        kind = "web_search"
        query = params.get("query") or params.get("URL") or params.get("url")
        title = str(query or tool_name)
    elif name in {"invoke_subagent", "define_subagent", "manage_subagents"}:
        kind = "subagent"
    elif name in {"view_file", "list_dir", "grep_search", "find_by_name"}:
        path = (
            params.get("DirectoryPath")
            or params.get("FilePath")
            or params.get("SearchPath")
            or params.get("path")
        )
        title = f"{tool_name}: {path}" if path else tool_name

    # Titles are displayed in Discord. Keep them useful without allowing a huge
    # command or prompt to dominate the progress message.
    if len(title) > 300:
        title = f"{title[:297]}..."
    return Action(
        id=f"antigravity.tool.{step_index}",
        kind=kind,
        title=title,
        detail={"name": tool_name, "step_index": step_index},
    )


@dataclass(slots=True)
class AntigravityRunner(ResumeTokenMixin, JsonlSubprocessRunner):
    engine: EngineId = ENGINE
    resume_re: re.Pattern[str] = _RESUME_RE
    agy_cmd: str = "agy"
    model: str | None = None
    dangerously_skip_permissions: bool = True
    print_timeout: str = "30m"
    add_dirs: tuple[str, ...] = ("/workspace",)
    logger = logger

    def format_resume(self, token: ResumeToken) -> str:
        return f"`agy --conversation {token.value}`"

    def command(self) -> str:
        return self.agy_cmd

    def build_args(
        self, prompt: str, resume: ResumeToken | None, *, state: Any
    ) -> list[str]:
        args = [
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--print-timeout",
            self.print_timeout,
        ]
        for directory in self.add_dirs:
            args.extend(["--add-dir", directory])
        if self.dangerously_skip_permissions:
            args.append("--dangerously-skip-permissions")
        if resume is not None:
            args.extend(["--conversation", resume.value])
        run_options = get_run_options()
        model = run_options.model if run_options and run_options.model else self.model
        if model:
            args.extend(["--model", model])
        return args

    def stdin_payload(
        self, prompt: str, resume: ResumeToken | None, *, state: Any
    ) -> bytes | None:
        return None

    def new_state(
        self, prompt: str, resume: ResumeToken | None
    ) -> AntigravityStreamState:
        return AntigravityStreamState(
            conversation_id=resume.value if resume is not None else None,
            account_home=select_account(
                _get_account_homes(),
                marker=_ACCOUNT_MARKER,
                resume_token=resume.value if resume else None,
                session_pattern=(".gemini/antigravity-cli/conversations/{token}.db"),
            ),
        )

    def env(self, *, state: Any) -> dict[str, str] | None:
        env = dict(os.environ)
        if isinstance(state, AntigravityStreamState) and state.account_home:
            env["HOME"] = state.account_home
        return env

    def translate(
        self,
        data: Any,
        *,
        state: AntigravityStreamState,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
    ) -> list[TunapiEvent]:
        if not isinstance(data, dict):
            return []
        event_type = data.get("event")
        conversation_id = data.get("conversation_id")
        if not isinstance(conversation_id, str):
            payload = data.get(event_type)
            if isinstance(payload, dict):
                conversation_id = payload.get("conversation_id")
        if isinstance(conversation_id, str) and conversation_id:
            state.conversation_id = conversation_id

        token = (
            ResumeToken(engine=ENGINE, value=state.conversation_id)
            if state.conversation_id
            else None
        )
        if event_type == "init" and token is not None:
            meta = None
            if state.account_home:
                meta = {"account": Path(state.account_home).name}
            return [state.factory.started(token, title=self.model or ENGINE, meta=meta)]
        if event_type == "step_update":
            update = data.get("step_update")
            if not isinstance(update, dict):
                return []
            if update.get("step_type") == "agent_response":
                delta = update.get("text_delta")
                if isinstance(delta, str):
                    state.answer += delta
                return []
            if update.get("step_type") != "tool":
                return []

            step_index = update.get("step_index")
            if not isinstance(step_index, int):
                return []
            action = state.pending_actions.get(step_index)
            if action is None:
                action = _tool_action(step_index, update)
                state.pending_actions[step_index] = action
            action_state = update.get("state")
            if action_state == "ACTIVE":
                return [
                    state.factory.action_started(
                        action_id=action.id,
                        kind=action.kind,
                        title=action.title,
                        detail=action.detail,
                    )
                ]
            if action_state in {"DONE", "ERROR", "FAILED", "CANCELLED"}:
                state.pending_actions.pop(step_index, None)
                ok = action_state == "DONE"
                detail = dict(action.detail)
                duration = update.get("duration_seconds")
                if isinstance(duration, int | float):
                    detail["duration_seconds"] = duration
                return [
                    state.factory.action_completed(
                        action_id=action.id,
                        kind=action.kind,
                        title=action.title,
                        detail=detail,
                        ok=ok,
                        level=None if ok else "error",
                    )
                ]
            return []
        if event_type == "result":
            result = data.get("result")
            if not isinstance(result, dict):
                return []
            state.saw_result = True
            response = result.get("response")
            answer = response if isinstance(response, str) else state.answer
            ok = result.get("status") == "SUCCESS"
            error = str(result.get("error") or "antigravity failed")
            if (
                not ok
                and error
                and (
                    "context cancel" in error.lower()
                    or "context canceled" in error.lower()
                )
            ):
                if answer and answer.strip():
                    ok = True
                    error = None
            if not ok and looks_exhausted(error):
                rotate_account(
                    _get_account_homes(),
                    marker=_ACCOUNT_MARKER,
                    current=state.account_home,
                    mark_exhausted=True,
                )
            usage = (
                result.get("usage") if isinstance(result.get("usage"), dict) else None
            )
            return [
                CompletedEvent(
                    engine=ENGINE,
                    ok=ok,
                    answer=answer.strip(),
                    resume=token or resume,
                    error=None if ok else error,
                    usage=usage,
                )
            ]
        return []

    def process_error_events(
        self,
        rc: int,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: AntigravityStreamState,
        stderr: str = "",
    ) -> list[TunapiEvent]:
        message = f"antigravity failed (rc={rc})."
        if stderr.strip():
            detail = stderr.strip().splitlines()[-1]
            message = f"antigravity failed (rc={rc}): {detail}"
        return [
            CompletedEvent(
                engine=ENGINE,
                ok=False,
                answer=state.answer.strip(),
                resume=found_session or resume,
                error=message,
            )
        ]

    def stream_end_events(
        self,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: AntigravityStreamState,
    ) -> list[TunapiEvent]:
        if state.saw_result:
            return []
        return [
            CompletedEvent(
                engine=ENGINE,
                ok=False,
                answer=state.answer.strip(),
                resume=found_session or resume,
                error="antigravity finished without a result event",
            )
        ]


def build_runner(config: EngineConfig, config_path: Path) -> Runner:
    model = config.get("model")
    if model is not None and not isinstance(model, str):
        raise ConfigError(
            f"Invalid `antigravity.model` in {config_path}; expected a string."
        )
    skip = config.get("dangerously_skip_permissions", True)
    if not isinstance(skip, bool):
        raise ConfigError(
            "Invalid `antigravity.dangerously_skip_permissions`; expected a boolean."
        )
    print_timeout = config.get("print_timeout", "30m")
    if not isinstance(print_timeout, str) or not print_timeout.strip():
        raise ConfigError(
            "Invalid `antigravity.print_timeout`; expected a non-empty string."
        )
    add_dirs = config.get("add_dirs", ["/workspace"])
    if not isinstance(add_dirs, list) or not all(
        isinstance(directory, str) and directory for directory in add_dirs
    ):
        raise ConfigError(
            "Invalid `antigravity.add_dirs`; expected a list of non-empty strings."
        )
    return AntigravityRunner(
        agy_cmd=shutil.which("agy") or "agy",
        model=model,
        dangerously_skip_permissions=skip,
        print_timeout=print_timeout,
        add_dirs=tuple(add_dirs),
    )


BACKEND = EngineBackend(
    id="antigravity",
    build_runner=build_runner,
    cli_cmd="agy",
)
