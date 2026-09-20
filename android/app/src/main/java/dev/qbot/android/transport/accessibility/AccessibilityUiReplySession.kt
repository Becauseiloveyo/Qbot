package dev.qbot.android.transport.accessibility

data class AccessibilityUiProfile(
    val profileId: String,
    val packageName: String,
    val conversationTokenViewIds: Set<String>,
    val composerViewIds: Set<String>,
    val sendActionViewIds: Set<String>,
) {
    init {
        require(profileId.isNotBlank())
        require(packageName.isNotBlank())
        require(conversationTokenViewIds.isNotEmpty())
        require(composerViewIds.isNotEmpty())
        require(sendActionViewIds.isNotEmpty())
    }
}

data class AccessibilityConversationBinding(
    val accountId: String,
    val conversationId: String,
    val packageName: String,
    val expectedConversationToken: String,
    val profileId: String,
)

data class AccessibilityUiInspection(
    val packageName: String,
    val conversationToken: String?,
    val composerMatches: Int,
    val sendActionMatches: Int,
) {
    val controlsAreUnambiguous: Boolean
        get() =
            composerMatches == 1 &&
                sendActionMatches == 1
}

interface AccessibilityUiDriver {
    fun inspect(
        profile: AccessibilityUiProfile,
    ): AccessibilityUiInspection?

    fun setComposerText(
        profile: AccessibilityUiProfile,
        text: String,
    ): Boolean

    fun clickSend(
        profile: AccessibilityUiProfile,
    ): Boolean
}

data class AccessibilitySessionSpec(
    val profile: AccessibilityUiProfile,
    val binding: AccessibilityConversationBinding,
)

class ProfileBoundAccessibilityReplySession(
    private val spec: AccessibilitySessionSpec,
    private val driver: AccessibilityUiDriver,
) : AccessibilityReplySession {
    override val accountId: String =
        spec.binding.accountId

    override val conversationId: String =
        spec.binding.conversationId

    override fun isValid(): Boolean =
        inspectMatchesBinding()

    override suspend fun sendText(
        text: String,
    ): AccessibilityReplyResult {
        if (!inspectMatchesBinding()) {
            return AccessibilityReplyResult(
                actionAccepted = false,
                error = "accessibility UI no longer matches bound conversation",
            )
        }

        if (!driver.setComposerText(spec.profile, text)) {
            return AccessibilityReplyResult(
                actionAccepted = false,
                error = "accessibility composer rejected text action",
            )
        }

        // Re-check after editing and before the external send action. If the
        // window changed while text was being inserted, fail closed and do
        // not click another conversation's send control.
        if (!inspectMatchesBinding()) {
            return AccessibilityReplyResult(
                actionAccepted = false,
                error = "accessibility conversation changed before send action",
            )
        }

        if (!driver.clickSend(spec.profile)) {
            return AccessibilityReplyResult(
                actionAccepted = false,
                error = "accessibility send action was not accepted",
            )
        }

        return AccessibilityReplyResult(
            actionAccepted = true,
        )
    }

    private fun inspectMatchesBinding(): Boolean {
        val profile = spec.profile
        val binding = spec.binding

        if (
            profile.profileId != binding.profileId ||
            profile.packageName != binding.packageName
        ) {
            return false
        }

        val inspection = driver.inspect(profile)
            ?: return false

        return inspection.packageName == binding.packageName &&
            inspection.conversationToken ==
            binding.expectedConversationToken &&
            inspection.controlsAreUnambiguous
    }
}

/**
 * Process-local only. Exact UI bindings are intentionally not persisted.
 *
 * After process death the enhanced adapter must be re-armed from a trusted,
 * freshly verified source before it can address an Outbox conversation.
 */
object AccessibilitySessionSpecProvider {
    @Volatile
    private var spec: AccessibilitySessionSpec? = null

    fun current(): AccessibilitySessionSpec? = spec

    fun arm(value: AccessibilitySessionSpec) {
        spec = value
    }

    fun clear() {
        spec = null
    }
}
