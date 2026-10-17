"""Wortschatz des Fast-Path aus synonyms.yaml (plus optionaler Nutzerdatei)."""

import logging
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from cat.intents.text import fold

log = logging.getLogger("cat.intents")

_LISTS = ("on", "off", "up", "down", "stop", "lock", "unlock")


def _yaml_key(key: object) -> object:
    if isinstance(key, bool):
        return "on" if key else "off"
    return key


@dataclass
class Vocabulary:
    classes: dict[str, list[str]] = field(default_factory=dict)
    commands: dict[str, list[str]] = field(default_factory=dict)
    room_synonyms: dict[str, list[str]] = field(default_factory=dict)

    def merge(self, raw: dict[str, Any]) -> None:
        for name, words in (raw.get("classes") or {}).items():
            self.classes.setdefault(str(name), [])
            self.classes[str(name)] += [fold(str(w)) for w in words]
        # YAML 1.1 liest unquotiertes on/off als True/False: auch das akzeptieren.
        raw = {_yaml_key(k): v for k, v in raw.items()}
        for name in _LISTS:
            self.commands.setdefault(name, [])
            self.commands[name] += [fold(str(w)) for w in raw.get(name) or []]
        for room, words in (raw.get("rooms") or {}).items():
            key = fold(str(room))
            self.room_synonyms.setdefault(key, [])
            self.room_synonyms[key] += [fold(str(w)) for w in words]

    @property
    def command_words(self) -> dict[str, str]:
        return {word: cmd for cmd, words in self.commands.items() for word in words}


def load_vocabulary(user_file: Path | None = None) -> Vocabulary:
    vocab = Vocabulary()
    default = resources.files("cat.intents").joinpath("synonyms.yaml").read_text(encoding="utf-8")
    vocab.merge(yaml.safe_load(default) or {})
    if user_file is not None and user_file.is_file():
        try:
            vocab.merge(yaml.safe_load(user_file.read_text(encoding="utf-8")) or {})
        except (yaml.YAMLError, AttributeError, TypeError):
            log.warning("%s ist ungültig und wird ignoriert", user_file)
    return vocab
