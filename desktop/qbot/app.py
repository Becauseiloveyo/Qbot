from __future__ import annotations

from dataclasses import dataclass

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.transport import MockTransport, QQTransport


@dataclass(slots=True)
class DesktopRuntime:
    config: QbotConfig
    database: Database
    transport: QQTransport

    async def start(self) -> None:
        self.database.bootstrap()
        await self.transport.start()

    async def stop(self) -> None:
        await self.transport.stop()
        self.database.close()


def build_runtime(
    config: QbotConfig | None = None,
    transport: QQTransport | None = None,
) -> DesktopRuntime:
    resolved = config or QbotConfig()
    return DesktopRuntime(
        config=resolved,
        database=Database(resolved),
        transport=transport or MockTransport(),
    )
