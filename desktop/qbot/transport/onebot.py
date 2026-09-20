from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from websockets.asyncio.client import connect

from qbot.logging import log_event

from .base import (
    IncomingTransportEvent,
    OutgoingMessage,
    QQTransport,
    SendResult,
    TransportCapability,
)

logger = logging.getLogger(__name__)


class OneBotTransportConfig(BaseModel):
    """Runtime-only OneBot connection settings."""

    model_config = ConfigDict(frozen=True)

    url: str = Field(default="ws://127.0.0.1:3001/")
    access_token: str | None = None
    api_timeout_seconds: float = Field(default=10.0, gt=0)
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    reconnect_initial_seconds: float = Field(default=1.0, gt=0)
    reconnect_max_seconds: float = Field(default=30.0, gt=0)


class TransportHealthState(StrEnum):
    STOPPED = "STOPPED"
    CONNECTING = "CONNECTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"


class TransportHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: TransportHealthState
    reconnect_attempts: int = 0
    last_error: str | None = None


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
    """NapCat / OneBot v11 forward WebSocket transport with reconnect."""

    def __init__(
        self,
        config: OneBotTransportConfig,
        *,
        connect_factory: ConnectFactory = connect,
    ) -> None:
        self.config = config
        self._connect_factory = connect_factory
        self._connection: Any | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._incoming: asyncio.Queue[IncomingTransportEvent] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._connected = asyncio.Event()
        self._stopping = False
        self._health_state = TransportHealthState.STOPPED
        self._last_error: str | None = None
        self._reconnect_attempts = 0

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

    @property
    def health(self) -> TransportHealth:
        return TransportHealth(
            state=self._health_state,
            reconnect_attempts=self._reconnect_attempts,
            last_error=self._last_error,
        )

    async def start(self) -> None:
        if self._supervisor_task is not None:
            return

        self._stopping = False
        self._connected.clear()
        self._supervisor_task = asyncio.create_task(
            self._supervisor_loop(),
            name="qbot-onebot-supervisor",
        )
        try:
            await asyncio.wait_for(
                self._connected.wait(),
                timeout=self.config.connect_timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            await self.stop()
            raise RuntimeError(
                f"OneBot initial connection timed out: {self.config.url}"
            ) from exc

    async def stop(self) -> None:
        self._stopping = True
        task = self._supervisor_task
        self._supervisor_task = None

        connection = self._connection
        self._connection = None
        self._connected.clear()

        if task is not None:
            task.cancel()
        if connection is not None:
            await connection.close()
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._fail_pending(RuntimeError("OneBot transport stopped"))
        self._set_health(TransportHealthState.STOPPED, None)

    async def receive(self) -> IncomingTransportEvent:
        if self._stopping and self._incoming.empty():
            raise RuntimeError("OneBot transport is stopped")
        return await self._incoming.get()

    async def send(self, message: OutgoingMessage) -> SendResult:
        if self._connection is None:
            return SendResult(
                accepted=False,
                uncertain=False,
                error="OneBot transport is disconnected",
            )

        request = OneBotCodec.build_send_action(
            message,
            echo=f"qbot-{uuid4()}",
        )
        response, uncertain, error = await self._request_payload(request)
        if response is None:
            return SendResult(
                accepted=False,
                uncertain=uncertain,
                error=error,
            )
        return OneBotCodec.send_result_from_response(response)

    async def call_api(
        self,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._connection is None:
            raise RuntimeError("OneBot transport is disconnected")

        request = {
            "action": action,
            "params": params or {},
            "echo": f"qbot-{uuid4()}",
        }
        response, uncertain, error = await self._request_payload(request)
        if response is None:
            state = "uncertain" if uncertain else "not-sent"
            raise RuntimeError(f"OneBot API {action} failed ({state}): {error}")

        if response.get("status") != "ok" or response.get("retcode") != 0:
            raise OneBotProtocolError(
                f"OneBot API {action} failed: "
                f"status={response.get('status')!r}, "
                f"retcode={response.get('retcode')!r}"
            )

        data = response.get("data")
        return data if isinstance(data, dict) else {}

    async def get_status(self) -> dict[str, Any]:
        return await self.call_api("get_status")

    async def get_version_info(self) -> dict[str, Any]:
        return await self.call_api("get_version_info")

    async def _request_payload(
        self,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, bool, str | None]:
        connection = self._connection
        if connection is None:
            return None, False, "OneBot transport is disconnected"

        echo = str(request["echo"])
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
            return response, False, None
        except (TimeoutError, asyncio.TimeoutError) as exc:
            self._pending.pop(echo, None)
            return None, True, f"OneBot response timeout: {exc}"
        except Exception as exc:
            self._pending.pop(echo, None)
            return None, True, (
                f"OneBot request failed with unknown delivery state: {exc}"
            )

    async def _supervisor_loop(self) -> None:
        delay = self.config.reconnect_initial_seconds
        try:
            while not self._stopping:
                if self._connection is None:
                    self._set_health(TransportHealthState.CONNECTING, self._last_error)
                    try:
                        await self._connect_once()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self._reconnect_attempts += 1
                        self._set_health(TransportHealthState.DEGRADED, str(exc))
                        log_event(
                            logger,
                            "onebot_connect_failed",
                            url=self.config.url,
                            attempt=self._reconnect_attempts,
                            error=str(exc),
                            retry_seconds=delay,
                        )
                        await asyncio.sleep(delay)
                        delay = min(
                            delay * 2,
                            self.config.reconnect_max_seconds,
                        )
                        continue

                connection = self._connection
                if connection is None:
                    continue

                delay = self.config.reconnect_initial_seconds
                try:
                    await self._reader_loop(connection)
                    failure: BaseException = RuntimeError(
                        "OneBot connection closed"
                    )
                except asyncio.CancelledError:
                    raise
                except BaseException as exc:
                    failure = exc

                if self._connection is connection:
                    self._connection = None
                self._connected.clear()
                self._fail_pending(failure)

                if not self._stopping:
                    self._reconnect_attempts += 1
                    self._set_health(
                        TransportHealthState.DEGRADED,
                        str(failure),
                    )
                    log_event(
                        logger,
                        "onebot_disconnected",
                        url=self.config.url,
                        attempt=self._reconnect_attempts,
                        error=str(failure),
                        retry_seconds=delay,
                    )
                    await asyncio.sleep(delay)
                    delay = min(
                        delay * 2,
                        self.config.reconnect_max_seconds,
                    )
        finally:
            self._connected.clear()

    async def _connect_once(self) -> None:
        headers = None
        if self.config.access_token:
            headers = {
                "Authorization": f"Bearer {self.config.access_token}",
            }

        connection = await self._connect_factory(
            self.config.url,
            additional_headers=headers,
            proxy=None,
        )
        self._connection = connection
        self._last_error = None
        self._set_health(TransportHealthState.HEALTHY, None)
        self._connected.set()
        log_event(
            logger,
            "onebot_connected",
            url=self.config.url,
            reconnect_attempts=self._reconnect_attempts,
        )

    async def _reader_loop(self, connection: Any) -> None:
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

    def _set_health(
        self,
        state: TransportHealthState,
        error: str | None,
    ) -> None:
        self._health_state = state
        self._last_error = error

    def _fail_pending(self, exc: BaseException) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(exc)
