# DT-006 – tatsächlich ausgeführte Prüfungen

## Umgebung und Nachweisgrenze

Datum: 21.10.2026, UTC. Geprüft wurde die verwaltete Codex-Arbeitsumgebung
mit Linux 6.18.55, Python 3.12.14 und Python 3.13.5. Sie ist kein GitHub Codespace.
Auditbasis: `737dffc705b368e550e0a38803068e23b9c56d09` (gemergtes DT-005).
Reviewgrundlage ist PR #7 bei `54c4612ff2b00279e3291c4b1008d6331a6a116a` und der
[Review-Kommentar vom 21.10.2026](https://github.com/oxfrd1337/developer-team/pull/7#issuecomment-6326858522).
Diese Revision prüft ein festes Diagnoseformat vor jedem Schreibzugriff und trennt
die Hostmessung von deterministischen Status-Vertragstests. Sie aktualisiert
ausschließlich den bestehenden Draft-PR #7.

Die neue Implementierung startet keine echten KI-Agenten. Alle Tests verwenden
controllerseitige Python-Simulatoren und temporäre synthetische Repositories.
Für diese Prüfung wurden weder Login-/Secret-Konfigurationen noch Hostrechte,
Netzregeln oder vorhandene Schutzregeln geändert. Es wurden keine neuen Dienste
gebucht und keine Container-/VM-Ressourcen angelegt.

## Lokale Prüfergebnisse

| Ausgeführte Prüfung | Beobachtung |
| --- | --- |
| `python -m unittest discover -s tests -t . -v` unter Python 3.12.14 | **203 Tests erfolgreich**, kein Skip. |
| `/usr/bin/python3.13 -m unittest discover -s tests -t . -v` | **203 Tests erfolgreich**, kein Skip. |
| `python -m unittest tests.test_exec tests.test_boundaries -v` | **37 Tests erfolgreich**; vier zusätzliche Testfälle der Reviewrevision und erweiterte Negativmatrizen. |
| `python -m developer_team.boundary_probe` | **NO-GO**, erwarteter Exitcode 2; 97 bestandene Einzelbeobachtungen, 5 ausdrücklich `UNSUPPORTED`. Keine KI-Aufrufe. |
| `python -m developer_team validate examples/project.synthetic.toml` | Gültig, `grants_authority=false`. |
| `python -m developer_team validate examples/project.pilot.toml` | Gültig, `grants_authority=false`. |
| `python -m developer_team demo --scenario test-fix --output …` | Erwartetes `blocked`, ein echter lokaler Testfehler mit simulierter Entwicklerkorrektur, erfolgreiche Abnahmen; 0 reale Remoteänderungen, 0 Merge-Aufrufe. |
| `python -m compileall -q developer_team tests` und `git diff --check` | Erfolgreich; keine Aussage über Ruff oder Branch-Coverage. |
| Lokaler Setuptools-Backend-Build | Wheel und SDist erfolgreich über `setuptools.build_meta.build_wheel` / `build_sdist` in einer temporären Quellkopie erzeugt. Installierter Backend 84.0.0, Wheel 0.48.0; nicht die gepinnte CI-Werkzeugkette. |
| Wheel ohne Netzwerk in temporäres Ziel installieren und Smoke mit explizitem `--config` | Konfiguration gültig; `test-fix` wie im Quellbaum mit erwartetem `blocked`, ohne reale Remoteänderungen oder Merge. Ein erster Aufruf ohne Configpfad aus dem fremden Arbeitsverzeichnis scheiterte an der fehlenden relativen Beispielkonfiguration; mit explizitem Pfad behoben. |

Die Messung der Hostgrenzen ist in
[dt-006-boundary-report.json](dt-006-boundary-report.json) gespeichert, erhoben am
`2026-10-21T21:37:55.932321+00:00`. Der Bericht enthält den SHA-256 der tatsächlich
ausgeführten `boundary_probe.py`:
`fc38eb41ee8950df267d423184ea4409e16d0addfc3a6e73d8cc1bcc98819eb0`.
Die Datei ist ein Beobachtungsartefakt, keine gespeicherte Startberechtigung.

Die negativen Zugriffe wurden hier tatsächlich in getrennten User-, Mount-, PID-,
Netz-, IPC- und UTS-Namespaces ausgeführt. Dateiziele, lokale DNS-Transport-/HTTP-/
TCP-/Unix-/Abstract-Listener und der künstliche Hostprozess hatten erfolgreiche
Positivkontrollen. Snapshotdateien und Canaries blieben unverändert. Fehlende
Namensraumfunktionen, Fehler und unvollständige Resultate werden zusätzlich
modellfrei in den Regressionstests nachgebildet und müssen `UNSUPPORTED` ergeben.
Diese Vertragstests sind keine ausgeführten Hostprobes auf einem anderen System.

Für die Diagnose-Schnittstelle wurden falsche Herkunft/Quelle, echte oder nur
ähnlich falsche Attestierungswerte (z. B. `0`), fehlende/zusätzliche Felder, falsche
Digesttypen/-längen/-zeichen, Dict-Unterklassen, fremde Job-/HEAD-Bindungen sowie
unvollständige oder nicht simulierte Transporte abgelehnt. Aufruf und Ereignisliste
bleiben dabei unverändert. Gültige Diagnose bleibt `origin=simulated` und
`execution_attested=false`; ein neuer Controller erhält daraus keine Receipts.

Die getrennten synthetischen Berichtstests erlauben Basis-Namespaces zusammen mit
einzelnen `UNSUPPORTED`-Ergebnissen und unvollständigen Folgeprobes. Sie weisen
`FAIL` und unbekannte Statuswerte zurück, auch wenn der Gesamtbericht NO-GO sagt.
Die echte Hostprobe verlangt deshalb keinen erfundenen PASS für fehlende Funktionen.

**Alle vier Rollen meldeten UID 1000.** Die Namespaces und Mountgrenzen der Probe
sind keine getrennten Hostidentitäten. Die fünf offenen Komponenten sind:

1. Credential-sicherer Modellbroker für den vorhandenen ChatGPT-Login.
2. Extern erzwungener Modell-Egress mit gleichzeitig gesperrtem Tool-Egress.
3. Unabhängiger Supervisor mit Cleanup auch nach Controller-SIGKILL.
4. Aggregierte CPU-/Speicher-/PID-Durchsetzung für alle Nachfahren.
5. Getrennte Host-UID-/VM-Identitäten für Controller und Rollen.

Zusätzlich bleiben unveränderliche Live-Reviewer-Mounts und ein geschützter
unabhängiger Attestierungskollektor offen. Die separaten Simulator-Kopien werden
durch die neuen Inhaltsprüfungen nicht zu einer unveränderlichen OS-Grenze.

## Lokale Werkzeuggrenzen und vollständige CI

Folgende Aufrufe wurden erneut lokal versucht und scheiterten an fehlenden Modulen:

```text
python -m ruff check developer_team tests       -> No module named ruff
python -m ruff format --check developer_team tests -> No module named ruff
python -m coverage run --branch -m unittest …   -> No module named coverage
python -m build --no-isolation                 -> No module named build
```

Damit sind Ruff inklusive Securityregeln, Ruff-Format, Branch-Coverage ≥80 % und
das gepinnte Build-Frontend **lokal offen**, nicht bestanden. Der zusätzliche direkte
Backend-Build ersetzt diese fehlenden Werkzeug-/CI-Nachweise nicht. Python 3.11
ist lokal nicht vorhanden; auch dessen Matrixlauf bleibt offen.

Das lokale Netzwerkpolicy-Snapshot erlaubt keine externen HTTP-/TCP-Zielhosts.
Die aktuelle Laufzeitstatusabfrage meldet `mode=disabled`, `state=enforced` und
keine konfigurierten Credentials/Identitäten. Abhängigkeiten wurden deshalb nicht
aus dem Netz nachinstalliert; keine Proxy-, Auth- oder Policyumgehung.

Der ursprüngliche PR-HEAD enthielt `[skip ci]` und hatte deshalb keine Pflicht-CI.
Die Kostenprüfung dieser Revision ergab: Der GitHub-Connector bietet keinen
kontoweiten Billing-/Restkontingentzugriff und unterstützt keine User-/Organisation-Billing-APIs;
direkte Abfragen aus dem Worker sind durch die Netzpolicy gesperrt. Weder Restminuten
noch freier Artefaktspeicher konnten unabhängig abgelesen werden. Ein unbekanntes
Kontingent wird nicht als kostenfreies Restbudget ausgegeben.

Der Auftraggeber hat anschließend ausdrücklich angewiesen, den regulären Lauf
im kostenlosen Kontingent zu versuchen, und angegeben, dass keine Zahlungsdaten
hinterlegt sind. Auf dieser Grundlage entfällt `[skip ci]` beim Reviewcommit.
Es werden nur die bestehenden sechs Linux-Jobs der unveränderten CI versucht:
drei Qualitätsjobs mit je 10 Minuten Timeout und drei weitere Jobs mit je 5 Minuten,
zusammen 45 konfigurierte Jobminuten. Das ist keine Garantie über tatsächliche
Abrechnungsminuten oder gleichzeitigen Kontoverbrauch. Keine neuen Runnerklassen,
Käufe, Zahlungsdaten, Budgets oder Billing-Einstellungen; bei einer von GitHub
gemeldeten Kontingent-/Abrechnungssperre stoppen und diese dokumentieren.

Lesbar waren anschließend die runbezogenen Timing-Endpunkte der Läufe
[39679963318](https://github.com/oxfrd1337/developer-team/actions/runs/39679963318) und
[39680188884](https://github.com/oxfrd1337/developer-team/actions/runs/39680188884).
Beide API-Antworten melden `billable.UBUNTU.total_ms=0`, bei 28 bzw. 26 Sekunden
Gesamtlaufzeit. Diese Läufe fanden Import-/Formatbefunde; sie sind keine grünen
Prüfnachweise. Timingdaten ersetzen weder eine aktuelle Restkontingentabfrage
noch eine Prüfung des verfügbaren Artefaktspeichers oder eine Kostengarantie.

Die vollständige CI muss Python 3.11/3.12/3.13, Ruff inklusive Securityregeln,
Format, vollständige Suite mit Branch-Coverage ≥80 %, Build und Smoke für denselben
PR-HEAD belegen. Verbindliche Commit-SHA, Workflow-URLs und tatsächlich beobachtete
Ergebnisse werden in der Beschreibung von [PR #7](https://github.com/oxfrd1337/developer-team/pull/7)
festgehalten. Es wird kein CI-PASS aus den lokalen Tests abgeleitet. Die bestehende
CI und alle Merge-/Schutzregeln bleiben unverändert; der PR bleibt Draft.

## Nächste Betriebsentscheidung

**Weiterhin NO-GO für einen echten beaufsichtigten Lauf.** Zunächst nur dieselben
Offline-Probes im vorgesehenen Codespace erheben und einen unterstützten
Modell-/Tool-Brokervertrag ohne Projektzugriff auf Credentials nachweisen. Der
Codespace ist hier nicht geprüft worden. Bei fehlender Brokerfähigkeit eine der
Alternativen mit Kosten-/Rechtefolgen aus [dt-006.md](dt-006.md) entscheiden;
DT-006 installiert oder bucht keine davon.

Erst nach unabhängiger Hostprüfung und vollständigen Pflichtchecks darf über eine
separate ausdrückliche, zeitlich und an Run/Repo/Config/Commit gebundene Freigabe
für genau eine Vier-Rollen-Runde entschieden werden. Aufruf-/Zeitlimits bleiben
keine garantierten Euro-/Token-Caps. Keine automatische Wiederholung bei unklarem
Ausgang, kein Merge, kein Deployment und keine Umgehung bestehender Freigaben.
