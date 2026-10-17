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
