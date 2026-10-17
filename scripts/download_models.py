"""Lädt die Sprachmodelle vor (STT und Stimme) nach data/models.

    uv run python scripts/download_models.py            # Standard: base + thorsten
    uv run python scripts/download_models.py small      # größeres Erkennungsmodell

Cat lädt fehlende Modelle beim Start selbst nach (Internet nötig). Mit diesem Skript geht es
vorher und kontrolliert, z. B. auf einem Rechner ohne Internet-Zugang zum Server.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from cat.config import Settings  # noqa: E402
from cat.voice.setup import _download_voice, voice_file  # noqa: E402


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "base"
    settings = Settings(stt_model=model)  # type: ignore[call-arg]
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if not voice_file(settings).exists():
        print(f"Lade Stimme {settings.tts_voice} ...")
        _download_voice(settings)
    from faster_whisper import WhisperModel

    print(f"Lade Erkennungsmodell {model} ...")
    root = str(settings.models_dir / "whisper")
    WhisperModel(model, device="cpu", compute_type="int8", download_root=root)
    print(f"Fertig: {settings.models_dir}")


if __name__ == "__main__":
    main()
