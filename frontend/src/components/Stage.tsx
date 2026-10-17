import { Suspense, lazy } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ControlMode, DeviceInfo, StageItem, VoiceStateName } from "../protocol";
import DevicePanel from "./devices/DevicePanel";
import HtmlFrame from "./stage/HtmlFrame";
import Orb from "./Orb";

// Chart.js erst laden, wenn ein Diagramm gezeigt wird.
const ChartView = lazy(() => import("./stage/ChartView"));

const KIND_LABEL: Record<StageItem["kind"], string> = {
  html: "Grafik",
  chart: "Diagramm",
  markdown: "Text",
  devices: "Geräte",
};

interface DeviceProps {
  devices: DeviceInfo[];
  control: ControlMode;
  deviceError: string | null;
  onDeviceCommand: (id: string, command: string) => void;
}

function Content({ item, deviceProps }: { item: StageItem; deviceProps: DeviceProps }) {
  switch (item.kind) {
    case "html":
      return <HtmlFrame key={item.id} html={item.content} title={item.title} />;
    case "chart":
      return item.chart ? (
        <Suspense fallback={<p className="p-4 text-slate-400">Lade Diagramm …</p>}>
          <ChartView key={item.id} spec={item.chart} title={item.title} />
        </Suspense>
      ) : (
        <p className="p-4 text-slate-400">Keine Diagrammdaten.</p>
      );
    case "devices":
      return (
        <DevicePanel
          devices={deviceProps.devices}
          control={deviceProps.control}
          error={deviceProps.deviceError}
          room={item.content}
          onCommand={deviceProps.onDeviceCommand}
        />
      );
    case "markdown":
      return (
        <div className="prose-cat h-full overflow-y-auto p-5 text-sm leading-relaxed">
          <Markdown remarkPlugins={[remarkGfm]}>{item.content}</Markdown>
        </div>
      );
  }
}

function Chevron({ dir }: { dir: "left" | "right" }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d={dir === "left" ? "M8 1.5 3.5 6 8 10.5" : "M4 1.5 8.5 6 4 10.5"} />
    </svg>
  );
}

const navButton =
  "rounded-md border border-slate-700 px-2 py-1 text-slate-300 transition hover:border-slate-500 disabled:opacity-30";

export default function Stage({
  voice,
  items,
  index,
  onGo,
  onClear,
  devices = [],
  control = "readonly",
  deviceError = null,
  onDeviceCommand = () => {},
}: {
  devices?: DeviceInfo[];
  control?: ControlMode;
  deviceError?: string | null;
  onDeviceCommand?: (id: string, command: string) => void;
  voice: VoiceStateName;
  items: StageItem[];
  index: number;
  onGo: (index: number) => void;
  onClear: () => void;
}) {
  const item = items[index];
  return (
    <section
      aria-label="Stage"
      className="relative flex min-h-[18rem] min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/40 backdrop-blur"
    >
      {item ? (
        <>
          <header className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-2">
            <div className="flex min-w-0 items-baseline gap-2">
              <h2 className="truncate text-sm font-medium text-slate-100">{item.title}</h2>
              {KIND_LABEL[item.kind] !== item.title && (
                <span className="text-xs text-slate-500">{KIND_LABEL[item.kind]}</span>
              )}
            </div>
            <div className="flex items-center gap-2 text-xs">
              <button
                type="button"
                className={navButton}
                onClick={() => onGo(index - 1)}
                disabled={index <= 0}
                aria-label="Vorheriger Stage-Inhalt"
              >
                <Chevron dir="left" />
              </button>
              <span className="tabular-nums text-slate-400" aria-live="polite">
                {index + 1} / {items.length}
              </span>
              <button
                type="button"
                className={navButton}
                onClick={() => onGo(index + 1)}
                disabled={index >= items.length - 1}
                aria-label="Nächster Stage-Inhalt"
              >
                <Chevron dir="right" />
              </button>
              <button type="button" className={`${navButton} hover:border-rose-500`} onClick={onClear}>
                Leeren
              </button>
              <Orb state={voice} size="small" />
            </div>
          </header>
          <div className="min-h-0 flex-1">
            <Content item={item} deviceProps={{ devices, control, deviceError, onDeviceCommand }} />
          </div>
        </>
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <Orb state={voice} />
        </div>
      )}
    </section>
  );
}
