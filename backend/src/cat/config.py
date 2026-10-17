from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfiguration aus Umgebungsvariablen bzw. .env (Prefix CAT_)."""

    model_config = SettingsConfigDict(
        env_prefix="CAT_",
        env_file=(".env", "../.env"),
        extra="ignore",
        populate_by_name=True,
    )

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    data_dir: Path = Path("data")
    # Gebautes Frontend (im Container /app/static). Fehlt es, wird nur die API bedient.
    static_dir: Path | None = None

    # Login der Weboberfläche. Ohne Passwort ist kein Login möglich (fail closed).
    password: SecretStr | None = None
    # Schlüssel für Sitzungs-Cookies. Leer: zufällig pro Start (Sitzungen enden beim Neustart).
    session_secret: SecretStr | None = None
    session_ttl_hours: int = 24 * 7

    # "agent" = LLM mit Werkzeugen, "echo" = nur Echo (zum Testen der Oberfläche ohne LLM).
    responder: Literal["agent", "echo"] = "agent"
    # LLM (Phase 2). Der Schlüssel steht nur in der .env auf dem Server.
    llm_model: str = "anthropic/claude-haiku-5-5"
    llm_max_tokens: int = 1500
    agent_max_steps: int = 6
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CAT_ANTHROPIC_API_KEY"),
    )

    # Gerätesteuerung. readonly = nur lesen (Standard), test = nur Geräte mit test: true,
    # full = alle freigegebenen Geräte. Erst nach ausdrücklicher Freigabe auf full stellen.
    device_control: Literal["readonly", "test", "full"] = "readonly"
    # Fast-Path: Gerätebefehle ohne LLM (Phase 5). Abschaltbar zum Vergleichen.
    fastpath: bool = True
    # openHAB (Phase 4). Token optional (lokal ist die REST-API oft offen).
    openhab_url: str = "http://host.docker.internal:8080"
    openhab_token: SecretStr | None = None
    # Home Assistant (nur Mocks, solange es keinen HA gibt)
    ha_url: str = "http://homeassistant.local:8123"
    ha_token: SecretStr | None = None

    # Plugins (kommagetrennt) und Widgets (Phase 3)
    plugins: str = "system,weather"
    system_interval_s: float = 3.0
    disk_path: str = "/"
    weather_lat: float | None = None
    weather_lon: float | None = None
    weather_name: str = ""
    weather_ttl_s: float = 600.0

    @property
    def synonyms_file(self) -> Path:
        return self.data_dir / "config" / "synonyms.yaml"

    @property
    def devices_file(self) -> Path:
        return self.data_dir / "config" / "devices.yaml"

    @property
    def audit_file(self) -> Path:
        return self.data_dir / "audit.jsonl"

    @property
    def enabled_plugins(self) -> list[str]:
        return [name.strip() for name in self.plugins.split(",") if name.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
