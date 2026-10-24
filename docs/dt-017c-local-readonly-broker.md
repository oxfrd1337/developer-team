# DT-017C: lokaler Prepare-/Broker-Helper

Basis: `abb3eed41c8e056c930ae3f46bf7affad741afae` (DT-017B).
Der Helper ersetzt das manuelle Erstellen von FD-Pins, Identitaeten und Manifest.
Der bestehende DT-017B-Runner bleibt bytegleich. Der Helper prueft dessen SHA-256
und die Git-Abstammung vor jedem Erhebungsversuch. Ein installierter Wheel ohne
den passenden Git-Checkout reicht fuer die reale Erhebung nicht aus.

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
   python3 -m developer_team.provider_readonly_prepare
   ```

   Er zeigt nur fehlende nicht geheime Feldnamen. Kein Dateizugriff, kein FD,
   kein Secret-Read und kein Netzwerk. Exitcode 2 ist das beabsichtigte NO-GO.

2. Bereithalten: `project_id`, `service_account_ref`, `credential_ref` des
   Canary-Keys, separate Admin-Tracking-ID `admin_ref`, bestehende `agent_id`,
   separat freigegebenes `model`, `intent_id`, `idempotency_key`, `plan_digest`
   (64 Hexzeichen) und lokales `budget_cents` (1 bis 100) aus dem bestehenden
   DT-017-Plan. Keine Werte raten. Das Budgetfeld aendert keinen Spend-Wert.
   Ohne Saved Agent ist HALT erforderlich; hier wird keiner erstellt.

3. Nur fuer die ausdruecklich gewuenschte reale Read-only-Erhebung:

   ```sh
   python3 -m developer_team.provider_readonly_prepare --execute-real-readonly
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

Live-Blocker bleiben: reale lokale Credentials und bestaetigte Rollenbindung,
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
