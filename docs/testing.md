# Teststrategie

## DT-016

```sh
python -m unittest tests.test_agents_api tests.test_agents_api_journal tests.test_agents_api_review -v
```

Die 100 DT-016-Tests (65 ursprüngliche und 35 zusätzliche Review-Regressionen) verwenden
ausschließlich injizierte, credentialfreie
Wire-Fixtures und lokale SQLite-Journale in Speicher oder temporären Verzeichnissen.
Session-Create und Message-Submit werden getrennt geprüft. Die Negativmatrix umfasst
Idempotency-/Bindungswechsel, verlorene Antworten, ausschließlich lesende Reconciliation,
konkurrierende Controller, Journal-/Receipt-Verlust, Projekt-/Key-/Scope-/Spend-Gates,
verfallene Grants und unmittelbare Submit-Freigabe, 401/403/429/5xx, Cancel ohne
Terminalbestätigung, getrennte completed/failed/cancelled-Zustände, Secret-Leakage sowie
Byte-, Ereignis-, Request- und Timeoutgrenzen. Bestehende Tests bleiben unverändert.

Die Review-Regressionen für PR #32 prüfen außerdem technisch deaktiviertes Outbound-Netz,
explizite kleine Container und unveränderte Environment-ID, vollständig gepinnte effektive
Agent-Konfiguration einschließlich Modell/Reasoning/Service Tier sowie eigene frische,
bindungsbezogene Freigaben für Create, Submit und Cancel direkt vor jedem POST. Fehlende,
alte, zukünftige oder falsche Freigaben, Saved-Agent-Drift und Konfigurationsabweichungen
werden abgelehnt. Verzögerungen im Journal oder externen Verifier verlängern keine Freigabe.

Die vorhandene CI-Matrix führt diese Tests mit allen bisherigen Lint-, Format-,
Coverage-, Build-, Smoke- und Checkpoint-Anforderungen unter Python 3.11–3.13 aus.
Ausführliche Grenzen: [DT-016](dt-016-agents-api-provider.md).
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**

DT-006 ergänzt `tests/test_boundaries.py`, Inhalts-/Auditprüfungen im Exec-Pfad und
`python -m developer_team.boundary_probe`. Die Offline-Probe verwendet nur künstliche
Credentials und eigene lokale Canaries/Prozesse. Sie liefert immer **NO-GO** mit
Exitcode 2; fehlende Hostfähigkeiten sind `UNSUPPORTED`, kein Skip-als-PASS.
Einzelne erfolgreiche Namespace-/Negativprobes geben keinen Modellzugriff frei.
Neue Regressionstests prüfen versteckte/Git-/Cross-Controller-Manipulation,
`assume-unchanged`, falsche Attestierungen und die unabhängigen Controllerchecks.
Design und Aussagegrenzen: [dt-006.md](dt-006.md); tatsächlich ausgeführte Checks:
[dt-006-validation.md](dt-006-validation.md). Alle bisherigen CI-Anforderungen gelten
weiter; nicht verfügbare Werkzeuge oder nicht gestartete Jobs sind offene Checks.

Die Reviewkorrektur zu PR #7 ergänzt Schema-/Typ-/Digest-/Transporttests für die
Diagnose-Schnittstelle sowie getrennte Vertragstests für teilweise verfügbare
Hostgrenzen. `UNSUPPORTED` bleibt ein fehlender Nachweis bei **NO-GO**; tatsächliche
Zugriffsverletzungen (`FAIL`) und unbekannte Statuswerte lassen den Hosttest scheitern.

DT-004 ergänzt `tests/test_supervised_pilot.py`: lokale Vorbereitung ohne Cloud,
feste Dateigrenzen, vier Umgebungen, unveränderliche Grants/Budgets, verlorenes Journal,
gesperrte Anmeldung/Sandbox, Ergebnis-/Status-/Testbelege sowie echte Python-Fehler
und Korrekturen mit ausdrücklich simulierten Agentenantworten. Der optionale echte
Namespace-Test prüft Datei-/Credential-/Schreib-/Netzgrenzen. Ist die Hostfunktion
gesperrt, wird er als **Skip** ausgewiesen und bleibt ein Live-Blocker; die
Betreiberfunktion verweigert dann jede Cloud-Übermittlung. Diese Provider-Testadapter
belegen keine KI-Leistung. Details: [DT-004](dt-004.md).

Die Tests benötigen keine GitHub-/OpenAI-Credentials und rufen keine externen
Projekt-APIs auf. Git und Python-Prozesse arbeiten nur in temporären synthetischen
Repositories. Adaptertests verwenden ausdrücklich nachgebildete CLI-/REST-Antworten.
Eine positive simulierte Merge-Entscheidung erhöht lediglich einen lokalen Zähler;
sie führt weder `git merge` noch einen API-Aufruf aus.

DT-003 ergänzt `tests/test_pilot.py`: künstliches Unterprojekt im selben Repository,
strikte Importgrenzen, echte Abnahmetests, begrenzte Test-/QA-Korrekturen, Taskbudgets,
Portable-Checkpoint mit Runnerwechsel, Verlust/Manipulation von Zustand sowie
Artefaktherkunft und sichere CLI-Probe. [dt-003.md](dt-003.md) beschreibt Betrieb und
Startsperren; [dt-003-validation.md](dt-003-validation.md) hält beobachtete Ergebnisse fest.

DT-002 ergänzt `tests/test_cloud.py` mit kontrollierten CLI-/Ref-Testadaptern,
echten temporären Git-Importen und lokalen Testprozessen. Lifecycle, Reviewtrennung,
Wiederaufnahme mit neuem Controller, Korrekturen und Merge-Sperre sowie die Grenzen
der Testaussagen sind in [dt-002.md](dt-002.md) dokumentiert. Auch diese Tests starten
keine echten Cloud-Tasks und benötigen keine Freigabe mit Kosten-/Schreibwirkung.

```sh
python -m unittest discover -s tests -t . -v
.venv/bin/python -m coverage run --branch -m unittest discover -s tests -t . -v
.venv/bin/python -m coverage report --fail-under=80
.venv/bin/python -m ruff check developer_team tests
.venv/bin/python -m ruff format --check developer_team tests
.venv/bin/python -m build --no-isolation
python -m developer_team validate examples/project.pilot.toml
```

## Abdeckung der geforderten Fälle

| Anforderung | Nachweis |
| --- | --- |
| Vollständiger Ablauf | Echte synthetische Code-/Test-/Dokumentationscommits, Testprozesse, zwei getrennte Review-Aufrufe, simulierter PR und simulierter Merge bei ausschließlich im Test gesetzter Freigabe |
| Testfehler korrigieren | Falsche Rechenoperation scheitert am Test, wird einmal korrigiert und erneut geprüft |
| QA erfolgreich | Separater Prozess prüft positive/negative/Float-Werte und falsche Eingabetypen |
| QA fehlgeschlagen | Entwickler-Tests übersehen boolesche Eingaben; QA erkennt sie, korrigiert oder eskaliert nach drei Korrekturen |
| Security-Konflikt | Synthetischer Berechtigungsmarker wird korrigiert; verbotene Dummy-`.env` eskaliert direkt |
| Veraltete Nachweise | Falscher HEAD, Basis-, Konfigurations-, Plan-/Laufhash und abgelaufener Plattformzustand blockieren |
| Fehlende Rechte | Fehlende Entwicklungs-/PR-/Merge-/Cloud-Berechtigung verhindert die jeweilige Aktion |
| Unterbrechung | KeyboardInterrupt, unvollständiges Intent, sichere Pause/Fortsetzung und keine doppelte PR-Erstellung |
| Begrenzte Korrekturen | Exakt maximal drei Korrekturen; Gesamtbudget bleibt bei Fortsetzung erhalten |
| Unzulässiger Auto-Merge | Bootstrap, fehlende Erstfreigabe, geschützte Pfade, gefälschte/fehlende/doppelte Belege, unklare Regeln und simulierte Cloud-Belege sperren |

Weitere Prüfungen betreffen strikte TOML-Typen, alternative Sprach-/Frameworknamen,
individuelle Befehle, verschachtelte AGENTS.md, geschützte Umbenennungen, Symlinks,
fehlende Richtlinien, Prozess-Timeout mit Kindprozessen, Secret-Umgebungsfilter und
die exklusive Laufsperre. Ein Test verändert den Code während QA; der Controller
erkennt den unreinen Checkout und verwirft die Freigabe.

Die GitHub-Vertragstests prüfen App-Bindung, übersprungene Checks, Administratorrechte,
Fork-/Projektverwechslung, unvollständige Dateilisten, unbekannte Branch Protection,
Remote-SHA-Prüfung, PR-Idempotenz und den SHA im Merge-Payload. Ein Payload-Test nutzt
bewusst ein nachgebildetes positives Gate; er beweist keinen produktiven GitHub-Merge.
Codex-Vertragstests prüfen Testmodussperre, Projektgrant, getrennte Umgebungen,
einen Versuch pro Auftrag, nicht vertrauenswürdige Receipts und Argumentvalidierung.

## Reproduzierbare Demos

`python -m developer_team demo --scenario NAME` kennt:

| Szenario | Erwartetes Ergebnis im unveränderten DT-001-Modus |
| --- | --- |
| `happy` | Prüfungen erfolgreich, simulierter PR, Merge wegen Erstfreigabeschutz blockiert |
| `test-fix` | Ein Testfehler behoben, danach wie `happy` |
| `qa-fix` | Ein QA-Randfall behoben, danach wie `happy` |
| `qa-fail` | QA nach drei Korrekturen eskaliert, kein PR |
| `security-fix` | Ein Sicherheitsbefund behoben, alle Prüfungen erneut ausgeführt |
| `security-conflict` | Nicht behebbarer Richtlinienkonflikt eskaliert, kein PR |
| `protected-change` | Veränderung an AGENTS.md sperrt zusätzlich den Merge |
| `stale-evidence` | Abweichender Plattform-HEAD sperrt zusätzlich den Merge |
| `missing-permission` | Entwicklung vor dem ersten Schreibzugriff verweigert |
| `interrupted` | Lauf als unterbrochen protokolliert, keine automatische Wiederholung |
| `repair-limit` | Permanenter Testfehler nach drei Korrekturen eskaliert |

Die internen positiven Merge-Tests erstellen eine ausschließlich lokale Testfreigabe
mit `safe_test_mode=True`. Dieses Testobjekt aktiviert kein Repository und ist kein
CLI-Schalter. Die Demo schreibt weder reale PRs noch externe Branches.

## GitHub Actions und Aussagegrenzen

DT-003 ergänzt drei Jobs: reale Installation/lesende Probe der CLI 0.163.0 ohne
Anmeldung oder Auftrag, Export eines pausierten Testadapterlaufs und Wiederaufnahme
auf einem frischen Runner aus demselben exakten Artefakt. Die neue manuelle
`cloud-pilot.yml` bleibt ausschließlich auf Testadapter begrenzt. Ein separater
`workflow_dispatch`-Start kann erst nach manueller Aufnahme in den Defaultbranch
geprüft werden; CI-Nachweise dafür werden nicht erfunden.

`ci.yml` prüft Python 3.11, 3.12 und 3.13 auf Ubuntu: Lint mit Sicherheitsregeln,
Formatierung, Tests mit Branch-Messung, mindestens 80 % Gesamtabdeckung, Wheel/SDist
und einen sicheren Smoke-Lauf. Actions sind auf Commit-SHAs gebunden. Der Job hat nur
`contents: read`, keine persistierten Checkout-Credentials, keine Secrets und keine
Merge-/Deploy-Schritte. Der synthetische Report wird sieben Tage als Artefakt aufbewahrt.

Abdeckung misst ausgeführten Code und ersetzt keine unabhängige Sicherheitsbewertung.
Diese CI-Jobs bestätigen weder eine produktive Cloud-Ausführung noch isolierte
KI-Reviews. Tatsächlich gelaufene lokale und entfernte Prüfungen werden separat in
[handover.md](handover.md) dokumentiert. Ein CI-Lauf kann in einem privaten Repository
an Actions-Freigabe, Budget oder Planvorgaben scheitern; das wird nicht als Testpass gewertet.

## DT-005

`python -m unittest tests.test_exec -v` prüft den Exec-Vertrag mit echten lokalen
Python-Prozessen als ausdrücklich simulierten CLI-Antworten. Es wird kein Codex-
oder Modellprozess gestartet. Budgets, Ressourcen-/Ausgabegrenzen, Abbruch,
Ergebnisbindung, Reviewtrennung und Live-/Merge-Sperren sind in
[dt-005.md](dt-005.md) beschrieben. Diese Tests attestieren keine OS-Isolation.

## DT-007

```sh
python -m unittest tests.test_readiness tests.test_boundaries tests.test_exec -v
python -m developer_team.readiness_probe > /tmp/dt007-probes.json
# Erwarteter Exitcode 2: NO-GO, unabhängig von bestandenen Einzelprobes.
```

`test_readiness.py` prüft strikte Diagnose-/Bindungsschemas, Fake-PASS und fehlende
unabhängige Attestierung, JSON-/SQLite-/Env-/Projekt-/CI-Claims ohne Popen,
synthetische Brokeridentität und Replay, absolute Lease, atomaren Einmalintent,
Journalfehler und unveränderte Reviewquellen einschließlich bewusst nachgewiesener
Write-and-Restore-Lücke. Neue echte Hostprobes betreffen ausschließlich eigene
Datei-/FD-/Env-Canaries, lokale DNS-/IPv4-/IPv6-/HTTP-/TCP-/UDP-/Unix-/Abstractziele
sowie eigene synthetische Prozesse mit Controller-SIGKILL und Detached Child.
Kein Modell wird aufgerufen. Fehlende Hostfunktionen bleiben UNSUPPORTED, ohne
unsandboxierten Ersatzlauf als vermeintlichen Isolationsbeweis. Positive Kontrollen
sind Voraussetzung für negative Zugriffsbelege. Der Prozessharness ist kein externer
Supervisor. [DT-007](dt-007.md) trennt lokale Vertrags-PASS von Live-NO-GO;
[Validierung](dt-007-validation.md) dokumentiert Befehle, Hashes und echte CI.


DT-007-Reviewkorrektur: Die Prozessprobe übernimmt nur den vom eigenen Controller
per SCM_RIGHTS übertragenen, während einer ungeernteten Child-Lebenszeit geöffneten
pidfd. Negative Ownership-, Session-, Startzeit-, `/proc`-, FD-Bindungs-, frühe
Ende-/PID-Reuse- und Transferfälle prüfen ausdrücklich, dass **kein**
`pidfd_send_signal` und kein Controller-SIGKILL erfolgt und unbestätigte Handles
nur geschlossen werden. Positive Vertrags- und echte eigene Prozessprobes prüfen
den verifizierten Cleanup weiterhin. Ein fremder/unverifizierter Handle wird
niemals als Cleanup-Fallback signalisiert. Live bleibt NO-GO.
# DT-008

`python -m unittest tests.test_preflight -v` prüft Fake-GO/Stopclaims, fehlende
Verbindung, falsche Basis/Scope, verbotene Freigabeparameter und reale Cloud-Startsperre
vor Prozess-/Journal-/Refzugriff. `python -m developer_team.preflight` ist ein lesender
BLOCKED/NO-GO-Trockenlauf (Exitcode 2). Bestehende Lifecycle- und Bindungsnegativtests
bleiben unverändert aktiv; [Nachweise und Grenzen](dt-008-validation.md).

Die Reviewkorrektur ergänzt `tests/test_cloud_start_boundary.py`: sieben gezielte
Tests mit ansonsten gültigen Pilotbindungen prüfen direkten Runner, Lambda-Wrapper,
`functools.partial`, Callable-Objekt, Konstruktorinjektion, nachträgliche Attribute,
veränderte Simulationslabels und Fake-Grants. Für verweigerte produktive Aufrufe
gelten `subprocess.Popen.assert_not_called()` sowie keinerlei Ref-/Journalzugriff.
Der produktive Gateway akzeptiert keinen Runner und verweigert bedingungslos;
Lifecycle-Fixtures sind davon getrennt. Die feste Rehearsalantwort bleibt selbst bei
gesetzten Runnerattributen modellfrei. Bestehende Vertragstests wurden auf die
separate Test-Fixture umgestellt, ihre Prüfbedingungen nicht abgeschwächt.


## DT-017

`tests/test_agents_acceptance.py` und `tests/test_agents_https.py` prüfen den
kontrollierten Controller, alle Pre-Live-Gates, getrennte frische Operator-Challenges,
Drift, Unknown-Recovery, begrenztes Cleanup und den echten HTTPS-Code ausschließlich
mit injizierten Wire-Verbindungen. Account, Secretmaterial und Providerantworten sind
synthetisch. DNS/TLS/Connection/Timeout/401/403/429/5xx/Redirect und Größenlimits werden
ohne echte Credentials oder Provider-POST geprüft. [Vertrag und Live-Blocker](dt-017-controlled-acceptance.md).

**real_submissions = 0 · LIVE = NO-GO.**
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**


Die PR-35-Reviewregressionen in `tests/test_agents_acceptance_review.py` prüfen die
unveränderliche Credential-/Principal-/Handlebindung, fehlende/zusätzliche/veraltete
Identitäten, tatsächlichen FD-Austausch, Identitätsablauf während der Probe sowie die
unabhängige frische Read-only-Transport-Attestation einschließlich Origin, Projekt,
Credentialidentität, TLS-Regeln, Route und Widerruf direkt am Wire. Alle Attestierungen
und Transportproben sind synthetisch; kein echter OpenAI-Aufruf. Ein verfügbarer
Transport ohne diese Evidence meldet `real_transport=MISSING_OR_INVALID` und NO-GO.

## DT-017A

`python -m unittest tests.test_provider_readonly -v` prüft die GET-only-Grenze,
getrennte Admin-/Canary-Identitäten, Account-/Owner-/Expiry-Bindung, reale
Response-Schemas für Spend/Modelle/Agent, separat authentifizierte Scope-Evidence,
Sanitisierung und Transportlimits. Ausschließlich synthetische HTTP-Fixtures;
keine echten Provider-Credentials, keine echten OpenAI-Aufrufe in CI.
Die bestehende Suite wird unverändert zusätzlich ausgeführt.
[Vertrag, Negativmatrix und Live-Blocker](dt-017a-readonly-provider.md).
**real_submissions = 0 · LIVE = NO-GO.**
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**


DT-017A-Nachprüfung: Sechs zusätzliche Regressionen prüfen die Verkürzung der
Account-Evidence auf Key-/Service-Account-/Owner-Ablauf, abgelaufene gecachte
Observations, Ablauf während der abschließenden Handleprüfung sowie Canary-
Handlewechsel vor oder während der externen Scope-Verifikation. Die separate
Scope-Attestation gewährt weiterhin keine Transport- oder Live-Freigabe.


DT-017A-Reviewblocker: `tests/test_scope_evidence.py` ergänzt 32 Regressionen für
getrennte Key-/Principal-/effektive Typen und die Laufzeit-Trennung gepinnter
Attestor-/Verifier-Identitäten. Die bisherigen Scope-Fixtures verwenden getrennte
Source-/Verifier-Objekte. Namespace-Verwechslung, fehlende/zusätzliche/unbekannte
Rechte, inkonsistente effektive Rechte, Self-Attestation, gleiche oder vertauschte
Trust-Identitäten und Wechsel während externer Callbacks bleiben NO-GO. Der
unabhängige korrekte synthetische Verifier erfüllt ausschließlich das Scope-Gate.
Es erfolgen keine echten OpenAI-Aufrufe; real_submissions = 0, LIVE = NO-GO.
