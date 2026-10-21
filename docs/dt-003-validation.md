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
| Python 3.13.5, vollständige Suite | 147 Tests erfolgreich |
| Gesamtabdeckung / zentrales Merge-Gate | 90 % / 100 %; geforderte 80 % überschritten |
| Ruff 0.14.3 einschließlich Sicherheitsregeln | Erfolgreich |
| Ruff-Formatprüfung | Erfolgreich |
| Wheel und Source-Distribution, `build --no-isolation` | Erfolgreich |
| Bestehende und neue TOML-Konfiguration | Erfolgreich validiert; keine Rechte daraus abgeleitet |
| Bestehende Demo `test-fix` | Echte lokale Testkorrektur, Abschluss wie erwartet `blocked` |
| `actionlint` 1.7.7, beide Workflowdateien | Erfolgreich; Releasearchiv gegen offizielle Prüfsummen kontrolliert |
| Neuer CLI-Smoke-Lauf aus Commit `e81c28a` | Vorbereitung, Pause, Checkpoint und Resume im anderen Checkout erfolgreich; 6 eindeutige simulierte Tasks, eine QA-Korrektur, beide lokalen Tests PASS, Abschluss `blocked` |

Die neue Suite prüft unter anderem echte lokale Abnahme-/Entwicklertests,
Test-/QA-Korrekturen, Korrektur- und Taskbudget, unabhängige Rollenaufträge,
Import-Allowlist, Git-/SQLite-Checkpoint mit neuer Arbeitsposition, verlorene
Bestätigung, fehlende/leere/ersetzte Datenbank, Integritätsfehler, Symlinks,
unverwandte Läufe, Artefaktherkunft und den Ausschluss roher Login-Ausgaben.

Python 3.13 machte nicht geschlossene SQLite-Verbindungen sichtbar. `RunStore`
schließt Verbindungen nun nach Commit/Rollback ausdrücklich; auch Backup und
Restore schließen ihre Verbindungen. Danach wurden beide vollständigen lokalen
Suiten erneut mit jeweils 147 erfolgreichen Tests ausgeführt; die vorherigen
`ResourceWarning`-Meldungen sind in diesen Läufen nicht mehr aufgetreten.

## GitHub Actions

Beobachtet: [Actions-Lauf 39580481239](https://github.com/oxfrd1337/developer-team/actions/runs/39580481239)
zu PR-Head `e81c28a3a779020e82c955bd9caac182e2df6c7b`.

Auch [Lauf 39580980721](https://github.com/oxfrd1337/developer-team/actions/runs/39580980721)
am Head `d2a74901b97c3dcd37cc8563c10a1df0b0ff3614` ist vollständig erfolgreich;
dieser Lauf enthält die Korrektur zum expliziten Schließen der SQLite-Verbindungen.
Die abschließende Testadapter-Verdrahtung kennzeichnet zusätzlich sämtliche
Agentenbelege bereits im rohen SQLite-Audit als `simulated`; die lokalen Suiten
wurden damit erneut erfolgreich ausgeführt (jeweils 147 Tests, weiterhin 90 % Abdeckung).

| Tatsächlich abgeschlossener Job | Ergebnis |
| --- | --- |
| Python 3.11 / synthetic safety suite | Erfolgreich, einschließlich Lint, Format, Tests, Coverage, Build und bestehendem Smoke-Lauf |
| Python 3.12 / synthetic safety suite | Erfolgreich, einschließlich Berichtsupload |
| Python 3.13 / synthetic safety suite | Erfolgreich |
| Codex CLI interface on Actions (no login or tasks) | Erfolgreich: npm-Installation 0.163.0, Hilfen, sicherer Statusreport und Artefaktexport |
| Prepare and pause test-adapter pilot | Erfolgreich: ein nachgebildeter Pending-Task, SQLite-/Git-Export und Artefaktexport |
| Resume test-adapter pilot on a fresh runner | Erfolgreich: Download, Integritätsprüfung, Wiederaufnahme, sechs eindeutige simulierte Tasks, eine QA-Korrektur, echte lokale Tests und Bericht; Abschluss `blocked` |

Der echte Runner-Log der CLI-Probe enthält `chatgpt_login_reported=false`,
`unattended_cloud_auth_verified=false` und `remote_task_verified=false`. Eine
lokale ChatGPT-Sitzung wird nicht automatisch auf Actions übertragen. Die Artefakte
`dt-003-actions-codex-probe`, `dt-003-ci-checkpoint` und `dt-003-ci-rehearsal-report`
wurden tatsächlich von GitHub aufgeführt; die Jobschritte zum Up-/Download sind grün.

Ein manueller `cloud-pilot.yml`-Start vor Aufnahme in den Defaultbranch ist nicht
möglich und wird nicht als ausgeführt behauptet. Der Herkunftscheck für manuelle
Resume-Läufe, die Eingabeoberfläche, die Concurrency-Warteschlange, hartes
Job-Timeout/VM-Verlust und Wiederaufnahme über zwei manuelle Workflowläufe sind
vorbereitet bzw. lokal mit Testadaptern geprüft, aber noch nicht auf GitHub
ausgeführt. Erfolgreich gelaufen ist der getrennte PR-CI-Runnerwechsel. Kontobudget,
Live-Login, Remote-Tasklauf und Token-Erneuerung sind damit nicht belegt.

Echte Cloud-Aufträge: **0**. Kein automatischer Merge, keine produktiven Deployments,
keine Aktivierung, keine neuen API-Schlüssel oder kostenpflichtigen Dienste.
