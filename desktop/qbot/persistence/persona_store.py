from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from qbot.persona import ContactProfile, Persona

from .database import Database
from .tables import contact_profiles, personas, qbot_meta


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_tuple(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


class PersonaStore:
    """Authoritative persisted Persona / ContactProfile selection."""

    DEFAULT_PERSONA_KEY = "default_persona_id"

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_persona(
        self,
        persona: Persona,
        *,
        set_default: bool = False,
    ) -> None:
        with self.database.transaction() as conn:
            existing_version = conn.execute(
                select(personas.c.version).where(
                    personas.c.persona_id == persona.persona_id
                )
            ).scalar_one_or_none()
            version = (int(existing_version) + 1) if existing_version else 1
            conn.execute(
                sqlite_insert(personas)
                .values(
                    persona_id=persona.persona_id,
                    identity_summary=persona.identity_summary,
                    style_rules_json=json.dumps(
                        list(persona.style_rules),
                        ensure_ascii=False,
                    ),
                    hard_constraints_json=json.dumps(
                        list(persona.hard_constraints),
                        ensure_ascii=False,
                    ),
                    version=version,
                    updated_at=_now(),
                )
                .on_conflict_do_update(
                    index_elements=["persona_id"],
                    set_={
                        "identity_summary": persona.identity_summary,
                        "style_rules_json": json.dumps(
                            list(persona.style_rules),
                            ensure_ascii=False,
                        ),
                        "hard_constraints_json": json.dumps(
                            list(persona.hard_constraints),
                            ensure_ascii=False,
                        ),
                        "version": version,
                        "updated_at": _now(),
                    },
                )
            )
            if set_default:
                conn.execute(
                    sqlite_insert(qbot_meta)
                    .values(
                        key=self.DEFAULT_PERSONA_KEY,
                        value=persona.persona_id,
                    )
                    .on_conflict_do_update(
                        index_elements=["key"],
                        set_={"value": persona.persona_id},
                    )
                )

    def set_default_persona(self, persona_id: str) -> None:
        with self.database.transaction() as conn:
            exists = conn.execute(
                select(personas.c.persona_id).where(
                    personas.c.persona_id == persona_id
                )
            ).scalar_one_or_none()
            if exists is None:
                raise KeyError(f"unknown persona: {persona_id}")

            conn.execute(
                sqlite_insert(qbot_meta)
                .values(key=self.DEFAULT_PERSONA_KEY, value=persona_id)
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={"value": persona_id},
                )
            )

    def upsert_contact(
        self,
        profile: ContactProfile,
        *,
        persona_id: str | None = None,
    ) -> None:
        with self.database.transaction() as conn:
            if persona_id is not None:
                exists = conn.execute(
                    select(personas.c.persona_id).where(
                        personas.c.persona_id == persona_id
                    )
                ).scalar_one_or_none()
                if exists is None:
                    raise KeyError(f"unknown persona: {persona_id}")

            existing_version = conn.execute(
                select(contact_profiles.c.version).where(
                    contact_profiles.c.contact_id == profile.contact_id
                )
            ).scalar_one_or_none()
            version = (int(existing_version) + 1) if existing_version else 1

            values = {
                "contact_id": profile.contact_id,
                "relation": profile.relation,
                "stable_facts_json": json.dumps(
                    list(profile.stable_facts),
                    ensure_ascii=False,
                ),
                "style_overrides_json": json.dumps(
                    list(profile.style_overrides),
                    ensure_ascii=False,
                ),
                "persona_id": persona_id,
                "version": version,
                "updated_at": _now(),
            }
            conn.execute(
                sqlite_insert(contact_profiles)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["contact_id"],
                    set_={key: value for key, value in values.items() if key != "contact_id"},
                )
            )

    def load_persona(self, persona_id: str) -> Persona | None:
        with self.database.engine.connect() as conn:
            row = conn.execute(
                select(personas).where(personas.c.persona_id == persona_id)
            ).mappings().one_or_none()
        if row is None:
            return None
        return Persona(
            persona_id=row["persona_id"],
            identity_summary=row["identity_summary"],
            style_rules=_json_tuple(row["style_rules_json"]),
            hard_constraints=_json_tuple(row["hard_constraints_json"]),
        )

    def load_contact(self, contact_id: str) -> tuple[ContactProfile | None, str | None]:
        with self.database.engine.connect() as conn:
            row = conn.execute(
                select(contact_profiles).where(
                    contact_profiles.c.contact_id == contact_id
                )
            ).mappings().one_or_none()
        if row is None:
            return None, None
        return (
            ContactProfile(
                contact_id=row["contact_id"],
                relation=row["relation"],
                stable_facts=_json_tuple(row["stable_facts_json"]),
                style_overrides=_json_tuple(row["style_overrides_json"]),
            ),
            row["persona_id"],
        )

    def load_selected(
        self,
        *,
        contact_id: str | None,
        fallback_persona: Persona,
    ) -> tuple[Persona, ContactProfile | None]:
        contact: ContactProfile | None = None
        contact_persona_id: str | None = None
        if contact_id is not None:
            contact, contact_persona_id = self.load_contact(contact_id)

        selected_id = contact_persona_id
        if selected_id is None:
            with self.database.engine.connect() as conn:
                selected_id = conn.execute(
                    select(qbot_meta.c.value).where(
                        qbot_meta.c.key == self.DEFAULT_PERSONA_KEY
                    )
                ).scalar_one_or_none()

        if selected_id is not None:
            selected = self.load_persona(selected_id)
            if selected is not None:
                return selected, contact

        return fallback_persona, contact
