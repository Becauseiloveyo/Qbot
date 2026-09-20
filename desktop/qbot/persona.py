from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Persona(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_id: str = "default"
    identity_summary: str = ""
    style_rules: tuple[str, ...] = ()
    hard_constraints: tuple[str, ...] = ()

    def render_stable_prefix(self) -> str:
        sections = ["[USER_PERSONA]", self.identity_summary.strip()]
        if self.style_rules:
            sections.append("[STYLE_RULES]\n- " + "\n- ".join(self.style_rules))
        if self.hard_constraints:
            sections.append(
                "[HARD_CONSTRAINTS]\n- " + "\n- ".join(self.hard_constraints)
            )
        return "\n\n".join(part for part in sections if part)


class ContactProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    contact_id: str = Field(min_length=1)
    relation: str = ""
    stable_facts: tuple[str, ...] = ()
    style_overrides: tuple[str, ...] = ()

    def render_stable_prefix(self) -> str:
        lines = [f"[CONTACT id={self.contact_id}]"]
        if self.relation:
            lines.append(f"relation: {self.relation}")
        if self.stable_facts:
            lines.append("stable_facts:\n- " + "\n- ".join(self.stable_facts))
        if self.style_overrides:
            lines.append(
                "style_overrides:\n- " + "\n- ".join(self.style_overrides)
            )
        return "\n".join(lines)
