from __future__ import annotations

import unittest
from datetime import UTC, datetime

from qbot.transport import OutgoingMessage
from qbot.transport.onebot import OneBotCodec, OneBotProtocolError


class OneBotCodecTests(unittest.TestCase):
    def test_private_event_mapping(self) -> None:
        event = OneBotCodec.event_from_payload(
            {
                "time": 1718000000,
                "post_type": "message",
                "message_type": "private",
                "sub_type": "friend",
                "message_id": 1001,
                "user_id": 234567890,
                "message": [{"type": "text", "data": {"text": "你好"}}],
                "raw_message": "你好",
                "sender": {"user_id": 234567890, "nickname": "tester"},
                "self_id": 123456789,
            }
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.account_id, "123456789")
        self.assertEqual(event.conversation_id, "private:234567890")
        self.assertEqual(event.sender_id, "234567890")
        self.assertEqual(event.platform_message_id, "1001")
        self.assertEqual(event.text, "你好")
        self.assertEqual(event.occurred_at.tzinfo, UTC)

    def test_group_event_mapping(self) -> None:
        event = OneBotCodec.event_from_payload(
            {
                "time": 1718000001,
                "post_type": "message",
                "message_type": "group",
                "sub_type": "normal",
                "message_id": 2002,
                "user_id": 345678901,
                "group_id": 987654321,
                "message": [{"type": "text", "data": {"text": "hi"}}],
                "raw_message": "hi",
                "sender": {"user_id": 345678901},
                "self_id": 123456789,
            }
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.conversation_id, "group:987654321")
        self.assertEqual(event.message_type, "group")

    def test_message_sent_event_is_ignored(self) -> None:
        event = OneBotCodec.event_from_payload(
            {
                "time": 1718000000,
                "post_type": "message_sent",
                "message_type": "private",
                "message_id": 1,
                "user_id": 2,
                "raw_message": "self",
                "self_id": 3,
            }
        )
        self.assertIsNone(event)

    def test_private_send_action_uses_auto_escape(self) -> None:
        action = OneBotCodec.build_send_action(
            OutgoingMessage(
                account_id="123",
                conversation_id="private:456",
                dedupe_key="run-1:reply",
                text="[CQ:at,qq=1] literal",
            ),
            echo="echo-1",
        )
        self.assertEqual(action["action"], "send_private_msg")
        self.assertEqual(action["params"]["user_id"], 456)
        self.assertTrue(action["params"]["auto_escape"])
        self.assertEqual(action["echo"], "echo-1")

    def test_group_send_action(self) -> None:
        action = OneBotCodec.build_send_action(
            OutgoingMessage(
                account_id="123",
                conversation_id="group:789",
                dedupe_key="run-1:reply",
                text="hello",
            ),
            echo="echo-2",
        )
        self.assertEqual(action["action"], "send_group_msg")
        self.assertEqual(action["params"]["group_id"], 789)

    def test_invalid_conversation_id_is_rejected(self) -> None:
        with self.assertRaises(OneBotProtocolError):
            OneBotCodec.build_send_action(
                OutgoingMessage(
                    account_id="123",
                    conversation_id="bad-id",
                    dedupe_key="run-1:reply",
                    text="hello",
                ),
                echo="echo-3",
            )

    def test_api_success_response_returns_message_id(self) -> None:
        result = OneBotCodec.send_result_from_response(
            {
                "status": "ok",
                "retcode": 0,
                "data": {"message_id": 9001},
                "echo": "echo-1",
            }
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.platform_message_id, "9001")


if __name__ == "__main__":
    unittest.main()
