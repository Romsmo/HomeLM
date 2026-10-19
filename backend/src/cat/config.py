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

    # HTTPS (Mikrofon im Browser braucht einen sicheren Kontext, docs/https.md). Beide Dateien
    # setzen, dann lauscht Cat zusätzlich auf `tls_port`. Leer = nur HTTP.
    tls_cert: Path | None = None
    tls_key: Path | None = None
    tls_port: int = 8443
    # Reverse-Proxy (Caddy), dem Cat die Client-IP und das Schema (X-Forwarded-*) glaubt. Komma-
    # getrennte IPs oder Netze, z. B. 172.19.0.0/16 (das Docker-Netz von Caddy). Leer = niemand.
    # Ohne das sähe Cat hinter dem Proxy nur die Proxy-IP (Anmelde-Sperre träfe alle gemeinsam).
    trusted_proxies: str = ""

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
    # Offline-Fallback (Phase 9, nur im Cloud-Modus): leer = aus. Beispiel: ollama_chat/qwen3:4b
    # (siehe docs/offline.md). Übernimmt nur, wenn der Cloud-Anbieter nicht erreichbar ist.
    fallback_model: str = ""
    ollama_url: str = "http://ollama:11434"

    # Lokal zuerst: Ist `local_model` gesetzt, beantwortet das Modell auf dem Server (Ollama)
    # alles selbst. Claude kommt nur ins Spiel, wenn es etwas nicht kann (docs/claude.md).
    # Leer = alter Cloud-Modus (`llm_model`). Beispiel: qwen3:4b-instruct-2507-q4_K_M
    local_model: str = ""
    local_num_ctx: int = 4096
    # Rechenthreads für Ollama: so viele wie `cpus` des Ollama-Containers (sonst drosselt das
    # CFS-Limit, gemessen: 2,4 statt 10 Token pro Sekunde bei 6 Threads auf 3 CPUs).
    local_threads: int = 5
    local_keep_alive: str = "60m"
    # Wartezeit zwischen zwei Teilen der Antwort; die Verarbeitung eines langen Prompts auf der
    # CPU braucht oft über eine Minute, bevor das erste Wort kommt.
    local_timeout_s: float = 240.0
    local_max_tokens: int = 700

    # Claude über das Abo (Brücke-Container `claude-bridge`, docs/claude.md). Leer = aus.
    claude_url: str = ""
    claude_model: str = "sonnet"
    claude_timeout_s: float = 240.0
    # Obergrenze an Fragen an Claude pro Tag (Schutz für das Abo-Limit und die Privatsphäre).
    claude_daily_limit: int = 25
    # Darf Claude die Notizen des Gedächtnisses lesen (Second Brain, nur lesend)?
    claude_memory: bool = True
    # Wartezeit auf den Cloud-Anbieter, wenn ein Fallback konfiguriert ist (schnell umschalten).
    llm_timeout_s: float = 20.0
    fallback_cooldown_s: float = 60.0
    agent_max_steps: int = 6
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CAT_ANTHROPIC_API_KEY"),
    )

    # Gerätesteuerung. readonly = nur lesen (Standard), test = nur Geräte mit test: true,
    # full = alle freigegebenen Geräte. Erst nach ausdrücklicher Freigabe auf full stellen.
    device_control: Literal["readonly", "test", "full"] = "readonly"
    # Gedächtnis (Phase 8): Notizen unter data/memory, Gesprächsverlauf unter data/sessions.
    session_log: bool = True
    # Alte Gespräche per LLM in Notizen zusammenfassen (braucht Internet und API-Schlüssel).
    summarize_sessions: bool = True
    # Code-Sandbox (Phase 9): Tool run_python, Container homelm-sandbox ohne Netzwerk.
    sandbox: bool = True
    # Sprache (Phase 6): STT faster-whisper, TTS Piper, VAD Silero. Modelle in data/models.
    voice: bool = False
    stt_model: str = "small"  # small (Standard, nach Messung) oder base, siehe docs/voice.md
    stt_compute: str = "int8"
    stt_threads: int = 4
    tts_voice: str = "de_DE-thorsten-medium"
    vad_silence_s: float = 1.1  # Pause bis zum Ende der Äußerung
    # Aktivierungsphrasen für das Browser-Mikrofon (voice/wake.py): ohne sie antwortet Cat nicht.
    wake_required: bool = True
    wake_phrases: str = "hey cat,hallo cat,okay cat"  # kommagetrennt
    wake_followup_s: float = 20.0  # nach einer Antwort braucht die nächste Äußerung keine Phrase
    # Füllsätze beim Nachdenken (intents/fillers.py): nach so vielen Sekunden ohne Antwort
    # sagt Cat etwas Passendes, danach alle `filler_repeat_s` Sekunden, höchstens dreimal.
    filler: bool = True
    filler_delay_s: float = 1.0
    filler_repeat_s: float = 9.0
    filler_generate: bool = True  # neue Sätze von selbst dazulernen (nur wenn Cat untätig ist)

    @property
    def fillers_file(self) -> Path:
        return self.data_dir / "fillers.json"

    voice_nice: int = 10  # Rechenthreads mit niedriger Priorität, Nextcloud und Co. haben Vorrang
    # Lernen aus Wiederholungen (intents/learned.py): Kurzbefehle ohne Sprachmodell.
    learn: bool = True
    learn_after: int = 2  # so oft muss dieselbe Formulierung gleich gelöst werden
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
    def satellites_file(self) -> Path:
        return self.data_dir / "config" / "satellites.yaml"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def sandbox_dir(self) -> Path:
        return self.data_dir / "sandbox"

    @property
    def plugins_dir(self) -> Path:
        return self.data_dir / "plugins"

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def learned_file(self) -> Path:
        return self.data_dir / "learned.json"

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
