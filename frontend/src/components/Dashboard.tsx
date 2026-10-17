import { useCat } from "../hooks/useCat";
import Header from "./Header";
import ChatPanel from "./ChatPanel";
import Stage from "./Stage";
import ConfirmDialog from "./devices/ConfirmDialog";
import DevicesCard from "./devices/DevicesCard";
import WidgetColumn from "./WidgetColumn";
import { renderWidget } from "./widgets/renderWidget";

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

  return (
    <div className="flex h-dvh flex-col">
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

      {/* Breit: Widgets | Stage | Chat. Tablet: Widgets oben, darunter Stage und Chat. Schmal: untereinander. */}
      <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-y-auto p-3 md:grid-cols-[minmax(0,1fr)_20rem] md:grid-rows-[auto_minmax(0,1fr)] md:overflow-hidden xl:grid-rows-1 xl:grid-cols-[16rem_minmax(0,1fr)_24rem]">
        <div className="md:col-span-2 xl:col-span-1 xl:min-h-0">
          <WidgetColumn
            widgets={state.widgets}
            renderWidget={(w) => renderWidget(w, (id) => send({ type: "widget.refresh", id }))}
          />
          <DevicesCard
            devices={state.devices}
            control={state.control}
            onOpen={() => dispatch({ kind: "showDevices" })}
          />
        </div>
        <Stage
          voice={state.voice}
          items={state.stage}
          index={state.stageIndex}
          onGo={(index) => dispatch({ kind: "stageGo", index })}
          onClear={() => send({ type: "stage.clear" })}
          devices={state.devices}
          control={state.control}
          deviceError={state.deviceError}
          onDeviceCommand={(id, command) => send({ type: "device.command", id, command })}
        />
        <div className="flex min-h-[26rem] flex-col md:min-h-0">
          <ChatPanel
            messages={state.messages}
            connected={connected}
            busy={busy}
            onSend={(text) => send({ type: "chat.message", text })}
            onClear={() => send({ type: "chat.clear" })}
          />
        </div>
      </main>
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
