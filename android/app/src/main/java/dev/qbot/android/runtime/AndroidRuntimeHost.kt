package dev.qbot.android.runtime

import android.content.Context
import dev.qbot.android.data.AgentRunRepository
import dev.qbot.android.data.DurableStateRepository
import dev.qbot.android.data.InboundAdmissionRepository
import dev.qbot.android.data.db.QbotDatabaseProvider
import dev.qbot.android.transport.notification.NotificationTransportProvider
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class AndroidRuntimeHost(
    context: Context,
    private val scope: CoroutineScope = CoroutineScope(
        SupervisorJob() + Dispatchers.Default,
    ),
) {
    private val applicationContext = context.applicationContext
    private val started = AtomicBoolean(false)

    fun start() {
        if (!started.compareAndSet(false, true)) {
            return
        }

        val database = QbotDatabaseProvider.get(applicationContext)
        val transport =
            NotificationTransportProvider.get(applicationContext)
        val dao = database.qbotDao()
        val core = AndroidCore(
            transport = transport,
            admission = InboundAdmissionRepository(database),
            runRepository = AgentRunRepository(dao),
            stateRepository = DurableStateRepository(dao),
        )

        scope.launch {
            transport.start()
            while (isActive) {
                try {
                    core.processOne()
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Exception) {
                    // Durable admission is idempotent. Keep the host alive and
                    // let the next event/recovery pass retry from Room state.
                    delay(250)
                }
            }
        }
    }
}

object AndroidRuntimeHostProvider {
    @Volatile
    private var instance: AndroidRuntimeHost? = null

    fun get(context: Context): AndroidRuntimeHost {
        instance?.let { return it }

        return synchronized(this) {
            instance ?: AndroidRuntimeHost(
                context.applicationContext,
            ).also { created ->
                instance = created
            }
        }
    }
}
