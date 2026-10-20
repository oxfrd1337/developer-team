# Universelles KI-Entwicklerteam · DT-001

Modularer Python-Kern für Anforderung, Planung, Architektur, Entwicklung, Tests,
unabhängigen QA- und Security-Review, Korrekturen und kontrollierte PR-Freigabe.
Das Repository enthält **einen ausführbaren sicheren Testmodus**. Es ist noch kein
aktiviertes, beliebige Projekte selbstständig bearbeitendes Codex-Cloud-Team.

Die fünf Rollen sind logisch getrennt. Orchestrator und Architekt teilen sich einen
Planungsaufruf; Entwickler, QA und Security haben getrennte Identitäten und Aufrufe.
Nach einer Codekorrektur werden sämtliche Tests und Reviews neu ausgeführt.

## Schnellstart

Voraussetzungen: Linux/macOS, Python 3.11+ und Git. Keine Laufzeitpakete, API-Schlüssel,
Cloud-Aufträge oder externen Projekte sind für die Demo erforderlich.

```sh
python -m developer_team validate examples/project.synthetic.toml
python -m developer_team demo --scenario test-fix --output /tmp/dt-001-demo
python -m unittest discover -s tests -t . -v
```

Das Ausgabeverzeichnis muss leer sein. Es enthält ein synthetisches Git-Repository,
`state.sqlite3` mit Ereignisjournal und `report.json`. Ohne `--output` wird ein neues
temporäres Verzeichnis angelegt und dessen Pfad ausgegeben. Im Normalfall endet die
Demo mit `blocked`: Tests und Reviews sind erfolgreich, der Einrichtungs- und
Erstfreigabeschutz verhindert den Merge. Das ist das erwartete sichere Ergebnis.

```sh
python -m developer_team demo --scenario qa-fail
python -m developer_team demo --scenario security-conflict
python -m developer_team demo --scenario stale-evidence
python -m developer_team probe-codex
```

`qa-fail` und `security-conflict` liefern Exitcode 1 und konkrete Eskalationsvorschläge.
`stale-evidence` demonstriert eine blockierte Freigabe. `probe-codex` prüft nur die
installierte CLI und Anmeldung; es startet keinen Cloud-Auftrag. Die Demo ist ein
deterministischer Testtreiber für die festgelegte Beispielanforderung. Freie produktive
Anforderungen benötigen den noch zu vervollständigenden Cloud-Agentenadapter.

## Stand der Funktionen

| Komponente | Tatsächlich implementiert / Grenze |
| --- | --- |
| Ablaufsteuerung | Zustandsautomat, SQLite-Journal, Prozesssperre, Pause/Fortsetzung, kontrollierter Abbruch |
| Fünf Rollen | Austauschbarer Agentenvertrag; deterministische synthetische Implementierung |
| Entwicklung und Tests | Echte temporäre Git-Commits und Test-/Build-Prozesse; separater QA-Randfalltest |
| Korrekturen | Höchstens drei Korrekturen pro fest definierter Fehlerklasse und höchstens 100 Schritte |
| Projektanbindung | Striktes TOML v1, sprachunabhängige Befehle, AGENTS.md, Richtlinien und getrennte Grants |
| Merge-Prüfung | Commit-, Basis-, Konfigurations-, Plan- und Laufbindung; unbekannt/fehlend blockiert |
| GitHub | REST-Adapter über vorhandene `gh`-Anmeldung; SHA-Prüfung, Check-App-Bindung, Pagination, PR-Idempotenz |
| Codex Cloud | Beobachtete experimentelle CLI für Submit/Status/Diff; Probe ausführbar; Remote-Lauf nicht nachgewiesen |
| Live-Betrieb | Gesperrt: isolierte Ergebnisse und vertrauenswürdige Review-Attestierungen fehlen |
| CI | GitHub Actions für synthetische Tests, Lint/Sicherheitsregeln und Paketbau; keine Merge-/Deploy-Rechte |

Der Einrichtungs-PR wird manuell geprüft und gemergt. Das Mergen dieses PRs aktiviert
den Live-Betrieb nicht. Es gibt keinen CLI-Schalter zur Erstfreigabe. Auch vollständig
grüne Checks dieses Repositories sind keine unabhängigen Cloud-Review-Nachweise.

## Dokumentation

- [Architektur und fünf Rollen](docs/architecture.md)
- [Versionierte Projektkonfiguration](docs/configuration.md)
- [Ablauf, Korrekturen und Wiederaufnahme](docs/workflow.md)
- [Sicherheit und Berechtigungen](docs/security.md)
- [Teststrategie und Szenarien](docs/testing.md)
- [Spätere Projektanbindung und Erstfreigabe](docs/onboarding.md)
- [Geprüfte Schnittstellen, Kosten und Einschränkungen](docs/integrations.md)
- [Übergabe und nächste Schritte](docs/handover.md)

Für Entwicklung und Paketbau:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m ruff check developer_team tests
.venv/bin/python -m ruff format --check developer_team tests
.venv/bin/python -m coverage run --branch -m unittest discover -s tests -t . -v
.venv/bin/python -m coverage report --fail-under=80
.venv/bin/python -m build --no-isolation
```

Nach optionaler Installation per `pip install -e .` heißt der Einstiegspunkt
`developer-team`. Beispielkonfigurationen werden über ihren expliziten Pfad geladen;
die Befehle oben werden im Repository-Verzeichnis ausgeführt.
