package dev.qbot.android.runtime

import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ConversationLockManagerTest {
    @Test
    fun sameConversationNeverRunsAuthoritativeBlocksConcurrently() = runTest {
        val locks = ConversationLockManager()
        val active = AtomicInteger(0)
        val maxActive = AtomicInteger(0)

        val jobs = (1..20).map {
            async {
                locks.serial("acc-1", "conv-1") {
                    val now = active.incrementAndGet()
                    maxActive.updateAndGet { previous -> maxOf(previous, now) }
                    repeat(3) { yield() }
                    active.decrementAndGet()
                }
            }
        }
        jobs.awaitAll()

        assertEquals(1, maxActive.get())
    }

    @Test
    fun differentConversationsCanProgressIndependently() = runTest {
        val locks = ConversationLockManager()
        val entered = mutableSetOf<String>()

        val first = async {
            locks.serial("acc-1", "conv-a") {
                entered += "a"
                yield()
            }
        }
        val second = async {
            locks.serial("acc-1", "conv-b") {
                entered += "b"
                yield()
            }
        }

        awaitAll(first, second)
        assertTrue(entered.containsAll(setOf("a", "b")))
    }
}
