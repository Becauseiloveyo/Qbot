package dev.qbot.android.transport.shizuku

enum class ShizukuProviderState {
    NOT_INSTALLED,
    SERVICE_STOPPED,
    PERMISSION_REQUIRED,
    READY,
    UNAVAILABLE,
}

enum class ShizukuSystemCapability {
    SYSTEM_API_BRIDGE,
    PACKAGE_QUERY,
    START_ACTIVITY,
}

data class ShizukuCapabilitySnapshot(
    val state: ShizukuProviderState,
    val capabilities: Set<ShizukuSystemCapability>,
    val detail: String? = null,
)

interface ShizukuCapabilityProvider {
    fun snapshot(): ShizukuCapabilitySnapshot
}

/**
 * Deliberately reports no QQTransport capabilities.
 *
 * Shizuku is a privileged system-API bridge. It is not, by itself, proof that
 * Qbot can read QQ messages, identify a QQ conversation, or send a QQ reply.
 * An enhanced QQ adapter may consume this provider, but must independently
 * advertise and test its own QQTransport capabilities.
 */
class NoShizukuCapabilityProvider : ShizukuCapabilityProvider {
    override fun snapshot(): ShizukuCapabilitySnapshot =
        ShizukuCapabilitySnapshot(
            state = ShizukuProviderState.NOT_INSTALLED,
            capabilities = emptySet(),
            detail = "Shizuku integration is optional and not available",
        )
}
