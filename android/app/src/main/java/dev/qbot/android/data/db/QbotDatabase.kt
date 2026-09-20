package dev.qbot.android.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

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
        MemoryEntity::class,
    ],
    version = 2,
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
    val MIGRATION_1_2: Migration = object : Migration(1, 2) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL(
                """
                CREATE TABLE IF NOT EXISTS `memories` (
                    `memory_id` TEXT NOT NULL,
                    `schema_version` TEXT NOT NULL,
                    `state` TEXT NOT NULL,
                    `scope` TEXT NOT NULL,
                    `owner_id` TEXT,
                    `conversation_id` TEXT,
                    `task_id` TEXT,
                    `content` TEXT NOT NULL,
                    `entities_json` TEXT NOT NULL,
                    `importance` REAL,
                    `trust` REAL NOT NULL,
                    `confidence` REAL,
                    `source_type` TEXT NOT NULL,
                    `source_message_id` TEXT,
                    `source_event_id` TEXT,
                    `valid_from` TEXT,
                    `valid_to` TEXT,
                    `supersedes` TEXT,
                    `created_at` TEXT NOT NULL,
                    PRIMARY KEY(`memory_id`),
                    FOREIGN KEY(`supersedes`) REFERENCES `memories`(`memory_id`)
                        ON UPDATE NO ACTION ON DELETE RESTRICT
                )
                """.trimIndent(),
            )
            db.execSQL(
                "CREATE INDEX IF NOT EXISTS " +
                    "`index_memories_conversation_id_state_created_at` " +
                    "ON `memories` (`conversation_id`, `state`, `created_at`)",
            )
            db.execSQL(
                "CREATE INDEX IF NOT EXISTS " +
                    "`index_memories_task_id_state_created_at` " +
                    "ON `memories` (`task_id`, `state`, `created_at`)",
            )
            db.execSQL(
                "CREATE INDEX IF NOT EXISTS " +
                    "`index_memories_scope_owner_id_state` " +
                    "ON `memories` (`scope`, `owner_id`, `state`)",
            )
            db.execSQL(
                "CREATE INDEX IF NOT EXISTS `index_memories_source_event_id` " +
                    "ON `memories` (`source_event_id`)",
            )
            db.execSQL(
                "CREATE INDEX IF NOT EXISTS `index_memories_supersedes` " +
                    "ON `memories` (`supersedes`)",
            )
        }
    }

    val ALL: Array<Migration> = arrayOf(MIGRATION_1_2)
}
