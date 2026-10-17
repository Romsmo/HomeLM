// Ersatz für die `claude`-CLI in den Tests: liest den Prompt von stdin und antwortet im
// JSON-Format der echten CLI. Das Verhalten steuert ein "MODE:xyz" im Prompt.
import fs from "node:fs";

if (process.argv.includes("--version")) {
  console.log("9.9.9 (Claude Code, Test)");
  process.exit(0);
}
const prompt = fs.readFileSync(0, "utf8");
const mode = /MODE:(\w+)/.exec(prompt)?.[1] ?? "ok";
const result = (extra) =>
  console.log(JSON.stringify({ type: "result", session_id: "s", num_turns: 1, total_cost_usd: 0.002, ...extra }));

if (mode === "hang") {
  setInterval(() => {}, 1000);
} else if (mode === "limit") {
  result({ subtype: "success", is_error: true, result: "Claude usage limit reached. Your limit will reset at 5pm." });
  process.exit(1);
} else if (mode === "auth") {
  result({ subtype: "success", is_error: true, result: "Invalid API key · Please run /login" });
  process.exit(1);
} else if (mode === "garbage") {
  console.log("kein json");
} else if (mode === "crash") {
  console.error("Segfault");
  process.exit(2);
} else if (mode === "maxturns") {
  result({ subtype: "error_max_turns", is_error: false });
} else if (mode === "list") {
  console.log(JSON.stringify([{ type: "system" }, { type: "result", subtype: "success", is_error: false, result: "aus Liste", num_turns: 2 }]));
} else {
  // Gibt zurück, womit die CLI gestartet wurde, damit die Tests die Sicherheitsflags prüfen.
  result({
    subtype: "success",
    is_error: false,
    result: JSON.stringify({ args: process.argv.slice(2), prompt, cwd: process.cwd(), env: Object.keys(process.env).sort() }),
  });
}
