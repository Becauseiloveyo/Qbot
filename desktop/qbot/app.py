from __future__ import annotations

from dataclasses import dataclass

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.runtime import DesktopCore
from qbot.transport import MockTransport, QQTransport


@dataclass(slots=True)
class DesktopRuntime:
    config: QbotConfig
    database: Database
    transport: QQTransport
    core: DesktopCore

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
    database = Database(resolved)
    resolved_transport = transport or MockTransport()
    return DesktopRuntime(
        config=resolved,
        database=database,
        transport=resolved_transport,
        core=DesktopCore(database, resolved_transport),
    )
