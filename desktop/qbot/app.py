from __future__ import annotations

from dataclasses import dataclass

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.runtime import DesktopCore
from qbot.runtime.decision import DecisionEngine
from qbot.runtime.recovery import RecoveryPlanner
from qbot.runtime.recovery_executor import (
    RecoveryExecutor,
    RecoveryMode,
    RecoveryReport,
)
from qbot.transport import MockTransport, QQTransport


@dataclass(slots=True)
class DesktopRuntime:
    config: QbotConfig
    database: Database
    transport: QQTransport
    core: DesktopCore
    recovery_report: RecoveryReport | None = None

    async def start(
        self,
        recovery_mode: RecoveryMode | str = RecoveryMode.OBSERVE,
    ) -> RecoveryReport:
        self.database.bootstrap()
        await self.transport.start()

        planner = RecoveryPlanner(
            runs=self.core.runs,
            outbox=self.core.outbox,
            transport=self.transport,
        )
        executor = RecoveryExecutor(
            planner=planner,
            runs=self.core.runs,
            outbox=self.core.outbox,
            journal=self.core.journal,
            transport=self.transport,
            reply_flow=self.core.reply_flow,
        )
        self.recovery_report = await executor.run(recovery_mode)
        return self.recovery_report

    async def stop(self) -> None:
        await self.transport.stop()
        self.database.close()


def build_runtime(
    config: QbotConfig | None = None,
    transport: QQTransport | None = None,
    decision: DecisionEngine | None = None,
) -> DesktopRuntime:
    resolved = config or QbotConfig()
    database = Database(resolved)
    resolved_transport = transport or MockTransport()
    return DesktopRuntime(
        config=resolved,
        database=database,
        transport=resolved_transport,
        core=DesktopCore(database, resolved_transport, decision=decision),
    )
