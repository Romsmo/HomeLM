"""Gerätedienst: Allowlist, Zustände, Steuerung mit Modus, Risikostufen und Bestätigung."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from cat.audit import AuditLog
from cat.devices.allowlist import Allowlist
from cat.devices.commands import DeviceError, describe_command, is_controllable, normalize_command
from cat.devices.confirm import ConfirmManager
from cat.devices.models import Control, DeviceInfo, DeviceSpec
from cat.ws.protocol import DeviceList, DeviceStateEvent, ServerEvent

log = logging.getLogger("cat.devices")

SETTLE_DELAY_S = 0.4


@dataclass(frozen=True)
class RawState:
    state: str | None
    unit: str | None = None


class DeviceBackend(Protocol):
    """Von openHAB- und Home-Assistant-Plugin implementiert."""

    async def read(self, spec: DeviceSpec) -> RawState: ...

    async def send(self, spec: DeviceSpec, command: str) -> None:
        """Sendet den kanonischen Befehl. Wirft DeviceError bei Ablehnung durch das Backend."""
        ...


class DeviceService:
    def __init__(
        self,
        allowlist: Allowlist,
        control: Control,
        emit: Callable[[ServerEvent], Awaitable[None]],
        audit: AuditLog,
        confirm: ConfirmManager,
    ) -> None:
        self._allowlist = allowlist
        self._control: Control = control
        self._emit = emit
        self._audit = audit
        self._confirm = confirm
        self._backends: dict[str, DeviceBackend] = {}
        self._states: dict[str, RawState] = {}
        self._offline: set[str] = set()
        self.settle_delay = SETTLE_DELAY_S

    # --- Registrierung und Sicht ---

    def register_backend(self, name: str, backend: DeviceBackend) -> None:
        self._backends[name] = backend

    @property
    def control(self) -> Control:
        return self._control

    @property
    def specs(self) -> list[DeviceSpec]:
        return self._allowlist.specs

    def specs_for(self, backend: str) -> list[DeviceSpec]:
        return [s for s in self._allowlist.specs if s.backend == backend]

    def _controllable(self, spec: DeviceSpec) -> bool:
        if not is_controllable(spec.type) or spec.backend not in self._backends:
            return False
        if self._control == "full":
            return True
        return self._control == "test" and spec.test

    def info(self, spec: DeviceSpec) -> DeviceInfo:
        raw = self._states.get(spec.id)
        return DeviceInfo(
            id=spec.id,
            name=spec.name,
            room=spec.room,
            type=spec.type,
            risk=spec.effective_risk,
            state=raw.state if raw else None,
            unit=raw.unit if raw else None,
            online=spec.id not in self._offline,
            controllable=self._controllable(spec),
            test=spec.test,
        )

    def snapshot(self, room: str | None = None) -> list[DeviceInfo]:
        wanted = room.strip().lower() if room else None
        return [
            self.info(s)
            for s in self._allowlist.specs
            if wanted is None or s.room.lower() == wanted
        ]

    def list_event(self) -> DeviceList:
        return DeviceList(
            control=self._control, error=self._allowlist.error, devices=self.snapshot()
        )

    def resolve(self, ref: str) -> DeviceSpec:
        """Findet ein Gerät über id oder Namen. Mehrdeutiges wird nicht geraten."""
        key = ref.strip().lower()
        specs = self._allowlist.specs
        exact = [s for s in specs if s.id == key]
        if not exact:
            exact = [s for s in specs if s.name.lower() == key]
        if not exact:
            exact = [s for s in specs if key in (syn.lower() for syn in s.synonyms)]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            names = ", ".join(f"{s.name} ({s.room})" for s in exact)
            raise DeviceError(f"'{ref}' ist mehrdeutig: {names}. Bitte die id angeben.")
        raise DeviceError(
            f"Das Gerät '{ref}' gibt es nicht (oder es ist nicht freigegeben). "
            "list_devices zeigt die verfügbaren Geräte."
        )

    # --- Lesen ---

    async def refresh_one(self, spec: DeviceSpec, notify: bool = True) -> DeviceInfo:
        backend = self._backends.get(spec.backend)
        if backend is None:
            self._offline.add(spec.id)
        else:
            try:
                self._states[spec.id] = await backend.read(spec)
                self._offline.discard(spec.id)
            except DeviceError as exc:
                log.warning("Lesen von %s fehlgeschlagen: %s", spec.id, exc)
                self._offline.add(spec.id)
        info = self.info(spec)
        if notify:
            await self._emit(
                DeviceStateEvent(id=info.id, state=info.state, unit=info.unit, online=info.online)
            )
        return info

    async def refresh_all(self, backend: str | None = None) -> None:
        for spec in self._allowlist.specs:
            if backend is None or spec.backend == backend:
                await self.refresh_one(spec, notify=False)
        await self._emit(self.list_event())

    async def get_state(self, ref: str) -> DeviceInfo:
        return await self.refresh_one(self.resolve(ref))

    async def on_state_change(self, backend: str, item: str, raw: RawState) -> None:
        """Vom Backend bei Änderungen aufgerufen (SSE bzw. WebSocket)."""
        for spec in self._allowlist.specs:
            if spec.backend == backend and spec.item == item:
                self._states[spec.id] = raw
                self._offline.discard(spec.id)
                await self._emit(
                    DeviceStateEvent(id=spec.id, state=raw.state, unit=raw.unit, online=True)
                )

    async def set_offline(self, backend: str) -> None:
        """Backend nicht erreichbar: alle seine Geräte als offline markieren."""
        changed = False
        for spec in self.specs_for(backend):
            if spec.id not in self._offline:
                self._offline.add(spec.id)
                changed = True
        if changed:
            await self._emit(self.list_event())

    # --- Steuern ---

    async def command(self, ref: str, raw_command: str, source: str = "agent") -> str:
        """Führt einen Befehl aus. Wirft DeviceError, wenn er nicht ausgeführt wurde.

        Die Prüfreihenfolge ist fest und gilt für Chat, Sprache und Oberfläche gleichermaßen:
        Allowlist, Modus, Befehl, Bestätigung (nur bei "high"), erst dann das Backend.
        """
        spec = self.resolve(ref)
        command = normalize_command(spec, raw_command)
        what = describe_command(spec, command)

        if self._control == "readonly":
            raise DeviceError(
                "Steuern ist ausgeschaltet (CAT_DEVICE_CONTROL=readonly). Ich kann nur lesen."
            )
        if self._control == "test" and not spec.test:
            raise DeviceError(
                f"'{spec.name}' ist kein Testgerät. Echte Geräte sind noch nicht freigegeben."
            )
        backend = self._backends.get(spec.backend)
        if backend is None:
            raise DeviceError(f"Das Backend '{spec.backend}' ist nicht aktiv.")

        if spec.effective_risk == "high":
            approved = await self._confirm.request(
                device=spec.id,
                command=command,
                summary=f"Soll ich {what}?",
            )
            await self._audit.record(
                "confirm",
                {"device": spec.id, "command": command, "risk": "high"},
                "bestätigt" if approved else "abgelehnt oder nicht beantwortet",
                ok=approved,
                source=source,
            )
            if not approved:
                raise DeviceError(
                    f"Nicht ausgeführt: Bestätigung für '{spec.name}' fehlt oder wurde abgelehnt."
                )

        await backend.send(spec, command)
        await asyncio.sleep(self.settle_delay)
        info = await self.refresh_one(spec)
        shown = f"{info.state} {info.unit}".strip() if info.state is not None else "unbekannt"
        return f"Befehl gesendet: {what}. Zustand jetzt: {shown}."
