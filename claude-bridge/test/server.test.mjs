import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import { buildArgs, classify, createServer, parseResult } from "../server.mjs";

const fake = path.join(path.dirname(fileURLToPath(import.meta.url)), "fake-claude.mjs");
const memory = fs.mkdtempSync(path.join(os.tmpdir(), "mem-"));

function start(options = {}) {
  const server = createServer({ bin: process.execPath, binArgs: [fake], memoryDir: memory, timeoutMs: 3000, ...options });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, url: `http://127.0.0.1:${server.address().port}` })));
}

async function ask(url, body) {
  const res = await fetch(`${url}/ask`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return { status: res.status, body: await res.json() };
}

describe("Hilfsfunktionen", () => {
  test("classify", () => {
    assert.equal(classify("Claude usage limit reached"), "limit");
    assert.equal(classify("HTTP 429 Too Many Requests"), "limit");
    assert.equal(classify("Invalid API key · Please run /login"), "auth");
    assert.equal(classify("irgendwas"), "error");
  });

  test("parseResult: Objekt, Liste, Fehler", () => {
    assert.deepEqual(parseResult(JSON.stringify({ type: "result", result: "Hi", total_cost_usd: 0.1, num_turns: 2 })), {
      ok: true, text: "Hi", cost_usd: 0.1, turns: 2,
    });
    assert.equal(parseResult(JSON.stringify([{ type: "system" }, { type: "result", result: "X" }])).text, "X");
    assert.equal(parseResult("nope").ok, false);
    assert.equal(parseResult(JSON.stringify({ type: "result", is_error: true, result: "rate limit hit" })).kind, "limit");
  });

  test("buildArgs: nur Lesewerkzeuge mit Gedächtnis, sonst keine", () => {
    const withMemory = buildArgs({ model: "sonnet", system: "S", memory: true });
    const at = withMemory.indexOf("--tools");
    assert.deepEqual(withMemory.slice(at, at + 4), ["--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob"]);
    const none = buildArgs({ model: "sonnet", system: "", memory: false });
    assert.equal(none[none.indexOf("--tools") + 1], "");
    for (const args of [withMemory, none]) {
      assert.ok(args.includes("--restricted") && args.includes("--no-session-persistence") && args.includes("--strict-mcp-config"));
      assert.equal(args[args.indexOf("--permission-mode") + 1], "dontAsk");
      assert.ok(!args.some((a) => /bypass|dangerously|Bash|Edit|Write/i.test(a)));
    }
  });
});

describe("HTTP-Dienst", () => {
  let ctx;
  before(async () => {
    ctx = await start();
  });
  after(() => ctx.server.close());

  test("Antwort, Flags, Arbeitsverzeichnis und Umgebung", async () => {
    process.env.ANTHROPIC_API_KEY = "sk-ant-darf-nicht-durch";
    process.env.CLAUDE_CODE_OAUTH_TOKEN = "token-test";
    const { status, body } = await ask(ctx.url, { prompt: "Hallo", system: "Du bist Cat", model: "sonnet", memory: true });
    delete process.env.ANTHROPIC_API_KEY;
    assert.equal(status, 200);
    assert.equal(body.ok, true);
    const seen = JSON.parse(body.text);
    assert.equal(fs.realpathSync(seen.cwd), fs.realpathSync(memory));
    assert.equal(seen.prompt, "Hallo");
    assert.ok(seen.args.includes("--append-system-prompt") && seen.args.includes("Du bist Cat"));
    assert.ok(seen.env.includes("CLAUDE_CODE_OAUTH_TOKEN"));
    assert.ok(!seen.env.includes("ANTHROPIC_API_KEY"), "API-Schlüssel darf nicht an die CLI gehen");
  });

  test("ohne Gedächtnis: keine Werkzeuge, nicht im Gedächtnis-Ordner", async () => {
    const { body } = await ask(ctx.url, { prompt: "Hi", memory: false });
    const seen = JSON.parse(body.text);
    assert.notEqual(fs.realpathSync(seen.cwd), fs.realpathSync(memory));
    assert.equal(seen.args[seen.args.indexOf("--tools") + 1], "");
  });

  for (const [mode, kind] of [["limit", "limit"], ["auth", "auth"], ["garbage", "error"], ["crash", "error"], ["maxturns", "error"]]) {
    test(`Fehlerart ${mode}`, async () => {
      const { body } = await ask(ctx.url, { prompt: `MODE:${mode}` });
      assert.equal(body.ok, false);
      assert.equal(body.kind, kind);
    });
  }

  test("Ausgabe als Liste", async () => {
    const { body } = await ask(ctx.url, { prompt: "MODE:list" });
    assert.deepEqual([body.ok, body.text], [true, "aus Liste"]);
  });

  test("ungültige Eingaben", async () => {
    assert.equal((await ask(ctx.url, {})).status, 400);
    assert.equal((await ask(ctx.url, { prompt: "x", model: "a b; rm -rf" })).status, 400);
    assert.equal((await ask(ctx.url, { prompt: "x".repeat(70_000) })).status, 400);
    const bad = await fetch(`${ctx.url}/ask`, { method: "POST", body: "{kaputt" });
    assert.equal(bad.status, 400);
    assert.equal((await fetch(`${ctx.url}/nichts`)).status, 404);
  });

  test("health nennt Version, ob ein Token da ist, und nie das Token selbst", async () => {
    process.env.CLAUDE_CODE_OAUTH_TOKEN = "geheim-123";
    const text = await (await fetch(`${ctx.url}/health`)).text();
    assert.ok(!text.includes("geheim-123"));
    const body = JSON.parse(text);
    assert.equal(body.ok, true);
    assert.match(body.claude, /9\.9\.9/);
    assert.equal(body.token, true);
  });
});

describe("Zeitlimit und Warteschlange", () => {
  test("hängende CLI wird nach dem Zeitlimit beendet", async () => {
    const { server, url } = await start({ timeoutMs: 500 });
    const { body } = await ask(url, { prompt: "MODE:hang" });
    server.close();
    assert.equal(body.kind, "timeout");
  });

  test("zu viele gleichzeitige Fragen: busy", async () => {
    const { server, url } = await start({ timeoutMs: 1500, maxQueue: 1 });
    const first = ask(url, { prompt: "MODE:hang" });
    await new Promise((resolve) => setTimeout(resolve, 150));
    const second = await ask(url, { prompt: "Hi" });
    assert.equal(second.body.kind, "busy");
    await first;
    server.close();
  });
});
