import { type FormEvent, useState } from "react";
import { login } from "../api";
import Orb from "./Orb";

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError(null);
    const result = await login(password);
    setBusy(false);
    if (result.ok) {
      setPassword("");
      onSuccess();
    } else {
      setError(result.message);
    }
  }

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-8 p-6">
      <Orb state={busy ? "thinking" : "idle"} />
      <form
        onSubmit={submit}
        className="flex w-full max-w-xs flex-col gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 p-5 backdrop-blur"
      >
        <h1 className="text-center text-lg font-semibold tracking-widest uppercase">Cat</h1>
        <label className="flex flex-col gap-1 text-sm text-slate-300">
          Passwort
          <input
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400"
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-rose-400">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || !password}
          className="rounded-lg bg-cyan-500 px-3 py-2 font-medium text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
        >
          Anmelden
        </button>
      </form>
    </main>
  );
}
