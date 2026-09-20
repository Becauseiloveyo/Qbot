package dev.qbot.android.transport.notification

import android.app.Notification
import android.service.notification.StatusBarNotification
import java.security.MessageDigest

enum class ConversationIdentityQuality {
    APP_SHORTCUT,
    APP_LOCUS,
    TITLE_FALLBACK,
    NOTIFICATION_SLOT,
}

data class ResolvedConversationIdentity(
    val conversationId: String,
    val quality: ConversationIdentityQuality,
)

class NotificationConversationIdentityResolver {
    fun resolve(sbn: StatusBarNotification): ResolvedConversationIdentity {
        val notification = sbn.notification
        val packageName = sbn.packageName

        notification.shortcutId
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?.let { shortcutId ->
                return resolved(
                    packageName = packageName,
                    quality = ConversationIdentityQuality.APP_SHORTCUT,
                    material = shortcutId,
                )
            }

        notification.locusId
            ?.id
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?.let { locusId ->
                return resolved(
                    packageName = packageName,
                    quality = ConversationIdentityQuality.APP_LOCUS,
                    material = locusId,
                )
            }

        notification.extras
            .getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)
            ?.toString()
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?.let { title ->
                return resolved(
                    packageName = packageName,
                    quality = ConversationIdentityQuality.TITLE_FALLBACK,
                    material = normalizeTitle(title),
                )
            }

        notification.extras
            .getCharSequence(Notification.EXTRA_TITLE)
            ?.toString()
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?.let { title ->
                return resolved(
                    packageName = packageName,
                    quality = ConversationIdentityQuality.TITLE_FALLBACK,
                    material = normalizeTitle(title),
                )
            }

        return resolved(
            packageName = packageName,
            quality = ConversationIdentityQuality.NOTIFICATION_SLOT,
            material = listOf(
                sbn.tag.orEmpty(),
                sbn.id.toString(),
            ).joinToString("|"),
        )
    }

    private fun resolved(
        packageName: String,
        quality: ConversationIdentityQuality,
        material: String,
    ): ResolvedConversationIdentity {
        val digest = sha256(
            listOf(
                packageName,
                quality.name,
                material,
            ).joinToString("\u001f"),
        )
        return ResolvedConversationIdentity(
            conversationId = "android-notification:" +
                packageName + ":" +
                quality.name.lowercase() + ":" +
                digest.take(24),
            quality = quality,
        )
    }

    private fun normalizeTitle(value: String): String =
        value
            .replace(Regex("\\s+"), " ")
            .trim()
            .lowercase()

    private fun sha256(value: String): String =
        MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
            .joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
}
