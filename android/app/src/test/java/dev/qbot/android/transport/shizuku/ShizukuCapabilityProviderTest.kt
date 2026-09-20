package dev.qbot.android.transport.shizuku

import android.content.pm.PackageManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ShizukuCapabilityProviderTest {
    @Test
    fun missingManagerReportsNotInstalled() {
        val api = FakeApi(
            installed = false,
            binder = false,
            permission = PackageManager.PERMISSION_DENIED,
        )

        val snapshot = ApiShizukuCapabilityProvider(api).snapshot()

        assertEquals(ShizukuProviderState.NOT_INSTALLED, snapshot.state)
        assertTrue(snapshot.capabilities.isEmpty())
    }

    @Test
    fun stoppedBinderReportsServiceStopped() {
        val api = FakeApi(
            installed = true,
            binder = false,
            permission = PackageManager.PERMISSION_DENIED,
        )

        val snapshot = ApiShizukuCapabilityProvider(api).snapshot()

        assertEquals(ShizukuProviderState.SERVICE_STOPPED, snapshot.state)
        assertTrue(snapshot.capabilities.isEmpty())
    }

    @Test
    fun liveBinderWithoutPermissionReportsPermissionRequired() {
        val api = FakeApi(
            installed = true,
            binder = true,
            permission = PackageManager.PERMISSION_DENIED,
        )

        val snapshot = ApiShizukuCapabilityProvider(api).snapshot()

        assertEquals(
            ShizukuProviderState.PERMISSION_REQUIRED,
            snapshot.state,
        )
        assertTrue(snapshot.capabilities.isEmpty())
    }

    @Test
    fun grantedProviderAdvertisesOnlySystemBridge() {
        val api = FakeApi(
            installed = true,
            binder = true,
            permission = PackageManager.PERMISSION_GRANTED,
        )

        val snapshot = ApiShizukuCapabilityProvider(api).snapshot()

        assertEquals(ShizukuProviderState.READY, snapshot.state)
        assertEquals(
            setOf(ShizukuSystemCapability.SYSTEM_API_BRIDGE),
            snapshot.capabilities,
        )
    }

    @Test
    fun requestPermissionDoesNotRunWithoutLiveBinder() {
        val api = FakeApi(
            installed = true,
            binder = false,
            permission = PackageManager.PERMISSION_DENIED,
        )
        val provider = ApiShizukuCapabilityProvider(api)

        val result = provider.requestPermission(42)

        assertEquals(
            ShizukuPermissionRequestResult.SERVICE_UNAVAILABLE,
            result,
        )
        assertEquals(0, api.requestCalls)
    }

    @Test
    fun requestPermissionIsExplicitAndOnlyRequestedOncePerCall() {
        val api = FakeApi(
            installed = true,
            binder = true,
            permission = PackageManager.PERMISSION_DENIED,
            rationale = false,
        )
        val provider = ApiShizukuCapabilityProvider(api)

        val result = provider.requestPermission(42)

        assertEquals(ShizukuPermissionRequestResult.REQUESTED, result)
        assertEquals(1, api.requestCalls)
        assertEquals(42, api.lastRequestCode)
    }

    @Test
    fun rationaleStateDoesNotSilentlyRequestAgain() {
        val api = FakeApi(
            installed = true,
            binder = true,
            permission = PackageManager.PERMISSION_DENIED,
            rationale = true,
        )
        val provider = ApiShizukuCapabilityProvider(api)

        val result = provider.requestPermission(9)

        assertEquals(
            ShizukuPermissionRequestResult.DENIED_WITH_RATIONALE,
            result,
        )
        assertEquals(0, api.requestCalls)
    }

    private class FakeApi(
        private val installed: Boolean,
        private val binder: Boolean,
        private val permission: Int,
        private val rationale: Boolean = false,
    ) : ShizukuApiFacade {
        var requestCalls = 0
        var lastRequestCode: Int? = null

        override fun isManagerInstalled(): Boolean = installed

        override fun pingBinder(): Boolean = binder

        override fun checkSelfPermission(): Int = permission

        override fun shouldShowRequestPermissionRationale(): Boolean =
            rationale

        override fun requestPermission(requestCode: Int) {
            requestCalls += 1
            lastRequestCode = requestCode
        }
    }
}
