package dev.qbot.android.transport.accessibility

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessibilityUiReplySessionTest {
    private val profile = AccessibilityUiProfile(
        profileId = "qq-known-layout-1",
        packageName = "com.tencent.mobileqq",
        conversationTokenViewIds = setOf("qq:id/conversation_token"),
        composerViewIds = setOf("qq:id/composer"),
        sendActionViewIds = setOf("qq:id/send"),
    )

    private val binding = AccessibilityConversationBinding(
        accountId = "acc-1",
        conversationId = "conv-1",
        packageName = "com.tencent.mobileqq",
        expectedConversationToken = "token-42",
        profileId = profile.profileId,
    )

    @Test
    fun mismatchedProfileBindingCannotBeArmed() {
        val mismatched = AccessibilitySessionSpec(
            profile = profile,
            binding = binding.copy(
                profileId = "different-profile",
            ),
        )

        try {
            AccessibilitySessionSpecProvider.arm(mismatched)
            throw AssertionError("mismatched binding should have been rejected")
        } catch (_: IllegalArgumentException) {
            // Expected.
        } finally {
            AccessibilitySessionSpecProvider.clear()
        }
    }

    @Test
    fun exactProfileTokenAndUniqueControlsCreateValidSession() {
        val driver = FakeDriver(
            inspection = matchingInspection(),
        )
        val session = ProfileBoundAccessibilityReplySession(
            AccessibilitySessionSpec(profile, binding),
            driver,
        )

        assertTrue(session.isValid())
    }

    @Test
    fun sameTitleIsIrrelevantWhenExactTokenDoesNotMatch() {
        val driver = FakeDriver(
            inspection = matchingInspection().copy(
                conversationToken = "different-token",
            ),
        )
        val session = ProfileBoundAccessibilityReplySession(
            AccessibilitySessionSpec(profile, binding),
            driver,
        )

        assertFalse(session.isValid())
    }

    @Test
    fun ambiguousComposerOrSendControlFailsClosed() {
        val driver = FakeDriver(
            inspection = matchingInspection().copy(
                composerMatches = 2,
            ),
        )
        val session = ProfileBoundAccessibilityReplySession(
            AccessibilitySessionSpec(profile, binding),
            driver,
        )

        assertFalse(session.isValid())
    }

    @Test
    fun conversationIsRevalidatedAfterTypingBeforeClick() = runTest {
        val driver = FakeDriver(
            inspection = matchingInspection(),
            inspectionAfterText = matchingInspection().copy(
                conversationToken = "changed-conversation",
            ),
        )
        val session = ProfileBoundAccessibilityReplySession(
            AccessibilitySessionSpec(profile, binding),
            driver,
        )

        val result = session.sendText("hello")

        assertFalse(result.actionAccepted)
        assertEquals(1, driver.setTextCalls)
        assertEquals(0, driver.clickCalls)
    }

    @Test
    fun exactSessionSetsTextThenClicksOnce() = runTest {
        val driver = FakeDriver(
            inspection = matchingInspection(),
        )
        val session = ProfileBoundAccessibilityReplySession(
            AccessibilitySessionSpec(profile, binding),
            driver,
        )

        val result = session.sendText("hello")

        assertTrue(result.actionAccepted)
        assertEquals("hello", driver.lastText)
        assertEquals(1, driver.setTextCalls)
        assertEquals(1, driver.clickCalls)
    }

    private fun matchingInspection(): AccessibilityUiInspection =
        AccessibilityUiInspection(
            packageName = "com.tencent.mobileqq",
            conversationToken = "token-42",
            composerMatches = 1,
            sendActionMatches = 1,
        )

    private class FakeDriver(
        private var inspection: AccessibilityUiInspection?,
        private val inspectionAfterText: AccessibilityUiInspection? = null,
    ) : AccessibilityUiDriver {
        var setTextCalls = 0
        var clickCalls = 0
        var lastText: String? = null

        override fun inspect(
            profile: AccessibilityUiProfile,
        ): AccessibilityUiInspection? =
            inspection

        override fun setComposerText(
            profile: AccessibilityUiProfile,
            text: String,
        ): Boolean {
            setTextCalls += 1
            lastText = text
            if (inspectionAfterText != null) {
                inspection = inspectionAfterText
            }
            return true
        }

        override fun clickSend(
            profile: AccessibilityUiProfile,
        ): Boolean {
            clickCalls += 1
            return true
        }
    }
}
