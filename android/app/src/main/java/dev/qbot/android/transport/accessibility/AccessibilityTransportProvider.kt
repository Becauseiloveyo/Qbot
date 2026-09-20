package dev.qbot.android.transport.accessibility

object AccessibilityTransportProvider {
    @Volatile
    private var instance: AccessibilityQQTransport? = null

    fun get(): AccessibilityQQTransport {
        instance?.let { return it }

        return synchronized(this) {
            instance ?: AccessibilityQQTransport().also { created ->
                instance = created
            }
        }
    }
}
