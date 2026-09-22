package dev.qbot.android.runtime

interface MemoryMaintenanceScheduler {
    fun enqueue(eventId: String)

    fun enqueueCatchUp()
}
