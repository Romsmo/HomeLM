import { useCallback, useEffect, useState } from "react";
import { type LearnedRow, forgetAllLearned, forgetLearned, listLearned } from "../lib/learned";

/** Was Cat sich gemerkt hat (Kurzbefehle). `refreshKey` ändern, um neu zu laden (z. B. neue Nachricht). */
export function useLearned(connected: boolean, refreshKey: number) {
  const [rows, setRows] = useState<LearnedRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRows(await listLearned());
    } catch {
      // nur eine Anzeige; beim nächsten Mal wieder
    }
  }, []);

  useEffect(() => {
    if (connected) void refresh();
  }, [connected, refreshKey, refresh]);

  const forget = useCallback(
    async (id: string) => {
      try {
        await forgetLearned(id);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Vergessen fehlgeschlagen");
      }
      void refresh();
    },
    [refresh],
  );

  const forgetAll = useCallback(async () => {
    try {
      await forgetAllLearned();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Vergessen fehlgeschlagen");
    }
    void refresh();
  }, [refresh]);

  return { rows, error, forget, forgetAll };
}
