from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class QbotConfig(BaseModel):
    """Validated Desktop runtime configuration.

    Secrets are intentionally absent from this initial model. Provider and
    transport credentials will use the OS credential store rather than plain
    config files.
    """

    model_config = ConfigDict(frozen=True)

    node_id: str = Field(default="desktop-local", min_length=1)
    database_path: Path = Path("./data/qbot.db")
    spec_version: str = "0.1.0"
    db_schema_version: str = "1"
