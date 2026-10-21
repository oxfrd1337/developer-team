# DT-006 – tatsächlich ausgeführte Prüfungen

## Umgebung und Nachweisgrenze

Datum: 21.10.2026, UTC. Geprüft wurde die verwaltete Codex-Arbeitsumgebung
mit Linux 6.18.55, Python 3.12.14 und Python 3.13.5. Sie ist kein GitHub Codespace.
Auditbasis: `737dffc705b368e550e0a38803068e23b9c56d09` (gemergtes DT-005).
Die ursprüngliche lokale Kopie war noch auf DT-004. Die DT-005-Dateien wurden über
den vorhandenen GitHub-Connector gelesen und ihre Blob-, Tree- und Commit-SHAs
vor dem Anlegen des Entwicklungsbranches gegen die Git-Objekte geprüft.

Die neue Implementierung startet keine echten KI-Agenten. Alle Tests verwenden
controllerseitige Python-Simulatoren und temporäre synthetische Repositories.
Für diese Prüfung wurden weder Login-/Secret-Konfigurationen noch Hostrechte,
Netzregeln oder vorhandene Schutzregeln geändert. Es wurden keine neuen Dienste
gebucht und keine Container-/VM-Ressourcen angelegt.

## Lokale Prüfergebnisse

| Ausgeführte Prüfung | Beobachtung |
| --- | --- |
| `python -m unittest discover -s tests -t . -v` unter Python 3.12.14 | **199 Tests erfolgreich**, kein Skip. |
| `/usr/bin/python3.13 -m unittest discover -s tests -t . -v` | **199 Tests erfolgreich**, kein Skip. |
| `python -m unittest tests.test_exec tests.test_boundaries -v` | **33 Tests erfolgreich**; darunter die 17 neuen Sicherheits-/Isolationsregressionen. |
| `python -m developer_team.boundary_probe` | **NO-GO**, erwarteter Exitcode 2; 97 bestandene Einzelbeobachtungen, 5 ausdrücklich `UNSUPPORTED`. Keine KI-Aufrufe. |
| `python -m developer_team validate examples/project.synthetic.toml` | Gültig, `grants_authority=false`. |
| `python -m developer_team validate examples/project.pilot.toml` | Gültig, `grants_authority=false`. |
| `python -m developer_team demo --scenario test-fix --output …` | Erwartetes `blocked`, ein echter lokaler Testfehler mit simulierter Entwicklerkorrektur, erfolgreiche Abnahmen; 0 reale Remoteänderungen, 0 Merge-Aufrufe. |
| `python -m compileall -q developer_team tests` und `git diff --check` | Erfolgreich; keine Aussage über Ruff oder Branch-Coverage. |
| Lokaler Setuptools-Backend-Build | Wheel und SDist erfolgreich über `setuptools.build_meta.build_wheel` / `build_sdist` in einer temporären Quellkopie erzeugt. Installierter Backend 84.0.0, Wheel 0.48.0; nicht die gepinnte CI-Werkzeugkette. |
| Wheel ohne Netzwerk in temporäres Ziel installieren und Smoke mit explizitem `--config` | Konfiguration gültig; `test-fix` wie im Quellbaum mit erwartetem `blocked`, ohne reale Remoteänderungen oder Merge. Ein erster Aufruf ohne Configpfad aus dem fremden Arbeitsverzeichnis scheiterte an der fehlenden relativen Beispielkonfiguration; mit explizitem Pfad behoben. |

Die Messung der Hostgrenzen ist in
[dt-006-boundary-report.json](dt-006-boundary-report.json) gespeichert, erhoben am
`2026-10-21T21:13:27.793009+00:00`. Der Bericht enthält den SHA-256 der tatsächlich
ausgeführten `boundary_probe.py`:
`9b063407143699b15f92a8228496d321d413eb4e7bd1b5ceb88c0b044109c413`.
Die Datei ist ein Beobachtungsartefakt, keine gespeicherte Startberechtigung.

Die negativen Zugriffe wurden hier tatsächlich in getrennten User-, Mount-, PID-,
Netz-, IPC- und UTS-Namespaces ausgeführt. Dateiziele, lokale DNS-Transport-/HTTP-/
TCP-/Unix-/Abstract-Listener und der künstliche Hostprozess hatten erfolgreiche
Positivkontrollen. Snapshotdateien und Canaries blieben unverändert. Fehlende
Namensraumfunktionen, Fehler und unvollständige Resultate werden zusätzlich
modellfrei in den Regressionstests nachgebildet und müssen `UNSUPPORTED` ergeben.
Diese Vertragstests sind keine ausgeführten Hostprobes auf einem anderen System.

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

## Noch offene Pflichtchecks

**Die CI-Akzeptanz ist noch nicht vollständig nachgewiesen.** Folgende Aufrufe
wurden versucht und scheiterten an fehlenden lokalen Modulen:

```text
python -m ruff check developer_team tests       -> No module named ruff
python -m ruff format --check developer_team tests -> No module named ruff
python -m coverage run --branch -m unittest …   -> No module named coverage
python -m build --no-isolation                 -> No module named build
```

Damit sind Ruff inklusive Securityregeln, Ruff-Format, Branch-Coverage ≥80 % und
das gepinnte Build-Frontend **offen**, nicht bestanden. Der zusätzliche direkte
Backend-Build ersetzt diese fehlenden Werkzeug-/CI-Nachweise nicht. Python 3.11
ist lokal nicht vorhanden; auch dessen Matrixlauf bleibt offen.

Das lokale Netzwerkpolicy-Snapshot erlaubt keine externen HTTP-/TCP-Zielhosts;
die Laufzeitstatusabfrage meldet keinen nachgewiesen erzwungenen HTTP-Status und
keine konfigurierten Credentials/Identitäten. Abhängigkeiten wurden deshalb nicht
aus dem Netz nachinstalliert; keine Proxy-, Auth- oder Policyumgehung.

Das Repository ist privat. Da zusätzliche Actions-Kosten nicht ausgeschlossen
werden können, erhält der Entwicklungscommit `[skip ci]`; es wird kein neuer
Actions-Lauf angefordert. Die bestehende CI und sämtliche Merge-/Schutzregeln
bleiben unverändert. Ausgelassene erforderliche Checks bleiben ausstehend und
berechtigen zu keiner Freigabe. Der PR bleibt Draft und wird nicht gemergt.

Nächster Prüfschritt: die unveränderten Checks aus [testing.md](testing.md) mit der
bereits freigegebenen gepinnten Werkzeugkette auf einer nachweislich kostenfreien
Prüfressource ausführen. Es wird kein grüner Python-3.11-/Ruff-/Coverage-/CI-Lauf
aus den beiden erfolgreichen lokalen Testläufen abgeleitet.

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
