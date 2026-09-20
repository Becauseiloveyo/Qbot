from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qbot.config import QbotConfig
from qbot.persona import ContactProfile, Persona
from qbot.persistence import Database
from qbot.persistence.persona_store import PersonaStore


class PersonaStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            QbotConfig(database_path=Path(self.tmp.name) / "qbot.db")
        )
        self.db.bootstrap()
        self.store = PersonaStore(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_default_and_per_contact_persona_selection(self) -> None:
        default = Persona(
            persona_id="default",
            identity_summary="默认语气",
            style_rules=("简短",),
        )
        close_friend = Persona(
            persona_id="friend-style",
            identity_summary="熟人语气",
            style_rules=("更随意",),
        )
        self.store.upsert_persona(default, set_default=True)
        self.store.upsert_persona(close_friend)
        self.store.upsert_contact(
            ContactProfile(
                contact_id="contact-1",
                relation="classmate",
                stable_facts=("同班同学",),
                style_overrides=("少用标点",),
            ),
            persona_id="friend-style",
        )

        persona, contact = self.store.load_selected(
            contact_id="contact-1",
            fallback_persona=Persona(),
        )
        self.assertEqual(persona.persona_id, "friend-style")
        self.assertEqual(contact.relation, "classmate")
        self.assertEqual(contact.stable_facts, ("同班同学",))

        persona2, contact2 = self.store.load_selected(
            contact_id="unknown",
            fallback_persona=Persona(),
        )
        self.assertEqual(persona2.persona_id, "default")
        self.assertIsNone(contact2)

    def test_updates_are_visible_without_cache(self) -> None:
        self.store.upsert_persona(
            Persona(persona_id="default", identity_summary="v1"),
            set_default=True,
        )
        first, _ = self.store.load_selected(
            contact_id=None,
            fallback_persona=Persona(),
        )
        self.assertEqual(first.identity_summary, "v1")

        self.store.upsert_persona(
            Persona(persona_id="default", identity_summary="v2")
        )
        second, _ = self.store.load_selected(
            contact_id=None,
            fallback_persona=Persona(),
        )
        self.assertEqual(second.identity_summary, "v2")


if __name__ == "__main__":
    unittest.main()
