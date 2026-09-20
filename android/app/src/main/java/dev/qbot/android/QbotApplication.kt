package dev.qbot.android

import android.app.Application
import dev.qbot.android.runtime.AndroidRuntimeHostProvider
import dev.qbot.android.work.StartupRecoveryWorker

class QbotApplication : Application() {
    override fun onCreate() {
        super.onCreate()

        AndroidRuntimeHostProvider.get(this).start()
        StartupRecoveryWorker.enqueue(this)
    }
}
