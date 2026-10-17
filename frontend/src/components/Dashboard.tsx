import { type ReactNode, useEffect, useRef, useState } from "react";
import { useCat } from "../hooks/useCat";
import { useFileDrop } from "../hooks/useFileDrop";
import { useFiles } from "../hooks/useFiles";
import { useLayout } from "../hooks/useLayout";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useVoice } from "../hooks/useVoice";
import { type ItemId, ITEM_IDS } from "../lib/layout";
import Header from "./Header";
import Stage from "./Stage";
import ConfirmDialog from "./devices/ConfirmDialog";
import DevicesCard from "./devices/DevicesCard";
import Caption from "./hud/Caption";
import CanvasItem from "./hud/CanvasItem";
import CatCore from "./hud/CatCore";
import ChatOverlay from "./hud/ChatOverlay";
import FilesPanel from "./hud/FilesPanel";
import { HudPanel } from "./hud/Hud";
import LayoutToolbar from "./hud/LayoutToolbar";
import { ClockRing, DateRing } from "./hud/TimeWidgets";
import UploadStatus from "./hud/UploadStatus";
import { renderWidget } from "./widgets/renderWidget";

/**
 * Arbeitsraum: Cat als leuchtender Kern in der Mitte, Widgets ringsum. Auf großen Bildschirmen
 * ist die Fläche frei: "Layout anpassen" erlaubt Verschieben, Skalieren und Ausblenden der
 * Elemente (wird im Browser gespeichert). Auf kleinen Bildschirmen stapelt alles.
 * Klick auf den Kern öffnet den Chat, das Mikrofon hört von selbst zu, Dateien lassen sich
 * überall ins Fenster ziehen.
 */
export default function Dashboard({
  onUnreachable,
  onLogout,
}: {
  onUnreachable: () => void;
  onLogout: () => void;
}) {
  const { state, dispatch, send } = useCat(onUnreachable);
  const connected = state.connection === "open";
  const busy = state.messages.some((m) => m.streaming);
  const mic = useVoice(connected, true);
  const wide = useMediaQuery("(min-width: 1024px)");
  const layout = useLayout();
  const files = useFiles(connected);
  const dragging = useFileDrop(files.upload);
  const canvas = useRef<HTMLDivElement>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [stageHidden, setStageHidden] = useState(false);
  const [editing, setEditing] = useState(false);

  // Neuer Stage-Inhalt (auch das Geräte-Panel oder eine abgelegte Datei) blendet die Stage ein
  // und legt sie nach vorn.
  const latestStage = state.stage[state.stage.length - 1]?.id;
  const { front } = layout;
  useEffect(() => {
    setStageHidden(false);
    if (latestStage) front("stage");
  }, [latestStage, front]);

  const refresh = (id: string) => send({ type: "widget.refresh", id });
  const showStage = state.stage.length > 0 && !stageHidden;
  const openChat = () => setChatOpen(true);

  const widget = (id: string, title: string): ReactNode => {
    const w = state.widgets[id];
    return w ? (
      renderWidget(w, refresh)
    ) : (
      <HudPanel title={title} className="h-full">
        <p className="text-sm text-cyan-200/50">Warte auf Daten …</p>
      </HudPanel>
    );
  };

  const stage = (
    <Stage
      items={state.stage}
      index={state.stageIndex}
      onGo={(index) => dispatch({ kind: "stageGo", index })}
      onClear={() => send({ type: "stage.clear" })}
      onHide={() => setStageHidden(true)}
      devices={state.devices}
      control={state.control}
      deviceError={state.deviceError}
      onDeviceCommand={(id, command) => send({ type: "device.command", id, command })}
    />
  );

  const content: Record<Exclude<ItemId, "stage">, ReactNode> = {
    date: <DateRing />,
    clock: <ClockRing />,
    system: widget("system", "System"),
    uptime: widget("uptime", "Uptime"),
    weather: widget("weather", "Wetter"),
    devices: (
      <DevicesCard
        devices={state.devices}
        control={state.control}
        onOpen={() => dispatch({ kind: "showDevices" })}
      />
    ),
    files: (
      <FilesPanel
        files={files.files}
        error={files.error}
        onPick={files.upload}
        onShow={files.show}
        onDelete={files.remove}
      />
    ),
    core: (
      <div className="flex h-full w-full items-center justify-center">
        <CatCore state={state.voice} onOpen={openChat} />
      </div>
    ),
    caption: (
      <div className="flex h-full w-full items-start justify-center">
        <Caption messages={state.messages} mic={mic} onOpenChat={openChat} />
      </div>
    ),
  };

  return (
    <div className="hud-bg flex h-dvh flex-col overflow-hidden">
      <Header
        connection={state.connection}
        weather={state.widgets.weather}
        provider={state.provider}
        onLogout={onLogout}
      />

      {state.notice && (
        <div
          role="alert"
          className="flex items-center justify-between gap-4 bg-rose-950/70 px-4 py-2 text-sm text-rose-200"
        >
          <span>{state.notice}</span>
          <button type="button" onClick={() => dispatch({ kind: "dismissNotice" })} className="underline">
            Schließen
          </button>
        </div>
      )}

      {wide ? (
        <main className="relative min-h-0 flex-1 p-2">
          <div ref={canvas} aria-label="Arbeitsraum" className="relative h-full w-full">
            {layout.state.order.map((id, index) => {
              if (id === "stage" ? !showStage : layout.state.hidden.includes(id)) return null;
              return (
                <CanvasItem
                  key={id}
                  id={id}
                  rect={layout.state.rects[id]}
                  z={index + 1}
                  editing={editing}
                  canvas={canvas}
                  onChange={layout.setRect}
                  onCommit={layout.commit}
                  onFront={layout.front}
                  onHide={layout.hide}
                >
                  {id === "stage" ? stage : content[id]}
                </CanvasItem>
              );
            })}
            <LayoutToolbar
              editing={editing}
              hidden={layout.state.hidden.filter((id) => ITEM_IDS.includes(id))}
              onToggle={() => setEditing((e) => !e)}
              onReset={layout.reset}
              onShow={layout.show}
            />
          </div>
        </main>
      ) : (
        <main className="min-h-0 flex-1 overflow-y-auto p-3">
          <div className="grid gap-3">
            <section aria-label="Cat" className="relative flex min-h-[26rem] flex-col items-center gap-2">
              <div className="relative flex min-h-0 w-full flex-1 items-center justify-center">
                <div className="flex h-[22rem] w-full max-w-[22rem] items-center justify-center">
                  <CatCore state={state.voice} onOpen={openChat} />
                </div>
                {showStage && <div className="absolute inset-0 z-10">{stage}</div>}
              </div>
              <Caption messages={state.messages} mic={mic} onOpenChat={openChat} />
            </section>
            <div className="mx-auto h-44 w-full">{content.date}</div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="min-h-[12rem]">{content.system}</div>
              <div className="min-h-[12rem]">{content.weather}</div>
              <div className="min-h-[10rem]">{content.devices}</div>
              <div className="min-h-[10rem]">{content.files}</div>
              <div className="min-h-[6rem]">{content.uptime}</div>
            </div>
          </div>
        </main>
      )}

      <UploadStatus dragging={dragging} uploads={files.uploads} onDismiss={files.dismiss} />

      {chatOpen && (
        <ChatOverlay
          onClose={() => setChatOpen(false)}
          messages={state.messages}
          connected={connected}
          busy={busy}
          onSend={(text) => send({ type: "chat.message", text })}
          onClear={() => send({ type: "chat.clear" })}
          mic={mic}
        />
      )}

      {state.confirm && (
        <ConfirmDialog
          confirm={state.confirm}
          onAnswer={(approved) => {
            send({ type: "confirm.response", id: state.confirm?.id ?? "", approved });
            dispatch({ kind: "confirmClose" });
          }}
        />
      )}
    </div>
  );
}
