# DT-017E: Test-, QA- und Security-Bericht

## Gegenstand

Issue #44 auf separatem Branch `dt-017e-safe-provider-diagnostics` von
`main=e230ddb42fcfad624221a6ed31808b03c7ca6816`.
Feste Diagnosecodes und GET-Stufen, Schema-2-Propagation durch Collector, Runner
und Broker sowie deutsche [Bedienungsanleitung](dt-017e-safe-diagnostics.md).
Der Draft-PR enthält zusätzlich den abschließenden CI-Status mit Run-Link.

## Testnachweise

16 neue synthetische Regressionstests mit zahlreichen Matrix-Unterfällen:

- Alle sechs bisherigen Operationen mit 401/403/429/500/599, vier Redirectklassen,
  404 und unerwartetem 201; erste Fehlerstufe, kein Retry, keine neue Operation.
- Alle sechs Operationen mit 200 und ungültiger Contractstruktur; gültige
  Antworten liefern unverändert nur drei providerprüfbare Gates.
- Fehlende Account-/Key-/Modell-Einträge, Agent-Drift und ungültiges Budget.
- DNS, TLS, Proxykonfiguration, Verbindungsfehler, Timeout sowie Connect-/Read-
  Wartefristen, Header-/Body-Größenlimits, defektes JSON, Duplikate und NaN.
- Keine Rohfehler in stdout/stderr; fixe Exceptiontexte ohne Exceptionverkettung.
  Synthetische Secret-/Bodymarker dürfen nicht in JSON erscheinen.
- Rollen-FD-Tausch ohne Providerzugriff; Ablauf verwirft sämtliche Evidence und
  Diagnosen. Verifierablehnung kann kein Diagnose-PASS hinterlassen.
- Schema-1-Ablehnung, unbekannte/zusätzliche/verschachtelte Felder, falsche Typen,
  widersprüchliche Stage-/Gate-/Zählerwerte und Bool als Integer.
- Unveränderte Produktions-Runner-SHA blockiert vor Release-/Secretzugriff.

Alle Provider-Fixtures sperren echte Sockets. Die bestehenden Rollen-, FD-, Scope-,
Release-Integritäts-, Controller-, Budget- und Mutation-Gate-Tests bleiben aktiv.
Die bisherigen Runner-Tests prüfen zusätzlich die Diagnosekonsistenz jedes Reports.
Broker-/Release-Erfolgsfixtures ersetzen den Runner-Hash ausschließlich innerhalb
ihres synthetischen Testprozesses, um die nachgelagerten Schutzmechanismen weiterhin
zu testen. Kein tatsächlicher Release-Pin wird geschrieben oder als Approval verwendet.

Lokale Befehle:

```sh
DT_PROVIDER_OFFLINE=1 python -m unittest discover -s tests -t . -v
DT_PROVIDER_OFFLINE=1 /usr/bin/python3.13 -m unittest discover -s tests -t . -v
python -m unittest tests.test_provider_readonly_diagnostics -v
python -m developer_team validate examples/project.synthetic.toml
python -m developer_team demo --scenario test-fix --output work/dt017e-smoke
```

Konfigurationsprüfung und synthetischer Smoke bestehen; der Smoke bleibt erwartbar
BLOCKED mit manuellen Merge-/Release-Blockern. Die vollständige Suite besteht lokal unter Python 3.12 und 3.13 mit jeweils
726 Tests (35,1 bzw. 35,2 Sekunden). Abschließende CI-Ergebnisse stehen im Draft-PR.
Die lokale Installation von Ruff/Coverage/Build wurde durch HTTP-Proxy-403 blockiert;
diese Prüfungen werden deshalb in der vorhandenen gepinnten GitHub-CI ausgeführt.
Es wurde keine Netzsperre umgangen. Python 3.11 wird durch CI geprüft.

Die unveränderte CI prüft Python 3.11–3.13, Ruff einschließlich Security-Regeln,
Format, Branch-Coverage >=80 %, Build, synthetischen Smoke und Checkpoint/Restore.
`DT_PROVIDER_OFFLINE=1` bleibt gesetzt. Es gibt keinen neuen Live-Workflow.

## QA-Prüfung der Implementierung

Die Prüfung des Changesets durch den implementierenden Agenten ergibt:

- Die sechs GETs und ihre bisherigen Rollen bleiben gleich. Fehler beenden
  ausschließlich die bereits bestehende GET-Kette des jeweiligen Gates.
- Ausgabe-PASS wird mit den akzeptierten Checks abgeglichen; der Zähler zählt
  ausschließlich die drei Provider-Gates. Scope und alle anderen Gates bleiben
  ohne bisherige unabhängige Evidence MISSING_OR_INVALID.
- Der Broker rekonstruiert bekannte Felder, akzeptiert keine alten Reports und
  verweigert widersprüchliche BLOCKED-/PASS-Claims.
- `COLLECTED` ist ausdrücklich Erhebungsversuch; null gültige Observations sind
  maschinenlesbar. Diagnosewerte werden nie als Freigabequelle eingelesen.
- Späte Worker übergeben ihre Codes nur über die jeweilige Request-Queue.
  Es gibt keine Diagnose-Schreiboperation aus einem verspäteten Worker.

Dies ist ein Implementierungsbericht, **kein unabhängiger QA-Review**.
Ein unabhängiger Review des endgültigen exact-HEAD ist vor Merge zwingend offen.

## Security-Prüfung und verbleibende Grenzen

Kein neuer Endpunkt, keine zusätzliche Operation oder Provider-Mutation.
Kein Session-Create, Submit, Cancel, Key-/Spend-/Agent-Update und keine
kostenpflichtige Agentenausführung. Keine Credentialbeschaffung oder Secretdatei-
Ad-hoc-Skripte. Der Runtimepfad bleibt ausschließlich stdlib.

Der gemeinsame HTTPS-Worker transportiert intern zusätzlich einen festen Code.
Seine bisherigen Größen-/Fristgrenzen, DNS/TCP/TLS-Begrenzung, Proxy-/CA-Regeln,
Redirect-/Retry-Sperren, Mutation-Gates und Reconciliation-Fehler bleiben erhalten.
Nur die Read-only-Unterklasse klassifiziert Fehler; sie verwendet Typen und feste
interne Codes statt Fehlertexten. TLS-/Proxy-Code bezeichnet eine sichere Klasse,
keine bewiesene konkrete Ursache. Credentials und sensible Providerwerte werden
weder gehasht noch in Diagnosefelder übernommen.

Externe exakte Release-Identität, vollständiges Inventar, isolierter Snapshot,
Rollen-FDs und finale Frischeprüfungen bleiben Pflicht. Die Produktionskonstante
`RUNNER_SHA256` ist unverändert. Dadurch bleibt dieser geänderte Runner für reale
Erhebungen schon vor Secret-Auswahl gesperrt. Ein grüner Draft, synthetischer Pin
oder eigener Bericht ist kein Self-Approval. Keine automatische Pin-Erneuerung.

Offen bleiben unabhängiger QA-/Security-Review und manueller Merge. Ein späterer,
separat beauftragter realer Read-only-Lauf erfordert separat reviewed exact-HEAD,
unabhängig bestätigte Runner-SHA und extern bereitgestellten Release-Pin sowie
sämtliche bisherigen lokalen Voraussetzungen. Fehlende Live-Evidence bleibt ein
Blocker. Der vorliegende Auftrag erlaubt keine Live-Aktivierung.

**real_submissions=0 · LIVE=NO-GO · live_authorized=false.**
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**
