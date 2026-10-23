# Universelles KI-Entwicklerteam · DT-001 / DT-002 / DT-003

## DT-017: kontrollierte Pre-Live-Abnahme

[Transport, Accountprüfung und Operator-Halt](docs/dt-017-controlled-acceptance.md):
getrennte frische Create-/Submit-Zustimmungen, feste HTTPS-Wire-Grenze und dauerhaft
begrenzte Cleanup-Anforderung. Kein Standardbroker, keine CLI-Aktivierung.
**real_submissions = 0 · LIVE = NO-GO.**
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**


## DT-016 V0.1: streng begrenzter Agents-API-Provideradapter

[Adaptervertrag, Negativmatrix und Live-Blocker](docs/dt-016-agents-api-provider.md):
Session-Erstellung und genau eine feste Canary-Nachricht sind getrennte Operationen.
Ein exklusives Journal sperrt Wiederholungen nach unklaren Antworten; Reconciliation
ist lesend, Cancel-Annahme und Turn-Terminalnachweis bleiben getrennt.
**Standardmäßig deaktiviert, ausschließlich Wire-Fixtures getestet, real_submissions = 0,
Live NO-GO. OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**

## DT-012 V0.1: synthetischer Agents-API-Canary-Replay

[Reproduzierbarer Lebenszyklus-Prüfer ohne API-Aufrufe](docs/dt-012-canary-replay.md):
einmaliger Submit, unklare Providerantwort, Wiederaufnahme und behaupteter Turnabschluss.
**Nur künstliche Ereignisse und Negativtests; keine Cloud-, Billing-, Stop- oder Mergefreigabe.**

## DT-011 V0: Betriebsweg zu kontrollierter Automatisierung (nur Design)

[Vergleich Agents API, bestehender Codex Cloud und Codex SDK/app-server](docs/dt-011-provider-path.md)
mit einem später separat zu genehmigenden rein synthetischen API-Canary.
**Keine API-Aufrufe, Kosten, Agentenstarts oder neue Berechtigungen; produktives Live bleibt NO-GO.**

## DT-010 V0.1: manuell beaufsichtigte Übergaben

[Deutsche Bedienungsanleitung mit vier Prompt-Vorlagen](docs/dt-010-manual-workflow.md)
für Architektur, Developer, QA und Security sowie ein optionaler Offline-Abgleich.
Aufgaben werden weiterhin einzeln durch den Betreiber gestartet; fehlende oder
veraltete Belege, FAIL und UNSUPPORTED blockieren. Keine automatische Merge- oder
Cloudfreigabe; produktive Cloud-Aufrufe bleiben gesperrt.

## DT-008: erster echter Vier-Rollen-Pilot bleibt NO-GO

Die Betriebswegprüfung bestätigt CLI 0.163.0 und bestehenden ChatGPT-Login, aber keinen
unabhängig attestierten Cloud-Rollen-/Stoppvertrag. Echte Cloud-Submissions sind jetzt
explizit gesperrt. Der lesende `python -m developer_team.preflight` liefert BLOCKED,
Exitcode 2; er erteilt keine Freigabe. Einzige nächste Architekturentscheidung ist der
administrierte externe Betriebsweg mit Kostenrahmen. Kein Agentenstart im DT-008-Auftrag.

[Betriebsweg/Nachweise](docs/dt-008.md) · [Validierung](docs/dt-008-validation.md) ·
[Schritt-für-Schritt-Betreiberanleitung](docs/dt-008-go-live.md).

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
Anforderungen unterstützt der neue, ausdrücklich freizugebende Cloud-Pilotadapter
im bestehenden Zustandsautomaten. Die CLI aktiviert ihn nicht. Ein echter Cloud-
Ende-zu-Ende-Lauf wurde nicht gestartet; [DT-002](docs/dt-002.md) trennt Implementierung,
Testadapter, Berechtigungen und verbleibende Herkunftsgrenzen.

## Stand der Funktionen

| Komponente | Tatsächlich implementiert / Grenze |
| --- | --- |
| Ablaufsteuerung | Zustandsautomat, SQLite-Journal, Prozesssperre, Pause/Fortsetzung, kontrollierter Abbruch |
| Fünf Rollen | Synthetischer Adapter und Cloud-Backend; gebündelte Planung, eigene Entwicklungs-/QA-/Security-Tasks |
| Entwicklung und Tests | Echte temporäre Git-Commits und Test-/Build-Prozesse; separater QA-Randfalltest |
| Korrekturen | Höchstens drei Korrekturen pro fest definierter Fehlerklasse und höchstens 100 Schritte |
| Projektanbindung | Striktes TOML v1, sprachunabhängige Befehle, AGENTS.md, Richtlinien und getrennte Grants |
| Merge-Prüfung | Commit-, Basis-, Konfigurations-, Plan- und Laufbindung; unbekannt/fehlend blockiert |
| GitHub | REST-Adapter über vorhandene `gh`-Anmeldung; SHA-Prüfung, Check-App-Bindung, Pagination, PR-Idempotenz |
| Codex Cloud | Reale CLI-Aufrufe für Submit/Status/List/Diff, dauerhaftes Taskjournal, Commitrefs, Ergebnisimport und begrenzte Wiederaufnahme; mit Testadapter geprüft |
| Cloud-Pilot | Nur mit separater laufgebundener Betreiberfreigabe; keine automatische Aktivierung, PR-Erstellung oder Merges |
| Produktivbetrieb | Gesperrt: Remote-Ende-zu-Ende-Prüfung, attestierter Checkout und durchgesetzte Rollenisolierung fehlen |
| CI | GitHub Actions für synthetische Tests, Lint/Sicherheitsregeln und Paketbau; keine Merge-/Deploy-Rechte |

Der Einrichtungs-PR wird manuell geprüft und gemergt. Das Mergen dieses PRs aktiviert
den Live-Betrieb nicht. Es gibt keinen CLI-Schalter zur Erstfreigabe. Auch vollständig
grüne Checks dieses Repositories sind keine unabhängigen Cloud-Review-Nachweise.

## Dokumentation

- [DT-004: Echter Pilot, Zugangsprüfung und offene Voraussetzungen](docs/dt-004.md)
- [Konkrete Live-Freigabevorlage und Betreiberanleitung](docs/dt-004-approval.md)
- [Architektur und fünf Rollen](docs/architecture.md)
- [DT-002: Cloud-Integration, Testnachweise und erster Pilot](docs/dt-002.md)
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

## DT-003: kontrollierte Cloud-Vorbereitung

Der manuelle GitHub-Actions-Workflow und das künstliche Pilotprojekt sind ausschließlich
mit Testadaptern vorbereitet. Echte Cloud-Aufträge benötigen eine separate konkrete
Freigabe; es gibt keine Live-Aktivierung und keinen automatischen Merge.
[Betrieb, Kosten und Freigabeablauf](docs/dt-003.md) ·
[Beobachtete Prüfungen](docs/dt-003-validation.md).

## DT-005: Codex Exec

Der optionale Exec-Adapter nutzt die bestehenden Engine-Stufen ausschließlich mit
lokalen CLI-Simulatoren. Echte Aufrufe bleiben technisch gesperrt. Architektur,
Sicherheitsanalyse und die NO-GO-Entscheidung für einen beaufsichtigten Pilot stehen
in [docs/dt-005.md](docs/dt-005.md).

## DT-006: aktuelle Sicherheitsprüfung

Der echte Exec-Agentenlauf bleibt technisch gesperrt. Die Offline-Probes und
zusätzlichen controllerseitigen Snapshotprüfungen sind in [DT-006](docs/dt-006.md)
beschrieben; offene Host-/Credential-/Netz-/Supervisorgrenzen und die nächste
Freigabeentscheidung stehen dort zusammen mit dem Risikoregister.
Prüfergebnisse: [Validierungsprotokoll](docs/dt-006-validation.md).

## DT-007: Offline-Sicherheitsarchitektur

[DT-007](docs/dt-007.md) ergänzt rein synthetische Broker-/Lease-/Reviewverträge,
einen typisierten, nichtautoritativen NO-GO-Bericht und lokale modellfreie
Negativprobes. Kein produktiver Runner: **Live bleibt NO-GO**, auch bei grüner CI.
Nachweise und konkrete verbleibende Betriebsblocker:
[Validierung](docs/dt-007-validation.md).
