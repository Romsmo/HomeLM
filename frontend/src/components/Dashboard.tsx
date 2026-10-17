import { useEffect, useState } from "react";
import { useCat } from "../hooks/useCat";
import { useVoice } from "../hooks/useVoice";
import Header from "./Header";
import Stage from "./Stage";
import ConfirmDialog from "./devices/ConfirmDialog";
import DevicesCard from "./devices/DevicesCard";
import Caption from "./hud/Caption";
import CatCore from "./hud/CatCore";
import ChatOverlay from "./hud/ChatOverlay";
import { HudPanel } from "./hud/Hud";
import { ClockRing, DateRing } from "./hud/TimeWidgets";
import { renderWidget } from "./widgets/renderWidget";

/** Widget oder, solange es noch keine Daten gibt, ein Platzhalter gleicher Größe. */
function slot(
  widgets: ReturnType<typeof useCat>["state"]["widgets"],
  id: string,
  title: string,
  onRefresh: (id: string) => void,
) {
  const widget = widgets[id];
  return widget ? (
    renderWidget(widget, onRefresh)
  ) : (
    <HudPanel title={title}>
      <p className="text-sm text-cyan-200/50">Warte auf Daten …</p>
    </HudPanel>
  );
}

/**
 * Arbeitsraum: Cat als leuchtender Kern in der Mitte, Widgets links und rechts, die den Platz
 * untereinander aufteilen. Klick auf den Kern öffnet den Chat, das Mikrofon hört von selbst zu.
 * Zeigt die Stage etwas, liegt sie über dem Kern ("Ausblenden" bringt ihn zurück).
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
  const [chatOpen, setChatOpen] = useState(false);
  const [stageHidden, setStageHidden] = useState(false);

  // Neuer Stage-Inhalt (auch das Geräte-Panel) blendet die Stage wieder ein.
  const latestStage = state.stage[state.stage.length - 1]?.id;
  useEffect(() => {
    setStageHidden(false);
  }, [latestStage]);

  const refresh = (id: string) => send({ type: "widget.refresh", id });
  const showStage = state.stage.length > 0 && !stageHidden;

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

      <main className="min-h-0 flex-1 overflow-y-auto p-3 lg:overflow-hidden">
        <div className="grid gap-3 lg:h-full lg:grid-cols-[minmax(13rem,1fr)_minmax(0,2.1fr)_minmax(13rem,1fr)]">
          <aside aria-label="Widgets links" className="order-2 flex min-h-0 flex-col gap-3 lg:order-1">
            <DateRing />
            <div className="flex min-h-0 flex-1 flex-col gap-3">
              {slot(state.widgets, "system", "System", refresh)}
              {slot(state.widgets, "uptime", "Uptime", refresh)}
            </div>
          </aside>

          <section
            aria-label="Cat"
            className="relative order-1 flex min-h-[26rem] min-w-0 flex-col items-center gap-2 lg:order-2 lg:min-h-0"
          >
            <div className="relative flex min-h-0 w-full flex-1 items-center justify-center">
              <div className="flex h-[22rem] w-full max-w-[46rem] items-center justify-center lg:h-full lg:max-h-[64vh]">
                <CatCore state={state.voice} onOpen={() => setChatOpen(true)} />
              </div>
              <div className="pointer-events-none absolute top-0 right-0 hidden w-[clamp(5rem,12vh,8rem)] xl:block">
                <ClockRing />
              </div>
              {showStage && (
                <div className="absolute inset-0 z-10">
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
                </div>
              )}
            </div>
            <Caption messages={state.messages} mic={mic} onOpenChat={() => setChatOpen(true)} />
          </section>

          <aside aria-label="Widgets rechts" className="order-3 flex min-h-0 flex-col gap-3">
            <div className="flex min-h-[14rem] flex-[3] flex-col">{slot(state.widgets, "weather", "Wetter", refresh)}</div>
            <div className="flex min-h-0 flex-[2] flex-col">
              <DevicesCard
                devices={state.devices}
                control={state.control}
                onOpen={() => dispatch({ kind: "showDevices" })}
              />
            </div>
          </aside>
        </div>
      </main>

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
