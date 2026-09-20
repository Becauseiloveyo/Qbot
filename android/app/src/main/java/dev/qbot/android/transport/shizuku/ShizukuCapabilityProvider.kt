package dev.qbot.android.transport.shizuku

import android.content.Context
import android.content.pm.PackageManager
import rikka.shizuku.Shizuku

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

enum class ShizukuPermissionRequestResult {
    ALREADY_GRANTED,
    REQUESTED,
    SERVICE_UNAVAILABLE,
    DENIED_WITH_RATIONALE,
    FAILED,
}

interface ShizukuCapabilityProvider {
    fun snapshot(): ShizukuCapabilitySnapshot

    fun requestPermission(
        requestCode: Int,
    ): ShizukuPermissionRequestResult =
        ShizukuPermissionRequestResult.SERVICE_UNAVAILABLE
}

interface ShizukuApiFacade {
    fun isManagerInstalled(): Boolean
    fun pingBinder(): Boolean
    fun checkSelfPermission(): Int
    fun shouldShowRequestPermissionRationale(): Boolean
    fun requestPermission(requestCode: Int)
}

class AndroidShizukuApiFacade(
    context: Context,
) : ShizukuApiFacade {
    private val applicationContext = context.applicationContext

    override fun isManagerInstalled(): Boolean =
        try {
            applicationContext.packageManager.getApplicationInfo(
                SHIZUKU_MANAGER_PACKAGE,
                0,
            )
            true
        } catch (_: PackageManager.NameNotFoundException) {
            false
        }

    override fun pingBinder(): Boolean =
        Shizuku.pingBinder()

    override fun checkSelfPermission(): Int =
        Shizuku.checkSelfPermission()

    override fun shouldShowRequestPermissionRationale(): Boolean =
        Shizuku.shouldShowRequestPermissionRationale()

    override fun requestPermission(
        requestCode: Int,
    ) {
        Shizuku.requestPermission(requestCode)
    }

    companion object {
        const val SHIZUKU_MANAGER_PACKAGE =
            "moe.shizuku.privileged.api"
    }
}

/**
 * Optional Shizuku integration.
 *
 * READY proves only a live, authorized system-API bridge. It does not prove
 * access to QQ conversation identity, message history, or send semantics.
 */
class ApiShizukuCapabilityProvider(
    private val api: ShizukuApiFacade,
) : ShizukuCapabilityProvider {
    override fun snapshot(): ShizukuCapabilitySnapshot =
        try {
            when {
                !api.isManagerInstalled() ->
                    emptySnapshot(
                        state = ShizukuProviderState.NOT_INSTALLED,
                        detail = "Shizuku manager is not installed",
                    )

                !api.pingBinder() ->
                    emptySnapshot(
                        state = ShizukuProviderState.SERVICE_STOPPED,
                        detail = "Shizuku binder is not running",
                    )

                api.checkSelfPermission() !=
                    PackageManager.PERMISSION_GRANTED ->
                    emptySnapshot(
                        state = ShizukuProviderState.PERMISSION_REQUIRED,
                        detail = "Qbot has not been granted Shizuku permission",
                    )

                else ->
                    ShizukuCapabilitySnapshot(
                        state = ShizukuProviderState.READY,
                        capabilities = setOf(
                            ShizukuSystemCapability.SYSTEM_API_BRIDGE,
                        ),
                        detail = "authorized Shizuku system API bridge",
                    )
            }
        } catch (failure: RuntimeException) {
            emptySnapshot(
                state = ShizukuProviderState.UNAVAILABLE,
                detail = failure.message
                    ?: failure::class.java.simpleName,
            )
        }

    override fun requestPermission(
        requestCode: Int,
    ): ShizukuPermissionRequestResult {
        return try {
            when {
                !api.isManagerInstalled() || !api.pingBinder() ->
                    ShizukuPermissionRequestResult.SERVICE_UNAVAILABLE

                api.checkSelfPermission() ==
                    PackageManager.PERMISSION_GRANTED ->
                    ShizukuPermissionRequestResult.ALREADY_GRANTED

                api.shouldShowRequestPermissionRationale() ->
                    ShizukuPermissionRequestResult.DENIED_WITH_RATIONALE

                else -> {
                    api.requestPermission(requestCode)
                    ShizukuPermissionRequestResult.REQUESTED
                }
            }
        } catch (_: RuntimeException) {
            ShizukuPermissionRequestResult.FAILED
        }
    }

    private fun emptySnapshot(
        state: ShizukuProviderState,
        detail: String,
    ): ShizukuCapabilitySnapshot =
        ShizukuCapabilitySnapshot(
            state = state,
            capabilities = emptySet(),
            detail = detail,
        )
}

class NoShizukuCapabilityProvider : ShizukuCapabilityProvider {
    override fun snapshot(): ShizukuCapabilitySnapshot =
        ShizukuCapabilitySnapshot(
            state = ShizukuProviderState.NOT_INSTALLED,
            capabilities = emptySet(),
            detail = "Shizuku integration is optional and not available",
        )
}
