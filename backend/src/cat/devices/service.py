"""Gerätedienst: Allowlist, Zustände, Steuerung mit Modus, Risikostufen und Bestätigung."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from rapidfuzz import fuzz

from cat.audit import AuditLog
from cat.devices.allowlist import Allowlist
from cat.devices.commands import DeviceError, describe_command, is_controllable, normalize_command
from cat.devices.confirm import ConfirmManager
from cat.devices.discovery import DiscoverConfig
from cat.devices.models import Control, DeviceInfo, DeviceSpec
from cat.intents.text import fold, tokenize
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
        self._discovered: list[DeviceSpec] = []
        self._all: list[DeviceSpec] = []
        self._by_item: dict[tuple[str, str], list[DeviceSpec]] = {}
        self.last_device: str | None = None  # zuletzt bedientes oder abgefragtes Gerät (id)
        self._rebuild()

    def _rebuild(self) -> None:
        """Von Hand eingetragene Geräte gelten vor erkannten (gleiches Item oder gleiche id)."""
        explicit = list(self._allowlist.specs)
        items = {(s.backend, s.item) for s in explicit}
        ids = {s.id for s in explicit}
        merged = list(explicit)
        for spec in self._discovered:
            if (spec.backend, spec.item) in items or spec.id in ids:
                continue
            merged.append(spec)
            ids.add(spec.id)
        self._all = merged
        index: dict[tuple[str, str], list[DeviceSpec]] = {}
        for spec in merged:
            index.setdefault((spec.backend, spec.item), []).append(spec)
        self._by_item = index

    def set_discovered(self, specs: list[DeviceSpec]) -> None:
        """Vom Backend erkannte Geräte (docs/devices.md). Ersetzt die vorige Erkennung."""
        self._discovered = list(specs)
        self._rebuild()
        known = {s.id for s in self._all}
        for stale in set(self._states) - known:
            self._states.pop(stale, None)
            self._offline.discard(stale)

    def seed_states(self, backend: str, states: dict[str, RawState]) -> None:
        """Zustände aus einer Sammelabfrage übernehmen (Item -> Zustand), ohne Einzelabfragen."""
        for spec in self._all:
            if spec.backend == backend and spec.item in states:
                self._states[spec.id] = states[spec.item]
                self._offline.discard(spec.id)

    def discover_config(self, backend: str) -> DiscoverConfig | None:
        """Einstellungen der automatischen Erkennung, falls eingeschaltet."""
        cfg = self._allowlist.discover.get(backend)
        return cfg if cfg is not None and cfg.enabled else None

    def explicit_items(self, backend: str) -> set[str]:
        """Items, die von Hand in devices.yaml stehen (die Erkennung lässt sie in Ruhe)."""
        return {s.item for s in self._allowlist.specs if s.backend == backend}

    def has_item(self, backend: str, item: str) -> bool:
        return (backend, item) in self._by_item

    # --- Registrierung und Sicht ---

    def register_backend(self, name: str, backend: DeviceBackend) -> None:
        self._backends[name] = backend

    @property
    def control(self) -> Control:
        return self._control

    @property
    def specs(self) -> list[DeviceSpec]:
        """Alle Geräte (von Hand eingetragene und erkannte)."""
        return self._all

    @property
    def listed_specs(self) -> list[DeviceSpec]:
        """Die Geräte, die in Listen, Dashboard und Sprachhinweisen erscheinen."""
        return [s for s in self._all if s.listed]

    def specs_for(self, backend: str) -> list[DeviceSpec]:
        return [s for s in self._all if s.backend == backend]

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

    def snapshot(self, room: str | None = None, include_unlisted: bool = False) -> list[DeviceInfo]:
        wanted = room.strip().lower() if room else None
        return [
            self.info(s)
            for s in (self._all if include_unlisted else self.listed_specs)
            if wanted is None or s.room.lower() == wanted
        ]

    def search(self, query: str, limit: int = 20) -> list[DeviceInfo]:
        """Unscharfe Suche über Name, Raum und Synonyme aller Geräte (auch technische)."""
        key = fold(query)
        if not key:
            return []
        scored: list[tuple[float, DeviceSpec]] = []
        for spec in self._all:
            texts = [spec.name, spec.room, f"{spec.room} {spec.name}", *spec.synonyms]
            best = max(
                max(fuzz.WRatio(key, fold(t)), fuzz.partial_ratio(key, fold(t)) * 0.95)
                for t in texts
            )
            if best >= 72:
                scored.append((best, spec))
        scored.sort(key=lambda x: (-x[0], not x[1].listed, x[1].name))
        return [self.info(spec) for _, spec in scored[:limit]]

    def list_event(self) -> DeviceList:
        return DeviceList(
            control=self._control, error=self._allowlist.error, devices=self.snapshot()
        )

    def resolve(self, ref: str) -> DeviceSpec:
        """Findet ein Gerät über id oder Namen. Mehrdeutiges wird nicht geraten."""
        key = ref.strip().lower()
        specs = self._all
        exact = [s for s in specs if s.id == key]
        if not exact:
            exact = [s for s in specs if s.name.lower() == key]
        if not exact:
            exact = [s for s in specs if key in (syn.lower() for syn in s.synonyms)]
        if not exact:
            exact = self._resolve_loose(fold(ref))
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            names = ", ".join(f"{s.name} ({s.room}, id {s.id})" for s in exact[:6])
            raise DeviceError(f"'{ref}' ist mehrdeutig: {names}. Bitte die id angeben.")
        near = self.search(ref, 4)
        hint = (
            " Ähnliche Geräte: " + "; ".join(f"{i.name} ({i.room}, id {i.id})" for i in near) + "."
            if near
            else ""
        )
        raise DeviceError(
            f"Das Gerät '{ref}' gibt es nicht (oder es ist nicht freigegeben).{hint} "
            "list_devices mit query sucht in allen Geräten."
        )

    def similar_with_state(self, info: DeviceInfo) -> list[DeviceInfo]:
        """Ähnlich benannte Geräte gleichen Typs im selben Raum, die einen Zustand melden.

        In openHAB gibt es oft zwei Items für dasselbe Gerät (eines ohne Wert, eines mit). Ist der
        Zustand unbekannt, zeigt das den Fund, ohne zu raten, welches das "richtige" ist."""
        if info.state is not None:
            return []
        mine = fold(info.name)
        found: list[tuple[float, DeviceInfo]] = []
        for other in self.snapshot(info.room, include_unlisted=True):
            if other.id == info.id or other.type != info.type or other.state is None:
                continue
            score = fuzz.partial_token_sort_ratio(mine, fold(other.name))
            if score >= 90:
                found.append((score, other))
        found.sort(key=lambda x: -x[0])
        return [i for _, i in found[:3]]

    def resolve_exact(self, ref: str) -> DeviceSpec | None:
        """Nur bei genau gleicher Bezeichnung (id, Name oder Synonym, ohne Groß-/Kleinschreibung,
        Umlaute und Satzzeichen), nie unscharf. Für Gelerntes: lieber nichts als das falsche."""
        if not ref:
            return None
        direct = [s for s in self._all if s.id == ref]
        if len(direct) == 1:
            return direct[0]
        key = " ".join(tokenize(ref))
        if not key:
            return None
        found = [
            s
            for s in self._all
            if key in {" ".join(tokenize(n)) for n in (s.name, s.id.replace("_", " "), *s.synonyms)}
        ]
        return found[0] if len(found) == 1 else None

    def last_device_hint(self) -> str:
        """Für den Kontext des Modells: worauf sich "es" oder "das Licht" gerade bezieht."""
        spec = next((s for s in self._all if s.id == self.last_device), None)
        if spec is None:
            return ""
        return f"Zuletzt bedient oder abgefragt: {spec.name} ({spec.room}, id {spec.id})."

    def _resolve_loose(self, key: str) -> list[DeviceSpec]:
        """Gleiche Schreibweise ohne Umlaute, Groß-/Kleinschreibung und Unterstriche, sonst das
        eindeutig beste unscharfe Ergebnis (nie raten, wenn zwei fast gleich gut sind)."""
        if not key:
            return []
        folded = [
            (spec, [fold(spec.name), *(fold(syn) for syn in spec.synonyms), fold(spec.id)])
            for spec in self._all
        ]
        same = [spec for spec, names in folded if key in names]
        if same:
            return same
        scored = sorted(
            ((max(fuzz.WRatio(key, n) for n in names), spec) for spec, names in folded),
            key=lambda x: -x[0],
        )
        if scored and scored[0][0] >= 90 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 6):
            return [scored[0][1]]
        return []

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
        if notify and spec.listed:
            await self._emit(
                DeviceStateEvent(id=info.id, state=info.state, unit=info.unit, online=info.online)
            )
        return info

    async def refresh_all(self, backend: str | None = None, skip_known: bool = False) -> None:
        """Alle Zustände neu lesen. `skip_known`: nur Geräte ohne bekannten Zustand (nach einer
        Sammelabfrage sind die erkannten Geräte schon aktuell)."""
        for spec in self._all:
            if backend is not None and spec.backend != backend:
                continue
            if skip_known and spec.id in self._states and spec.id not in self._offline:
                continue
            await self.refresh_one(spec, notify=False)
        await self._emit(self.list_event())

    async def get_state(self, ref: str) -> DeviceInfo:
        spec = self.resolve(ref)
        self.last_device = spec.id
        return await self.refresh_one(spec)

    async def on_state_change(self, backend: str, item: str, raw: RawState) -> None:
        """Vom Backend bei Änderungen aufgerufen (SSE bzw. WebSocket)."""
        for spec in self._by_item.get((backend, item), []):
            self._states[spec.id] = raw
            self._offline.discard(spec.id)
            if spec.listed:  # technische Geräte melden sich nicht ständig beim Browser
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
        self.last_device = spec.id
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
