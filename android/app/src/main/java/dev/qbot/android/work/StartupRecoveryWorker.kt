package dev.qbot.android.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import dev.qbot.android.data.AgentRunRepository
import dev.qbot.android.data.OutboxRepository
import dev.qbot.android.data.db.QbotDatabaseProvider
import dev.qbot.android.runtime.RecoveryExecutor
import dev.qbot.android.runtime.RecoveryMode
import dev.qbot.android.runtime.RecoveryOutcome
import dev.qbot.android.runtime.RecoveryPlanner
import dev.qbot.android.transport.notification.NotificationTransportProvider

class StartupRecoveryWorker(
    appContext: Context,
    workerParams: WorkerParameters,
) : CoroutineWorker(appContext, workerParams) {
    override suspend fun doWork(): Result {
        val database = QbotDatabaseProvider.get(applicationContext)
        val transport =
            NotificationTransportProvider.get(applicationContext)

        return try {
            transport.start()
            val runs = AgentRunRepository(database.qbotDao())
            val outbox = OutboxRepository(database)
            val executor = RecoveryExecutor(
                planner = RecoveryPlanner(
                    runs = runs,
                    outbox = outbox,
                    transport = transport,
                ),
                runs = runs,
                outbox = outbox,
                transport = transport,
            )
            val report = executor.run(RecoveryMode.ASSIST)

            Result.success(
                androidx.work.workDataOf(
                    "planned" to report.plan.items.size,
                    "executed" to report.executions.count {
                        it.outcome in setOf(
                            RecoveryOutcome.SENT,
                            RecoveryOutcome.RECONCILED,
                            RecoveryOutcome.FINALIZED,
                        )
                    },
                    "deferred" to report.executions.count {
                        it.outcome == RecoveryOutcome.DEFERRED
                    },
                    "send_unknown" to report.executions.count {
                        it.outcome == RecoveryOutcome.SEND_UNKNOWN
                    },
                ),
            )
        } catch (_: Exception) {
            Result.retry()
        }
    }

    companion object {
        private const val UNIQUE_WORK_NAME =
            "qbot-android-startup-recovery"

        fun enqueue(context: Context) {
            val request =
                OneTimeWorkRequestBuilder<StartupRecoveryWorker>()
                    .build()

            WorkManager.getInstance(context.applicationContext)
                .enqueueUniqueWork(
                    UNIQUE_WORK_NAME,
                    ExistingWorkPolicy.KEEP,
                    request,
                )
        }
    }
}
