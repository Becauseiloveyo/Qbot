package dev.qbot.android.transport.accessibility

import dev.qbot.android.transport.DeliveryLookupResult
import dev.qbot.android.transport.IncomingTransportEvent
import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.QQTransport
import dev.qbot.android.transport.SendAvailability
import dev.qbot.android.transport.SendReadiness
import dev.qbot.android.transport.SendResult
import dev.qbot.android.transport.TransportCapability
import dev.qbot.android.transport.routing.AdapterHealth
import dev.qbot.android.transport.routing.AdapterTier
import dev.qbot.android.transport.routing.TransportAdapterSnapshot

data class AccessibilityReplyResult(
    val actionAccepted: Boolean,
    val uncertain: Boolean = false,
    val error: String? = null,
)

interface AccessibilityReplySession {
    val accountId: String
    val conversationId: String

    fun isValid(): Boolean

    suspend fun sendText(text: String): AccessibilityReplyResult
}

class AccessibilityQQTransport : QQTransport {
    @Volatile
    private var started = false

    @Volatile
    private var serviceConnected = false

    @Volatile
    private var replySession: AccessibilityReplySession? = null

    override val name: String = "android-accessibility"

    override val capabilities: Set<TransportCapability>
        get() =
            if (
                started &&
                serviceConnected &&
                replySession?.isValid() == true
            ) {
                setOf(TransportCapability.SEND_TEXT)
            } else {
                emptySet()
            }

    override suspend fun start() {
        started = true
    }

    override suspend fun stop() {
        started = false
        replySession = null
    }

    override suspend fun receive(): IncomingTransportEvent =
        error(
            "AccessibilityQQTransport does not advertise READ_TEXT; " +
                "it is not an inbound event source in v0.6",
        )

    override suspend fun checkSendReadiness(
        message: OutgoingMessage,
    ): SendReadiness {
        if (!started) {
            return SendReadiness(
                SendAvailability.TEMPORARILY_UNAVAILABLE,
                "accessibility transport is not started",
            )
        }
        if (!serviceConnected) {
            return SendReadiness(
                SendAvailability.TEMPORARILY_UNAVAILABLE,
                "accessibility service is not connected",
            )
        }

        val session = replySession
            ?: return SendReadiness(
                SendAvailability.TEMPORARILY_UNAVAILABLE,
                "no positively recognized QQ reply session",
            )

        if (!session.isValid()) {
            replySession = null
            return SendReadiness(
                SendAvailability.TEMPORARILY_UNAVAILABLE,
                "recognized QQ reply session is no longer valid",
            )
        }

        if (
            session.accountId != message.accountId ||
            session.conversationId != message.conversationId
        ) {
            return SendReadiness(
                SendAvailability.UNSUPPORTED,
                "accessibility session cannot address this Qbot conversation",
            )
        }

        return SendReadiness(SendAvailability.READY)
    }

    override suspend fun send(
        message: OutgoingMessage,
    ): SendResult {
        val readiness = checkSendReadiness(message)
        if (!readiness.ready) {
            return SendResult(
                accepted = false,
                error = readiness.reason,
            )
        }

        val session = requireNotNull(replySession)
        val result = session.sendText(message.text)

        return when {
            result.uncertain -> SendResult(
                accepted = false,
                uncertain = true,
                error = result.error
                    ?: "accessibility send action outcome is uncertain",
            )

            result.actionAccepted -> SendResult(
                accepted = true,
            )

            else -> SendResult(
                accepted = false,
                error = result.error
                    ?: "accessibility send action was rejected",
            )
        }
    }

    override suspend fun lookupDelivery(
        accountId: String,
        dedupeKey: String,
    ): DeliveryLookupResult =
        DeliveryLookupResult(found = false)

    fun onServiceConnected() {
        serviceConnected = true
    }

    fun onServiceDisconnected() {
        serviceConnected = false
        started = false
        replySession = null
    }

    fun updateReplySession(
        session: AccessibilityReplySession?,
    ) {
        replySession = session
    }

    fun snapshot(
        priority: Int = 20,
    ): TransportAdapterSnapshot {
        val session = replySession
        val health = when {
            !started -> AdapterHealth.STOPPED
            !serviceConnected -> AdapterHealth.PERMISSION_REQUIRED
            session?.isValid() == true -> AdapterHealth.READY
            else -> AdapterHealth.DEGRADED
        }

        return TransportAdapterSnapshot(
            adapterId = name,
            tier = AdapterTier.ENHANCED,
            health = health,
            capabilities = capabilities,
            priority = priority,
            detail = when (health) {
                AdapterHealth.STOPPED ->
                    "accessibility transport is stopped"
                AdapterHealth.PERMISSION_REQUIRED ->
                    "accessibility service is not enabled/connected"
                AdapterHealth.DEGRADED ->
                    "QQ UI is connected but no safe reply session is recognized"
                AdapterHealth.READY ->
                    "exact Qbot conversation reply session is available"
                AdapterHealth.UNAVAILABLE ->
                    "accessibility transport is unavailable"
            },
        )
    }
}
