# Personen und Stimmerkennung

Cat lernt die Menschen im Haus kennen, damit es persönlicher antworten kann: mit dem Namen ansprechen, deren Notizen bevorzugen, Vorlieben merken. Das geht an der **Stimme** oder, wenn die nicht reicht, durch **Fragen** (Sprache und Chat).

## Ablauf (ohne Sprachmodell, mit festen kurzen Sätzen)

1. **Erkennen.** Bei jeder Sprachäußerung, die Cat betrifft (nach der Aktivierungsphrase), wird ein Stimm-Fingerabdruck berechnet und mit den gespeicherten verglichen: **erkannt**, **unsicher** ("Bist du Roman?") oder **unbekannt**.
2. **Fragen.** Cat hängt an seine Antwort **eine** Frage an, nie davor (die Anfrage wird nicht aufgehalten): bei unbekannter Stimme "Übrigens, ich kenne deine Stimme noch nicht. Wie heißt du?", im Chat ohne bekannte Person "Übrigens, mit wem spreche ich eigentlich? Wie heißt du?". Höchstens alle 20 Minuten, nach "Nein" 6 Stunden gar nicht, und wer stattdessen etwas anderes fragt, wird nicht weiter bedrängt.
3. **Kennenlernen.** Wer seinen Namen sagt ("Roman", "Ich heiße Roman", "Mein Name ist Roman"), wird angelegt. Bei Sprache fragt Cat danach: "Darf ich mir deine Stimme merken, damit ich dich nächstes Mal erkenne? Das bleibt nur hier im Haus." **Ohne ausdrückliches Ja wird keine Stimme gespeichert.**
4. **Begrüßen.** Die erste Äußerung nach längerer Pause (6 Stunden) beginnt mit "Hallo Roman!".
5. **Personalisieren.** Wer spricht, steht im Kontext des Modells ("Du sprichst gerade mit Roman"), und die Notizen dieser Person kommen zuerst aus dem Gedächtnis (Profil-Notiz `personen/<name>.md`, selbst gemerkte Fakten mit dem Namen als Tag). Der Chat übernimmt, wer in den letzten 10 Minuten per Stimme erkannt wurde, sonst gilt ein im Chat genannter Name 6 Stunden.

Ausdrückliche Vorstellungen ("Ich heiße ...") gelten jederzeit. "Ich bin ..." gilt nur nach der Frage ("Ich bin müde" ist kein Name).

## Vergessen (jederzeit)

- Sprache oder Chat: **"Vergiss meine Stimme"** (löscht nur den Fingerabdruck) und **"Vergiss mich"** (Name, Stimme, Profil-Notiz und alle mit dem Namen markierten Notizen).
- Oberfläche: Widget "Gelernt", Reiter "Personen" (`DELETE /api/people/<id>` und `/voice`).

## Technik

- Modell: **WeSpeaker CAM++** (ONNX, 29 MB, trainiert auf VoxCeleb), Merkmale Kaldi-Fbank (`kaldi-native-fbank`), Läuft mit onnxruntime auf der CPU wie die Spracherkennung. Das Modell wird beim ersten Start einmal von GitHub (sherpa-onnx-Veröffentlichung) nach `data/models/speaker/` geladen und per SHA-256 geprüft. Geht das nicht (kein Internet), bleibt die Stimmerkennung aus; Fragen und Chat funktionieren trotzdem.
- Aufwand: ca. 40 ms je Äußerung auf einem normalen PC (auf dem Server gemessen: siehe PROGRESS), mindestens 1 Sekunde Sprache nötig (kürzere Äußerungen wie "Ja." werden nicht zugeordnet).
- **Genauigkeit:** Gemessen an den Beispielen von sherpa-onnx: gleiche Person 0,69 bis 0,81, verschiedene 0,10 bis 0,49 (Cosinus). Cat nimmt eine Stimme ab 0,60 an (und mindestens 0,08 Abstand zur zweitähnlichsten Person), zwischen 0,45 und 0,60 fragt es nach, darunter ist sie unbekannt (`CAT_SPEAKER_THRESHOLD`, `CAT_SPEAKER_UNCERTAIN`, `CAT_SPEAKER_MARGIN`). Browser-Mikrofone, Hall und Erkältungen verschlechtern die Werte: Deshalb die Rückfrage im Zweifel. Bei sehr ähnlichen Stimmen (Geschwister, Vater und Sohn) kann es Verwechslungen geben. Jede sicher erkannte Äußerung frischt den Fingerabdruck auf (höchstens 8 pro Person).
- **Sicherheit:** Die Erkennung dient nur der Personalisierung, **nie** der Freigabe: Bestätigungen für Türen, Schlösser und Tore und alle anderen Prüfungen gelten für jeden gleich. Eine Stimme lässt sich nachahmen oder abspielen.
- Datenschutz: Fingerabdrücke sind biometrische Daten. Sie liegen nur in `data/people.json` (Rechte 600), werden nie in Notizen, Logs oder an Claude gegeben und nur nach Ja gespeichert. Ohne Zustimmung wird der Fingerabdruck einer unbekannten Stimme nur für die Dauer des Kennenlernens im Arbeitsspeicher gehalten (höchstens 3 Äußerungen).
- Einstellungen: `CAT_PEOPLE` (alles aus), `CAT_SPEAKER` (nur die Stimmerkennung aus), `CAT_PEOPLE_VOICE_ASK`, `CAT_PEOPLE_CHAT_ASK` (nicht nachfragen), `CAT_PEOPLE_TTL_H`.

## Änderungen nach dem Test vom 20.10. (Phase 23)

- **Namen, die auch Gerätewörter sind** ("Roman", "Marius" sind auch Räume): "Roman." als Antwort auf "Wie heißt du?" gilt jetzt als Name (vorher als Gerätebefehl, das Rollo ging auf). Als Anfrage zählen nur Fragen, Schaltwörter und längere Sätze über Geräte.
- **"Nein, Roman" nach "Bist du Christian?"** legt Roman an, merkt sich die Stimme als "gehört nicht zu Christian" (`negatives`) und fragt nach der Erlaubnis für Romans Stimme. Eine als falsch gemeldete Stimme wird nicht wieder für Christian gehalten.
- **"Ich bin Christian"** gilt auch ohne Frage, wenn der Name bekannt ist, oder wenn Cat gar nicht weiß, wer spricht (groß geschriebener Name). "Ich bin müde" bleibt kein Name. Außerdem "Du sollst dir Roman als Nutzer merken" und "Nenn mich Roman".
- **"Wer bin ich?"**, "Kennst du mich?", "Erkennst du meine Stimme?" werden fest beantwortet ("Du bist Christian, ich habe dich an der Stimme erkannt", "Ich glaube, du bist Christian. Stimmt das?" bei unsicherer Stimme, sonst die Frage nach dem Namen).
- **Lernphase:** Nach dem Ja zur Stimme lernen die nächsten 3 Äußerungen der Sitzung mit (eine einzige kurze Probe reicht nicht, um Stimmen zu unterscheiden). Der Fingerabdruck ignoriert Ausreißer (eine fremde Stimme im Gespräch zieht ihn nicht weg).
- **Schwellen:** erkannt ab 0,60 (und 0,08 Abstand zur zweitähnlichsten Person), "unsicher" ab 0,50 (vorher 0,45), darunter unbekannt. Jede Zuordnung steht im Log (`Stimme: bester Treffer ... 0.52 (zweiter ...)`), damit sich die Schwellen an echten Werten einstellen lassen.
