"""WebSocket-Protokoll Browser <-> Backend. Dokumentation: docs/protocol.md.

Das Frontend spiegelt diese Typen in frontend/src/protocol.ts.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from cat.devices.models import Control, DeviceInfo
from cat.stage.models import StageItem

Role = Literal["user", "assistant", "system"]
VoiceStateName = Literal["idle", "listening", "thinking", "speaking"]
WidgetStatus = Literal["loading", "ok", "error"]


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Server -> Browser ---


class ChatMessage(_Event):
    type: Literal["chat.message"] = "chat.message"
    id: str
    role: Role
    text: str
    ts: float
    # Runde mit Werkzeugen/Kurzbefehl: bleibt aus dem Verlauf des lokalen Modells (es ahmt sonst
    # "Okay, Licht ist aus" nach, statt das Werkzeug aufzurufen).
    tooled: bool = False


class ChatDelta(_Event):
    type: Literal["chat.delta"] = "chat.delta"
    id: str
    delta: str


class ChatFiller(_Event):
    """Füllsatz, solange Cat noch nachdenkt (wird beim ersten Wort der Antwort ersetzt)."""

    type: Literal["chat.filler"] = "chat.filler"
    id: str
    text: str


class ChatDone(_Event):
    type: Literal["chat.done"] = "chat.done"
    id: str


class ChatClear(_Event):
    type: Literal["chat.clear"] = "chat.clear"


class StageShow(_Event):
    type: Literal["stage.show"] = "stage.show"
    item: StageItem


class StageClear(_Event):
    type: Literal["stage.clear"] = "stage.clear"


class WidgetUpdate(_Event):
    type: Literal["widget.update"] = "widget.update"
    id: str
    kind: str
    title: str
    status: WidgetStatus
    data: dict[str, object] = Field(default_factory=dict)
    error: str | None = None
    updated_at: float | None = None
    refreshable: bool = False


class VoiceState(_Event):
    type: Literal["voice.state"] = "voice.state"
    state: VoiceStateName


class DeviceList(_Event):
    type: Literal["device.list"] = "device.list"
    control: Control
    error: str | None = None
    devices: list[DeviceInfo]


class DeviceStateEvent(_Event):
    type: Literal["device.state"] = "device.state"
    id: str
    state: str | None
    unit: str | None = None
    online: bool = True


class ConfirmRequest(_Event):
    type: Literal["confirm.request"] = "confirm.request"
    id: str
    device: str
    command: str
    summary: str
    expires_in: int


class ConfirmResolved(_Event):
    type: Literal["confirm.resolved"] = "confirm.resolved"
    id: str


class ProviderState(_Event):
    """Welches Sprachmodell gerade antwortet (offline=True: lokales Fallback-Modell)."""

    type: Literal["provider.state"] = "provider.state"
    name: str
    offline: bool


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    message: str


ServerEvent = (
    ChatMessage
    | ChatDelta
    | ChatFiller
    | ChatDone
    | ChatClear
    | StageShow
    | StageClear
    | WidgetUpdate
    | VoiceState
    | DeviceList
    | DeviceStateEvent
    | ConfirmRequest
    | ConfirmResolved
    | ProviderState
    | ErrorEvent
)


# --- Browser -> Server ---


class ClientChatMessage(_Event):
    type: Literal["chat.message"] = "chat.message"
    text: str = Field(min_length=1, max_length=4000)


class ClientChatClear(_Event):
    type: Literal["chat.clear"] = "chat.clear"


class ClientStageClear(_Event):
    type: Literal["stage.clear"] = "stage.clear"


class ClientWidgetRefresh(_Event):
    type: Literal["widget.refresh"] = "widget.refresh"
    id: str


class ClientConfirmResponse(_Event):
    type: Literal["confirm.response"] = "confirm.response"
    id: str
    approved: bool


class ClientDeviceCommand(_Event):
    type: Literal["device.command"] = "device.command"
    id: str
    command: str = Field(min_length=1, max_length=20)


ClientEvent = Annotated[
    ClientChatMessage
    | ClientChatClear
    | ClientStageClear
    | ClientWidgetRefresh
    | ClientConfirmResponse
    | ClientDeviceCommand,
    Field(discriminator="type"),
]

client_event_adapter: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)

SERVER_EVENT_TYPES = (
    "chat.message",
    "chat.delta",
    "chat.done",
    "chat.clear",
    "stage.show",
    "stage.clear",
    "widget.update",
    "voice.state",
    "device.list",
    "device.state",
    "confirm.request",
    "confirm.resolved",
    "provider.state",
    "error",
)
CLIENT_EVENT_TYPES = (
    "chat.message",
    "chat.clear",
    "stage.clear",
    "widget.refresh",
    "confirm.response",
    "device.command",
)
