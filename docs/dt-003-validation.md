# DT-003 · Prüfprotokoll

Stand: 21. Oktober 2026. Dieses Protokoll unterscheidet lokale Ausführung,
GitHub Actions und Testadapter. Ein simulierter Task ist kein echter Cloud-Auftrag.

## Bereits beobachtet

- CLI `codex-cli 0.163.0` lokal vorhanden; Submit-/Status-/Diff-/JSON-List-Hilfen
  und Anmeldestatus gelesen. ChatGPT-Anmeldung gemeldet, tatsächlicher Cloud-Zugang
  und unbeaufsichtigte Erneuerung nicht geprüft.
- Dieselbe npm-Version isoliert temporär installiert; sichere Probe erfolgreich.
- Neue Sicherheits-/Wiederaufnahmetests mit echten lokalen Git-/Python-Prozessen
  und ausschließlich nachgebildeten Cloud-Antworten ausgeführt.
- Direkter GitHub-API-Leseversuch auf `actions/permissions`: `Forbidden` aus dieser
  Ausführungsumgebung. Kein Billing- oder Berechtigungswert daraus abgeleitet.

## Lokale Abschlussprüfungen

| Prüfung | Beobachtetes Ergebnis |
| --- | --- |
| Python 3.12.14, vollständige Suite mit Branch-Coverage | 147 Tests erfolgreich |
| Gesamtabdeckung / zentrales Merge-Gate | 90 % / 100 %; geforderte 80 % überschritten |
| Ruff 0.14.3 einschließlich Sicherheitsregeln | Erfolgreich |
| Ruff-Formatprüfung | Erfolgreich |
| Wheel und Source-Distribution, `build --no-isolation` | Erfolgreich |
| Bestehende und neue TOML-Konfiguration | Erfolgreich validiert; keine Rechte daraus abgeleitet |
| Bestehende Demo `test-fix` | Echte lokale Testkorrektur, Abschluss wie erwartet `blocked` |
| `actionlint` 1.7.7, beide Workflowdateien | Erfolgreich; Releasearchiv gegen offizielle Prüfsummen kontrolliert |

Die neue Suite prüft unter anderem echte lokale Abnahme-/Entwicklertests,
Test-/QA-Korrekturen, Korrektur- und Taskbudget, unabhängige Rollenaufträge,
Import-Allowlist, Git-/SQLite-Checkpoint mit neuer Arbeitsposition, verlorene
Bestätigung, fehlende/leere/ersetzte Datenbank, Integritätsfehler, Symlinks,
unverwandte Läufe, Artefaktherkunft und den Ausschluss roher Login-Ausgaben.

## GitHub Actions

Die PR-CI wird nach Veröffentlichung dieses Branches beobachtet. Nur tatsächlich
abgeschlossene Jobs werden als bestanden eingetragen. Ein manueller
`cloud-pilot.yml`-Start vor Aufnahme in den Defaultbranch ist nicht möglich und
wird nicht als ausgeführt behauptet. Kontobudget, Live-Login, Remote-Tasklauf und
Token-Erneuerung sind durch lokale Tests und Testadapter nicht belegt.

Echte Cloud-Aufträge: **0**. Kein automatischer Merge, keine produktiven Deployments,
keine Aktivierung, keine neuen API-Schlüssel oder kostenpflichtigen Dienste.
