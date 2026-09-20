package dev.qbot.android.runtime

import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class ConversationLockManager {
    private data class Key(
        val accountId: String,
        val conversationId: String,
    )

    private val locks = ConcurrentHashMap<Key, Mutex>()

    suspend fun <T> serial(
        accountId: String,
        conversationId: String,
        block: suspend () -> T,
    ): T {
        val mutex = locks.computeIfAbsent(
            Key(accountId, conversationId),
        ) { Mutex() }

        return mutex.withLock {
            block()
        }
    }
}
