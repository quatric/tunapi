from typing import Any, Protocol

from ..transport import (
    Transport,
    MessageRef,
    SendOptions,
    RenderedMessage,
)

import dataclasses
import json
import uuid

from ..logging import get_logger

logger = get_logger(__name__)


class WsSendable(Protocol):
    async def send(self, data: str) -> None: ...


def _dc_to_dict(obj: Any) -> dict[str, Any]:
    """dataclass를 dict로 변환, None 필드 제외"""
    return {k: v for k, v in dataclasses.asdict(obj).items() if v is not None}


class TunadishTransport(Transport):
    """
    tunadish 클라이언트로 rendered message를 전파(Relay)하는 Transport 구현체.
    """

    def __init__(self, ws: WsSendable):
        self._ws = ws
        self._pending_rpc_id: str | int | None = None

    def set_rpc_id(self, rpc_id: str | int | None) -> None:
        """다음 _send_notification 호출을 JSON-RPC 2.0 response로 변환."""
        self._pending_rpc_id = rpc_id

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        rpc_id = self._pending_rpc_id
        if rpc_id is not None:
            self._pending_rpc_id = None
            if "error" in params and isinstance(params["error"], str):
                raw = json.dumps({
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32000, "message": params["error"]},
                })
            else:
                raw = json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": params})
        else:
            raw = json.dumps({"method": method, "params": params})
        try:
            await self._ws.send(raw)
        except Exception as e:
            logger.error("ws.push_failed", error=str(e))

    async def _send_response(self, rpc_id: str | int, result: dict[str, Any]) -> None:
        """JSON-RPC 2.0 성공 response 전송."""
        raw = json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result})
        try:
            await self._ws.send(raw)
        except Exception as e:
            logger.error("ws.push_failed", error=str(e))

    async def _send_error(self, rpc_id: str | int, code: int, message: str) -> None:
        """JSON-RPC 2.0 에러 response 전송."""
        raw = json.dumps({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": code, "message": message},
        })
        try:
            await self._ws.send(raw)
        except Exception as e:
            logger.error("ws.push_failed", error=str(e))

    async def send(
        self,
        *,
        channel_id: str,
        message: RenderedMessage,
        options: SendOptions | None = None,
    ) -> MessageRef | None:
        ref = MessageRef(channel_id=channel_id, message_id=str(uuid.uuid4()))
        await self._send_notification(
            method="message.new",
            params={"ref": _dc_to_dict(ref), "message": _dc_to_dict(message)},
        )
        return ref

    async def edit(
        self,
        *,
        ref: MessageRef,
        message: RenderedMessage,
        wait: bool = True,
    ) -> MessageRef | None:
        await self._send_notification(
            method="message.update",
            params={"ref": _dc_to_dict(ref), "message": _dc_to_dict(message)},
        )
        return ref

    async def delete(self, *, ref: MessageRef) -> bool:
        await self._send_notification(
            method="message.delete",
            params={"ref": _dc_to_dict(ref)},
        )
        return True

    async def close(self) -> None:
        pass
