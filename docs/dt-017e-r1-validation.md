# DT-017E R1: Fix-Nachweis zu Issue #49

Einziger PR: [Draft #45](https://github.com/oxfrd1337/developer-team/pull/45).
Bestehender Branch: `dt-017e-safe-readonly-diagnostics`.
Ausgangs-HEAD: `749047443a9db533785073ff990ab21336e4a98e`;
unveränderte Basis: `e230ddb42fcfad624221a6ed31808b03c7ca6816`.
Der neue exakte Commit, sein Tree und die abschließenden CI-Ergebnisse werden
nach Veröffentlichung im R1-Nachweis in PR #45 gebunden. Dieser Bericht ist
Entwicklungsvalidierung, keine unabhängige QA-/Security- oder Release-Freigabe.

## Befund und Korrektur

| Befund | Korrektur | Reproduzierbare Regression |
| --- | --- | --- |
| P2 QA-01 | `ProviderReadOnlyCollector.report()` behält die vom bestehenden Verifier akzeptierten Observations und prüft sie gegen die frische Abschlusszeit. Ablauf oder Alter über 300 Sekunden stuft das Gate auf `MISSING_OR_INVALID` zurück; eine vorherige Diagnose-PASS wird `FINAL_VALIDATION / OBSERVATION_INVALID`. Keine weiteren GETs, keine Aufwertung zuvor verworfener Evidence. | `DiagnosticsTests.test_direct_report_revalidates_account_at_completion_without_extra_gets`: Accountablauf bei NOW+2, Uhrwechsel beim letzten Canary-GET auf NOW+1/+2/+3. Vorher PASS, genau bei und nach Ablauf MISSING; andere gültige Provider-Gates bleiben PASS, exakte sechs GETs. `RunnerTests.test_runner_final_account_expiry_still_enforced_and_broker_consistent` prüft dieselben Grenzen im bestehenden Runner und Broker. |
| P2 QA-02 / Security F1 | Der offizielle Schema-2-Sanitizer akzeptiert PASS ausschließlich für die drei Provider-Gates und nur bei konsistenter Diagnose/Summary. Alle neun weiteren Gates müssen `MISSING_OR_INVALID` sein. Ungültige Typen für Outcome, Summary und Checks liefern ebenfalls eine feste sichere Abweisung. Die optionale echte Python-Scope-Verifikation bleibt separat. | `tests/test_provider_readonly_report_boundary.py`: neun **getrennte Testmethoden**, je Gate zwei Angriffe (NONE_VALID und ansonsten vollständig konsistentes SOME_VALID). Alle acht Provider-PASS-Teilmengen werden positiv und mit widersprüchlichen Checks/Summaries negativ geprüft. BLOCKED mit gefälschten Checks oder Diagnosen, Schema-/Boolean-/Typverwechslungen, zusätzliche/fehlende Felder und doppelte Schlüssel werden verworfen. |
| P3 Security F2 | Allgemeine `http.client.HTTPException` fällt neutral unter `TRANSPORT_FAILURE`. `TLS_OR_PROXY_FAILURE` bleibt auf `ssl.SSLError` beziehungsweise die exakt bekannte interne Proxykonfigurationskonstante begrenzt. Keine Auswertung von Exceptiontext. | Bestehende sechs-Stufen-Matrix um `BadStatusLine`, `IncompleteRead` und `RemoteDisconnected` erweitert; Basistyp ebenfalls neutral. Dieselben vier Typen zusätzlich beim Connect beider Rollen geprüft: feste Exception ohne ursprünglichen Kontext, keine Marker in formatiertem Traceback, Report, stdout oder stderr. |
| P3 Security F3 | `ExternalFD.validate()` verlangt wie der Broker exakt `stat.S_IMODE(info.st_mode) == 0o600`. Keine Rechteerhöhung und keine Änderung echter Schlüsseldateien. | `RunnerTests.test_exact_0600_required_for_both_roles_even_with_matching_pins`: je Admin/Canary acht abweichende Modi, einschließlich 0400/0500/0700, Gruppenrechten und Sonderbits, mit jeweils passendem synthetischen Dateipin. Ablehnung vor `pread` und Verbindungsaufbau. Bestehende positive 0600- und negative Broker-/FD-/Rollenwechseltests bleiben aktiv. |

## Tatsächlich ausgeführte lokale Prüfungen

Alle Regressionen verwenden künstliche Antworten, injizierte Verbindungen und
wegwerfbare Dateien. Neue Tests sperren echte Sockets; die JSON-Grenztests sperren
zusätzlich `os.pread`. Passende Release-/Runner-Testpins existieren ausschließlich
in begrenzten Mock-Kontexten und temporären synthetischen Release-Repositories.

1. **RED am alten Quellstand**, nur neue/geänderte Tests aufgelegt: 17 Testmethoden,
   54 fehlgeschlagene Teilfälle und 28 Typ-Abweisungsfehler. Darunter Ablauf auf/nach
   der Grenze, 18 Gatefälschungen, 24 HTTPException-Stufenfälle und zehn zuvor
   akzeptierte Eigentümer-/Sondermodi. Die 28 Typfehler waren `TypeError` statt
   der verlangten sicheren `AgentsAPIError`-Abweisung. Bestehende Runnerfrische
   und kanonische BLOCKED-/gültige Providerkombinationen waren bereits korrekt.
2. **GREEN nach Korrektur:** 59 gezielte Tests unter Python 3.12.14, keine Skips.
3. **Vollständige lokale Suite:** Python 3.12.14, **741 Tests, OK, 0 Skips**.
   Gegenüber dem alten Stand kommen 16 Testmethoden hinzu; zusätzliche
   Matrix-Teilfälle sind keine weiteren unittest-Testmethoden.
4. **Erweiterte betroffene Suite:** Python 3.13.5, **195 Tests, OK, 0 Skips**,
   einschließlich Scope-Evidence und Release-/Broker-/Providervertrag.
5. Pilot- und Synthetic-Konfiguration valide, `grants_authority=false`;
   synthetischer `test-fix`-Smoke erfolgreich mit `run.status=blocked`,
   `real_remote_mutations=0`, `simulated_merge_calls=0`.
6. Vollständiges deutsches JSON-Beispiel durch den echten Broker-Sanitizer: PASS.
   `git diff --check`: PASS.
7. Entwicklungsvergleich gegen Ausgangs-HEAD: zehn Dateien bytegleich
   (gemeinsamer HTTPS-/Mutations-/Credential-/Acceptance-/Scope-/Release-Code,
   CI-Workflow und Abhängigkeitskonfiguration). 21 AST-Vergleiche bestätigen
   unveränderte GET-Whitelist, Rollenbindung, Collector-Reads, Broker-Release-/
   FD-/Snapshot-Pfad sowie Runner-Erhebung und CLI-/Manifestvertrag.
   Die vier gezielt geänderten Funktionen sind davon ausdrücklich ausgenommen.

Die lokal fehlenden Werkzeuge Ruff, Coverage und Build sind kein lokaler PASS.
Die vollständige bestehende GitHub-CI führt unter Python 3.11/3.12/3.13 jeweils
Security-Lint, Format, gesamte Suite mit Branch-Coverage (Grenze 80 %), Wheel/SDist
und synthetischen Smoke aus. Hinzu kommen CLI-Hilfe-/Loginstatusprobe ohne Login
oder Tasks sowie Checkpoint und Restore auf frischem Runner. Der R1-Kommentar
in PR #45 dokumentiert alle sechs Jobs mit exakter HEAD-/Tree-Bindung, Testzahlen,
Coverage und separat gezählten Skips. Ergebnisse des alten CI-Laufs #104 werden
nicht als neue R1-Evidence übernommen.

Reproduktion am neuen in PR #45 genannten HEAD (alle Ausgaben nur künstlich):

```sh
git branch --show-current
git rev-parse HEAD 'HEAD^{tree}'
git merge-base e230ddb42fcfad624221a6ed31808b03c7ca6816 HEAD
git diff --check 749047443a9db533785073ff990ab21336e4a98e HEAD
DT_PROVIDER_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_provider_readonly_diagnostics tests.test_provider_readonly_report_boundary tests.test_provider_readonly_runner -v
DT_PROVIDER_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -t . -v
DT_PROVIDER_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 python3.13 -m unittest tests.test_provider_readonly_diagnostics tests.test_provider_readonly_report_boundary tests.test_provider_readonly tests.test_provider_readonly_runner tests.test_provider_readonly_prepare tests.test_provider_readonly_release tests.test_provider_contract tests.test_scope_evidence -v
DT_PROVIDER_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 python -m developer_team validate examples/project.pilot.toml
DT_PROVIDER_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 python -m developer_team validate examples/project.synthetic.toml
DT_PROVIDER_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 python -m developer_team demo --scenario test-fix --output /tmp/dt49-smoke-neu
```

Gepinnte Entwicklungswerkzeuge und vollständige CI-Befehle:
[`requirements-dev.txt`](../requirements-dev.txt), [Teststrategie](testing.md),
[Workflow](../.github/workflows/ci.yml). Die RED-Reproduktion verwendet dieselben
R1-Testdateien auf einem **wegwerfbaren separaten Checkout** des Ausgangs-HEAD;
die produktiven Pins werden dabei ebenfalls nicht angepasst.

## Unveränderte Grenzen und erneute unabhängige Abnahme

`RUNNER_SHA256` bleibt unverändert. Der bestehende Produktionspin sperrt den
geänderten Runner vor Credential-Auswahl, FD-Duplizierung, `pread` und Lesen des
externen Release-Pins. Die vollständige Release-Negativsuite prüft dies weiter.
Kein produktiver Release-Pin wurde gelesen, erzeugt oder geändert. Der getrennte
Release-Pin behält seinen Vertrag (unter anderem Modus 0400); die 0600-Korrektur
betrifft die beiden Credential-Handles.

Nur die bisherigen vier Admin- und zwei Canary-GETs, kein zusätzlicher Request,
Retry, Redirect-Follow oder Mutationspfad. Keine Provider-Credentials, echten
Provideraufrufe, Session-Erstellung, Submit-/Cancel-, Agent-/Key-/Spend-Mutation
oder Live-Aktivierung in diesem Auftrag. Diagnosen sind keine autoritative
Scope-, Journal-, Spend-, Grant-, Operator- oder Release-Freigabe.

Die alten [QA-Befunde #47](https://github.com/oxfrd1337/developer-team/issues/47)
und [Security-Befunde #48](https://github.com/oxfrd1337/developer-team/issues/48)
bleiben historische FAIL-Berichte zum alten HEAD. **Neue getrennte rein lesende
QA- und Security-Prüfungen am neuen exakten HEAD sind erforderlich.** Der
Prüfauftrag wird ausschließlich in PR #45 vorbereitet, ohne weitere PRs oder
Änderung der bestehenden Review-Issues.

- QA: komplette CI-/Quellbaumidentität, Ablaufgrenzen, neun Gatefälschungen,
  vollständige Stufen-/Fehlerprioritätsmatrix und eigene zusätzliche Negativprobe.
- Security: Report-Trust-Boundary, neutrale Fehlerklassifizierung ohne Leakage,
  exakte 0600-Prüfung beider Rollen, unveränderte Mutations-/Release-Sperren und
  eigener zusätzlicher Angriffstest.
- Jeweils eigener Bericht mit PASS/FAIL/UNSUPPORTED, Kommandos und Ergebnissen.
  QA- und Security-Identitäten müssen nachweisbar voneinander und von der
  Entwicklung getrennt sein; ohne diesen Nachweis bleibt die formale
  Unabhängigkeit **UNSUPPORTED**. Keine Selbstattestierung als Freigabe.
- Der bestehende Bubblewrap-Skip in CI bleibt fehlende Hostisolationsevidence:
  **UNSUPPORTED** und Live-Blocker, unabhängig vom lokalen Lauf ohne Skips.

PR bleibt **Draft**, Merge-Gate **HALT**, kein Merge/Auto-Merge. Eine spätere
Runner-/Release-Pin-Freigabe ist ein separat autorisierter Vorgang und gehört
nicht zu Issue #49.

**LIVE=NO-GO · real_submissions=0 · live_authorized=false.**
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**
