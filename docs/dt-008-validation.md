# DT-008: Validierung und Grenzen

Stand 22.10.2026, bestätigte main-Basis
`799f6719dc7c39d64f8738023e4f8fec851ddd21`, Tree
`9b19ad70d82c65b634c05e5c43a7db3148c56680`.
Entwicklungsworker: verwaltetes Linux, Python 3.12.14, Codex CLI 0.163.0;
**kein historischer Codespace**. Keine echten developer-team-Modellaufträge.

## Reproduzierbare echte Leseprüfungen

```sh
codex --version
codex cloud --help
codex cloud exec --help
codex cloud status --help
codex cloud diff --help
codex cloud list --help
python -m developer_team probe-codex
python -m developer_team.preflight
python -m unittest discover -s tests -t . -v
python -m developer_team validate examples/project.pilot.toml
```

Die ersten Befehle lesen nur Hilfe; **kein** `cloud exec QUERY`, `cloud apply`,
interaktives `cloud`, `login`, Tasklisting oder Authcache-Lesen. Probe sanitisiert
Loginstatus auf einen booleschen Hinweis; beobachtet true, unbeaufsichtigte
Cloudberechtigung weiterhin false. Exitcode des Preflight erwartungsgemäß **2**:
`preflight -> BLOCKED / NO-GO -> awaiting-architecture-decision / NOT-GRANTED`.
Der Report schreibt nichts und akzeptiert keinen Freigabe-/Belegimport.
Ein schmutziger Checkout ergänzt einen Blocker. `observed_at/expires_at` betreffen
nur die lokale Diagnose; 300 Sekunden sind keine Provider-Lease.

GitHub-Leseprüfungen mit vorhandener Verbindung:

- `GET /repos/oxfrd1337/developer-team/branches/main`: bestätigter SHA, protected=false.
- `GET .../rulesets`: 403, Planbeschränkung ausdrücklich gemeldet.
- `GET .../branches/main/protection`: 403, Integration ohne Administrationszugriff.
- Effektive Branchregeln konnten nicht vollständig gelesen werden. Der Connector
  lehnt `/rules/branches/main` selbst als nicht unterstützten Endpoint ab.

Runtime-Status liefert aktuelle running-Beobachtung für die angehängte Instanz,
spec revision 2, keine Secrets/Runtimevariables/Outboundidentitäten, policy
mode disabled/state unknown. Die Datei `/etc/codex/network-policy.json` v1 enthält
restricted mit leeren HTTP-/TCP-Zielen und vpn_configured=false. Das ist keine
Attestierung aktiver vierfacher Rollen-/Netzisolation. `git fetch` scheitert am
nicht erreichbaren Proxy; kein direkter Netzwerk-Fallback oder Policywechsel.
GitHub-Connector materialisierte die PR-#9-Dateien, der komplette Basis-Tree und
originale Commit-Hash wurden lokal exakt geprüft.

## Negativfälle und Aussagekraft

| Fall | Prüfung |
| --- | --- |
| Fake GO / behauptetes Cancel / Fake-Signatur | Neue Preflighttests: weiterhin BLOCKED; reale Gateway-Submission vor Prozess/Refs/Journal gesperrt |
| Falsche Repo/Run/Task/Config/SHA/Rolle/Zeit/Reviewer | Neue Gateway-Claimvarianten sowie bestehende test_cloud/test_readiness/test_supervised_pilot: fehlende, doppelte, widersprüchliche, abgelaufene und manipulierte Bindungen verweigert |
| Verbindungsverlust | Sanitisiertes UNSUPPORTED, kein Freigabepfad; bestehende lesende Recovery nur für bekannte Task-ID |
| Doppel-Submission/unklarer Empfang | Bestehende Lifecycletests: ein Intent, keine Wiederholung bei mehrdeutigem Receipt, keine automatische Erstattung des Budgets |
| Falsches Stopversprechen | Trotz behauptetem provider_cancel_available gesperrt; bestehender Deadline-Test behauptet ausdrücklich keinen Remote-Cancel |
| Setup/Netz/Credentials ungeprüft | Fehlen immer als UNSUPPORTED; Claim-PASS öffnet nichts |
| GitHubschutz fehlt | Permanenter eigener Preflightblocker, unabhängig von CLI-/CI-PASS |
| Reportdatei als Freigabe | Kein Importparameter; --claims/--approval/--live/--force abgewiesen |

Die Tests verwenden injizierte modellfreie Antworten bzw. eigene temporäre
synthetische Repos/Prozesse. Es wurde **kein** positiver unabhängiger Signaturverifikator
für Cloudattestierungen gebaut: Ein negativer Signaturclaim-Test belegt nur die
Verweigerung, keine existierende PKI oder Hostabnahme. Bestehende Broker-/Lease-/
Reviewverträge werden wiederverwendet und bleiben ausdrücklich Offlinebelege.

## Sicherheitsreview und Korrektur der Transportgrenze

Der [Review vom 22.10.2026](https://github.com/oxfrd1337/developer-team/pull/11#pullrequestreview-5611437964)
zu HEAD `f0bdc914e73fa498f405d8195a5ec7c72f7a56d3` weist korrekt nach, dass
`runner is run_cli` nur ein Funktionsobjekt sperrt. Lambda, Partial oder Callable
könnten echte Submissions weiterleiten. Die früheren Default-Runner-Tests und grünen
CI-Läufe belegen **keinen Schutz gegen diese Umgehung**.

Korrektur: produktiver `CodexCloudGateway` ohne Runnerparameter, bedingungslose
NO-GO-Verweigerung für Submission und Collection. Die produktive Probe verwendet nur
fest vorgegebene lesende CLI-Argumente. Der bisherige Lifecycle lebt getrennt in
`_OfflineCloudLifecycle` ohne CLI-/Netzwerktransport. `RehearsalCloudGateway` verdrahtet
fest den deterministischen `RehearsalCLI`; frei geskriptete Vertragstransporte gibt es
nur in `tests/cloud_support.py`. Kein Produktionskonstruktor kann sie auswählen.

`python -m unittest tests.test_cloud_start_boundary -v`: sieben neue Methoden bestehen
lokal. Vor jedem Produktionstest werden die ansonsten gültigen Repo-/Config-/Run-/Job-/
Rollen-/Umgebungs-/Zeitbindungen durch die bestehende Offline-Autorisierungsprüfung
positiv kontrolliert. Geprüft sind direkte Funktion, Lambda, Partial, Callable-Objekt,
positionelle/benannte Runnerinjektion, nachträgliche runner/_runner/transport-Attribute,
vier Simulationskennzeichen, Fake-Grants/-Approvals/-Jobs sowie gesperrte Collection.
Negative Produktionsfälle verlangen keine CLI-/Popen-Aufrufe und leere Ref-/Journal-
Mockaufruflisten. Der feste Rehearsaltransport liefert auch bei solchen Attributen und
geändertem Label ausschließlich simulierte Receipts, ohne Prozessstart.

Bestehende Cloud-/Pilot-Vertragstests bleiben erhalten und verwenden explizite
Offline-Fixtures; Loginprobetests patchen nur die feste lesende Prozessfunktion.
Die sieben neuen Methoden sind zusätzlich zu den früheren 227 Tests auszuführen.
Die unveränderte vollständige CI muss für den korrigierten finalen HEAD erneut laufen;
die folgenden älteren Läufe sind ausschließlich historische Nachweise ihres Standes.

Gesamtlauf der Reviewkorrektur lokal unter Python 3.12.14 und 3.13.5: jeweils
**234 Tests, 232 PASS / 1 unveränderter Socket-Host-ERROR / 1 alter Namespace-Host-Skip**.
Der bestehende Sockettest scheitert weiterhin an der Workerbeschränkung; keine neue
Produktionsfreigabe und keine abgeschwächten Hostprüfungen. Konfigurationsvalidierung,
sanitisierte CLI-Probe und lesender Preflight sind ausführbar; Preflight bleibt
BLOCKED / NO-GO. Endgültiger neuer CI-Run samt finalem HEAD wird im Draft-PR #11
nachvollziehbar ergänzt; kein neuer PR und kein Merge.

## Nicht verfügbare echte Abnahmen

Alle folgenden Kontrollen bleiben **UNSUPPORTED**, niemals PASS: vier unabhängige
Rollen-/Repo-/Secret-/Netz-/Schreibgrenzen; externer Controller/Grant/Journal/Kollektor;
Provider-Quell-/Test-/Reviewerattestierung am identischen HEAD; Remote-Cancel und
bestätigter Terminalzustand; harte aggregierte Ressourcen-/Cleanupgrenzen;
Provider-Idempotenz; verfügbare Restquote und hartes Kostenlimit; wirksamer strikter
GitHubschutz; Betreiberbestätigung des realen Incidentverfahrens. Eine gemessene
CLI-Hilfe oder funktionierender Login ersetzt keinen dieser Nachweise.

Die zusätzlich ausgeführte bestehende `readiness_probe` meldete insbesondere fehlende
Namespacefähigkeit (`NETLINK_ROUTE: Operation not permitted`), cgroup nur lesend,
keinen externen Supervisor und zeitweise nicht ausführbare pidfd-/Socketprobes.
Dies ist kein neuer Produktionsbeleg. Die historischen DT-006/007-Berichte bleiben
unverändert. Der alte optionale Namespace-Test darf als sichtbarer Host-Skip erscheinen,
bleibt aber im Abnahmeurteil UNSUPPORTED.

## Testergebnisse und CI-Bindung

Die unveränderte `.github/workflows/ci.yml` muss alle sechs Jobs bestehen:
Python 3.11/3.12/3.13 jeweils Ruff inkl. Security, Format, vollständige Unittests mit
Branch-Coverage >=80 %, Wheel/SDist und Smoke; dazu CLI-Leseprobe und zwei modellfreie
Checkpoint-/Restorejobs. Kein eigener Liveworkflow oder Secret wird ergänzt.

Lokale und entfernte endgültige Ergebnisse, Run-URLs und finaler Commit stehen im
Draft-PR [#11](https://github.com/oxfrd1337/developer-team/pull/11). Der finale Commit kann nicht seinen eigenen SHA
in seiner Datei enthalten: maßgeblich sind PR-HEAD plus Actions-API `head_sha`,
bei PR-Mergecheckout zusätzlich dessen Eltern und Treevergleich. Ein späterer Commit
benötigt einen neuen vollständigen CI-Lauf. Frühere Läufe dürfen nicht als dessen
Nachweis gelten. Die konkreten historischen SHA-/Runreferenzen folgen unten;
der abschließende Status bleibt im PR prüfbar.

Lokal fehlen Ruff, Coverage und Build-Frontend sowie Python 3.11.
Diese werden nicht als lokal bestanden ausgegeben. Keine Checks oder Workflows wurden
für eine grüne Anzeige abgeschwächt. Der vollständige GitHubnachweis bleibt erforderlich.

Erster lokaler Gesamtlauf: **227 Tests, 225 PASS, 1 ERROR, 1 Host-Skip**.
Der unveränderte `test_positive_controls_detect_access_when_boundary_is_absent`
scheitert an `socket.socket: PermissionError / Operation not permitted` des Workers.
Der optionale Namespace-Test bleibt wegen Hostgrenzen übersprungen. Die fünf neuen
Preflightmethoden bestehen vollständig. Keine Tests wurden dafür entfernt/geändert.
Konfigurationsvalidierung besteht. Der vorhandene modellfreie Testadapter-Gesamtlauf
endet erwartungsgemäß blocked, beide lokalen Pilotchecks pass, sechs simulierte Tasks
einschließlich einer QA-Korrektur, **0 echte Cloudsubmissions / 0 Remotemutationen**.
Diese bestehende Korrekturdemo ist kein vierfacher Livepilot und erweitert dessen
vorgeschlagenes Vier-Aufgaben-Budget nicht.

Erster CI-Versuch: [Run 39746998524](https://github.com/oxfrd1337/developer-team/actions/runs/39746998524),
HEAD `ee6353fdfc99dd3ea3a45d6086fc8154ad1312ac`, **nicht vollständig grün**:
die drei Qualitätsjobs scheitern an genau einer 101-Zeichen-Zeile im neuen Preflight
(Ruff E501); CLI-Probe und beide Checkpoint-/Restorejobs bestehen. Die Zeile wurde
verkürzt, zusätzlich die Testformatierung an den bestehenden Stil angepasst.
Der nächste Lauf prüft wieder die vollständige unveränderte CI.

## Erfolgreicher vollständiger Quellcode-Nachweis

[Run 39747223045 / #26](https://github.com/oxfrd1337/developer-team/actions/runs/39747223045):
**completed / success, alle 6 Jobs erfolgreich**, Actions-API
`head_sha=330f1ee90127f1508da4de19cdfc2e83f0c99a8a`.

| Job | Tests | Branch-Coverage | Weitere Prüfungen |
| --- | --- | --- | --- |
| [Python 3.11](https://github.com/oxfrd1337/developer-team/actions/runs/39747223045/job/119718598266) | 227: 226 PASS / 1 alter Host-Skip | 91 % | Ruff/Security, Format, Wheel/SDist, Konfiguration, Smoke PASS |
| [Python 3.12](https://github.com/oxfrd1337/developer-team/actions/runs/39747223045/job/119718598296) | 227: 226 PASS / 1 alter Host-Skip | 91 % | alle PASS |
| [Python 3.13](https://github.com/oxfrd1337/developer-team/actions/runs/39747223045/job/119718598300) | 227: 226 PASS / 1 alter Host-Skip | 91 % | alle PASS |

Jeweils `All checks passed!`, `50 files already formatted`, 3137 Statements und
898 Branches, Coverage 91 % >=80 %. Der einzige Skip ist
`test_real_namespace_boundary_if_supported_by_host`: fehlendes Bubblewrap auf Actions,
kein Isolations-PASS. CLI-Leseprobe und beide Checkpoint-/Restorejobs sind erfolgreich.

Die unveränderte PR-CI prüfte GitHubs temporären Mergecheckout
`4cbc2ce638f6d6883dd6cb65cdd4b74cbfc764cb`. Seine Eltern sind exakt die bestätigte
main-Basis und obiger HEAD, sein Tree `1cc1e0be4ffe6ae7b2d2e7f84e5abb23d27651e5`
ist identisch zum HEAD-Tree. Das ist **kein Merge des PR**.

Erneuter lokaler Gesamtlauf unter **Python 3.12.14 und 3.13.5**: jeweils 227 Tests,
225 PASS / derselbe unveränderte Socket-Host-ERROR / derselbe alte Host-Skip.
Der Fehler ist eine echte Workerbeschränkung, keine erfolgreiche lokale Gesamtsuite.
GitHub bestätigt denselben Socket-Test auf unterstütztem Actions-Host erfolgreich.
Wheel und SDist wurden lokal mit dem vorhandenen Setuptools-Backend gebaut (ohne
fehlendes Build-Frontend); alle Pythonquellen im Wheel byteidentisch zum Checkout.
Separat entpackter Wheel-Smoke `test-fix` erfolgreich, erwarteter blocked-Abschluss.

Echter lesender Preflight am **22.10.2026, 08:22:29 UTC (10:22:29 Berlin)**,
sauberer Controller-HEAD `330f1ee90127f1508da4de19cdfc2e83f0c99a8a`, Basis wie oben,
effektiver Configdigest
`c35e4a0adfadd3a3946518f5f16897ed4f8ebb3badf7da316f75aa4cd794b496`:
BLOCKED / NO-GO, awaiting-architecture-decision, NOT-GRANTED, real_submissions=0.
Das Diagnosefenster ist mittlerweile abgelaufen und erteilt ohnehin keine Autorität.

Nach diesem Nachweis wird ausschließlich diese Ergebnisdokumentation aktualisiert.
Auch der resultierende finale PR-HEAD erhält erneut die **vollständige** unveränderte
GitHub-CI; deren URL und exakter HEAD werden im PR-Abschluss festgehalten.
