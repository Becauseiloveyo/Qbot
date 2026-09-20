package dev.qbot.android.transport.shizuku

import android.content.Context

object ShizukuCapabilityProviderHolder {
    @Volatile
    private var instance: ShizukuCapabilityProvider? = null

    fun get(
        context: Context,
    ): ShizukuCapabilityProvider {
        instance?.let { return it }

        return synchronized(this) {
            instance ?: ApiShizukuCapabilityProvider(
                AndroidShizukuApiFacade(
                    context.applicationContext,
                ),
            ).also { created ->
                instance = created
            }
        }
    }
}
