from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from qbot.app import build_runtime
from qbot.config import QbotConfig
from qbot.logging import configure_logging
from qbot.transport import MockTransport
from qbot.transport.onebot import (
    OneBotForwardWsTransport,
    OneBotTransportConfig,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qbot-desktop")
    parser.add_argument("--log-level", default=os.getenv("QBOT_LOG_LEVEL", "INFO"))

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the Desktop event service")
    run.add_argument(
        "--transport",
        choices=["mock", "onebot"],
        default=os.getenv("QBOT_TRANSPORT", "mock"),
    )
    run.add_argument(
        "--db",
        default=os.getenv("QBOT_DB", "./data/qbot.db"),
    )
    run.add_argument(
        "--node-id",
        default=os.getenv("QBOT_NODE_ID", "desktop-local"),
    )
    run.add_argument(
        "--onebot-url",
        default=os.getenv("QBOT_ONEBOT_URL", "ws://127.0.0.1:3001/"),
    )

    diag = sub.add_parser(
        "diagnostic",
        help="Connect to OneBot and query status/version without sending chat messages",
    )
    diag.add_argument(
        "--onebot-url",
        default=os.getenv("QBOT_ONEBOT_URL", "ws://127.0.0.1:3001/"),
    )
    diag.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("QBOT_ONEBOT_TIMEOUT", "10")),
    )

    return parser


def _runtime_token() -> str | None:
    token = os.getenv("QBOT_ONEBOT_TOKEN")
    return token if token else None


async def _run(args: argparse.Namespace) -> int:
    config = QbotConfig(
        node_id=args.node_id,
        database_path=Path(args.db),
    )

    if args.transport == "mock":
        transport = MockTransport()
    else:
        transport = OneBotForwardWsTransport(
            OneBotTransportConfig(
                url=args.onebot_url,
                access_token=_runtime_token(),
            )
        )

    runtime = build_runtime(config=config, transport=transport)
    await runtime.start()

    try:
        while True:
            # v0.2 is deliberately observe-only on real transports.
            # It durably admits events but does not generate autonomous replies.
            await runtime.core.process_one()
    finally:
        await runtime.stop()


async def _diagnostic(args: argparse.Namespace) -> int:
    transport = OneBotForwardWsTransport(
        OneBotTransportConfig(
            url=args.onebot_url,
            access_token=_runtime_token(),
            api_timeout_seconds=args.timeout,
        )
    )
    await transport.start()
    try:
        status = await transport.get_status()
        version = await transport.get_version_info()
        print(
            "OneBot diagnostic OK\n"
            f"health={transport.health.state}\n"
            f"online={status.get('online')}\n"
            f"good={status.get('good')}\n"
            f"app_name={version.get('app_name')}\n"
            f"app_version={version.get('app_version')}\n"
            f"protocol_version={version.get('protocol_version')}"
        )
        return 0
    finally:
        await transport.stop()


async def _amain(args: argparse.Namespace) -> int:
    if args.command == "run":
        return await _run(args)
    if args.command == "diagnostic":
        return await _diagnostic(args)
    raise RuntimeError(f"unsupported command: {args.command}")


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    configure_logging(args.log_level)
    try:
        raise SystemExit(asyncio.run(_amain(args)))
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
