"""WebSocket-Protokoll Browser <-> Backend. Dokumentation: docs/protocol.md.

Das Frontend spiegelt diese Typen in frontend/src/protocol.ts.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

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


class ChatDelta(_Event):
    type: Literal["chat.delta"] = "chat.delta"
    id: str
    delta: str


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


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    message: str


ServerEvent = (
    ChatMessage
    | ChatDelta
    | ChatDone
    | ChatClear
    | StageShow
    | StageClear
    | WidgetUpdate
    | VoiceState
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


ClientEvent = Annotated[
    ClientChatMessage | ClientChatClear | ClientStageClear | ClientWidgetRefresh,
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
    "error",
)
CLIENT_EVENT_TYPES = ("chat.message", "chat.clear", "stage.clear", "widget.refresh")
