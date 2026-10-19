# Lernen aus Wiederholungen (Kurzbefehle ohne Sprachmodell)

Cat hat **keine vorgefertigten Befehlssätze** mehr (früher: Fast-Path mit Synonymliste). Stattdessen gilt:

1. Jede Anfrage löst zuerst das lokale Modell (bei Bedarf Claude) mit seinen Geräte-Werkzeugen. Das dauert je nach Anfrage 5 bis 60 Sekunden.
2. Cat beobachtet, **was dabei passiert ist**: Welche Geräte-Werkzeuge hat das Modell aufgerufen (`set_state`, `get_state`), mit welchem Ergebnis?
3. Führt **dieselbe Formulierung zweimal** (einstellbar, `CAT_LEARN_AFTER`) zu **denselben Aktionen**, merkt sich Cat sie als Kurzbefehl. Es sagt das im Chat ("Gemerkt: Auf "schalte {dev} an" antworte ich künftig sofort ...").
4. Ab dem dritten Mal läuft der Kurzbefehl **ohne Sprachmodell**: Antwort in Millisekunden, auch ohne Internet. Ausgeführt wird er über denselben Gerätedienst wie alles andere: Steuerungsmodus, Risikostufe, Bestätigung bei Türen und Schlössern, Audit-Log (`learned_shortcut`).

## Bausteine

Damit nicht jede Formulierung einzeln gelernt werden muss, zerlegt Cat, was es gelernt hat:

| Baustein | Beispiel |
|---|---|
| **Gerät** als Platzhalter: steht der Name des Geräts (oder ein Synonym) wörtlich im Satz | gelernt "schalte deckenlicht roman an" → gilt auch für "schalte deckenlicht marius an", obwohl das nie gesagt wurde |
| **Zahl** als Platzhalter | gelernt "fahre romans rollo auf 50 prozent" → gilt auch für "auf 30 prozent" (der Bereich wird geprüft, 500 Prozent geht an das Modell) |
| **Raum** (Satellit oder Raumgerät) | "mach das licht an" im Küchen-Satelliten gilt nur dort und schaltet das Küchenlicht |
| **Ablauf** mehrerer Geräte in einem Satz | "gute nacht" → mehrere Lichter aus, Rollläden zu (nur wörtlich, nur wenn es immer dasselbe ergab) |
| **Abfragen** | "ist romans rollo offen", "wie warm ist es draußen" |

Ein Gerätename mit Umlauten, Groß-/Kleinschreibung oder Satzzeichen ist egal. Der Platzhalter findet das Gerät nur bei **genau** gleicher Bezeichnung (Name, Synonym oder id), nie unscharf: im Zweifel fragt Cat lieber das Modell.

## Was nicht gelernt wird

- Anfragen, bei denen etwas anderes als Geräte-Werkzeuge lief (Gedächtnis, Stage, Rechnen, Claude) oder etwas scheiterte.
- Sätze, die vom Gespräch abhängen: "mach es wieder aus" direkt nach demselben Gerät (das "es" ändert sich ja).
- Eine Formulierung, die einmal zu anderen Aktionen führte, beginnt von vorn zu zählen.

## Transparenz und Kontrolle

Das Widget **"Gelernt"** (links unten, verschiebbar) zeigt alles, was Cat sich gemerkt hat: die Formulierung, was sie tut, wie oft sie genutzt wurde, und was noch auf dem Weg ist ("gesehen 1/2"). Jeder Eintrag lässt sich löschen (zweimal klicken), oder alles auf einmal ("Alles vergessen"). Verschwindet ein Gerät aus openHAB, vergisst Cat den zugehörigen Kurzbefehl selbst. Die Datei ist `data/learned.json` (höchstens 300 Einträge, ältere ungenutzte fallen zuerst heraus). Ausschalten: `CAT_LEARN=false`.

## Sicherung gegen erfundene Erfolgsmeldungen

Das kleine lokale Modell hat einmal "Okay, Deckenlicht Roman ist aus" geantwortet, **ohne** ein Werkzeug aufzurufen (am 17.10.2026 im Chat, "Mach es wieder aus": das Licht blieb an). Jetzt prüft der Agent jede Antwort, die eine Schaltung oder einen Gerätezustand behauptet ("ist aus", "ist jetzt an", "habe eingeschaltet", "erledigt"), gegen die Werkzeugaufrufe dieser Anfrage. Ohne Werkzeug wird die Antwort **nicht gezeigt**; das Modell bekommt den Hinweis, dass nichts passiert ist, und muss das Werkzeug aufrufen oder ehrlich sagen, dass es nicht ging. Gelingt auch das nicht, antwortet Cat: "Das habe ich nicht ausgeführt, weil ich dafür kein Gerät angesprochen habe." Außerdem weiß das Modell jetzt, welches Gerät zuletzt bedient wurde ("es" und "das Licht" lassen sich so auflösen), und bei Satelliten, in welchem Raum der Nutzer spricht.

## Füllsätze (intents/fillers.py)

Passend zur Anfrage wählt Cat eine von fünf Arten: **nachsehen** ("Welche Markisen sind offen?": "Warte kurz, ich schaue schnell nach."), **schalten** ("Mach das Licht an": "Mach ich, einen Moment."), **merken**, **nachdenken** (allgemeine Frage) und **Claude** (schwere Frage, dauert länger). Manche Sätze nennen das Stichwort der Anfrage ("Ich schaue kurz bei Markisen nach."). Die Wahl ist **keine Modellanfrage** (auch eine kurze kostet auf dieser CPU 3 bis 5 Sekunden und käme zu spät), sondern entsteht in Mikrosekunden aus den Wörtern der Anfrage: Frage oder Schaltbefehl, kommt ein Gerätewort vor, geht es an Claude.

Die Liste **lernt dazu**:
- **Sie wächst von selbst.** Ist Cat untätig (90 Sekunden keine Anfrage), lässt es das lokale Modell neue Sätze für die Art schreiben, die am meisten gebraucht wird und die wenigsten Sätze hat (höchstens 4 Läufe pro Tag, `CAT_FILLER_GENERATE`). Jeder neue Satz wird geprüft: 2 bis 9 Wörter, Satzzeichen am Ende, keine Zahlen, kein Markdown, nichts, was ein Ergebnis behauptet ("Das Licht ist aus."), nicht doppelt.
- **Abwechslung:** Der am längsten nicht benutzte Satz kommt zuerst, nie zweimal derselbe hintereinander. Der Gebrauch wird gezählt.
- **Löschen:** Im Widget "Gelernt", Reiter "Füllsätze", lässt sich jeder Satz löschen. Gelöschte Sätze kommen nicht wieder, auch nicht die Vorgaben.
- Gespeichert in `data/fillers.json`.
