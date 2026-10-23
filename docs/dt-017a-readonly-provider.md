# DT-017A: getrennte Provider-Collector

DT-017A ergänzt Issue #36 auf `main` d516115b75b7da94691272b226c9aeb674f48f56.
Der vollständige Issue-Text und der neueste Codex-Handoff wurden vor Beginn gelesen.
**real_submissions = 0 · LIVE = NO-GO.** Kein Merge, kein Deployment.
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**

## Vertrauensgrenzen und Verwendung

`provider_readonly.ProviderReadOnlyCollector` implementiert den bestehenden
`read(binding, check)`-Vertrag für `ReadOnlyVerifier` und `AcceptanceController`.
Es gibt keinen Standard-Collector, keine Credential-Suche in Dateien/Umgebung,
keine CLI-Aktivierung und keinen Freigabeschalter. Konstruktion und `report()` ohne
externe Handles ergeben ausschließlich `MISSING_OR_INVALID`.

Ein vertrauenswürdiger lokaler Controller provisioniert explizit:

1. Eine frische unveränderliche `CredentialIdentity`, denselben `FDSecretStore`
   und dieselbe Identität wie später für `HardenedHTTPS` in DT-017. Es findet
   keine Key-Erstellung, Änderung oder Scope-Erweiterung statt.
2. Eine getrennte `AdminCredentialIdentity` und einen extern geöffneten privaten
   regulären Dateideskriptor für `AdminFDSecretStore`. Kein Pfad wird aufgelöst,
   kein Secret zurückgegeben. Admin- und Canary-Handle-/Credential-Referenzen
   müssen verschieden sein. Der gemeinsame Adapter verweigert auch zwei
   verschiedene Deskriptoren auf dieselbe Datei vor dem ersten Providerzugriff.
3. `AdminReadOnlyCollector(binding, identity, admin_store)` und
   `CanaryReadOnlyCollector(binding, identity, canary_store,
   approved_models=frozenset({binding.model}))`. Die Modellfreigabe ist eine
   explizite lokale Richtlinie; GET-Verfügbarkeit allein erteilt sie nicht.
4. `ProviderReadOnlyCollector(binding, identity, admin=admin, canary=canary,
   scope_source=trusted_source, scope_verifier=independent_verifier)`.
   Dieses Objekt kann als `collector` in DT-017 injiziert werden. Der bestehende
   Acceptance-Controller bleibt unverändert; alle bisherigen Gates gelten weiter.

`connection_factory`, Zeitquellen, Scope-Quelle und Scope-Verifier sind ausschließlich
vertrauenswürdige Controller-Abhängigkeiten. Sie dürfen niemals aus einem Plan,
einem Agentenergebnis, gespeichertem JSON oder einer Benutzereingabe geladen werden.
Die Wire-Testnaht darf nicht als produktiver Transportnachweis ausgewiesen werden.

## GET-Vertrag

Exakt `https://api.openai.com`, ohne alternative Ports, Redirects oder Retry:

| Identität | Erlaubte Pfade |
| --- | --- |
| Admin | `/v1/organization/projects/{gebundenes_projekt}` |
| Admin | derselbe Projektpfad + `/service_accounts` |
| Admin | derselbe Projektpfad + `/api_keys?owner_project_access=any` |
| Admin | derselbe Projektpfad + `/api_keys/{gebundener_key}` (optional) |
| Admin | derselbe Projektpfad + `/spend_limit` |
| Canary | `/v1/models` |
| Canary | `/v1/agents/{gebundener_agent}` |

Die Collector-Schnittstelle akzeptiert keine freie URL. Die interne Wire-Grenze
prüft nochmals Methode, exakte Origin/Pfade, Header, Body und Limits vor Handle-
und Socketzugriff. Canary-Reads senden `OpenAI-Beta: agents=v1` und den exakt
gebundenen `OpenAI-Project`-Header. Admin-Identitäten werden vom normalen
`HardenedHTTPS`-Transport abgelehnt. Keine Sessions, Messages, Cancel-, Key-,
Spend- oder Agent-Mutationen sind Bestandteil dieser Collector.

DNS/TCP/TLS, absolute Deadline, Header- und Bodylimits verwenden die vorhandene
DT-017-Härtung. Connect-/Read-Timeout höchstens fünf Sekunden (Standard zwei),
Gesamtdeadline fünf Sekunden, Body höchstens 65.536 Byte, Header höchstens 8.192
Byte. HTTPS mit Hostnamen- und Zertifikatsprüfung; vorhandener Proxy und CA-Trust
bleiben erhalten. Fehler-/Redirect-Bodies und Responseheader werden verworfen.
Kein automatischer Reconnect, kein Retry, kein direkter Proxy-Fallback.

## Evidence und Fail-closed-Verhalten

Projekt muss aktiv sein. Service Account und Key müssen exakt zu den extern
gebundenen Referenzen passen, der Key-Owner muss dieser Service Account sein,
`owner_project_access` muss `active` sein. Explizite Ablauf-/Status-/Projektfelder
werden geprüft. Fehlende optionale Ablaufdaten bedeuten laut Providervertrag
keinen bekannten Ablauf; sie beweisen keinerlei Scope. Mehrdeutige, doppelte,
fehlende oder paginierte Treffer blockieren. Es werden keine Folgeseiten geraten;
pro Liste höchstens 100 Records. Ein späterer kontrollierter Pagination-Ausbau
bedarf eines eigenen Reviews. Vollständige Listen können deshalb NO-GO liefern.

`SpendEvidence` liest den dokumentierten `project.spend_limit` mit
`threshold_amount` **in Cent**, `currency=USD`, `interval=month` und
`enforcement.status=enforcing`. Der Wert muss exakt dem bestehenden gebundenen
DT-017-Budget entsprechen. Fehlend, soft, inaktiv, ungültig, fremde Felder oder
abweichender Wert blockieren. `enforcement_delayed=True` bleibt explizit:
Ein Monatslimit garantiert kein sofortiges Stoppen einzelner Requests. Lokales
Budget, exklusive Ownership und unabhängiger Single-Canary-Grant bleiben nötig.

Modelle werden ausschließlich mit dem Canary-Key gelesen. Erwartetes Modell muss
exakt einmal in der begrenzten Liste vorkommen und lokal freigegeben sein.
Angekündigte Shutdown-Daten und unbekannte Lifecycle-Felder blockieren; es gibt keinen erfundenen
Lifecycle-Endpunkt. Die Saved-Agent-Konfiguration muss vollständig der gebundenen
Konfiguration entsprechen. Der dokumentierte aufgelöste Wert
`multi_agent.max_concurrent_subagents=null` wird bei deaktivierten Subagents
geprüft. Zusätzliche Tools, Netz-/Environment-Felder, abweichende Subagent- oder
Kostenkonfiguration und unbekannte ausführungsrelevante Felder blockieren.
Saved Agents liefern keinen Nachweis einer späteren Session-Umgebung: deren
Acceptance-Gate bleibt fehlend und benötigt eine unabhängige kontrollierte Prüfung.

### Separate Scope-Attestation

Die öffentliche Project-Key-GET-Antwort dokumentiert keinen belastbaren
Scope-Readback. Erfolgreiche GETs oder ein zusätzliches `scopes`-Feld darin
können niemals `credential_scope=PASS` ergeben.

`ScopeEvidence` muss von einer kontrollierten Account-/Dashboard-Quelle kommen.
`scope_source.read_scope(binding, identity)` liefert das streng typisierte Objekt;
`scope_verifier.verify(evidence)` muss **das vollständige Objekt** unabhängig
authentifizieren und exakt `True` zurückgeben. Die Signatur ist ein begrenzter,
undurchsichtiger Nachweis für diesen Verifier. Es gibt keinen JSON-Loader,
selbst gesetzten `verified`-Schalter oder Standard-Verifier. Ein produktiver
Attestor/Signaturprüfer muss außerhalb des getesteten Agents provisioniert werden.
Tests verwenden ausschließlich eine ausdrücklich synthetische Autorität.

Die vollständige immutable Identität bindet Projekt, Credential, Service Account,
Handle und Binding-Digest. Evidence darf höchstens 300 Sekunden alt sein, nicht
in der Zukunft liegen und keine Lease über 300 Sekunden haben. Key-, Principal-
und effektive Rechte müssen jeweils exakt dieser Liste entsprechen:

- `api.agents.read`
- `api.agents.write`
- `api.responses.write`
- `api.model.read` (dokumentiertes Modell-Listenrecht, Singular)

Zusätzliche Rechte, inklusive Files/Web/Admin/all-permissions, sperren.
Erst nach unabhängiger Authentifizierung erfolgt die Übersetzung auf die
bestehenden lokalen DT-017-Capabilitynamen. Diese lokalen Namen sind keine
behaupteten Provider-RBAC-Bezeichner. Auch ein authentifizierter Scope-Nachweis
erteilt keine Create-/Submit-Zustimmung.

### Normalisierung

Nur bestehende `Observation`-Fakten mit gebundenen IDs, Digests, Booleans und dem
gebundenen Budget verlassen die Collector. Keine Rohantworten werden gespeichert;
Namen, E-Mail-Adressen, redacted key values, Signaturen und Secretmaterial kommen
nicht in Reports, Exceptions oder Logs. Doppelte JSON-Schlüssel, Nicht-Objekte,
NaN/Infinity, unvollständige Antworten und Timeout blockieren. Alle Leases werden
nach der Erhebung erneut geprüft; die ursprüngliche Beobachtungszeit wird nicht
auf das Ende einer langsamen Erhebung verschoben.

Dieser Schritt erhebt vier Gates. `provider_contract_current`, `secret_store`,
`environment_configuration`, `single_canary_grant` und `real_transport` werden
nicht aus GET-Erfolg erfunden und bleiben ohne unabhängige Evidence fehlend.
Insbesondere attestiert ein anderer Read-only-Transport niemals die Route des
späteren Session-Transports. `report()` enthält immer `real_submissions=0`,
`live=NO-GO`, `live_authorized=False` und den verbindlichen Offline-Hinweis.

## Prüfung und verbleibende Live-Blocker

`tests/test_provider_readonly.py` enthält 43 neue Tests mit zusätzlicher
parametrisierter Negativmatrix; `tests/provider_readonly_support.py` ausschließlich
synthetische Fixtureantworten und Schlüsselmarker. Jeder neue HTTP-Test injiziert
eine lokale Wire-Fixture. CI provisioniert keine Provider-Credentials und führt
keine echten OpenAI-Aufrufe aus. Bestehende Tests bleiben unverändert.

Vollständige Ergebnisse und CI-Run werden im Draft-PR nachgetragen. Verbindliche
Checks: Python 3.11–3.13, gesamte Suite, Ruff/Format, Branch-Coverage mindestens
80 %, Wheel/SDist, sichere Smoke-Demo und Checkpoint/Restore.

Live bleibt gesperrt bis mindestens reale getrennte externe Handles, aktuelle
Owner-/Projekt-/Spend-/Modell-/Agent-Evidence, unabhängig authentifizierter
Scope-Nachweis, offizieller Vertragsnachweis, bestätigter Secret-Store,
Session-Umgebung/Route, dauerhaftes Journal und exklusiver Budgetgrant unabhängig
bestätigt sind. Separate frische Operator-Zustimmungen vor jedem POST sind eine
spätere DT-017/#34-Abnahme und gehören nicht zu diesem Schritt. Keine dieser
Voraussetzungen wird durch eine grüne CI ersetzt.

## Offizielle Quellen

Am 23.10.2026 lesend geprüft; kein Provider-Account-GET wurde ausgeführt:

- [Admin APIs](https://developers.openai.com/api/docs/guides/admin-apis)
- [RBAC](https://developers.openai.com/api/docs/guides/rbac)
- [Project API Keys: List](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/projects/subresources/api_keys/methods/list)
- [Project Spend Limit: Retrieve](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/projects/subresources/spend_limit/methods/retrieve)
- [Saved Agent: Retrieve](https://developers.openai.com/api/reference/resources/beta/subresources/agents/methods/retrieve)
- [Modelle: List](https://developers.openai.com/api/reference/resources/models/methods/list)

Die im Issue verlinkte CLI-Spend-Referenz war beim Abruf nicht erreichbar; der
GET-Vertrag wurde anhand der offiziellen API-Referenz desselben Resources geprüft.
Es wurden keine zusätzlichen Provider-Endpunkte ergänzt.


## Nachprüfung der Evidence-Fristen

Die Account-Observation endet spätestens beim frühesten ausdrücklich gemeldeten
Ablauf von Key, Service Account oder Key-Owner. Der Ablauf wird nach den GETs und
der abschließenden Handleprüfung erneut berücksichtigt. Eine zuvor gespeicherte
Observation kann deshalb nach Providerablauf auch innerhalb der üblichen
300-Sekunden-Frist keinen PASS mehr erzeugen. Fehlende oder null-Ablaufwerte im
optionalen Providerschema bleiben unverändert behandelt; sie beweisen keine Scopes.

Wenn ein Canary-Collector vorhanden ist, prüft der Scope-Adapter dessen tatsächliche
immutable Identität und Handlebindung vor dem externen Scope-Read sowie nach der
unabhängigen Signaturprüfung. Ein Handlewechsel innerhalb des externen Verifiers
wird verworfen. Eine separate Account-Attestation ohne Canary-Transport kann nur
das Scope-Gate erfüllen; Transport, Secret-Store und übrige Live-Gates bleiben gesperrt.
