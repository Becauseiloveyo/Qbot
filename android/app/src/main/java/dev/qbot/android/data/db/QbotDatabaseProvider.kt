package dev.qbot.android.data.db

import android.content.Context

object QbotDatabaseProvider {
    @Volatile
    private var instance: QbotDatabase? = null

    fun get(context: Context): QbotDatabase {
        instance?.let { return it }

        return synchronized(this) {
            instance ?: QbotDatabase.build(
                context.applicationContext,
            ).also { created ->
                instance = created
            }
        }
    }
}
