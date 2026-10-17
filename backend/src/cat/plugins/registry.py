import logging
from collections.abc import Callable
from dataclasses import dataclass

from cat.config import Settings
from cat.devices.service import DeviceService
from cat.plugins.base import Plugin
from cat.plugins.external import load_external
from cat.plugins.homeassistant import HomeAssistantPlugin
from cat.plugins.openhab import OpenHabPlugin
from cat.plugins.system import SystemPlugin
from cat.plugins.weather import WeatherPlugin

log = logging.getLogger("cat.plugins")


@dataclass(frozen=True)
class PluginServices:
    """Gemeinsame Dienste, die Plugins bei der Erzeugung bekommen."""

    devices: DeviceService


Factory = Callable[[PluginServices], Plugin]

# Name (wie in CAT_PLUGINS) -> Fabrik.
AVAILABLE: dict[str, Factory] = {
    "system": lambda _: SystemPlugin(),
    "weather": lambda _: WeatherPlugin(),
    "openhab": lambda services: OpenHabPlugin(services.devices),
    "homeassistant": lambda services: HomeAssistantPlugin(services.devices),
}


def build_plugins(settings: Settings, services: PluginServices) -> list[Plugin]:
    plugins: list[Plugin] = []
    for name in settings.enabled_plugins:
        factory = AVAILABLE.get(name)
        if factory is None:
            # Nicht eingebaut: nur ein von Hand freigegebenes Plugin aus active/ kommt infrage.
            external = load_external(settings.plugins_dir / "active", name, services)
            if external is None:
                log.warning("Unbekanntes Plugin '%s' in CAT_PLUGINS wird ignoriert", name)
                continue
            plugins.append(external)
            continue
        plugins.append(factory(services))
    return plugins
