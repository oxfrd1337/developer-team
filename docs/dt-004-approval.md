# DT-004 · Freigabevorlage und Betreiberrezept

**Aktuell NICHT freigegeben. Erst nach Ausfüllen und Prüfung aller Pflichtangaben
entscheidungsreif. Diese Datei ist keine vom Programm ladbare Freigabe.**
Ein Merge dieses PRs, CI-Erfolg oder DT-003-Simulation ersetzt die Entscheidung nicht.

## 1. Zunächst nur lokal vorbereiten

Manuell geprüften Controllercommit sauber auf einem vorhandenen Linux-Rechner
auschecken: Python 3.11+, Git, `gh`, Codex CLI **0.163.0**, `bwrap` und verwendbare
unprivilegierte Namensräume. Fehlende Werkzeuge sind Voraussetzungen und werden
hier nicht automatisch installiert. Kein neuer Server oder Dienst erforderlich.

```sh
umask 077
python -m developer_team validate examples/project.pilot.toml
python -m developer_team probe-codex
python -m developer_team pilot-plan --output /absoluter/privater/dt-004-pilot
```

Zielpfad leer/neu, außerhalb des Repositories und dauerhaft auf demselben Rechner.
`preparation.json` liefert UUID und echte Controller-/Konfigurations-/Anforderungshashes
für die Freigabe. Noch keine Cloud-Betreiberfunktion aufrufen. Sandbox lokal prüfen:

```python
from pathlib import Path
from developer_team.pilot_runner import PilotCommandRunner

root = Path('/absoluter/privater/dt-004-pilot')
PilotCommandRunner(root / 'checks').require_available(root / 'project')
```

Zusätzlich muss der echte Grenztest auf dem Betreiberhost ohne Skip bestehen:

```sh
python -m unittest tests.test_supervised_pilot.PilotIsolationTests -v
```

Er prüft Zugriff auf eine künstliche Controllerdatei/Umgebungscredential,
Source-Schreibzugriff und Netzwerk. Ein Skip ist **kein Live-Isolationsnachweis**.

## 2. Pflichtangaben außerhalb des Repositorys festhalten

| Angabe | Tatsächlicher Wert / Beleg |
| --- | --- |
| Betreiber/Freigebender, UTC-Zeit, Freigabereferenz | AUSFÜLLEN |
| Repository | `oxfrd1337/developer-team` |
| Geprüfte Controller-SHA, Pilot-UUID, beide Hashes | Exakt aus `preparation.json` |
| Bestehender Linux-Host und absoluter Sessionpfad | AUSFÜLLEN |
| Privater dauerhafter Datenträger; kein Rollback-/Artefakt-Restore | Prüfreferenz AUSFÜLLEN |
| CLI 0.163.0, boolescher ChatGPT-Loginstatus, Konto/Workspace | Beleg AUSFÜLLEN; keine Tokens |
| Cloud-Umgebung Planung/Architektur | Echte ID AUSFÜLLEN |
| Cloud-Umgebung Entwicklung | Andere echte ID AUSFÜLLEN |
| Cloud-Umgebung QA | Dritte echte ID AUSFÜLLEN |
| Cloud-Umgebung Security | Vierte echte ID AUSFÜLLEN |
| Tatsächliche Cloud-Dateirechte, Credential-/Netzisolation, Repositorybindung aller Rollen | Beleg AUSFÜLLEN; IDs/Prompts reichen nicht |
| Lokale Sandbox | Hostbeleg mit erfolgreichem Grenztest ohne Skip AUSFÜLLEN |
| Controller-GitHub-/Git-Zugang | Lesen und neue Taskrefs nur hier, keine Schutzänderung/Mergefreigabe |
| Kontingent/Plan, bestehende Credits, kein automatischer Nachkauf | Im Konto prüfen, Zeitpunkt/Beleg AUSFÜLLEN; keine Käufe |
| Ablaufzeitpunkt | Festen UTC-Zeitpunkt und Unix-Zeitstempel AUSFÜLLEN |
| Nutzungsgrenzen | 8 Tasks, 1 Versuch, 900 s/Task, 3600 s gesamt, 60 Polls/Task, Abstand 10 s, 3 Lesefehler |
| Korrekturen | Maximal 1 pro Fehlerklasse; Taskbudget kann früher stoppen |
| Stopp-/Recoveryverantwortlicher | Name, Erreichbarkeit und Verfahren AUSFÜLLEN |
| Aufbewahrung und manuelle Bereinigung lokaler Artefakte/Taskrefs | Betreiber und Frist AUSFÜLLEN |

Cloudzugriff auf jede ausgewählte Umgebung vorher nur lesend prüfen, etwa
`codex cloud list --json --env ECHTE_ID --limit 1`. Keine fremden Umgebungen auswählen,
keine Taskdaten oder Credentials ins Repository/Freigabetext kopieren. Repositorybindung,
Setupskripte und effektive Rechte zusätzlich in der Cloud-Oberfläche prüfen. Eine leere
erfolgreiche Taskliste allein beweist weder Checkoutzugriff noch Isolation.

## 3. Konkreter Freigabetext

> Ich gebe genau einen beaufsichtigten Codex-Cloud-Piloten mit den oben vollständig
> eingetragenen Bindungen, Umgebungen, Fristen und Nutzungsgrenzen frei. Verwendet wird
> ausschließlich die unveränderte Anforderung `pilot_project/requirement.txt` des
> genannten Controllercommits. Der Entwickler darf ausschließlich
> `pilot_project/calculator.py`, `pilot_project/tests/test_calculator.py` und
> `pilot_project/usage.md` bearbeiten. Planung, QA und Security dürfen keinen Source
> ändern. Als technische Exportausnahme darf jeder isolierte Task ausschließlich
> `.developer-team/cloud-result.json` neu schreiben; sie wird niemals als Source
> übernommen. Der Controller darf neue laufgebundene `dt/cloud/UUID/...`-Taskrefs nur
> in `oxfrd1337/developer-team` erzeugen und validierte Ergebnisse lokal übernehmen.
> Vier getrennte Cloud-Aufträge und echte isolierte Python-Tests sind vorgesehen;
> Korrekturen benötigen innerhalb derselben Obergrenzen weitere Aufträge. Tatsächliche
> Rollen-/Dateirechte und Credential-Isolation sind geprüft und belegt. Bestehendes
> freigegebenes Kontingent darf genutzt werden; neue Dienste, Server, Schlüssel,
> Credits oder Nachkäufe sind nicht freigegeben. Kein automatischer Merge, kein
> produktives Deployment, keine anderen Repositories, keine Schutzregeländerungen
> und keine produktive Erstfreigabe. Bei unklarem Submit, Zustandsverlust, fehlenden
> Belegen oder Fristüberschreitung wird angehalten und manuell geklärt. Angenommene
> Remote-Tasks können nach Controllerstopp weiter Kontingent verbrauchen; eine
> automatische Remote-Abbruchgarantie besteht nicht.
>
> Entscheidung: AUSFÜLLEN · Name: AUSFÜLLEN · Datum: AUSFÜLLEN · Referenz: AUSFÜLLEN

Ein unbekannter Pflichtbeleg lässt die Freigabe offen. Eine Bestätigung ersetzt
keinen technischen Nachweis der geforderten Cloud-Isolation.

## 4. Erst NACH ausdrücklicher Freigabe ausführen

Folgendes als privates Betreiberskript außerhalb von Repository und Agentencheckout
speichern. Keine Anmeldetokens; die bestehenden CLI-Anmeldungen werden genutzt.
Die freigegebenen Werte einmal fest einsetzen. Den Ablaufzeitpunkt bei Wiederaufnahme
niemals aus der aktuellen Zeit neu berechnen. Ein neuer Sessionpfad/eine neue UUID
ist keine Wiederaufnahme. Die Platzhalter sind absichtlich nicht ausführbar:

```python
from pathlib import Path
from developer_team.adapters.cloud_contracts import CloudApproval
from developer_team.authority import ProjectGrant
from developer_team.models import Role
from developer_team.supervised_pilot import PilotReadiness, execute_supervised

root = Path('/absoluter/privater/dt-004-pilot')
approval = CloudApproval(
    run_id='APPROVED_PILOT_UUID',
    repository='oxfrd1337/developer-team',
    config_digest='APPROVED_CONFIG_DIGEST',
    approved_by='APPROVED_OPERATOR_AND_REFERENCE',
    expires_at=APPROVED_UNIX_TIMESTAMP,
    max_tasks=8, task_timeout_seconds=900, runtime_seconds=3600,
    max_polls=60, poll_interval_seconds=10, max_read_errors=3,
)
grant = ProjectGrant(
    project_id='dt-003-pilot', repository=approval.repository,
    config_digest=approval.config_digest,
    capabilities=frozenset({'read', 'develop', 'cloud_submit', 'cloud_publish', 'pull_request'}),
    approved_by=approval.approved_by,
    cloud_environments=(
        (Role.ORCHESTRATOR, 'APPROVED_PLANNING_ENV'),
        (Role.DEVELOPER, 'APPROVED_DEVELOPER_ENV'),
        (Role.QA, 'APPROVED_QA_ENV'),
        (Role.SECURITY, 'APPROVED_SECURITY_ENV'),
    ),
)
readiness = PilotReadiness(
    controller_sha='APPROVED_CONTROLLER_SHA',
    durable_storage_review='ACTUAL_STORAGE_INSPECTION_REFERENCE',
    cloud_role_isolation_review='ACTUAL_CLOUD_ISOLATION_INSPECTION_REFERENCE',
    account_quota_review='ACTUAL_ACCOUNT_QUOTA_INSPECTION_REFERENCE',
)
report = execute_supervised(root, approval=approval, grant=grant, readiness=readiness)
print(report['run']['id'], report['run']['stage'], report['run']['status'])
```

Aus dem unveränderten freigegebenen Controllercheckout starten. Skript/Zustandsdaten
bleiben für Agenten unzugänglich. Der erste Aufruf kann sofort einen echten
Planungsauftrag und eine Taskref erzeugen. **Für DT-004 wurde dieses Rezept nicht
ausgeführt.** Vorher Freigabe und sämtliche Pflichtangaben prüfen.

Nach Freigabe beispielsweise aus diesem Checkout mit Python über stdin starten,
damit genau dessen `developer_team` importiert wird:

```sh
python - < /absoluter/privater/dt-004-operator.py
```

Bei `paused` mindestens zehn Sekunden warten und dasselbe Skript einmal erneut
aufrufen. Keine parallelen Bediener, automatischen Shellschleifen oder erneute
Vorbereitung. Der vorhandene Lock verweigert konkurrierende Bedienung. Lesende Einsicht:

```sh
python -m developer_team show \
  --state /absoluter/privater/dt-004-pilot/state.sqlite3 --run-id APPROVED_PILOT_UUID
```

Bei `blocked` beide bestandenen Python-Checks, eigene QA-/Security-IDs/Umgebungen,
Commit-/Kriterienbindungen, erlaubte Dateigrenzen und Merge-Sperre manuell prüfen.
Ein erfolgreicher Live-Pilot bleibt ohne unabhängige Cloud-Attestierung und ohne
produktive Mergefreigabe.

Bei `escalated`/`interrupted`, unklarem Submit oder verlorenen Daten nicht neu starten:
bekannte Task-IDs/Taskrefs lesen, laufende Tasks kontrollieren, Teilimports untersuchen.
Kein Force-/Reset-/Resubmitbefehl. Fristen nicht verlängern, keine bereits beauftragten
Jobs nachbauen. Nach Abschluss Belege manuell prüfen und Taskrefs erst nach Inspektion
manuell bereinigen. Kein Pilotresultat automatisch mergen.
