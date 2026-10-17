# Code-Sandbox (`run_python`)

Cat kann Python-Programme für Rechnungen, Auswertungen und Diagramme ausführen, **aber nie im Cat-Prozess**.

## Aufbau

- Eigener Container `homelm-sandbox` (Verzeichnis `sandbox/`), gestartet mit dem Cat-Stack.
- **Kein Netzwerk** (`network_mode: none`), Dateisystem schreibgeschützt (nur `/tmp` als kleines tmpfs), **alle Linux-Capabilities entfernt**, `no-new-privileges`, Prozesslimit 64, **512 MB RAM**, 1 CPU, läuft als unprivilegierter Benutzer.
- Cat bekommt **keinen Docker-Zugriff** (kein Docker-Socket). Cat und Sandbox tauschen nur Dateien im Ordner `data/sandbox` aus: Cat legt `jobs/<id>/code.py` und `request.json` ab, der Worker führt aus und schreibt `result.json` (und PNG-Bilder).
- Jeder Auftrag läuft als eigener Prozess mit CPU-Zeitlimit (1 bis 30 s, Standard 10 s), Speicherlimit (450 MB), Dateigrößenlimit (10 MB), höchstens 64 offenen Dateien und eigener Prozessgruppe, die bei Zeitüberschreitung mit SIGKILL beendet wird. Ausgaben werden auf 20.000 Zeichen gekürzt.
- Verfügbar: Python 3.12, Standardbibliothek, numpy, matplotlib (Backend Agg). Kein pip, kein Internet.

## Ergebnisse

- Text (`print`) und Fehlerausgabe gehen an das Modell.
- **Diagramme:** PNG-Dateien im Arbeitsordner (`plt.savefig('bild.png')`, bis zu 5 Stück, je höchstens 1,5 MB) erscheinen auf der Stage (eingebettet als `data:`-URL in der Sandbox-iframe).
- Läuft der Container nicht, meldet das Tool das ausdrücklich und führt **nichts** anderswo aus.

## Grenzen (ehrlich)

- Mehrere Aufträge teilen sich den Container: Ein bösartiger Auftrag könnte die Ergebnisdateien eines gleichzeitigen anderen Auftrags verändern. Cat führt Aufträge nacheinander aus und es gibt nur einen Nutzer, das Risiko ist gering.
- Die Sandbox schützt vor Netzwerkzugriff, Zugriff auf Hausdaten und Ressourcenverbrauch. Ein Ausbruch aus Docker selbst (Kernel-Lücke) ist damit nicht ausgeschlossen, wie bei jedem Container.
- Abschalten: `CAT_SANDBOX=false` (Tool wird nicht angeboten) und `docker compose stop sandbox`.
