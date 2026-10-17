"""Lädt geprüfte, von Hand aktivierte Plugins aus data/plugins/active/<name>/plugin.py.

Geladen wird nur, was (1) dort liegt UND (2) in CAT_PLUGINS steht. pending/ wird nie angefasst.
Ein Plugin bietet ein Objekt `PLUGIN` oder eine Funktion `create_plugin(services)`.
"""

import importlib.util
import logging
import re
from pathlib import Path
from typing import Any

from cat.plugins.base import Plugin

log = logging.getLogger("cat.plugins")
_NAME = re.compile(r"^[a-z0-9_]{1,40}$")


def load_external(active_dir: Path, name: str, services: Any) -> Plugin | None:
    if not _NAME.match(name):
        return None
    path = active_dir / name / "plugin.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(f"cat_external_{name}", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugin = (
            module.create_plugin(services) if hasattr(module, "create_plugin") else module.PLUGIN
        )
    except Exception:
        # Ein fehlerhaftes Fremd-Plugin darf Cat nicht am Start hindern.
        log.exception("Externes Plugin '%s' konnte nicht geladen werden", name)
        return None
    for member in ("name", "start", "stop", "tools", "widgets", "intents"):
        if not hasattr(plugin, member):
            log.error(
                "Externes Plugin '%s' erfüllt die Schnittstelle nicht (%s fehlt)", name, member
            )
            return None
    log.warning("Externes Plugin '%s' aus %s geladen", name, path)
    return plugin  # type: ignore[no-any-return]
