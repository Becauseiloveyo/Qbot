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


if __name__ == "__main__":
    unittest.main()
