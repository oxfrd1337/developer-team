# DT-007 – Validierungsprotokoll

## Herkunft und Basis

Entwicklungsbranch: `dt-007/offline-security-foundation`, Refs #8.
GitHub-`main` und gemergter PR #7 wurden über den verbundenen GitHub-Connector
geprüft: `09a1b0c7d0a43d226973a9990b552dd766287381`, Tree
`dfcda52f14c0a3a7bb4be8674ce8d8a676980b08`. Die bereitgestellte lokale Kopie
stand zunächst auf DT-005. Die elf geänderten DT-006-Dateien und der signierte
Git-Commit wurden über den Connector gelesen und lokal bytegenau wiederhergestellt;
Commit-SHA und vollständiger Git-Tree stimmen mit GitHub überein. Kein fremdes
Repository, keine Netzpolicyänderung und kein unsicherer Git-Fallback.

Historische Codespace-Messung, getrennt vom aktuellen Worker:
[Original](https://github.com/oxfrd1337/developer-team/issues/6#issuecomment-6334230368)
und [Auswertung](https://github.com/oxfrd1337/developer-team/issues/6#issuecomment-6334248837),
am 22.10.2026 gelesen. `97 PASS / 5 UNSUPPORTED / 0 FAIL`, NO-GO, `ai_calls=0`,
alle vier Rollen UID 1000; Probehash
`fc38eb41ee8950df267d423184ea4409e16d0addfc3a6e73d8cc1bcc98819eb0`.
Keine neue Messung dieses Codespaces und keine unabhängige Attestierung.

## Aktuelle Arbeitsumgebung und exakte Befehle

Verwalteter Codex-Worker, Linux `6.18.55`, UID 1000, Python `3.12.14` und
`/usr/bin/python3.13` (3.13.5). Kein GitHub Codespace. Netzwerkpolicy-Snapshot v1:
keine externen HTTP-/TCP-Ziele, kein VPN. Der Runtime-Status meldet keine Secrets
oder Outbound-Identitäten und keinen nachgewiesenen Enforcement-Zustand. Es wird
keine Aussage über Internet- oder Modell-Egress aus diesem Status abgeleitet.

```sh
codex --version
codex exec --help
codex app-server --help
cat /proc/self/cgroup
cat /sys/fs/cgroup/cgroup.controllers
test -w /sys/fs/cgroup/cgroup.subtree_control
mount | rg cgroup
python -m unittest discover -s tests -t . -v
/usr/bin/python3.13 -m unittest discover -s tests -t . -v
python -m unittest tests.test_readiness tests.test_boundaries tests.test_exec -v
python -m developer_team.boundary_probe > /workspace/work/dt006-current-worker.json
python -m developer_team.readiness_probe > /workspace/work/dt007-probes.json
python -m developer_team validate examples/project.synthetic.toml
python -m developer_team validate examples/project.pilot.toml
python -m developer_team demo --scenario test-fix --output /workspace/work/dt007-smoke
python -m ruff check developer_team tests
python -m ruff format --check --diff developer_team tests
python -m coverage run --branch -m unittest discover -s tests -t . -v
python -m build --no-isolation
```

Die drei Codex-Aufrufe zeigen nur Version/Hilfe: `codex-cli 0.163.0`.
Kein Agent, Modellrequest, App-Server oder Login wird gestartet. Die Hilfe warnt,
dass PATH-Aliase im lesenden Dateisystem nicht angelegt werden können. Entscheidend:
`--ignore-user-config` belässt die Authentisierung über `CODEX_HOME`.
Die experimentellen App-Server-Optionen sind kein verifizierter externer Tool-Split.

`/proc/self/cgroup` meldet `0::/`. cgroup v2 listet CPU-/RAM-/PID-Controller,
ist aber `ro` gemountet; `test -w` ist negativ. Keine cgroup wurde erstellt oder
verändert. Delegation und externer Supervisor bleiben UNSUPPORTED.

## Lokale Ergebnisse und Grenzen

Die vollständige Suite wurde unter beiden verfügbaren Pythonversionen ausgeführt:
**222 Tests (221 PASS / 1 expliziter historischer Host-Skip), kein Fehler**.
Der unveränderte Test `test_real_namespace_boundary_if_supported_by_host` überspringt
wegen nicht bereitstellbarer Namespaces. Das ist keine bestandene Isolationsprüfung.
Die neuen Hostprobes verwenden UNSUPPORTED-Beobachtungen statt Skip=PASS.
Die jetzt 19 DT-007-Testmethoden enthalten zusätzlich zahlreiche parametrisierte
Negativfälle und konkurrierende Reservierungen; diese Fallzahl ist keine Testzahl.

Ein erster Lauf ohne Socketrechte scheiterte im bestehenden DT-006-Positivkontrolltest
an `socket: Operation not permitted`; ein bestehender Hosttest wurde übersprungen.
Für die ausdrücklich beauftragten eigenen Loopback-/Socket-Canaries wurden danach
nur die Ausführungsrechte des Shellwerkzeugs für lokale Netzwerkoperationen benutzt.
Die Zielhostpolicy, Authentisierung, Firewall und Sysctls wurden nicht verändert;
kein externer Host wurde kontaktiert. Unter diesen Bedingungen bestanden die
Positivkontrollen und beide vollständigen Suiten. Die Namespacevoraussetzung
scheitert weiterhin: `bwrap: setting up uid map: Read-only file system`.

| Prüfung | Tatsächlich beobachtet |
| --- | --- |
| Typisierter Diagnosevertrag | Exakte Felder, Typen, Digests, Zeiten; fehlende/mehrdeutige Beobachtungen und falsche Bindungen blockieren. Vollständiger Fake-PASS bleibt ohne unabhängige Quelle NO-GO. |
| Brokervertrag | Künstliche gebundene Identität einmal erfolgreich; falscher Client, Rolle, Run, Config, Ablauf, Token, Replay, Refresh/Proxy abgewiesen. Keine produktive Authentisierung. |
| Lease-/Journalvertrag | Konkurrenz erlaubt exakt einen fsync-gesicherten uncertain-Intent; Restart, Teilfehler, Symlink und falsche Gesamtbudgets geben keinen Start frei. |
| Reviewquellen | Beide Kopien an Controller-HEAD/Tree/Content gebunden; persistente Source-/Git-/Symlink-/Hardlink-Manipulation abgewiesen. Wiederhergestellte Mutation wird ausdrücklich nicht erkannt. |
| Prozessprobe | Eigenes detached Child überlebt SIGKILL seines Controllers; pidfd-Harnesscleanup und direkte Timeoutprobe erfolgreich. Externes Cleanup und aggregierte Grenzen UNSUPPORTED. |
| Credential-/Netzprobe | Künstliche Datei-/Env-/FD-Positivkontrolle und acht eigene Listener erfolgreich. Negative Namespaceversuche UNSUPPORTED; kein produktiver Broker-/Egressbeleg. |
| Gateway / Engine / Freigaben | Fake-PASS, JSON/SQLite/Env/TOML/CI/Syntheticclaims starten kein Popen. Vorhandene Cloud-/Exec-/Grant-/Release-/Schutztests unverändert ausgeführt. |
| Beispiele / Smoke | Beide Konfigurationen gültig; `test-fix` endet erwartungsgemäß blocked, ein Testfix, kein echter Remoteeingriff und kein Merge. |

Ruff, Coverage und Build-Frontend fehlen lokal (`No module named …`). Sie wurden
nicht aus dem gesperrten Netz nachinstalliert. Python 3.11 fehlt ebenfalls.
Ein zusätzlicher lokaler Wheel-/SDist-Build über den vorhandenen Setuptools-Backend
funktionierte; das ersetzt weder das gepinnte Frontend noch CI.

Der endgültige nichtautoritative Worker-Probebericht und die Quellhashes werden
neben diesem Protokoll gespeichert. Der vollständige GitHub-CI-Nachweis wird an den
**endgültigen PR-HEAD** in der Draft-PR-Beschreibung gebunden; ein Dokument kann
seinen eigenen Commit-SHA nicht inhaltlich referenzieren, ohne ihn zu verändern.

## Vollständige GitHub-CI und Kostenrahmen

Beide vorhandenen Workflows bleiben bytegleich zur Basis. Kein `[skip ci]`.
Der Entwicklungsauftrag autorisiert den Versuch der bestehenden CI; es gibt keinen
verifizierten kontoweiten Restminuten-/Speichernachweis und keine Kostengarantie.
Keine neuen Runnerklassen, kostenpflichtigen Bestellungen, Billing-/Budgetänderungen
oder Umgehungen einer Kontingentsperre. Sechs vorhandene Linux-Jobs mit insgesamt
45 konfigurierten Timeout-Jobminuten je regulärem Lauf.

Pflichtnachweis für denselben endgültigen PR-HEAD: Python **3.11/3.12/3.13**,
Ruff inklusive Securityregeln, Ruff-Format, gesamte Suite mit Branchmessung
**≥80 %**, Wheel/SDist und Smoke; außerdem CLI-Hilfeprobe ohne Login/Tasks,
Testadapter-Checkpoint und Wiederaufnahme auf frischem Runner.

In der PR-Beschreibung werden SHA, Run-URL, tatsächliche Job-/Schrittergebnisse,
Testzahlen, Host-Skips, Coverage und gegebenenfalls Fehlversuche dokumentiert.
Bis zur echten Ausführung gelten diese Checks als ausstehend, nicht bestanden.
CI-Grün wäre weiterhin kein Host-, Credential-, Supervisor- oder Live-Nachweis.

## Unverändertes Betriebsresultat

**Live NO-GO.** Alle fünf harten Kontrollen sowie unveränderliche Live-Reviews und
unabhängige Attestierung bleiben UNSUPPORTED. Keine echten Agenten, Live-Freigabe,
Käufe, Merges oder Deployments. Die konkrete nächste Betreiberentscheidung und
Alternativen mit Rechte-/Kostenfolgen stehen in [DT-007](dt-007.md).

## Gesicherte Worker-Diagnose und Quellhashes

[Probebericht](dt-007-probe-report.json), erhoben `2026-10-22T07:46:18.271590+00:00`: **13 PASS / 19 UNSUPPORTED / 0 FAIL**, Gesamtentscheidung NO-GO, `ai_calls=0`.
PASS umfasst nur positive Canaries und synthetische Prozessbeobachtungen, keine bestandene Live-Grenze. Der Bericht ist kein HostReadinessReport-Import und keine Autorität.

| Quelle | SHA-256 |
| --- | --- |
| `developer_team/boundary_contracts.py` | `1ff3777827740b29fe9723107c4ffcb350249dadc1061c337daeb71f4153a996` |
| `developer_team/host_readiness.py` | `505b1595099eaccaa7ffcd9bd51ccb1674f59aa45724a8a32e2c147f7e17bd3f` |
| `developer_team/readiness_probe.py` | `ca9dd15acb13ff1bcab4c9383cf9e5fe253b28e5d11998e148fcfc6a533b1aeb` |
| `docs/dt-007-probe-report.json` | `914846b81ab0670cdcca13ee4e5fec46c1b991968181f7060d5b8add9a031241` |

## CI-Zwischenstände

[Run 39737020504](https://github.com/oxfrd1337/developer-team/actions/runs/39737020504), HEAD `b84f02a5e6a5c97c601ba0677eca1ce30f5a8976`: drei Qualitätsjobs scheiterten an zwei Ruff-Befunden (S105 für ausdrücklich künstliches Canaryliteral, UP031). Korrigiert durch neutrale Canaryvariable und f-String, keine Regelunterdrückung. Drei übrige Jobs erfolgreich.

[Run 39737156705](https://github.com/oxfrd1337/developer-team/actions/runs/39737156705), HEAD `c878bff8551da7a09b92c7f5ab93e84b642e4fe7`: Lint erfolgreich, Qualitätsjobs stoppen am Ruff-Formatcheck. Den tatsächlichen Formatter-Diff übernommen; keine fachliche Teständerung. Drei übrige Jobs erfolgreich. Beide Läufe sind ausdrücklich keine vollständigen grünen Nachweise.

## Reviewkorrektur: stabile Prozessidentität vor SIGKILL

Ausgangspunkt dieses Reviews ist PR-HEAD
`8e1f02dd2016406c5fa24346f3c3eadbfba7a00f` und der
[Review vom 22.10.2026](https://github.com/oxfrd1337/developer-team/pull/9#pullrequestreview-5610658818)
einschließlich [Inlinekommentar](https://github.com/oxfrd1337/developer-team/pull/9#discussion_r4345646358).
Der ursprüngliche `finally`-Pfad konnte einen unverifizierten pidfd signalisieren;
der zuvor dokumentierte Cleanup war für diesen Fehlerfall nicht sicher.

Jetzt öffnet ausschließlich der synthetische Controller den pidfd seines eigenen,
noch nicht abgeholten `Popen`-Kindes. Er überträgt den kernelgebundenen Handle per
SCM_RIGHTS über ein nur an diesen Controller vererbtes Socketpaar. Der Harness
öffnet keinen Prozess anhand einer gemeldeten PID. Vor SIGKILL bindet er Startzeit,
Parent, Session, Zustand, FD-PID, Liveness und lebenden Controller; erst danach
setzt er die Cleanup-Berechtigung für diesen eigenen Handle. Unbestätigte Handles
werden nur geschlossen und bleiben UNSUPPORTED. Kein Signal-/Blind-Kill-Fallback.

Zusätzliche modellfreie Tests:

```sh
python -m unittest tests.test_readiness.SupervisorIdentityTests -v
python -m unittest tests.test_readiness -v
python -m unittest discover -s tests -t . -v
/usr/bin/python3.13 -m unittest discover -s tests -t . -v
python -m developer_team.readiness_probe > docs/dt-007-probe-report.json
```

Fünf neue Testmethoden prüfen insgesamt 28 parametrisierte Negativvarianten sowie
positive Vertrags-/eigene Prozessläufe: falsche Parent-/Session-/Prozess-ID,
unpassende bzw. wechselnde Startzeit (PID-Reuse-Simulation), Zombie/Endzustand,
fehlende, ungültige oder zwischenzeitlich verschwundene `/proc`-Daten, falsche,
fehlende oder mehrdeutige FD-PID, lebend gemeldeten bereits beendeten pidfd,
Controllerverlust und fehlschlagende Sessionabfrage. Ungültige, mehrdeutige und
trunkierte SCM_RIGHTS-/JSON-Übertragungen schließen alle empfangenen Handles.
Für unverifizierte Ziele ist `pidfd_send_signal.assert_not_called()` Pflicht;
zusätzlich werden FD-Schließen und ausbleibender Controller-SIGKILL geprüft.

Der echte eigene Child-Lauf bestätigt weiterhin Überleben nach Controller-SIGKILL
und anschließenden verifizierten Harness-Cleanup. Externe Supervisorgrenze und
alle übrigen Live-Kontrollen bleiben UNSUPPORTED / NO-GO. Der erneuerte Probebericht
oben bindet exakt den aktuellen Probequellhash. Die bisherigen CI-Läufe sind nur
historische Nachweise; der neue HEAD, alle sechs Jobs und deren echte Ergebnisse
werden in der aktualisierten Beschreibung desselben Draft-PR #9 festgehalten.
