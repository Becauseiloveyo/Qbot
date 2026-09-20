from __future__ import annotations

import asyncio
import json
import unittest

from qbot.transport import OutgoingMessage
from qbot.transport.onebot import (
    OneBotForwardWsTransport,
    OneBotTransportConfig,
)


_STOP = object()


class FakeConnection:
    def __init__(self, *, auto_api_response: bool = True) -> None:
        self.incoming: asyncio.Queue[object] = asyncio.Queue()
        self.sent: list[dict[str, object]] = []
        self.closed = False
        self.auto_api_response = auto_api_response

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.incoming.get()
        if item is _STOP:
            raise StopAsyncIteration
        return item

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        if self.auto_api_response and "echo" in payload:
            await self.incoming.put(
                json.dumps(
                    {
                        "status": "ok",
                        "retcode": 0,
                        "data": {"message_id": 7788},
                        "echo": payload["echo"],
                    }
                )
            )

    async def close(self) -> None:
        self.closed = True
        await self.incoming.put(_STOP)

    async def push(self, payload: dict[str, object]) -> None:
        await self.incoming.put(json.dumps(payload))


class OneBotForwardWsTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_combined_socket_routes_events_and_echo_responses(self) -> None:
        connection = FakeConnection()
        connect_args: dict[str, object] = {}

        async def fake_connect(url: str, **kwargs):
            connect_args["url"] = url
            connect_args.update(kwargs)
            return connection

        transport = OneBotForwardWsTransport(
            OneBotTransportConfig(
                url="ws://127.0.0.1:3001/",
                access_token="secret",
                api_timeout_seconds=1,
            ),
            connect_factory=fake_connect,
        )
        await transport.start()
        try:
            self.assertEqual(connect_args["url"], "ws://127.0.0.1:3001/")
            self.assertEqual(
                connect_args["additional_headers"],
                {"Authorization": "Bearer secret"},
            )
            self.assertIsNone(connect_args["proxy"])

            await connection.push(
                {
                    "time": 1718000000,
                    "post_type": "message",
                    "message_type": "private",
                    "sub_type": "friend",
                    "message_id": 1001,
                    "user_id": 456,
                    "message": [{"type": "text", "data": {"text": "你好"}}],
                    "raw_message": "你好",
                    "sender": {"user_id": 456},
                    "self_id": 123,
                }
            )
            event = await asyncio.wait_for(transport.receive(), timeout=1)
            self.assertEqual(event.conversation_id, "private:456")

            result = await transport.send(
                OutgoingMessage(
                    account_id="123",
                    conversation_id="private:456",
                    dedupe_key="run-1:reply",
                    text="收到",
                )
            )
            self.assertTrue(result.accepted)
            self.assertEqual(result.platform_message_id, "7788")
            self.assertEqual(connection.sent[0]["action"], "send_private_msg")
        finally:
            await transport.stop()

    async def test_api_timeout_returns_uncertain_delivery(self) -> None:
        connection = FakeConnection(auto_api_response=False)

        async def fake_connect(_url: str, **_kwargs):
            return connection

        transport = OneBotForwardWsTransport(
            OneBotTransportConfig(
                api_timeout_seconds=0.01,
            ),
            connect_factory=fake_connect,
        )
        await transport.start()
        try:
            result = await transport.send(
                OutgoingMessage(
                    account_id="123",
                    conversation_id="private:456",
                    dedupe_key="run-2:reply",
                    text="收到",
                )
            )
            self.assertFalse(result.accepted)
            self.assertTrue(result.uncertain)
        finally:
            await transport.stop()


if __name__ == "__main__":
    unittest.main()
