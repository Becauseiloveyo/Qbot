package dev.qbot.android.transport.accessibility

import android.accessibilityservice.AccessibilityService
import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo

class AndroidAccessibilityUiDriver(
    private val service: AccessibilityService,
) : AccessibilityUiDriver {
    private data class ResolvedUi(
        val inspection: AccessibilityUiInspection,
        val composers: List<AccessibilityNodeInfo>,
        val sendActions: List<AccessibilityNodeInfo>,
    )

    override fun inspect(
        profile: AccessibilityUiProfile,
    ): AccessibilityUiInspection? {
        val root = service.rootInActiveWindow
            ?: return null
        return resolve(root, profile).inspection
    }

    override fun setComposerText(
        profile: AccessibilityUiProfile,
        expectedConversationToken: String,
        text: String,
    ): Boolean {
        val root = service.rootInActiveWindow
            ?: return false
        val resolved = resolve(root, profile)
        if (
            resolved.inspection.conversationToken !=
            expectedConversationToken ||
            !resolved.inspection.controlsAreUnambiguous
        ) {
            return false
        }

        val composer = resolved.composers.singleOrNull()
            ?: return false
        val arguments = Bundle().apply {
            putCharSequence(
                AccessibilityNodeInfo
                    .ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                text,
            )
        }

        return composer.performAction(
            AccessibilityNodeInfo.ACTION_SET_TEXT,
            arguments,
        )
    }

    override fun clickSend(
        profile: AccessibilityUiProfile,
        expectedConversationToken: String,
    ): Boolean {
        val root = service.rootInActiveWindow
            ?: return false
        val resolved = resolve(root, profile)
        if (
            resolved.inspection.conversationToken !=
            expectedConversationToken ||
            !resolved.inspection.controlsAreUnambiguous
        ) {
            return false
        }

        val send = resolved.sendActions.singleOrNull()
            ?: return false
        return send.performAction(
            AccessibilityNodeInfo.ACTION_CLICK,
        )
    }

    private fun resolve(
        root: AccessibilityNodeInfo,
        profile: AccessibilityUiProfile,
    ): ResolvedUi {
        val packageName = root.packageName
            ?.toString()
            .orEmpty()

        if (packageName != profile.packageName) {
            return ResolvedUi(
                inspection = AccessibilityUiInspection(
                    packageName = packageName,
                    conversationToken = null,
                    composerMatches = 0,
                    sendActionMatches = 0,
                ),
                composers = emptyList(),
                sendActions = emptyList(),
            )
        }

        val tokenValues = nodesByIds(
            root,
            profile.conversationTokenViewIds,
        )
            .mapNotNull(::nodeText)
            .map(String::trim)
            .filter(String::isNotEmpty)
            .distinct()

        val composers = nodesByIds(
            root,
            profile.composerViewIds,
        ).filter(::isSafeComposer)

        val sends = nodesByIds(
            root,
            profile.sendActionViewIds,
        ).filter(::isSafeSendAction)

        return ResolvedUi(
            inspection = AccessibilityUiInspection(
                packageName = packageName,
                conversationToken = tokenValues.singleOrNull(),
                composerMatches = composers.size,
                sendActionMatches = sends.size,
            ),
            composers = composers,
            sendActions = sends,
        )
    }

    private fun nodesByIds(
        root: AccessibilityNodeInfo,
        viewIds: Set<String>,
    ): List<AccessibilityNodeInfo> =
        viewIds
            .flatMap { viewId ->
                runCatching {
                    root.findAccessibilityNodeInfosByViewId(viewId)
                }.getOrDefault(emptyList())
            }
            .distinct()

    private fun nodeText(
        node: AccessibilityNodeInfo,
    ): String? =
        node.text?.toString()
            ?.takeIf { it.isNotBlank() }
            ?: node.contentDescription
                ?.toString()
                ?.takeIf { it.isNotBlank() }

    private fun isSafeComposer(
        node: AccessibilityNodeInfo,
    ): Boolean =
        node.isEnabled &&
            node.isVisibleToUser &&
            node.isEditable &&
            (
                node.actionList.any {
                    it.id == AccessibilityNodeInfo.ACTION_SET_TEXT
                } ||
                    (
                        node.actions and
                            AccessibilityNodeInfo.ACTION_SET_TEXT
                        ) != 0
                )

    private fun isSafeSendAction(
        node: AccessibilityNodeInfo,
    ): Boolean =
        node.isEnabled &&
            node.isVisibleToUser &&
            node.isClickable &&
            (
                node.actionList.any {
                    it.id == AccessibilityNodeInfo.ACTION_CLICK
                } ||
                    (
                        node.actions and
                            AccessibilityNodeInfo.ACTION_CLICK
                        ) != 0
                )
}
