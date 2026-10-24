# DT-017E: sichere Diagnose fehlender Provider-Evidence

Issue #44, Basis `e230ddb42fcfad624221a6ed31808b03c7ca6816`.
Der historische all-MISSING-Bericht beweist keine konkrete Ursache. Erst ein
separat autorisierter Erhebungsversuch mit dieser Diagnoseversion kann sichere
Fehlerklassen und die betroffene zugelassene Operation unterscheiden.

## Diagnosevertrag

Das Runner-/Broker-Reportschema wechselt von **1 auf 2**: Die zusätzlichen festen
Felder `provider_diagnostics` und `provider_observations` müssen atomar durch den
Broker-Sanitizer geprüft werden. Version 1 wird abgelehnt; unbekannte Felder,
Werte, falsche Typen und widersprüchliche PASS-/Zählerangaben werden gesperrt.
Das Eingabemanifest und die Rollen-/FD-/Release-Verträge bleiben unverändert.

`provider_diagnostics` enthält exakt drei Gates. Jedes enthält ausschließlich
`stage` und `code` aus dem geschlossenen Vokabular. Bei einem Fehler stoppt das
betroffene Gate an dieser Stufe; andere Gates werden wie bisher unabhängig
versucht. Nachfolgende Operationen desselben Gates werden nicht ausgeführt.
`PASS` gilt erst nach vollständiger Collector-Prüfung und abschließender
Identitäts-/Zeitprüfung; es belegt keine Live-Freigabe.

| Gate | Mögliche Operationsstufen in Ausführungsreihenfolge |
| --- | --- |
| `account_project_binding` | `ADMIN_PROJECT`, `ADMIN_SERVICE_ACCOUNTS`, `ADMIN_API_KEYS` |
| `spend_controls` | `ADMIN_SPEND_LIMIT` |
| `agent_configuration` | `CANARY_MODELS`, `CANARY_AGENT` |

Alle Gates kennen außerdem `NOT_ATTEMPTED`, `IDENTITY_VALIDATION` und
`FINAL_VALIDATION`. `ADMIN_API_KEYS` bezeichnet die bestehende gefilterte
Key-Liste. Der vorhandene einzelne Key-Detail-GET wird weiterhin nicht aufgerufen.
Es gibt höchstens vier Admin- und zwei Canary-GETs, keine neuen Endpunkte,
Extrarequests, Redirect-Follows oder Retries. Scheitert ein früher GET, können es
weniger als sechs sein. Die Diagnose enthält keine Pfade oder Referenzen.

| Code | Sichere Bedeutung |
| --- | --- |
| `NOT_ATTEMPTED` | Gate noch nicht erhoben; insbesondere bei PLAN/BLOCKED |
| `PASS` | Valide normalisierte Providerobservation dieses Gates |
| `HTTP_401`, `HTTP_403`, `HTTP_429` | Genau dieser HTTP-Status; keine weitergehende Ursachenbehauptung |
| `HTTP_5XX` | HTTP-Status 500–599 |
| `HTTP_OTHER` | Anderer Status außer 200; Body verworfen |
| `REDIRECT_BLOCKED` | HTTP-Status 300–399; kein Follow, kein Body-/Location-Read |
| `TLS_OR_PROXY_FAILURE` | TLS-/HTTP-Protokollfehler oder ungültige Proxykonfiguration; keine Ursachenauflösung aus Fehlertext |
| `DNS_FAILURE` | Resolverfehler vom Typ `socket.gaierror` |
| `TIMEOUT` | Transporttimeout oder Connect-/Read-/Gesamtfrist überschritten |
| `RESPONSE_TOO_LARGE` | Bodygrenze (maximal 65536 Bytes) oder Headergrenze überschritten |
| `TRANSPORT_FAILURE` | Sonstiger sicher klassifizierter Wire-Fehler, einschließlich nicht genauer einordenbarer Proxy-/Verbindungsabbrüche |
| `OBSERVATION_INVALID` | Collector erfolgreich, aber Observation vom bestehenden Verifier oder abschließender Frischeprüfung verworfen; kein Rückschluss auf Authentifizierung |
| `READ_UNAVAILABLE` | Kein verwertbares Read-Ergebnis, etwa Secret-Store-/Handle-/Abschlussfehler; keine sichere feinere Ursachenbestimmung |
| `SCHEMA_MISMATCH` | JSON-/Contractprüfung scheitert, einschließlich doppelter Keys, Nichtfinite-Werte, falscher Typen und unbekannter Agentfelder |
| `EXPECTED_RECORD_MISSING` | Erwarteter Eintrag fehlt in gültiger Account-/Key-/Modellliste |
| `CONFIGURATION_MISMATCH` | Vollständige Saved-Agent-Konfiguration weicht vom erwarteten Digest ab |
| `BUDGET_MISMATCH` | Typkorrektes Projektlimit unterschreitet das lokale Budget oder überschreitet 100 Cent |
| `IDENTITY_OR_HANDLE_INVALID` | Lokale Identitäts-/Rollen-/Frischeprüfung scheitert |

`COLLECTED` bedeutet ausschließlich **Erhebungsversuch abgeschlossen**.
`provider_observations=NONE_VALID` bedeutet null gültige Providerobservations der
oben genannten drei Gates; `SOME_VALID` bedeutet mindestens eine. Diese Angabe
wird aus den abschließend gültigen Gate-Ergebnissen berechnet, niemals aus HTTP
200 allein. Eine abgelaufene Observation wird nicht als PASS weitergegeben.
Bei einem globalen Sicherheitsfehler bleibt `outcome=BLOCKED`, sämtliche Checks
fehlen und die Diagnosen stehen auf `NOT_ATTEMPTED`.

`credential_scope` bleibt ohne unabhängigen externen Verifier
`MISSING_OR_INVALID`, auch bei sechs erfolgreichen GETs. Alle anderen bisher
fehlenden Gates bleiben unverändert. Kein Diagnosecode ist Scope-, Budget-,
Grant-, Review- oder Release-Evidence. Keine Session-Create/Submit/Cancel-, Key-,
Spend- oder Agent-Mutation wird hinzugefügt.

## Betreiberanleitung: ein offizieller Diagnoseaufruf

**In diesem Draft nicht ausführen.** Der fest hinterlegte `RUNNER_SHA256` bleibt
absichtlich auf dem bisherigen Stand; weder dieser Wert noch der externe
Release-Pin werden hier erneuert. Der Broker sperrt daher den geänderten Runner
bereits vor der Credential-Auswahl (`runner_changed`). Für einen späteren realen
Lauf sind zunächst unabhängiger QA-/Security-Review des exakten finalen HEAD,
separat überprüfte Runner-SHA-Freigabe sowie ein unabhängig bereitgestellter
exakter Release-Pin zwingend. Ein grüner Testlauf ersetzt keinen dieser Schritte.
Kein Self-Approval und keine Umgehung des Pins.

Im anschließend separat freigegebenen, sauberen lokalen Release-Checkout:

```sh
python3 -B -m developer_team.provider_readonly_prepare --execute-real-readonly
```

Der bestehende Terminaldialog fragt die nicht geheimen Bindungsfelder und die
zwei vorhandenen privaten Dateien ab. Voraussetzungen und feste Reihenfolge:
[DT-017C-Bedienung](dt-017c-local-readonly-broker.md#mac-ablauf).
Die Admin-/Canary-Dateien müssen außerhalb des Repositorys liegen, dem Benutzer
gehören, regulär, getrennt, unverändert und exakt `0600` sein. Keine Schlüssel
kopieren, keine Secretwerte in Shell, CLI oder Env eintragen. Keine alternativen
Diagnoseskripte, keine manuellen zusätzlichen Providerrequests. Bei unbekannter
Rollenzuordnung anhalten. Der Helper prüft Release und Rollenbindung vor Zugriff.
CI-/Offline-Marker und Secret-Env-Namen sperren weiterhin vor Secret-Auswahl.

Exitcode **2** und `LIVE=NO-GO` sind immer beabsichtigt. stdout enthält nur den
sanitisierten Report; keine IDs, URLs, Header, Bodies, Fehlertexte, Hashes von
Credentials oder Secret-Fingerprints. Keine Logs über GitHub hochladen.

Vollständiger synthetischer Beispielreport eines abgeschlossenen Versuchs ohne
valide Observation (keine Aussage über den historischen Vorfall):

```json
{
  "schema_version": 2,
  "mode": "READ_ONLY",
  "outcome": "COLLECTED",
  "checks": {
    "account_project_binding": "MISSING_OR_INVALID",
    "credential_scope": "MISSING_OR_INVALID",
    "spend_controls": "MISSING_OR_INVALID",
    "provider_contract_current": "MISSING_OR_INVALID",
    "agent_configuration": "MISSING_OR_INVALID",
    "environment_configuration": "MISSING_OR_INVALID",
    "secret_store": "MISSING_OR_INVALID",
    "real_transport": "MISSING_OR_INVALID",
    "single_canary_grant": "MISSING_OR_INVALID",
    "durable_journal": "MISSING_OR_INVALID",
    "fresh_create_approval": "MISSING_OR_INVALID",
    "fresh_submit_approval": "MISSING_OR_INVALID"
  },
  "provider_diagnostics": {
    "account_project_binding": {"stage": "ADMIN_SERVICE_ACCOUNTS", "code": "HTTP_403"},
    "spend_controls": {"stage": "ADMIN_SPEND_LIMIT", "code": "HTTP_403"},
    "agent_configuration": {"stage": "CANARY_AGENT", "code": "CONFIGURATION_MISMATCH"}
  },
  "provider_observations": "NONE_VALID",
  "LIVE": "NO-GO",
  "real_submissions": 0,
  "live_authorized": false,
  "validation": "OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION."
}
```

## Prüfung und Grenzen

Die synthetische Matrix in `tests/test_provider_readonly_diagnostics.py` prüft alle
sechs Operationsstufen mit Erfolg, HTTP-Fehlern, Redirects, ungültigem JSON/Schema,
überlangen Antworten und DNS-/TLS-/Proxy-/Timeout-/Transportfehlern. Fehlende
Einträge, Agentendrift, Budget, Rollenwechsel, Diagnose-Reset, geschlossene
Reportfelder und Broker-Konsistenz werden zusätzlich geprüft. Bestehende Tests
für unveränderliche/vertauschte/ersetzte FDs, echte Zeitgrenzen, Releaseintegrität,
Scope-Self-Attestation und Live-Sperren bleiben verpflichtend.

Die Python-3.11–3.13-CI verwendet weiterhin ausschließlich synthetische Fixtures
und `DT_PROVIDER_OFFLINE=1`. Die Formatdiagnose läuft auch nach einem Lintfehler,
damit beide Befunde sichtbar sind. Sicherheitschecks werden dadurch nicht grün.
Der QA-/Security-Bericht im Draft-PR unterscheidet ausgeführte Prüfungen von
noch ausstehendem unabhängigen Review. Kein Merge und keine Live-Aktivierung.

**real_submissions=0 · LIVE=NO-GO · live_authorized=false.**
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**
