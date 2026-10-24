# DT-017E: Test-, QA- und Security-Bericht

Basis: `e230ddb42fcfad624221a6ed31808b03c7ca6816` (`main`, über GitHub geprüft).
Branch: `dt-017e-safe-readonly-diagnostics`. Auftrag: Issue #44.
Dieser Bericht beschreibt Entwicklungsprüfung, keine unabhängige Release-Freigabe.

## Umsetzung und QA-Befund

- Feste Diagnose je `account_project_binding`, `spend_controls` und
  `agent_configuration`: Operationsstufe und geschlossener Fehlercode.
- Vier bestehende Admin- und zwei bestehende Canary-GETs bleiben getrennt;
  keine neuen Requests, Endpunkte, Retries oder Mutationen. Ein fehlerhaftes Gate
  stoppt an seiner ersten gescheiterten Stufe; andere Gates werden weiter geprüft.
- Schema 2 wird durch Runner und Broker strikt geprüft und neu aufgebaut.
  Versionswechsel und alle Enums sind [dokumentiert](dt-017e-safe-diagnostics.md).
- `COLLECTED` ist ein Erhebungsversuch. `NONE_VALID`/`SOME_VALID` wird aus den
  abschließend gültigen drei Provider-Gates abgeleitet. Diagnose-PASS allein
  überschreibt keinen fehlenden oder abgelaufenen Check.
- Vollständiger deutscher Beispielreport und genau ein offizieller
  Diagnoseaufruf über den bestehenden Broker; keine alternativen Secretpfade.
- Bestehende Mutationstransportschnittstelle bleibt fail-closed: Die neuen
  Wire-Hooks geben dort weiterhin keine Fehlerantwort als Erfolg zurück.
  Read-only-Fehler werden erst außerhalb des Secret-Stores als sichere Exception
  weitergegeben. Nicht-200-Bodies werden für diese GETs nicht gelesen.

## Testmatrix

| Fall | Synthetischer Nachweis |
| --- | --- |
| Sechs gültige 200-GETs | Genau drei Provider-PASS, Scope bleibt fehlend, kein weiterer Request |
| 401/403/429/500/599/302/404/204 | Jede der sechs Stufen; feste Codes, kein Lesen von Fehlerbody oder Redirect-Follow |
| JSON-Liste, doppelte Keys, NaN, ungültiges UTF-8, Secretmarker, 65537 Bytes | Jede Stufe; Schema-/Größenfehler ohne Rohdaten im Report |
| Falsches Contractschema | Jede Stufe separat |
| DNS, TLS, HTTP-Protokoll/Proxy, Timeout, Verbindung, Headergrenze | Jede Stufe separat; Typklassifizierung ohne Fehlertext |
| Früher Connectfehler | Kein Request gesendet, sichere Exception ohne ursprünglichen Kontext |
| Fehlende Account-/Key-/Modellrecords | Separater `EXPECTED_RECORD_MISSING` |
| Agentendrift, Limit über 100 Cent | `CONFIGURATION_MISMATCH`, `BUDGET_MISMATCH` |
| Rollenwechsel, FDs, unveränderliche Pins | Neue Diagnoseprüfung plus bisherige vollständige Rollen-/FD-Suite |
| Wiederholte Erhebung nach Erfolg | Alter PASS wird durch aktuellen Fehler ersetzt |
| Reportmanipulation | Unbekannte/zusätzliche Felder, falsche Typen, Schema 1 und widersprüchliche PASS-/Zählerangaben werden gesperrt |
| Releaseintegrität | Vollständige bisherige Suite plus Sperre des unveränderten Produktions-Runner-Pins vor Credential-Zugriff |

Die neuen Tests sperren echte Sockets und prüfen stdout, stderr, JSON sowie
Exceptiondarstellung auf synthetische Credential-/Antwortmarker. Die bestehenden
Wiretests prüfen echte enge Connect-/Readfristen, Socketabschluss und verspätete
Sendesperren. Alle Fixtures sind künstlich; keine echten Credentials verwendet.

## Ausführungsstand

- Vollständige lokale Python-3.12-Suite: **723 Tests PASS**, kein Skip.
- Betroffene Module unter Python 3.12 und zusätzlich Python 3.13: jeweils
  **103 Tests PASS**.
- Konfigurationsvalidierung für Pilot und synthetisches Projekt: PASS.
- Synthetischer CLI-Smoke `test-fix`: PASS, erwarteter sicher gesperrter Status.
- `git diff --check`: PASS.
- Die verwaltete Umgebung enthält keine Ruff-/Coverage-/Build-Installation;
  Installation der gepinnten Werkzeuge war dort nicht verfügbar. Diese lokalen
  Prüfungen sind deshalb kein PASS. Die bestehende GitHub-CI-Matrix 3.11–3.13
  übernimmt Lint/Format/Coverage ≥80 %, Build, Smoke und Checkpoint/Restore.
- CI-Ergebnisse und Links werden im Draft-PR festgehalten.

## Security-Prüfung und verbleibende Freigaben

Der Entwicklungsreview prüfte die geschlossene GET-Liste, Rollen-/FD-Grenzen,
Fehlerklassifizierung, den Datenfluss zum Broker-Sanitizer und die Trennung von
Diagnose und Observation. Keine URLs, IDs, Header, Providerbodies, dynamischen
Metadaten, Credential-Hashes oder Secret-Fingerprints werden ausgegeben.
Die sichere Transportklassifizierung verwendet Typen beziehungsweise exakt
bekannte interne Fehlercodes; unbekannte Ursachen bleiben generisch.
Der historische all-MISSING-Befund wird keiner unbewiesenen Ursache zugeordnet.

`RUNNER_SHA256` bleibt bytegleich auf dem bisherigen Pin. Der unabhängige externe
Release-Pin wird weder gelesen, erstellt noch erneuert, außer innerhalb der
isolierten synthetischen Release-Testfixtures. Produktive Release-/Snapshot-
Verifikation ist unverändert; die neue Diagnosequelle gehört zum vollständigen
Releaseinventar. Der geänderte Runner ist mit dem alten SHA erwartungsgemäß
blockiert. Es gibt kein Self-Approval, keine Auto-Merge-/Aktivierungsfreigabe.

**Noch erforderlich vor Merge:** unabhängiger QA- und Security-Review des exakten
finalen HEAD durch getrennte Reviewer. Dieser Entwicklungsbericht und grüne CI
ersetzen ihn nicht. **Vor realer Erhebung zusätzlich erforderlich:** separat
reviewte Runner-SHA-Freigabe, unabhängig bereitgestellter exakter Release-Pin und
ausdrückliche lokale Read-only-Erhebung. Dieser Auftrag führt keinen realen Lauf
aus. Fehlende Hostisolation oder andere bestehende Gates bleiben Live-Blocker.

**real_submissions=0 · LIVE=NO-GO · live_authorized=false.**
Kein Merge, keine Live-Aktivierung, keine kostenpflichtige Agentenausführung,
keine Session-Create/Submit/Cancel- oder Providerkonfigurationsmutation.
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**
