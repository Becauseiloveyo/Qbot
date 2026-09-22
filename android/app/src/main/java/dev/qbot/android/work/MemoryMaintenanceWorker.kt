package dev.qbot.android.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import dev.qbot.android.data.MemoryMaintenanceEngine
import dev.qbot.android.data.db.QbotDatabase
import dev.qbot.android.data.db.QbotDatabaseProvider
import dev.qbot.android.runtime.MemoryMaintenanceScheduler

object MemoryMaintenanceRuntimeRegistry {
    @Volatile
    private var factory:
        ((QbotDatabase) -> MemoryMaintenanceEngine)? = null

    fun configure(
        factory: (QbotDatabase) -> MemoryMaintenanceEngine,
    ) {
        this.factory = factory
    }

    fun clear() {
        factory = null
    }

    fun isConfigured(): Boolean = factory != null

    internal fun create(
        database: QbotDatabase,
    ): MemoryMaintenanceEngine? =
        factory?.invoke(database)
}

class MemoryMaintenanceWorker(
    appContext: Context,
    workerParams: WorkerParameters,
) : CoroutineWorker(appContext, workerParams) {
    override suspend fun doWork(): Result {
        val database = QbotDatabaseProvider.get(applicationContext)
        val engine =
            MemoryMaintenanceRuntimeRegistry.create(database)
                ?: return Result.retry()

        return try {
            val eventId = inputData.getString(KEY_EVENT_ID)
            if (eventId == null) {
                val reports = engine.catchUp()
                Result.success(
                    workDataOf(
                        "processed" to reports.size,
                        "failed" to reports.count {
                            it.extractionStatus == "FAILED" ||
                                it.summaryStatus == "FAILED"
                        },
                    ),
                )
            } else {
                val report = engine.processEvent(eventId)
                Result.success(
                    workDataOf(
                        "event_id" to eventId,
                        "extraction_status" to
                            report.extractionStatus,
                        "summary_status" to report.summaryStatus,
                        "candidate_count" to
                            report.candidateIds.size,
                    ),
                )
            }
        } catch (_: IllegalArgumentException) {
            Result.failure()
        } catch (_: IllegalStateException) {
            Result.failure()
        } catch (_: Exception) {
            Result.retry()
        }
    }

    companion object {
        const val KEY_EVENT_ID = "event_id"
    }
}

class WorkManagerMemoryMaintenanceScheduler(
    context: Context,
) : MemoryMaintenanceScheduler {
    private val workManager =
        WorkManager.getInstance(context.applicationContext)

    override fun enqueue(eventId: String) {
        if (!MemoryMaintenanceRuntimeRegistry.isConfigured()) {
            return
        }
        val request =
            OneTimeWorkRequestBuilder<MemoryMaintenanceWorker>()
                .setInputData(
                    Data.Builder()
                        .putString(
                            MemoryMaintenanceWorker.KEY_EVENT_ID,
                            eventId,
                        )
                        .build(),
                )
                .build()
        workManager.enqueueUniqueWork(
            "qbot-memory-maintenance-$eventId",
            ExistingWorkPolicy.KEEP,
            request,
        )
    }

    override fun enqueueCatchUp() {
        if (!MemoryMaintenanceRuntimeRegistry.isConfigured()) {
            return
        }
        val request =
            OneTimeWorkRequestBuilder<MemoryMaintenanceWorker>()
                .build()
        workManager.enqueueUniqueWork(
            "qbot-memory-maintenance-catch-up",
            ExistingWorkPolicy.KEEP,
            request,
        )
    }
}
