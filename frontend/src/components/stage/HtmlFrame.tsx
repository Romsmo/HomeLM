import { useEffect, useMemo, useRef, useState } from "react";
import { buildSrcDoc, parseFrameMessage } from "../../lib/stageFrame";

/**
 * Rendert KI-HTML isoliert: sandbox="allow-scripts" OHNE allow-same-origin (eigener, leerer
 * Ursprung ohne Zugriff auf Cookies oder die Oberfläche), strikte CSP im Dokument, keine
 * Referrer. Rückkanal nur über die feste postMessage-Schnittstelle (siehe stageFrame.ts).
 */
export default function HtmlFrame({ html, title }: { html: string; title: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const srcDoc = useMemo(() => buildSrcDoc(html), [html]);

  useEffect(() => {
    setReady(false);
    function onMessage(event: MessageEvent) {
      if (event.source !== ref.current?.contentWindow) return;
      if (parseFrameMessage(event.data)?.type === "cat.ready") setReady(true);
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [srcDoc]);

  return (
    <iframe
      ref={ref}
      title={title}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      srcDoc={srcDoc}
      data-ready={ready}
      className="h-full w-full border-0 bg-slate-950"
    />
  );
}
