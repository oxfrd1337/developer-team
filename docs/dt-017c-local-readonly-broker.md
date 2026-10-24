# DT-017C: lokaler Prepare-/Broker-Helper

Aktueller Stand DT-017E: [Schema 2 und sichere Diagnosen](dt-017e-safe-diagnostics.md).
Die folgenden Beschreibungen des bytegleichen/unveränderten DT-017B-Runners sind
historischer DT-017C-Stand. Der Diagnose-Runner ist geändert; seine bisherige
Produktions-SHA bleibt unverändert und blockiert reale Erhebungen bis zur separaten
unabhängigen Freigabe. `COLLECTED` bedeutet nur Erhebungsversuch; entscheidend ist
zusätzlich `provider_observations` (0–3). Keine Live-Freigabe.

Basis: `abb3eed41c8e056c930ae3f46bf7affad741afae` (DT-017B).
Der Helper ersetzt das manuelle Erstellen von FD-Pins, Identitaeten und Manifest.
Der bestehende DT-017B-Runner bleibt bytegleich. Der Helper prueft dessen SHA-256
und die exakte unabhaengig gepinnte Release-Identitaet. Abstammung von einer Basis
genuegt nicht. Ein installierter Wheel ohne passenden sauberen Git-Checkout und
externen Release-Pin reicht fuer die reale Erhebung nicht aus.

## Mac-Ablauf

Voraussetzungen: Python ab 3.11, ein lokaler Checkout dieses Branches sowie bereits
vorhandene Admin- und Canary-Dateien ausserhalb des Repositorys. Die beiden Dateien
muessen dir gehoeren, regulaere Dateien mit exakt `0600` sein und jeweils 1 bis
512 Byte enthalten. Inhalt: bestehender Key ohne Zeilenumbruch, entsprechend dem
Runner-Vertrag (ASCII-Buchstaben, Ziffern, `_`, `-`). Keine Secretwerte in Befehle,
Shell-Variablen, Chat oder Konfigurationen einfuegen. Vorhandene
Secret-Umgebungsvariablen blockieren die Erhebung.

1. Terminal im Repository-Ordner oeffnen. Sicherer Standardaufruf:

   ```sh
   python3 -B -m developer_team.provider_readonly_prepare
   ```

   Er zeigt nur fehlende nicht geheime Feldnamen. Kein Dateizugriff, kein FD,
   kein Secret-Read und kein Netzwerk. Exitcode 2 ist das beabsichtigte NO-GO.

2. Bereithalten: `project_id`, `service_account_ref`, `credential_ref` des
   Canary-Keys, separate Admin-Tracking-ID `admin_ref`, bestehende `agent_id`,
   separat freigegebenes `model`, `intent_id`, `idempotency_key`, `plan_digest`
   (64 Hexzeichen) und lokales `budget_cents` (1 bis 100) aus dem bestehenden
   DT-017-Plan. Keine Werte raten. Das Budgetfeld aendert keinen Spend-Wert.
   Ohne Saved Agent ist HALT erforderlich; hier wird keiner erstellt.

3. Der unabhaengige Reviewer muss vorher den unten beschriebenen nicht geheimen
   Release-Pin ausserhalb des Checkouts bereitstellen. Dieser PR und gruene CI
   stellen keine Release-Freigabe dar. Der Helper erstellt oder erneuert keinen Pin.
   Fuer die Erhebung einen separaten sauberen Release-Checkout ohne Bytecode-Caches,
   Build-, Coverage- oder sonstige untracked/ignored-Dateien verwenden. Python mit
   `-B` starten, damit keine neuen Bytecode-Caches geschrieben werden.

4. Nur fuer die ausdruecklich gewuenschte reale Read-only-Erhebung:

   ```sh
   python3 -B -m developer_team.provider_readonly_prepare --execute-real-readonly
   ```

   Der lokale Terminaldialog fragt die nicht geheimen Felder in dieser Reihenfolge
   ab. Eingaben werden vorsorglich nicht angezeigt. Leer beendet mit HALT.
   Danach werden getrennt der absolute Dateipfad fuer Admin (mit Tracking-ID)
   und Canary (mit Credential-Referenz) abgefragt. Auch diese Pfade erscheinen
   nicht auf dem Bildschirm. Hier nur vorhandene Dateipfade eingeben, niemals
   einen Key. Die Rollenzuordnung muss vor Ort bekannt und korrekt sein.
   Symlinks in allen Pfadteilen sind gesperrt; auf macOS daher beispielsweise
   `/private/tmp/...` statt `/tmp/...` verwenden. Private dauerhafte Dateien
   ausserhalb des Checkouts sind vorzuziehen.

stdout enthaelt genau einen sanitisierten JSON-Report; Dialoge laufen ausschliesslich
ueber `/dev/tty`, niemals stdin. Keine Pfade, IDs, Exceptiontexte oder Rohantworten
werden in Reports kopiert. Nicht geheime Bindungen koennen alternativ mit den
gleichnamigen CLI-Optionen wie `--project-id` uebergeben werden. Secretpfad- und
Secretwert-Optionen sowie JSON-Eingaben gibt es nicht. Nichtinteraktive Aufrufer
muessen alle Bindungen und bereits geoeffnete, rollenrichtig zugeordnete private
Read-only-FDs mit `--admin-fd` und `--canary-fd` liefern. Standard-FDs sind gesperrt.
Die urspruenglichen FDs bleiben Eigentum des Aufrufers; eigene Duplikate werden
geschlossen. Auch diese Variante benoetigt den expliziten Schalter.

## Vertrauensgrenze und Bereinigung

### Exakte Release-Bindung

Der feste Pin liegt unter `.config/developer-team/readonly-release.json` im durch
die Betriebssystem-Benutzerdatenbank bestimmten Home-Verzeichnis. `HOME`, XDG-,
Git- oder andere Umgebungsvariablen koennen ihn nicht auswaehlen. Er muss ausserhalb
des Repositorys liegen, eine eigene regulaere Datei mit exakt `0400` sein und darf
keine Symlinks im Pfad haben. Das Schema hat exakt drei nicht geheime Felder:
`commit` (40 Hexzeichen), `tree` (40 Hexzeichen), `inventory_sha256` (64 Hexzeichen).
Nur eine unabhaengig gepruefte Release-Identitaet darf dort installiert werden.
Es gibt keine CLI-/env-Freigabeoption und keinen automatischen Schreibpfad.

Reproduzierbare Berechnung fuer den Reviewer, ausschliesslich im bereits geprueften
sauberen Checkout, ohne Dateien zu schreiben:

```sh
python3 -B -c 'import json; from pathlib import Path; from developer_team.provider_readonly_release import _inventory; print(json.dumps(_inventory(Path.cwd())[0], sort_keys=True))'
```

Die Berechnung allein ist **keine** unabhaengige Freigabe. Die Ausgabe darf nicht
ungeprueft als Approval installiert werden. Fuer diesen Draft wird kein echter
Release-Pin erstellt; der reale Modus bleibt bis zur unabhaengigen Bereitstellung
gesperrt. Das Pin-Provisioning und der vertrauenswuerdige lokale Python-/Git-/OS-
Startpunkt liegen ausserhalb der Selbstattestierung dieses Helpers. Wer bereits
beliebigen Code im Operatorprozess oder dessen Trust Anchor ersetzen kann, kann
nicht durch einen im selben Prozess laufenden Python-Selbsttest abgewehrt werden.

Der Inventarhash ist SHA-256 des UTF-8-JSON-Arrays in Git-ls-tree-Reihenfolge mit
kompakten Separatoren und je `[Pfad, Git-Modus, SHA256(Dateibytes)]`. Er umfasst
**alle** getrackten Dateien, insbesondere Broker, Integritaetspruefer, Collector,
Scope, HTTPS-, Credential- und Contract-Module. Es gibt keine sich selbst
ausschliessende ausfuehrbare Datei. Jeder Blob wird zusaetzlich mit seinem Git-Objekt
verglichen. Index und getrackter Arbeitsbaum muessen exakt HEAD entsprechen;
direkte Dateihashes erkennen auch `assume-unchanged`, `skip-worktree` und veraltete
Stat-Caches. Untracked und ignored Dateien werden ebenfalls gesperrt, einschliesslich
Bytecode, nativer Erweiterungen und Import-Hooks. Ein spaeterer Commit, auch ein
leerer Commit mit identischem Tree, wird ohne neuen unabhaengigen Pin abgelehnt.

Die Pruefung erfolgt vor Secret-Auswahl/FD-Verwendung und erneut direkt vor jedem
Credential-Oeffnen bzw. Duplizieren. Vor dem Runnerstart wird nochmals geprueft und
nur verifizierter Python-Quelltext in ein privates temporaeres Verzeichnis kopiert.
Der unveraenderte Runner startet mit `-I -S -B` aus dieser Kopie, ohne Site-Packages,
PYTHONPATH oder Checkout-Bytecode. Nachtraegliche Worktree-Aenderungen werden nicht
in den Kindprozess importiert. Die Quellkopie wird auch bei Fehlern entfernt.

Der Helper liest keine Secretbytes. Er prueft Owner, exakt `0600`, regulaeren
Dateityp, Groesse und Read-only-Zugriffsmodus, lehnt Symlinks in allen Pfadteilen
ab und vergleicht die Dateisnapshots vor der Uebergabe erneut. Identische Dateien
einschliesslich Hardlinks fuer beide Rollen sind gesperrt. Pins enthalten nur
Device, Inode, Groesse, mtime und ctime. Immutable Identitaeten haben getrennte
Rollenhandles, dieselbe Planbindung und maximal 300 Sekunden Gueltigkeit.
Lokale Rollenzuordnung beweist keine Providerberechtigung. Falsche Konten, Owners
oder fehlende Saved Agents koennen nur durch die bestehenden GETs geprueft werden.
Ein nicht vorhandener Agent ergibt ein fehlendes Gate, keine automatische
Erstellung. `COLLECTED` allein bedeutet keinen PASS.

Das temporaere Manifest liegt in einem privaten `0700`-Verzeichnis, hat `0600`
und enthaelt nur nicht geheime Bindungen, Identitaeten und Pins. Nur die beiden
Secret-FDs werden an den unveraenderten Runner vererbt. stdin ist geschlossen,
stderr wird verworfen und stdout strikt auf das feste Reportschema reduziert.
Nach Abschluss, Fehler, Timeout oder KeyboardInterrupt werden Manifest,
Verzeichnis und eigene FDs entfernt. Bei SIGKILL oder Stromausfall kann das
ausschliesslich nicht geheime Manifest verbleiben; seine Lease laeuft nach
maximal 300 Sekunden ab. Sichere physische Loeschung wird nicht behauptet.

Die vorhandene Proxy-/CA-Konfiguration bleibt erhalten. `CI`, `GITHUB_ACTIONS`
und `DT_PROVIDER_OFFLINE` sperren durch Anwesenheit vor der Secret-Auswahl.
Secret-/Key-/Credential-/Password-/Token-Variablen der Namespaces `OPENAI_`,
`DT_`, `ADMIN_`, `CANARY_` sperren ebenfalls, ohne ihre Werte zu lesen.
Kein Keychain- oder Password-Manager-Zugriff.

## Tests und verbleibende Blocker

```sh
DT_PROVIDER_OFFLINE=1 python3 -m unittest tests.test_provider_readonly_prepare -v
DT_PROVIDER_OFFLINE=1 python3 -m unittest discover -s tests -t . -v
```

Tests verwenden eigene synthetische Dateien und simulierte Providerantworten.
Ein echter Kindprozess prueft nur Offline-Sperre und FD-Vererbung. Die bestehenden
DT-017B-/DT-017A-Tests bleiben unveraendert aktiv. Actions prueft weiterhin Python
3.11 bis 3.13, Ruff, Format, Coverage, Build, Smoke und Checkpoint mit
`DT_PROVIDER_OFFLINE=1`. Es wurden keine realen Provider-Reads ausgefuehrt.

Live-Blocker bleiben: unabhaengig bereitgestellter exakter externer Release-Pin,
reale lokale Credentials und bestaetigte Rollenbindung,
Saved Agent und genehmigte Plan-/Modellbindung, reale Read-only-Account-Evidence,
unabhaengige Scope-Evidence und Verifier, aktueller Providervertrag,
Secret-Store- und Realtransport-Attestation, Session-Environment-Nachweis,
dauerhaftes Journal, exklusiver Single-Canary-Grant und frische getrennte
Create-/Submit-Freigaben. Der Helper stellt diese Nachweise nicht selbst aus.
Unabhaengiger Review und manueller Merge bleiben erforderlich.

Immer: **`real_submissions=0`, `LIVE=NO-GO`, `live_authorized=false`.**
Keine Provider-Mutationen, Session-Erstellung, Message-Submission, Cancel,
Agent-Erstellung, Key-/Spend-Aenderung, GitHub-Schreiboperation aus dem Helper,
Merge oder Deployment.

**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**
