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
**217 Tests, kein Fehler, jeweils ein expliziter historischer Host-Skip**.
Der unveränderte Test `test_real_namespace_boundary_if_supported_by_host` überspringt
wegen nicht bereitstellbarer Namespaces. Das ist keine bestandene Isolationsprüfung.
Die neuen Hostprobes verwenden UNSUPPORTED-Beobachtungen statt Skip=PASS.
Die 14 neuen DT-007-Testmethoden enthalten zusätzlich zahlreiche parametrisierte
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
