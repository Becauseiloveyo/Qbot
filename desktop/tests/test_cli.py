from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from qbot.cli import _parser, _runtime_token


class CliTests(unittest.TestCase):
    def test_runtime_token_only_reads_environment(self) -> None:
        with patch.dict(os.environ, {"QBOT_ONEBOT_TOKEN": "secret"}, clear=False):
            self.assertEqual(_runtime_token(), "secret")

    def test_diagnostic_parser(self) -> None:
        args = _parser().parse_args(
            ["diagnostic", "--onebot-url", "ws://127.0.0.1:3001/"]
        )
        self.assertEqual(args.command, "diagnostic")
        self.assertEqual(args.onebot_url, "ws://127.0.0.1:3001/")


    def test_run_defaults_to_observe_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            args = _parser().parse_args(["run"])
        self.assertEqual(args.agent_mode, "observe")

    def test_assist_mode_requires_explicit_selection(self) -> None:
        args = _parser().parse_args(["run", "--agent-mode", "assist"])
        self.assertEqual(args.agent_mode, "assist")
    def test_journal_parser_is_read_only_surface(self) -> None:
        args = _parser().parse_args(
            ["journal", "--db", "qbot.db", "--run-id", "run-1", "--json"]
        )
        self.assertEqual(args.command, "journal")
        self.assertEqual(args.run_id, "run-1")
        self.assertTrue(args.json)


if __name__ == "__main__":
    unittest.main()
