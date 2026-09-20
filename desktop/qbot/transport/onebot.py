from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from websockets.asyncio.client import connect

from .base import (
    IncomingTransportEvent,
    OutgoingMessage,
    QQTransport,
    SendResult,
    TransportCapability,
)


class OneBotTransportConfig(BaseModel):
    """Runtime-only OneBot connection settings.

    Access tokens must be supplied at runtime (environment / OS credential
    integration later) rather than persisted in ordinary Qbot config files.
    """

    model_config = ConfigDict(frozen=True)

    url: str = Field(default="ws://127.0.0.1:3001/")
    access_token: str | None = None
    api_timeout_seconds: float = Field(default=10.0, gt=0)


class OneBotProtocolError(RuntimeError):
    pass


class OneBotCodec:
    @staticmethod
    def event_from_payload(payload: dict[str, Any]) -> IncomingTransportEvent | None:
        if payload.get("post_type") != "message":
            return None

        message_type = payload.get("message_type")
        self_id = payload.get("self_id")
        user_id = payload.get("user_id")
        message_id = payload.get("message_id")
        if self_id is None or user_id is None or message_id is None:
            return None

        if message_type == "private":
            conversation_id = f"private:{user_id}"
        elif message_type == "group":
            group_id = payload.get("group_id")
            if group_id is None:
                return None
            conversation_id = f"group:{group_id}"
        else:
            return None

        timestamp = payload.get("time")
        if isinstance(timestamp, (int, float)):
            occurred_at = datetime.fromtimestamp(timestamp, tz=UTC)
        else:
            occurred_at = datetime.now(UTC)

        raw_message = payload.get("raw_message")
        text = raw_message if isinstance(raw_message, str) else None
        if text is None:
            text = OneBotCodec._extract_text(payload.get("message"))

        metadata = {
            "sub_type": payload.get("sub_type"),
            "sender": payload.get("sender"),
            "message": payload.get("message"),
        }

        return IncomingTransportEvent(
            account_id=str(self_id),
            conversation_id=conversation_id,
            sender_id=str(user_id),
            platform_message_id=str(message_id),
            message_type=str(message_type),
            text=text,
            occurred_at=occurred_at,
            metadata=metadata,
        )

    @staticmethod
    def build_send_action(
        message: OutgoingMessage,
        *,
        echo: str,
    ) -> dict[str, Any]:
        prefix, separator, target = message.conversation_id.partition(":")
        if not separator or not target.isdigit():
            raise OneBotProtocolError(
                "OneBot conversation_id must be private:<qq> or group:<group_id>"
            )

        if prefix == "private":
            action = "send_private_msg"
            params: dict[str, Any] = {
                "user_id": int(target),
                "message": message.text,
                "auto_escape": True,
            }
        elif prefix == "group":
            action = "send_group_msg"
            params = {
                "group_id": int(target),
                "message": message.text,
                "auto_escape": True,
            }
        else:
            raise OneBotProtocolError(
                "OneBot conversation_id must be private:<qq> or group:<group_id>"
            )

        return {
            "action": action,
            "params": params,
            "echo": echo,
        }

    @staticmethod
    def send_result_from_response(payload: dict[str, Any]) -> SendResult:
        status = payload.get("status")
        retcode = payload.get("retcode")
        if status == "ok" and retcode == 0:
            data = payload.get("data")
            message_id = data.get("message_id") if isinstance(data, dict) else None
            return SendResult(
                accepted=True,
                platform_message_id=(
                    str(message_id) if message_id is not None else None
                ),
            )

        return SendResult(
            accepted=False,
            error=f"OneBot API failed: status={status!r}, retcode={retcode!r}",
        )

    @staticmethod
    def _extract_text(message: object) -> str | None:
        if isinstance(message, str):
            return message
        if not isinstance(message, list):
            return None

        parts: list[str] = []
        for segment in message:
            if not isinstance(segment, dict) or segment.get("type") != "text":
                continue
            data = segment.get("data")
            if not isinstance(data, dict):
                continue
            text = data.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts) if parts else None


ConnectFactory = Callable[..., Awaitable[Any]]


class OneBotForwardWsTransport(QQTransport):
    """NapCat / OneBot v11 forward WebSocket transport.

    Uses the combined `/` endpoint: events and API responses share one
    connection. API responses are correlated with request `echo` values.
    """

    def __init__(
        self,
        config: OneBotTransportConfig,
        *,
        connect_factory: ConnectFactory = connect,
    ) -> None:
        self.config = config
        self._connect_factory = connect_factory
        self._connection: Any | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._incoming: asyncio.Queue[IncomingTransportEvent] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader_error: BaseException | None = None

    @property
    def name(self) -> str:
        return "onebot11-forward-ws"

    @property
    def capabilities(self) -> frozenset[TransportCapability]:
        return frozenset(
            {
                TransportCapability.READ_TEXT,
                TransportCapability.SEND_TEXT,
                TransportCapability.GROUP_MESSAGE,
            }
        )

    async def start(self) -> None:
        if self._connection is not None:
            return

        headers = None
        if self.config.access_token:
            headers = {
                "Authorization": f"Bearer {self.config.access_token}",
            }

        self._reader_error = None
        self._connection = await self._connect_factory(
            self.config.url,
            additional_headers=headers,
            proxy=None,
        )
        self._reader_task = asyncio.create_task(
            self._reader_loop(),
            name="qbot-onebot-reader",
        )

    async def stop(self) -> None:
        reader = self._reader_task
        self._reader_task = None

        connection = self._connection
        self._connection = None

        if reader is not None:
            reader.cancel()
        if connection is not None:
            await connection.close()
        if reader is not None:
            try:
                await reader
            except asyncio.CancelledError:
                pass

        self._fail_pending(RuntimeError("OneBot transport stopped"))

    async def receive(self) -> IncomingTransportEvent:
        if self._reader_error is not None and self._incoming.empty():
            raise RuntimeError("OneBot reader stopped") from self._reader_error
        return await self._incoming.get()

    async def send(self, message: OutgoingMessage) -> SendResult:
        connection = self._require_connection()
        echo = f"qbot-{uuid4()}"
        request = OneBotCodec.build_send_action(message, echo=echo)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[echo] = future

        try:
            await connection.send(
                json.dumps(request, ensure_ascii=False, separators=(",", ":"))
            )
            response = await asyncio.wait_for(
                future,
                timeout=self.config.api_timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            self._pending.pop(echo, None)
            return SendResult(
                accepted=False,
                uncertain=True,
                error=f"OneBot response timeout: {exc}",
            )
        except Exception as exc:
            self._pending.pop(echo, None)
            return SendResult(
                accepted=False,
                uncertain=True,
                error=f"OneBot send failed with unknown delivery state: {exc}",
            )

        return OneBotCodec.send_result_from_response(response)

    async def _reader_loop(self) -> None:
        connection = self._require_connection()
        try:
            async for raw in connection:
                try:
                    payload = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, dict):
                    continue

                echo = payload.get("echo")
                if echo is not None:
                    future = self._pending.pop(str(echo), None)
                    if future is not None and not future.done():
                        future.set_result(payload)
                    continue

                event = OneBotCodec.event_from_payload(payload)
                if event is not None:
                    await self._incoming.put(event)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._reader_error = exc
            self._fail_pending(exc)

    def _require_connection(self) -> Any:
        if self._connection is None:
            raise RuntimeError("OneBot transport is not started")
        return self._connection

    def _fail_pending(self, exc: BaseException) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(exc)
