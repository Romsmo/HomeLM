# Gedächtnis (Second Brain)

Das Gedächtnis liegt **außerhalb des Modells**: Ein Wechsel von Anbieter oder Modell ändert nichts, die Notizen bleiben.

## Aufbau

- **Quelle der Wahrheit:** Markdown-Dateien in `data/memory/<thema>/<titel>.md` mit Frontmatter (`title`, `date`, `tags`). Sie sind von Hand les- und bearbeitbar (z. B. in Obsidian), neue Dateien werden automatisch erkannt.
- **Index:** SQLite mit FTS5 unter `data/memory/index.sqlite`. Das ist nur ein Cache: Er gleicht sich bei jeder Suche mit den Dateien ab (Größe und Änderungszeit) und lässt sich jederzeit löschen. Die Suche arbeitet mit Wortanfängen, damit "trinke" auch "trinkt" findet (kein deutscher Stemmer nötig).
- **Vektorsuche:** als Schnittstelle vorbereitet (`VectorIndex`, derzeit ein leerer Platzhalter). `sqlite-vec` plus ein kleines Embedding-Modell lassen sich später einhängen. Ob das nötig ist, zeigt die Praxis.

## Wie der Agent es nutzt

- Vor jeder Antwort sucht Cat lokal nach passenden Erinnerungen (die letzte Nutzernachricht als Suchtext) und gibt die besten drei als "Erinnerungen" in den Prompt. Unpassendes bleibt draußen.
- Werkzeuge: `memory_search` (gezielt suchen), `memory_write` (merken), `memory_list` (zeigen, was da ist).
- Geschrieben wird nur auf Aufforderung ("Merk dir, dass ...") oder bei klar dauerhaften Fakten (Vorlieben). Gleicher Titel im gleichen Thema ergänzt die Notiz.
- **Geheimnisse werden nicht gespeichert:** Texte, die wie Passwörter, Tokens oder API-Schlüssel aussehen, lehnt `memory_write` ab, weil die Dateien im Klartext liegen.
- Schutz vor Pfadtricks: Thema und Titel werden zu sicheren Dateinamen, nichts landet außerhalb von `data/memory`.

## Gesprächsverlauf

- Jede Nachricht wird in `data/sessions/<Sitzung>.jsonl` protokolliert (eine Sitzung beginnt beim Serverstart und bei "Leeren"). Abschaltbar mit `CAT_SESSION_LOG=false`.
- **Zusammenfassung:** Beim Start fasst Cat Sitzungen, die älter als 3 Tage sind (mindestens zwei Nutzernachrichten), per LLM in Notizen zusammen (Thema `gespraeche`, Tag `gespräch`) und markiert sie mit einer `.done`-Datei. Dabei gehen Gesprächsinhalte an den LLM-Anbieter (wie beim normalen Chat). Ohne API-Schlüssel oder Internet passiert nichts, der nächste Start versucht es erneut. Abschaltbar mit `CAT_SUMMARIZE_SESSIONS=false`.

## Datenschutz und Sicherung

Notizen und Verläufe liegen unverschlüsselt in `/srv/homelm/data`. Sie gehören in die tägliche Sicherung von `data/` (siehe `docs/cat-plan.md`, Abschnitt 8). Einzelne Erinnerungen löschen Sie, indem Sie die Datei löschen.

## Second Brain überall (Phase 20)

Das Gedächtnis ist nicht mehr nur ein Werkzeug, das der Agent auf Zuruf benutzt, sondern in allen Pfaden eingebunden:

- **Vor jeder Antwort** (lokal, über Claude, per Sprache, Satellit) sucht Cat passende Notizen und gibt sie dem Modell mit. Kennt Cat den Sprecher, kommen **dessen Notizen zuerst** (Profil und mit seinem Namen markierte Fakten).
- **Wissens-Cache:** Antwortet Claude auf eine allgemeine, zeitlose Frage ("Wer hat Faust geschrieben?"), wird die Antwort als Notiz im Thema `wissen` abgelegt (Frage, Antwort, Datum). Dieselbe Frage später beantwortet Cat **sofort aus dem Gedächtnis**, ohne Claude und ohne Abo-Kontingent, mit dem Hinweis "Aus dem Gedächtnis (Antwort von Claude vom ...)" und "Sag „frag Claude nochmal“ für eine frische Antwort". Nicht gespeichert wird, was sich ändert oder persönlich ist (Wetter, Uhrzeit, Nachrichten, Preise, "heute", "aktuell", Fragen über den Nutzer, Geräte, Grafiken). Antworten älter als 180 Tage gelten nicht mehr als fertige Antwort. Abschaltbar: `CAT_KNOWLEDGE_CACHE=false`.
- **Selbst merken (`memory/reflect.py`):** Sagt jemand "Ich trinke morgens Kaffee mit Hafermilch" oder "Meine Tochter heißt Lena", klingt das nach einem dauerhaften Fakt. Ein billiger Wortfilter merkt sich solche Äußerungen (keine Fragen, keine Gerätebefehle). Ist Cat 60 Sekunden untätig, fragt es das lokale Modell einmal, welche dauerhaften Fakten darin stehen (JSON), prüft jeden (dritte Person, kurz, keine Geheimnisse) und legt Notizen an (Tag `auto`, dazu der Name des Sprechers). Cat sagt im Chat, was es sich gemerkt hat. Abschaltbar: `CAT_REFLECT=false`.
- **Vergessen:** "Vergiss, dass ich ..." ruft `memory_forget` (löscht, wenn genau eine Notiz passt, sonst fragt Cat nach). Im Widget "Gelernt", Reiter "Notizen", lässt sich jede Notiz löschen (`GET`/`DELETE /api/memory`).
- **Kurzbefehle als Notiz:** Was Cat aus Wiederholungen gelernt hat, steht auch als Notiz `gelerntes/kurzbefehle.md` im Gedächtnis (für Obsidian und Claude lesbar).

## Wie das Second Brain aufgebaut ist und was es fürs Tempo bringt

**Aufbau.** Quelle der Wahrheit sind Markdown-Dateien `data/memory/<thema>/<titel>.md` (Kopf: Titel, Datum, Tags). Dazu ein SQLite-FTS5-Index als Wegwerf-Cache, der sich bei jeder Suche mit den Dateien abgleicht. Gesucht wird mit Wortanfängen (ODER-verknüpft, Titel zählt 4, Tags 3, Thema 2, Text 1, bm25). **Es gibt keine Vektorsuche**: Die Schnittstelle ist vorbereitet, benutzt wird sie nicht.
- Schreiben: Werkzeug `memory_write` (Modell), `teach` (Regeln, "merk dir das"), `reflect` (im Leerlauf Fakten aus Gesprächen), Wissens-Cache (Antworten von Claude), Profile von Personen, Kurzbefehle als Notiz, Zusammenfassungen alter Gespräche.
- Lesen: `context_for` (die besten 3 Treffer kommen an die Nutzernachricht, bei bekanntem Sprecher zuerst dessen Notizen), `memory_search`, `cached_answer` (vor dem Modell), Claude (nur lesend).
- Daneben stehen vier **Assoziationsspeicher außerhalb der Notizen**, die schneller sind als jede Suche: `learned.json` (Formulierung -> Aktion), `lexicon.json` (Begriff -> Geräte), `fillers.json` (Art der Anfrage -> Füllsatz), `people.json` (Stimme -> Person).

**Macht es das Modell schneller?** Nicht dadurch, dass das Modell "schneller denkt": Ein 4B-Modell hat kein assoziatives Gedächtnis, und Notizen im Prompt **kosten** Zeit (die CPU verarbeitet nur 38 Token/s, jedes Token also ca. 26 ms; deshalb bekommen Geräteanfragen keine Erinnerungen mehr). Das Tempo kommt aus den festen Schichten **vor** dem Modell, die bekannte Fälle abfangen: gelernter Kurzbefehl 0,0 s statt 2 bis 4 s, Wissens-Cache 0,0 s statt 5 bis 40 s (lokal) oder Claude, erklärter Begriff ohne Rückfrage und ohne Modelltoken. Die Notizen selbst verbessern vor allem Treffsicherheit und Persönlichkeit (Vorlieben, Namen, Wissen), nicht die Geschwindigkeit.
