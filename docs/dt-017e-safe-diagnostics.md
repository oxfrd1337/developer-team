# DT-017E: sichere Diagnose fehlender Provider-Evidence

Issue #44; Basis ist der verifizierte aktuelle `main`
`e230ddb42fcfad624221a6ed31808b03c7ca6816`.
Der dort beobachtete all-MISSING-Bericht belegt keine bestimmte Ursache.
Erfolgreiche separate GETs oder Responses-POSTs ersetzen keine DT-017-Evidence.

## Vertrag und Schema 2

`checks` behält unverändert `PASS` oder `MISSING_OR_INVALID` für alle zwölf Gates.
Nur `account_project_binding`, `spend_controls` und `agent_configuration` erhalten
zusätzlich je ein festes Objekt `{code, stage}` unter `provider_diagnostics`.
Die Diagnose entscheidet kein Gate. Ausschließlich die bisherige unabhängige
Observation-Prüfung entscheidet über PASS; abgelehnte Observations erhalten
`OBSERVATION_REJECTED`, niemals Diagnose-PASS.

`provider_observations` ist die Anzahl der zum Reportzeitpunkt akzeptierten
Providerobservations (Integer 0–3). `outcome=COLLECTED` bedeutet ausschließlich
**Erhebungsversuch**, auch bei `provider_observations=0`. Es bedeutet weder
vollständige Evidence noch Live-Freigabe. PLAN/NOT_EXECUTED und BLOCKED enthalten
null Observations und `NOT_ATTEMPTED`-Diagnosen. Verfall oder abschließender
Rollen-/FD-Fehler verwirft alle früheren Checks und Diagnosen zusammen.

Schema 2 ist wegen der zwei neuen Pflichtfelder erforderlich. Der Broker akzeptiert
nur exakt dieses Schema, bekannte Gates/Codes/Stages und konsistente PASS-Zähler.
Schema 1, fehlende/zusätzliche Felder, dynamische Werte, falsche Typen (auch Bool
als Zähler) und widersprüchliche Angaben blockieren. Er rekonstruiert die Ausgabe
statt beliebigen Kindprozess-JSON weiterzugeben. PLAN/PREPARE verwenden ebenfalls
Schema 2 und behalten ihre bisherigen festen Zusatzfelder.

## Feste Prüfstufen

| Gate | Stage | Bisherige Whitelist-Operation |
| --- | --- | --- |
| `account_project_binding` | `ADMIN_PROJECT` | Admin: Projekt-GET |
| `account_project_binding` | `ADMIN_SERVICE_ACCOUNTS` | Admin: Service-Account-Liste |
| `account_project_binding` | `ADMIN_API_KEYS` | Admin: API-Key-Liste mit bestehendem Access-Filter |
| `spend_controls` | `ADMIN_SPEND_LIMIT` | Admin: Spend-Limit-GET |
| `agent_configuration` | `CANARY_MODELS` | Canary: Modellliste |
| `agent_configuration` | `CANARY_AGENT` | Canary: bestehender Saved Agent |

`PRECHECK` bezeichnet die lokale Rollen-/Identitäts-/Handle-Vorprüfung,
`NOT_ATTEMPTED` einen noch nicht begonnenen Gateversuch und `COMPLETE` die
abgeschlossene Collectorprüfung. Ein Fehler beendet die GET-Kette dieses Gates;
andere Gates werden wie bisher unabhängig geprüft. Erfolgreiche vorherige Schritte
sind implizit; ausgegeben wird die erste scheiternde Stufe je Gate. Es gibt keine
zusätzlichen Requests, Pagination, Retries oder Redirect-Folgen. Maximal dieselben
vier Admin- und zwei Canary-GETs. Die bisherige Transport-Whitelist bleibt bytegleich
hinsichtlich erlaubter Methoden, Pfade und Rollen; ein bereits erlaubter, vom
Collector nicht verwendeter Key-Einzelabruf wird weiterhin nicht ausgeführt.

## Feste Codes

| Code | Sichere Bedeutung |
| --- | --- |
| `NOT_ATTEMPTED` | Kein Versuch für dieses Gate; keine Providerursache ableitbar |
| `HTTP_401`, `HTTP_403`, `HTTP_429` | Genau dieser HTTP-Status bei der Stage; keine weitergehende Ursachenbehauptung |
| `HTTP_5XX` | HTTP 500–599 |
| `HTTP_REDIRECT` | HTTP 300–399, nicht verfolgt |
| `HTTP_OTHER` | Anderer HTTP-Status als das erforderliche 200 |
| `TLS_OR_PROXY_FAILURE` | TLS-Fehlertyp, nicht unterstützte Proxykonfiguration oder Betriebssystem-Verbindungsfehler bei konfiguriertem Proxy; genaue Ursache bleibt offen |
| `DNS_FAILURE` | DNS-Fehlertyp |
| `TIMEOUT` | Timeout-Fehlertyp oder Ablauf der bisherigen Connect-/Read-/Gesamtfrist |
| `TRANSPORT_FAILURE` | Sonstiger sicher klassifizierter Transportfehler; kein Fehlertext |
| `RESPONSE_TOO_LARGE` | Bisherige Header- oder Body-Grenze überschritten |
| `SCHEMA_MISMATCH` | JSON/Contract ungültig, einschließlich doppelter Felder, NaN, falscher Typen |
| `EXPECTED_RECORD_MISSING` | Erwarteter Account/Key/Modell-Eintrag nicht eindeutig vorhanden |
| `CONFIGURATION_MISMATCH` | Agentkonfiguration weicht ab, Modellabschaltung angekündigt oder Budget außerhalb des zugelassenen Bereichs |
| `LOCAL_VALIDATION_FAILED` | Lokale Sicherheits-/Identitätsprüfung fehlgeschlagen; keine erfundene HTTP-Ursache |
| `OBSERVATION_REJECTED` | Collector fertig, aber bisheriger Verifier oder finale Frischeprüfung akzeptiert die Observation nicht |
| `PASS` | Provider-Gate durch bisherigen Verifier akzeptiert; keine Gesamtfreigabe |

Die Klassifizierung verwendet ausschließlich Typen und feste interne Fehlercodes,
niemals Provider-Fehlertexte. Es verlassen keine Rohantworten, URLs/Querywerte,
Header, IDs, Namen, Zeitwerte, Credential-Hashes oder Secret-Fingerprints den
Diagnosepfad. Der Worker übergibt nur den festen Fehlercode an den wartenden
Transport; ein verspäteter Worker kann keine nächste Diagnose überschreiben.
Credentials bleiben in getrennten bestehenden Admin-/Canary-FD-Stores.
`credential_scope` bleibt ohne unabhängig authentifizierte Scope-Evidence und
Verifier MISSING_OR_INVALID. HTTP 200 ist kein Scope-Nachweis. Alle weiteren
nicht attestierbaren Gates bleiben ebenfalls gesperrt.

## Offizieller Diagnoseaufruf für Betreiber

Dieser Draft autorisiert **keinen realen Lauf**. Vor einer später separat
beauftragten Erhebung sind unabhängiger QA-/Security-Review des exact-HEAD,
eine separat geprüfte Runner-SHA und der extern bereitgestellte exakte Release-Pin
zwingend. Die bestehende Produktionskonstante `RUNNER_SHA256` wurde ausdrücklich
**nicht erneuert**. Der geänderte Runner wird deshalb derzeit schon mit
`reason=runner_changed` blockiert, bevor Credentials ausgewählt oder gelesen werden.
Ein neuer externer Release-Pin allein hebt diese zusätzliche Sperre nicht auf.
Keine Hash-Erzeugung, Pin-Provisionierung oder Self-Approval durch diesen Auftrag.

Nach separater Freigabe ausschließlich den bestehenden Broker verwenden:

```sh
python3 -B -m developer_team.provider_readonly_prepare --execute-real-readonly
```

Ein sauberer, unabhängig gepinnter Release-Checkout und die bestehenden
[DT-017C-Voraussetzungen](dt-017c-local-readonly-broker.md) bleiben Pflicht.
Der lokale `/dev/tty`-Dialog fragt nicht geheime Planbindungen sowie die Pfade
bereits vorhandener separater privater Admin-/Canary-Dateien außerhalb des
Repositorys ab. Keine Schlüssel kopieren, keine neuen Secretparameter oder
Secret-Umgebungsvariablen verwenden. Keine Logs, Credentials oder Rohantworten
über GitHub hochladen. Der einzige stdout-Report ist sanitisiertes JSON;
Exitcode 2 bleibt immer beabsichtigt. Fehlende Voraussetzungen bedeuten HALT.
Keine Ad-hoc-Providerproben als Ersatz und keine automatische Konten-, Rollen-,
Key-, Spend- oder Agentkorrektur.

Synthetisches Beispiel eines Erhebungsversuchs mit drei verweigerten Erst-GETs:

```json
{
  "schema_version": 2,
  "mode": "READ_ONLY",
  "outcome": "COLLECTED",
  "checks": {
    "provider_contract_current": "MISSING_OR_INVALID",
    "account_project_binding": "MISSING_OR_INVALID",
    "credential_scope": "MISSING_OR_INVALID",
    "spend_controls": "MISSING_OR_INVALID",
    "secret_store": "MISSING_OR_INVALID",
    "agent_configuration": "MISSING_OR_INVALID",
    "environment_configuration": "MISSING_OR_INVALID",
    "single_canary_grant": "MISSING_OR_INVALID",
    "real_transport": "MISSING_OR_INVALID",
    "durable_journal": "MISSING_OR_INVALID",
    "fresh_create_approval": "MISSING_OR_INVALID",
    "fresh_submit_approval": "MISSING_OR_INVALID"
  },
  "provider_diagnostics": {
    "account_project_binding": {
      "code": "HTTP_403",
      "stage": "ADMIN_PROJECT"
    },
    "spend_controls": {
      "code": "HTTP_403",
      "stage": "ADMIN_SPEND_LIMIT"
    },
    "agent_configuration": {
      "code": "HTTP_403",
      "stage": "CANARY_MODELS"
    }
  },
  "provider_observations": 0,
  "LIVE": "NO-GO",
  "real_submissions": 0,
  "live_authorized": false,
  "validation": "OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION."
}
```

Dies zeigt exakt die beobachteten HTTP-Klassen der betroffenen Operationen;
es beweist keine bestimmte RBAC-, Schlüssel- oder Netzwerkkonfiguration.

## Sicherheit und Freigabeblocker

Die minimale Erweiterung des gemeinsamen HTTPS-Workers transportiert intern einen
festen Fehlercode zusätzlich zur bisherigen Antwort. Mutation-Gates, TLS-/Proxy-
Routing, CA-Prüfung, Deadlines, Größenlimits, Credential-Stores und die
Reconciliation-Fehler des Mutationstransports bleiben bestehen. Es gibt keine neue
API, keine Provider-Mutation, Session-Create/Submit/Cancel oder kostenpflichtige
Agentenausführung. Diagnosen sind keine Attestierung und werden nicht als
Freigabequelle geladen.

Release-Inventar, externe Trust-Quelle, exakte Commit-/Tree-Bindung, saubere
Dateien, isolierte Quellkopie und Rollen-FD-Prüfungen bleiben zwingend.
Die synthetischen Broker-/Release-Fixtures ersetzen die Runner-SHA nur im eigenen
Testprozess; sie ändern keinen Produktionspin und stellen keine Live-Evidence aus.
Unabhängiger QA-/Security-Review vor manuellem Merge bleibt ausstehend und zwingend.
Auch danach benötigt ein realer Lauf separat bestätigtes exact-HEAD und externe Pins.

**real_submissions=0 · LIVE=NO-GO · live_authorized=false.**
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**
