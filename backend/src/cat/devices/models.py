"""Gemeinsames Gerätemodell für openHAB und Home Assistant."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Risk = Literal["low", "medium", "high"]
DeviceType = Literal[
    "light", "switch", "dimmer", "shutter", "thermostat", "sensor", "lock", "door", "garage"
]
Control = Literal["readonly", "test", "full"]
BackendName = Literal["openhab", "homeassistant"]

RISK_ORDER: dict[Risk, int] = {"low": 0, "medium": 1, "high": 2}
# Untergrenze je Typ: Türen, Schlösser und Garagen sind immer "high", auch wenn die Allowlist
# weniger einträgt. Die Allowlist kann Risiken nur anheben, nie unter die Untergrenze senken.
MIN_RISK: dict[DeviceType, Risk] = {
    "light": "low",
    "switch": "low",
    "dimmer": "low",
    "sensor": "low",
    "shutter": "medium",
    "thermostat": "medium",
    "lock": "high",
    "door": "high",
    "garage": "high",
}

_ID = re.compile(r"^[a-z0-9_]{1,64}$")


class DeviceSpec(BaseModel):
    """Eintrag der Allowlist (data/config/devices.yaml)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    backend: BackendName
    item: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    room: str = Field(min_length=1, max_length=60)
    type: DeviceType
    risk: Risk = "low"
    # Testgeräte dürfen schon gesteuert werden, bevor echte Geräte freigegeben sind.
    test: bool = False
    synonyms: list[str] = Field(default_factory=list, max_length=20)
    # Überschreibt die Standardübersetzung der Befehle ("unlock": "OFF").
    command_map: dict[str, str] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError("id darf nur a-z, 0-9 und _ enthalten (max. 64 Zeichen)")
        return value

    @property
    def effective_risk(self) -> Risk:
        floor = MIN_RISK[self.type]
        return self.risk if RISK_ORDER[self.risk] >= RISK_ORDER[floor] else floor


class DeviceInfo(BaseModel):
    """Zustand eines Geräts, wie er an Browser und Modell geht."""

    id: str
    name: str
    room: str
    type: DeviceType
    risk: Risk
    state: str | None = None
    unit: str | None = None
    online: bool = True
    controllable: bool = False
    test: bool = False
