# Autonomer Ablauf im Testmodus

1. **Anforderung:** Der Controller prüft Projektgrant, unveränderten Checkout,
   Richtlinien und den effektiven Konfigurationshash.
2. **Analyse:** Der Orchestrator liefert eindeutige messbare Abnahmekriterien und Aufgaben.
3. **Architekturprüfung:** Der Architekt bewertet Struktur, Abhängigkeiten,
   Schnittstellen und Risiken. Beide Planungsausgaben dürfen aus einem Aufruf stammen.
4. **Entwicklung:** Der Entwickler bearbeitet Implementierung, Tests und Dokumentation.
   Der Controller erstellt daraus einen Commit auf einem separaten Branch.
5. **Tests:** Alle konfigurierten Prüfungen laufen an diesem Commit. Fehlende oder
   nicht ausführbare Pflichtprüfungen sind kein Erfolg.
6. **Unabhängige QA:** Eigener Rollenaufruf mit finalem Commit und vollständiger
   Kriterienprüfung. Das synthetische Beispiel startet einen eigenen Randfallprozess,
   der einen Fehler erkennen kann, den die Entwickler-Tests übersehen.
7. **Security:** Separater Rollenaufruf gegen Projektregeln. In der Demo sind die
   Prüflogik und Befunde deterministisch; dies ist kein allgemeiner Schwachstellenscanner.
8. **Korrektur:** Behebbare Test-, QA- oder Sicherheitsbefunde gehen an den Entwickler.
   Nach jeder Änderung beginnen sämtliche Tests und Reviews erneut.
9. **Pull Request:** Erst bei erfolgreichen Prüfungen erstellt der Delivery-Adapter
   den gemeinsamen PR mit Implementierung, Tests und Dokumentation. In der Demo
   bleibt das ein `simulation://`-Datensatz.
10. **Freigabeprüfung:** Der getrennte Merger prüft aktuelle Belege, Projektfreigaben,
    Dateipfade, Berechtigungen und GitHub-Schutzregeln. DT-001 bleibt blockiert.
11. **Merge:** Nur eine vollständig autorisierte Simulation kann den simulierten
    Merge-Zähler erhöhen. Der mitgelieferte Live-Collector bestätigt keine isolierten
    Review-Nachweise und lässt daher keinen echten Merge zu.

## Grenzen der Wiederholung

Fehlerklassen sind fest vorgegeben: `implementation`, `test`, `qa`, `security`.
Der Testtreiber korrigiert Befunde aus Tests und Reviews; Adapter-/Implementierungs-
Ausnahmen eskalieren unmittelbar, damit unklare Seiteneffekte nicht wiederholt werden.
Die Budgetzuordnung stammt vom Controller-Schritt, nicht aus einer frei benennbaren
Fehlerkennung eines Agenten. Unterschiedliche Befundcodes setzen das Budget deshalb
nicht zurück. Höchstens drei Korrekturen je Klasse sind erlaubt, zusätzlich gilt
ein persistentes Gesamtbudget von standardmäßig 60, höchstens 100 Schritten.

Eine Korrektur zählt beim Rücksprung zur Entwicklung. Bei einem permanenten
Testfehler erfolgen somit ein ursprünglicher Entwicklungsversuch und höchstens drei
Korrekturversuche. Der vierte negative Test beendet den Lauf. Rechteprobleme,
unbekannte Pflichtwerkzeuge und als unauflösbar gemeldete Sicherheitskonflikte
eskalieren ohne sinnlose Korrekturschleifen.

Eskalationen enthalten Status, konkrete Ursache, Fehlerklasse, Zähler und
Lösungsvorschläge, etwa boolesche Eingaben explizit abzulehnen, eine fehlende
Toolchain bereitzustellen oder einen verbotenen Credentialspeicher zu entfernen.
Normale technische Detailentscheidungen benötigen im geplanten Produktivablauf
keine menschliche Zwischenfreigabe. Erstfreigabe, Projektberechtigungen und
Änderungen an der Vertrauensbasis bleiben bewusste Betreiberentscheidungen.

## Unterbrechung und Fortsetzung

SQLite speichert Zustand und Ereignis in derselben Transaktion. Vor jedem Schritt
steht ein `action_intent`, danach `action_completed`. Eine Dateisperre verhindert,
dass zwei Controller denselben Lauf parallel fortsetzen.

Eine kontrollierte Pause an einer Schrittgrenze lässt sich mit `Engine.execute(...,
pause_before=...)` erzeugen und mit `run_id` fortsetzen. Repository, Konfigurationshash,
Anforderungshash, Checkoutpfad und Commit müssen übereinstimmen. Bereits ausgeführte
Prüfungen im gespeicherten JSON sind **nur Auditdaten**: Nach einer Wiederaufnahme
werden Tests und Reviews neu ausgeführt. Ein bereits erstellter PR wird dabei nicht
noch einmal angelegt.

Bleibt nach einem Prozessabbruch ein nicht abgeschlossenes Intent zurück, ist das
Ergebnis unbekannt. Der Controller markiert den Lauf als `interrupted`, statt den
Schritt erneut auszulösen. Der Betreiber muss Checkout, Task oder PR anhand der
Lauf-ID abgleichen und einen bereinigten neuen Lauf starten. Cloud-Submit-Timeouts
dürfen insbesondere keinen unkontrollierten zweiten kostenpflichtigen Auftrag auslösen.

`python -m developer_team show --state /pfad/state.sqlite3 --run-id UUID` zeigt Zustand
und Ereignisliste an. Die CLI bietet absichtlich keine Fortsetzung beliebiger
Fremd-Checkouts; die Wiederaufnahmelogik wird mit synthetischen Projekten getestet.
