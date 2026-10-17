# Wake-Word: eigenes "Hey Cat" trainieren

Der Name "Cat" allein ist als Wake-Word sehr kurz und fehleranfällig. "Hey Cat" oder "Okay Cat" ist zuverlässiger. Der Satellit nutzt **openWakeWord** (läuft lokal auf dem Pi, mit ONNX).

## Zum Start: ein mitgeliefertes Modell

`wakeword_model: hey_jarvis` in der `config.yaml` (weitere: `alexa`, `hey_mycroft`, `hey_rhasspy`). Damit lässt sich der ganze Weg testen, ohne etwas zu trainieren. Die mitgelieferten Modelle sind nach der Dokumentation von openWakeWord nur für nichtkommerzielle Nutzung lizenziert (CC BY-NC-SA 4.0), für zu Hause ist das in Ordnung.

## Eigenes Modell "Hey Cat" trainieren

Stand der Anleitung: openWakeWord beschreibt zwei Wege, ein eigenes Modell zu erzeugen. Ich habe das Training **nicht selbst ausgeführt** (es braucht Rechenzeit auf einer GPU, etwa bei Google Colab, und dauert nach Angabe des Projekts ungefähr eine Stunde). Die Schritte folgen der Projektdokumentation (github.com/dscripka/openWakeWord):

1. **Notebook öffnen.** Entweder das im README verlinkte Google-Colab-Notebook (einfachster Weg, laut Projekt in unter einer Stunde ein Grundmodell) oder `notebooks/automatic_model_training.ipynb` aus dem Repository (mehr Einstellmöglichkeiten). Das Notebook `training_models.ipynb` ist nur zum Lernen gedacht, nicht für ein Modell im Alltag.
2. **Zielsatz festlegen:** `hey cat` (ggf. auch Varianten wie `okay cat`).
3. **Trainingsdaten:** Das Notebook erzeugt viele künstliche Sprachaufnahmen des Satzes mit einer Open-Source-Sprachsynthese. Das Projekt empfiehlt mindestens einige tausend Beispiele. Dazu kommen Negativdaten (Sprache, Geräusche, Musik ohne den Zielsatz), damit das Modell nicht ständig falsch auslöst; das Notebook bringt dafür Standarddaten mit.
4. **Training laufen lassen** und das fertige Modell herunterladen. Das Notebook gibt eine Modelldatei aus (die Dokumentation nennt sie nicht ausdrücklich; erwartet wird eine `.onnx`- oder `.tflite`-Datei). Der Satellit nutzt ONNX: Ist nur eine `.tflite`-Datei dabei, im Notebook die ONNX-Ausgabe wählen oder umwandeln.
5. **Auf den Pi kopieren** (z. B. nach `/opt/cat-satellite/models/hey_cat.onnx`) und in der `config.yaml` eintragen:
   ```yaml
   wakeword_model: /opt/cat-satellite/models/hey_cat.onnx
   wakeword_threshold: 0.5
   ```
6. **Mit echten Aufnahmen prüfen**, in jedem Raum, mit allen Sprechern im Haus, auch bei laufendem Fernseher. Schwelle anpassen: Löst es zu oft aus, `wakeword_threshold` erhöhen (z. B. 0,6 bis 0,7); überhört es dich, senken. Ein rein künstlich trainiertes Modell erkennt echte Stimmen meist schlechter als Synthetik, ein paar Wochen Alltagsbetrieb zeigen, ob ein Nachtraining mit eigenen Aufnahmen nötig ist.

## Hinweise

- Das Wake-Word läuft ausschließlich lokal auf dem Satelliten. Vor dem Auslösen verlässt kein Audio das Gerät.
- Mehrere Satelliten in Hörweite können gleichzeitig auslösen. Sie verbinden sich getrennt, der Server bedient sie nacheinander; räumlich nahe Satelliten besser mit verschiedenen Schwellen betreiben oder nur einen aktiv lassen.
