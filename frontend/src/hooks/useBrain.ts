import { useCallback, useEffect, useState } from "react";
import {
  type FillerRow,
  type NoteRow,
  type PeopleInfo,
  deleteFiller,
  deleteNote,
  forgetPerson,
  forgetVoice,
  listFillers,
  listNotes,
  listPeople,
} from "../lib/brain";

const NO_PEOPLE: PeopleInfo = { enabled: false, voiceAvailable: false, people: [] };

/** Notizen, Personen und Füllsätze. `refreshKey` ändern, um neu zu laden (z. B. neue Nachricht). */
export function useBrain(connected: boolean, refreshKey: number) {
  const [notes, setNotes] = useState<NoteRow[]>([]);
  const [people, setPeople] = useState<PeopleInfo>(NO_PEOPLE);
  const [fillers, setFillers] = useState<FillerRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    // Jede Liste für sich: fehlt eine Schnittstelle, bleiben die anderen nutzbar.
    await Promise.all([
      listNotes().then(setNotes, () => {}),
      listPeople().then(setPeople, () => {}),
      listFillers().then(setFillers, () => {}),
    ]);
  }, []);

  useEffect(() => {
    if (connected) void refresh();
  }, [connected, refreshKey, refresh]);

  const run = useCallback(
    (act: () => Promise<void>) => async () => {
      try {
        await act();
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Vergessen fehlgeschlagen");
      }
      void refresh();
    },
    [refresh],
  );

  return {
    notes,
    people,
    fillers,
    error,
    removeNote: (path: string) => run(() => deleteNote(path))(),
    removeVoice: (id: string) => run(() => forgetVoice(id))(),
    removePerson: (id: string) => run(() => forgetPerson(id))(),
    removeFiller: (text: string) => run(() => deleteFiller(text))(),
  };
}

export type Brain = ReturnType<typeof useBrain>;
