import logging

from cat.config import Settings
from cat.plugins.base import Plugin
from cat.plugins.system import SystemPlugin
from cat.plugins.weather import WeatherPlugin

log = logging.getLogger("cat.plugins")

# Name (wie in CAT_PLUGINS) -> Fabrik. Weitere Plugins (openhab, homeassistant) kommen in Phase 4.
AVAILABLE: dict[str, type[Plugin]] = {
    "system": SystemPlugin,
    "weather": WeatherPlugin,
}


def build_plugins(settings: Settings) -> list[Plugin]:
    plugins: list[Plugin] = []
    for name in settings.enabled_plugins:
        factory = AVAILABLE.get(name)
        if factory is None:
            log.warning("Unbekanntes Plugin '%s' in CAT_PLUGINS wird ignoriert", name)
            continue
        plugins.append(factory())
    return plugins
