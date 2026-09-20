from __future__ import annotations

from dataclasses import dataclass, field

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.persistence.database import BootstrapReport
from qbot.runtime import DesktopCore
from qbot.runtime.decision import DecisionEngine
from qbot.runtime.recovery import RecoveryPlanner
from qbot.runtime.recovery_executor import (
    RecoveryExecutor,
    RecoveryMode,
    RecoveryReport,
)
from qbot.transport import MockTransport, QQTransport


@dataclass(frozen=True, slots=True)
class RuntimeStartReport:
    bootstrap: BootstrapReport
    recovery: RecoveryReport | None

    @property
    def safe_mode(self) -> bool:
        return self.bootstrap.safe_mode


@dataclass(slots=True)
class DesktopRuntime:
    config: QbotConfig
    database: Database
    transport: QQTransport
    core: DesktopCore
    recovery_report: RecoveryReport | None = None
    _transport_started: bool = field(default=False, init=False, repr=False)

    async def start(
        self,
        recovery_mode: RecoveryMode | str = RecoveryMode.OBSERVE,
    ) -> RuntimeStartReport:
        bootstrap = self.database.bootstrap()
        if bootstrap.safe_mode:
            self.recovery_report = None
            return RuntimeStartReport(
                bootstrap=bootstrap,
                recovery=None,
            )

        await self.transport.start()
        self._transport_started = True

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
        return RuntimeStartReport(
            bootstrap=bootstrap,
            recovery=self.recovery_report,
        )

    async def stop(self) -> None:
        if self._transport_started:
            await self.transport.stop()
            self._transport_started = False
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
