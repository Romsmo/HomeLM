import { useCallback, useEffect, useState } from "react";
import {
  type FillerRow,
  type NoteRow,
  type PeopleInfo,
  type TermRow,
  deleteFiller,
  deleteNote,
  deleteTerm,
  forgetPerson,
  forgetVoice,
  listFillers,
  listNotes,
  listPeople,
  listTerms,
} from "../lib/brain";

const NO_PEOPLE: PeopleInfo = { enabled: false, voiceAvailable: false, people: [] };

/** Notizen, Personen und Füllsätze. `refreshKey` ändern, um neu zu laden (z. B. neue Nachricht). */
export function useBrain(connected: boolean, refreshKey: number) {
  const [notes, setNotes] = useState<NoteRow[]>([]);
  const [people, setPeople] = useState<PeopleInfo>(NO_PEOPLE);
  const [fillers, setFillers] = useState<FillerRow[]>([]);
  const [terms, setTerms] = useState<TermRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    // Jede Liste für sich: fehlt eine Schnittstelle, bleiben die anderen nutzbar.
    await Promise.all([
      listNotes().then(setNotes, () => {}),
      listPeople().then(setPeople, () => {}),
      listFillers().then(setFillers, () => {}),
      listTerms().then(setTerms, () => {}),
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
    terms,
    error,
    removeNote: (path: string) => run(() => deleteNote(path))(),
    removeVoice: (id: string) => run(() => forgetVoice(id))(),
    removePerson: (id: string) => run(() => forgetPerson(id))(),
    removeFiller: (text: string) => run(() => deleteFiller(text))(),
    removeTerm: (term: string) => run(() => deleteTerm(term))(),
  };
}

export type Brain = ReturnType<typeof useBrain>;
