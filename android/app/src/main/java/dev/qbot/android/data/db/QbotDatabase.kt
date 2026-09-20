package dev.qbot.android.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration

@Database(
    entities = [
        MetaEntity::class,
        InboundEventEntity::class,
        AgentRunEntity::class,
        TaskEntity::class,
        TaskStepEntity::class,
        TaskCheckpointEntity::class,
        OutboxMessageEntity::class,
        JournalEntity::class,
        PersonaEntity::class,
        ContactProfileEntity::class,
    ],
    version = 1,
    exportSchema = true,
)
abstract class QbotDatabase : RoomDatabase() {
    abstract fun qbotDao(): QbotDao

    companion object {
        const val DATABASE_NAME = "qbot.db"

        fun build(context: Context): QbotDatabase =
            Room.databaseBuilder(
                context.applicationContext,
                QbotDatabase::class.java,
                DATABASE_NAME,
            )
                .addMigrations(*QbotMigrations.ALL)
                .build()
    }
}

object QbotMigrations {
    // Android schema v1 is the first persistent schema. Future upgrades must
    // append explicit Migration objects here. Destructive fallback is forbidden.
    val ALL: Array<Migration> = emptyArray()
}
