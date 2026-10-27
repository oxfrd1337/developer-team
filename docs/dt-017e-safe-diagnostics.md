# DT-017E: sichere Diagnose fehlender Provider-Evidence

Issues #44 und #49 (R1), historische Entwicklungsbasis `e230ddb42fcfad624221a6ed31808b03c7ca6816`.
**Integrationsstatus 27.10.2026:** [PR #45](https://github.com/oxfrd1337/developer-team/pull/45) wurde technisch offline geprueft und mit `main`-Commit `4ec29a0ee27b0c306c65b299834679e45704c7a9` integriert. Keine reale Erhebung, keine unabhaengige produktive Releasefreigabe. [Aktueller Release-Preflight](dt-017-readonly-release-preflight.md).
Der historische all-MISSING-Bericht beweist keine konkrete Ursache. Erst ein
separat autorisierter Erhebungsversuch mit dieser Diagnoseversion kann sichere
Fehlerklassen und die betroffene zugelassene Operation unterscheiden.

## Diagnosevertrag

Das Runner-/Broker-Reportschema wechselt von **1 auf 2**: Die zusätzlichen festen
Felder `provider_diagnostics` und `provider_observations` müssen atomar durch den
Broker-Sanitizer geprüft werden. Version 1 wird abgelehnt; unbekannte Felder,
Werte, falsche Typen und widersprüchliche PASS-/Zählerangaben werden gesperrt.
Das Eingabemanifest und die Rollen-/Release-Bindungen bleiben unverändert.
R1 vereinheitlicht den Dateimodus an Broker und direktem Runner auf exakt `0600`.

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
| `TLS_OR_PROXY_FAILURE` | `ssl.SSLError` oder exakt bekannte interne ungültige Proxykonfiguration; keine Ursachenauflösung aus Fehlertext |
| `DNS_FAILURE` | Resolverfehler vom Typ `socket.gaierror` |
| `TIMEOUT` | Transporttimeout oder Connect-/Read-/Gesamtfrist überschritten |
| `RESPONSE_TOO_LARGE` | Bodygrenze (maximal 65536 Bytes) oder Headergrenze überschritten |
| `TRANSPORT_FAILURE` | Allgemeine HTTP-Protokollfehler (`http.client.HTTPException`, einschließlich `BadStatusLine`, `IncompleteRead`, `RemoteDisconnected`) und sonstige nicht genauer einordenbare Wire-/Verbindungsabbrüche; kein Beweis eines TLS-/Proxyfehlers |
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

Der direkte `ProviderReadOnlyCollector.report()` prüft die bereits vom Verifier
akzeptierten Observations erneut gegen die frische Abschlusszeit, ohne weitere
GETs. Es gilt `observed_at <= final < expires_at` und höchstens 300 Sekunden Alter.
Genau bei Ablauf und danach wird das Gate `MISSING_OR_INVALID` mit Diagnose
`FINAL_VALIDATION / OBSERVATION_INVALID`. Die zusätzliche Frischeprüfung des
offiziellen Runners bleibt erhalten; eine Startzeit-/Bindungsablehnung wird nicht
nachträglich zu PASS.

Im **offiziellen CLI-/Broker-Report** dürfen ausschließlich die drei oben genannten
Provider-Gates PASS sein, jeweils konsistent mit Verifierergebnis, Diagnose-PASS
an `FINAL_VALIDATION` und `provider_observations`. Der Sanitizer verwirft PASS für
jedes der neun übrigen Gates: `provider_contract_current`, `credential_scope`,
`secret_store`, `environment_configuration`, `single_canary_grant`, `real_transport`,
`durable_journal`, `fresh_create_approval`, `fresh_submit_approval`. Das gilt auch
bei ansonsten gültigen Providerobservations. Alle neun bleiben zwingend
`MISSING_OR_INVALID`; Booleanwerte sind keine Status-/Schema-/Zählerwerte.

Die optionale **vertrauenswürdige Python-Scope-Integration** mit unabhängigem
externem Verifier bleibt separat bestehen. Ein solcher Python-Report mit Scope-PASS
ist kein zulässiger offizieller Broker-Report; weder JSON noch sechs erfolgreiche
GETs konstruieren Scope-Evidence. Kein Diagnosecode ist Scope-, Budget-,
Grant-, Review- oder Release-Evidence. Keine Session-Create/Submit/Cancel-, Key-,
Spend- oder Agent-Mutation wird hinzugefügt.

## Betreiberanleitung: ein offizieller Diagnoseaufruf

**Weiterhin NICHT fuer einen realen Providerlauf freigegeben.** Der fest hinterlegte
`RUNNER_SHA256` bleibt absichtlich auf dem bisherigen Stand; weder dieser Wert
noch der externe Release-Pin werden hier erneuert. Der Broker sperrt deshalb
den geaenderten Runner bereits vor der Credential-Auswahl (`runner_changed`).
Die technischen QA-/Security-Reviews am finalen PR-HEAD waren Offline-PASS,
**nicht** aber eine unabhaengige Freigabe des nun gemergten Release-Commits.
Vor einem spaeteren realen GET-Lauf sind die neue unabhaengige Inventar- und
Runner-SHA-Freigabe fuer den dann exakten Release-Commit, ein extern provisionierter
Release-Pin, gepruefte Rollen-/Scope-Nachweise und eine ausdrueckliche, getrennte
lokale Read-only-Betreiberfreigabe erforderlich. CI ersetzt keinen dieser Schritte.
Kein Self-Approval, keine Eigen-Pin-Erstellung und keine Umgehung des alten Pins.

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
Auch direkt übergebene `ExternalFD`-Handles müssen exakt `0600` haben;
`0400`, ausführbare Eigentümermodi wie `0700` und Sonderbits werden abgelehnt,
selbst bei passenden externen Identitäts-/Dateipins. Die Prüfung ändert keine
Dateirechte und liest keine Secretbytes. Keine echten Schlüsseldateien für einen
Test umstellen. Der separate externe **Release-Pin** behält seinen eigenen
unveränderten Modusvertrag `0400`.

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
R1 ergänzt neun getrennte Gatefälschungstests, alle acht Provider-PASS-Teilmengen,
BLOCKED-Invarianten, boolesche Verwechslungen, unerwartete Typen und doppelte
JSON-Schlüssel. Ablaufgrenzen und direkte FD-Modi werden mit synthetischer Uhr
beziehungsweise wegwerfbaren künstlichen Dateien geprüft.
[R1-Fix-Nachweis und erneute Abnahme](dt-017e-r1-validation.md).

Die Python-3.11–3.13-CI verwendet weiterhin ausschließlich synthetische Fixtures
und `DT_PROVIDER_OFFLINE=1`. Die Formatdiagnose läuft auch nach einem Lintfehler,
damit beide Befunde sichtbar sind. Sicherheitschecks werden dadurch nicht grün.
Der historische R1-Entwicklungsbericht beschreibt den damaligen Draft-Status.
Die abschliessenden [QA](https://github.com/oxfrd1337/developer-team/pull/45#issuecomment-6440044175)- und [Security](https://github.com/oxfrd1337/developer-team/pull/45#pullrequestreview-5665877727)-Berichte betreffen den spaeter gemergten PR-Tree. Die formale getrennte Revieweridentitaet bleibt `UNSUPPORTED`;
der Code-Merge ist **keine** produktive Release-, Provider-GET- oder Live-Freigabe.

**real_submissions=0 · LIVE=NO-GO · live_authorized=false.**
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**
