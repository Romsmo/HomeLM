// Claude-Brücke: nimmt Fragen von Cat entgegen und stellt sie der Claude-Code-CLI (`claude -p`).
//
// Die CLI meldet sich mit dem Abo des Nutzers an (CLAUDE_CODE_OAUTH_TOKEN, erzeugt mit
// `claude setup-token`). Dieser Dienst ist die einzige Stelle, die das Token kennt. Er ist von
// außen nicht erreichbar (kein veröffentlichter Port) und gibt Cat nur Text zurück.
//
// Sicherheit der CLI-Sitzung: keine Befehls- oder Schreibwerkzeuge, nur Read/Grep/Glob auf das
// schreibgeschützt eingehängte Gedächtnis (oder gar keine Werkzeuge), keine Rückfragen, keine
// MCP-Server, keine gespeicherte Sitzung.

import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MODEL_RE = /^[A-Za-z0-9._\[\]-]{1,60}$/;
const MAX_BODY = 300_000;

/** Argumente für `claude`. Alles Sicherheitsrelevante steht hier an einer Stelle. */
export function buildArgs({ model, system, memory }, { restricted = true, maxTurns = 8 } = {}) {
  const args = [
    "-p",
    "--output-format", "json",
    "--model", model,
    "--no-session-persistence",
    "--disable-slash-commands",
    "--strict-mcp-config",
    "--permission-mode", "dontAsk",
    "--max-turns", String(maxTurns),
  ];
  if (restricted) args.push("--restricted");
  if (memory) args.push("--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob");
  else args.push("--tools", "");
  if (system) args.push("--append-system-prompt", system);
  return args;
}

/** Ordnet einen Fehlertext einer Art zu, auf die Cat reagiert (Pause bei limit/auth). */
export function classify(text) {
  const t = String(text || "");
  if (/rate.?limit|usage limit|limit reached|too many requests|\b429\b|overloaded|quota|weekly limit|resets? at/i.test(t)) return "limit";
  if (/not logged in|please run \/?login|log in|authenticat|oauth|invalid (api )?key|\b401\b|credential|unauthori[sz]ed|token (has )?expired/i.test(t)) return "auth";
  return "error";
}

/** Liest die JSON-Ausgabe der CLI (ein Objekt oder eine Liste von Meldungen). */
export function parseResult(stdout) {
  let data;
  try {
    data = JSON.parse(stdout);
  } catch {
    return { ok: false, kind: "error", message: "Claude hat keine lesbare Antwort geliefert." };
  }
  const result = Array.isArray(data) ? [...data].reverse().find((m) => m?.type === "result") : data;
  if (!result || result.type !== "result") {
    return { ok: false, kind: "error", message: "Claude hat keine Antwort geliefert." };
  }
  const text = typeof result.result === "string" ? result.result : "";
  if (result.is_error) {
    const kind = classify(text);
    const message = kind === "limit" ? "Das Abo-Limit von Claude ist gerade erreicht."
      : kind === "auth" ? "Claude ist nicht angemeldet (CLAUDE_CODE_OAUTH_TOKEN prüfen)."
      : "Claude konnte nicht antworten.";
    return { ok: false, kind, message, detail: text.slice(0, 300) };
  }
  if (String(result.subtype || "").startsWith("error")) {
    return { ok: false, kind: "error", message: "Claude hat die Aufgabe nicht abgeschlossen.", detail: String(result.subtype) };
  }
  return { ok: true, text, cost_usd: result.total_cost_usd ?? null, turns: result.num_turns ?? null };
}

function cleanEnv(extra = {}) {
  // Absichtlich nur eine feste Auswahl: nie ANTHROPIC_API_KEY o. ä. durchreichen. Mit einem
  // API-Schlüssel würde die CLI nach Verbrauch abrechnen statt über das Abo zu laufen.
  const env = {
    PATH: process.env.PATH,
    HOME: process.env.HOME,
    LANG: "C.UTF-8",
    NO_COLOR: "1",
    DISABLE_AUTOUPDATER: "1",
    DISABLE_TELEMETRY: "1",
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
    ...extra,
  };
  if (process.env.CLAUDE_CODE_OAUTH_TOKEN) env.CLAUDE_CODE_OAUTH_TOKEN = process.env.CLAUDE_CODE_OAUTH_TOKEN;
  return env;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size > MAX_BODY) { reject(new Error("too large")); req.destroy(); return; }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function send(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Content-Length": Buffer.byteLength(data) });
  res.end(data);
}

export function createServer({
  bin = process.env.CLAUDE_BIN || "claude",
  binArgs = [],
  memoryDir = process.env.MEMORY_DIR || "/memory",
  timeoutMs = Number(process.env.ASK_TIMEOUT_S || 200) * 1000,
  restricted = process.env.CLAUDE_RESTRICTED !== "0",
  maxTurns = Number(process.env.MAX_TURNS || 8),
  maxQueue = 3,
} = {}) {
  let waiting = 0;
  let tail = Promise.resolve();
  let version = null;

  function run(args, prompt, cwd) {
    return new Promise((resolve) => {
      const child = spawn(bin, [...binArgs, ...args], { cwd, env: cleanEnv(), stdio: ["pipe", "pipe", "pipe"] });
      let out = "", err = "", done = false;
      const finish = (value) => { if (!done) { done = true; clearTimeout(timer); resolve(value); } };
      const timer = setTimeout(() => {
        child.kill("SIGTERM");
        setTimeout(() => child.kill("SIGKILL"), 3000).unref();
        finish({ ok: false, kind: "timeout", message: "Claude hat zu lange gebraucht." });
      }, timeoutMs);
      child.stdout.on("data", (c) => { out += c; });
      child.stderr.on("data", (c) => { if (err.length < 4000) err += c; });
      child.on("error", () => finish({ ok: false, kind: "error", message: "Die Claude-CLI konnte nicht gestartet werden." }));
      child.on("close", (code) => {
        if (done) return;
        const parsed = out.trim() ? parseResult(out) : null;
        if (parsed && (parsed.ok || code === 0 || parsed.kind !== "error")) return finish(parsed);
        const kind = classify(`${out}\n${err}`);
        const message = kind === "limit" ? "Das Abo-Limit von Claude ist gerade erreicht."
          : kind === "auth" ? "Claude ist nicht angemeldet (CLAUDE_CODE_OAUTH_TOKEN prüfen)."
          : "Claude konnte nicht antworten.";
        console.error(`claude beendet mit Code ${code}: ${err.trim().slice(0, 300)}`);
        finish({ ok: false, kind, message });
      });
      child.stdin.on("error", () => {});
      child.stdin.end(prompt);
    });
  }

  async function ask(body) {
    const { prompt, system = "", model = "sonnet", memory = false } = body;
    if (typeof prompt !== "string" || !prompt.trim() || prompt.length > 60_000) return { status: 400, body: { ok: false, kind: "error", message: "prompt fehlt oder ist zu lang" } };
    if (typeof system !== "string" || system.length > 8_000) return { status: 400, body: { ok: false, kind: "error", message: "system ist zu lang" } };
    if (typeof model !== "string" || !MODEL_RE.test(model)) return { status: 400, body: { ok: false, kind: "error", message: "model ungültig" } };
    const useMemory = memory === true && fs.existsSync(memoryDir);
    const cwd = useMemory ? memoryDir : os.tmpdir();
    if (waiting >= maxQueue) return { status: 200, body: { ok: false, kind: "busy", message: "Claude ist gerade mit anderen Fragen beschäftigt." } };
    waiting += 1;
    const slot = tail.then(() => run(buildArgs({ model, system, memory: useMemory }, { restricted, maxTurns }), prompt, cwd));
    tail = slot.catch(() => {});
    try {
      return { status: 200, body: await slot };
    } finally {
      waiting -= 1;
    }
  }

  async function health() {
    if (version === null) {
      version = await new Promise((resolve) => {
        const child = spawn(bin, [...binArgs, "--version"], { env: cleanEnv(), stdio: ["ignore", "pipe", "ignore"] });
        let out = "";
        const timer = setTimeout(() => { child.kill(); resolve("unbekannt"); }, 10_000);
        child.stdout.on("data", (c) => { out += c; });
        child.on("error", () => { clearTimeout(timer); resolve("nicht installiert"); });
        child.on("close", () => { clearTimeout(timer); resolve(out.trim() || "unbekannt"); });
      });
    }
    return { ok: true, claude: version, token: Boolean(process.env.CLAUDE_CODE_OAUTH_TOKEN), memory: fs.existsSync(memoryDir) };
  }

  return http.createServer(async (req, res) => {
    try {
      if (req.method === "GET" && req.url === "/health") return send(res, 200, await health());
      if (req.method === "POST" && req.url === "/ask") {
        let body;
        try { body = JSON.parse(await readBody(req)); } catch { return send(res, 400, { ok: false, kind: "error", message: "Ungültiges JSON" }); }
        const { status, body: payload } = await ask(body || {});
        return send(res, status, payload);
      }
      send(res, 404, { ok: false, message: "nicht gefunden" });
    } catch (error) {
      console.error("Fehler:", error?.message);
      if (!res.headersSent) send(res, 500, { ok: false, kind: "error", message: "Interner Fehler" });
    }
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  fs.mkdirSync(process.env.HOME || os.tmpdir(), { recursive: true });
  const port = Number(process.env.PORT || 8099);
  createServer().listen(port, "0.0.0.0", () => console.log(`Claude-Brücke auf Port ${port}`));
}
