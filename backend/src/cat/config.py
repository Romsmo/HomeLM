from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfiguration aus Umgebungsvariablen bzw. .env (Prefix CAT_)."""

    model_config = SettingsConfigDict(
        env_prefix="CAT_",
        env_file=(".env", "../.env"),
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    data_dir: Path = Path("data")
    # Gebautes Frontend (im Container /app/static). Fehlt es, wird nur die API bedient.
    static_dir: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
