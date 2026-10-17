# KI-erzeugte Plugins: Vorschlag, Prüfung, Freigabe

Cat kann mit dem Tool `propose_plugin` Code für ein neues Plugin vorschlagen. Das ist ausdrücklich **kein** Selbstumbau: Ein Vorschlag wird nie importiert, gestartet oder ausgeführt.

## Ablauf

1. **Vorschlag.** Cat legt ihn unter `data/plugins/pending/<name>/` ab (`plugin.py`, `README.md` mit "NICHT AKTIV", `meta.json`) und zeigt den Code auf der Stage. Vorhandene Vorschläge werden nie überschrieben (der Name bekommt ein `_2`).
2. **Prüfung durch Sie.** Lesen Sie `plugin.py` ganz. Worauf achten: Netzwerkzugriffe (wohin?), Dateizugriffe außerhalb von `data/`, `subprocess`, `os.system`, `eval`/`exec`, Zugriff auf Tokens oder `.env`. Ein Plugin läuft **im Cat-Prozess mit denselben Rechten wie Cat**: Es kann alles, was Cat kann. Geben Sie nur Code frei, den Sie verstehen.
3. **Freigabe von Hand.**
   ```bash
   cd /srv/homelm/data/plugins
   mkdir -p active
   mv pending/<name> active/<name>
   ```
   dann in der `.env` den Namen zu `CAT_PLUGINS` hinzufügen (z. B. `CAT_PLUGINS=system,weather,openhab,<name>`) und Cat neu starten (`docker compose up -d --no-build`).
4. **Zurücknehmen.** Namen aus `CAT_PLUGINS` entfernen und neu starten, oder den Ordner aus `active/` löschen.

## Garantien (durch Tests abgesichert)

- Ein Plugin in `pending/` wird **nie** geladen, auch nicht, wenn sein Name in `CAT_PLUGINS` steht.
- Aus `active/` wird nur geladen, was **auch** in `CAT_PLUGINS` steht.
- Eingebaute Plugins (`system`, `weather`, `openhab`, `homeassistant`) lassen sich nicht durch einen Ordner in `active/` ersetzen.
- Ein fehlerhaftes oder unvollständiges Plugin wird übersprungen und im Log gemeldet; Cat startet trotzdem.
- Geräte-Steuerung durch ein Plugin läuft nicht an der Allowlist vorbei, **solange das Plugin den `DeviceService` benutzt**. Nichts hindert fremden Code aber daran, direkt eigene Netzwerkaufrufe zu machen: Deshalb ist die Prüfung in Schritt 2 die eigentliche Sicherheitsgrenze.

## Schnittstelle

`plugin.py` bietet ein Objekt `PLUGIN` oder eine Funktion `create_plugin(services)` mit den Mitgliedern `name`, `start(ctx)`, `stop()`, `tools()`, `widgets()`, `intents()` (siehe `backend/src/cat/plugins/base.py`).
