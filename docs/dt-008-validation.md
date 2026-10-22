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

Lokale und entfernte endgültige Ergebnisse, Run-URLs und finaler Commit werden nach
Ausführung im Draft-PR festgehalten. Der finale Commit kann nicht seinen eigenen SHA
in seiner Datei enthalten: maßgeblich sind PR-HEAD plus Actions-API `head_sha`,
bei PR-Mergecheckout zusätzlich dessen Eltern und Treevergleich. Ein späterer Commit
benötigt einen neuen vollständigen CI-Lauf. Frühere Läufe dürfen nicht als dessen
Nachweis gelten. Die CI-Dokumentation wird nach dem ersten Lauf um die konkreten
historischen SHA-/Runreferenzen ergänzt; finaler Status bleibt im PR prüfbar.

Lokal fehlen anfangs Ruff, Coverage und Build-Frontend sowie Python 3.11/3.13.
Diese werden nicht als lokal bestanden ausgegeben. Keine Checks oder Workflows wurden
für eine grüne Anzeige abgeschwächt. Der vollständige GitHubnachweis bleibt erforderlich.
