# DT-017B: lokaler Read-only-Evidence-Runner

Basis ist `f74a27d264988149c8125239870637627896c6a1` (DT-017A).
Der One-shot-Runner verwendet dessen getrennte Admin-/Canary-Collector und den
unabhängigen Scope-Verifier. Er besitzt keinen AcceptanceController, keine
Session-, Submit-, Cancel-, Schreib-, GitHub-, Merge- oder Deploymentoperation.

## Lokaler Operator-Halt

```sh
python -m developer_team.provider_readonly_runner --manifest /external/public-manifest.json
```

Standardmäßig entsteht nur ein deterministischer PLAN-Report: kein FD-Secret-Read,
kein Socket und alle Gates `MISSING_OR_INVALID`. Das Manifest enthält ausschließlich
bereits bestehende, nicht geheime Bindungen und Identitäten. Es ist kein Evidence-
oder Freigabenachweis. Unbekannte, doppelte und zusätzliche Felder werden abgelehnt.
Der Manifest-Read ist auf 8192 Bytes begrenzt; stdin, Pipes und Symlinks werden nicht
als Manifest unterstützt. Fehler geben keine Argumente oder Exceptiontexte aus.

Ein vertrauenswürdiger externer lokaler Credential-Broker muss **vor dem Start**
zwei getrennte, private reguläre Dateien ausschließlich lesend öffnen und die FDs
vererben. Der Runner öffnet selbst keine Credential-Datei. Beide Dateien müssen
dem effektiven Benutzer gehören, dürfen keine Gruppen-/Fremdrechte haben und
enthalten jeweils 1–512 ASCII-Zeichen gemäß dem bestehenden FDSecretStore-Vertrag.
Die Secrets dürfen weder in Chat/argv/stdin/env/JSON noch in Logs gelangen.
Es gibt keine Discovery und keine API-Key-Erstellung, Rotation oder Änderung.

Nur folgende zusätzliche lokale CLI-Option schaltet den GET-Lauf frei:

```sh
# FDs 3 und 4 sind hier bereits vom externen Broker geöffnet und vererbt.
python -m developer_team.provider_readonly_runner \
  --manifest /external/public-manifest.json \
  --admin-fd 3 --canary-fd 4 --execute-real-readonly
```

Die Option kann nicht im Manifest oder in env gesetzt werden. In CI verweigern
`CI`, `GITHUB_ACTIONS` oder `DT_PROVIDER_OFFLINE` schon durch ihre Anwesenheit den
echten Lauf. Die CI setzt zusätzlich ausdrücklich `DT_PROVIDER_OFFLINE=1`.
Auch vorhandene `OPENAI_API_KEY`, `OPENAI_ADMIN_API_KEY` oder `OPENAI_ADMIN_KEY`
blockieren den echten Lauf; ihre Werte werden nicht gelesen. Secretoptionen und
freie URLs, Methoden, Prompts oder importierbare Pluginpfade existieren nicht.

## Externe Bindung und Manifest

Der Broker liefert genau diese sechs Manifestfelder:

| Feld | Nicht geheimer Inhalt |
| --- | --- |
| `binding` | Exakte Felder einer bereits bestehenden `CanaryBinding`: `project_id`, `agent_id`, `intent_id`, `idempotency_key`, `plan_digest`, `budget_cents`, `model`, optional der feste `provider_base` |
| `canary_identity` | Exakte `CredentialIdentity`: `project_id`, `credential_ref`, `service_account_ref`, `handle_ref`, `binding_digest`, `issued_at`, `expires_at` |
| `admin_identity` | Exakte `AdminCredentialIdentity`: `project_id`, `admin_ref`, `handle_ref`, `binding_digest`, `issued_at`, `expires_at` |
| `admin_fd_pin` | Rollenbezogen gepinnte Liste `[st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns]` des externen Admin-Handles |
| `canary_fd_pin` | Entsprechender unabhängiger Pin des Canary-Handles |
| `approved_models` | Liste mit genau dem separat genehmigten gebundenen Modell |

Identitäten sind unveränderlich und höchstens 300 Sekunden gültig. Pins müssen
aus der vertrauenswürdigen externen Rollenbindung stammen, unabhängig von den
CLI-FD-Selektoren. Der Runner ermittelt **keinen** vertrauenswürdigen Rollenpin aus
einem ausgewählten FD. Vertauschte Selektoren, gleiche Dateien, Standard-FDs,
geschlossene, ersetzte, fremde oder schreibbare Deskriptoren blockieren vor dem Netz.
Metadaten werden vor dem Lauf und nach der Erhebung erneut geprüft; der bestehende
SecretStore prüft seinen unveränderlichen Snapshot bei jedem Wire-Zugriff.
Auf nicht unterstützten FD-Plattformen bleibt der Lauf gesperrt.

Die lokale Brokerbindung ist eine Vertrauensvoraussetzung: Der Runner kann aus
Secretbytes nicht erkennen, ob der Broker ursprünglich das richtige Konto oder
die richtige Rolle zugeordnet hat. Provider-GETs ersetzen keine Scope-Attestation.
Ein absichtlich neu falsch ausgestelltes Manifest ist kein unabhängiger Nachweis.

Python-Integrationen können `run_readonly` mit bestehenden Binding-/Identity-
Objekten, zwei rollenbezogenen `ExternalFD`-Objekten und optional externen
Scope-Adaptern verwenden. Source, unabhängiger Verifier und beide gepinnten
Trust-Identitäten werden ausschließlich als lokale vertrauenswürdige Objekte
übergeben. JSON lädt keine Scope-Evidence und keine Adapter. Ohne diese vier
unabhängigen Abhängigkeiten bleibt `credential_scope=MISSING_OR_INVALID`.
Source-/Verifier-Self-Attestation bleibt durch DT-017A gesperrt.

## Fester Providervertrag

Der Runner erhebt höchstens sechs unterschiedliche Requests, jeweils einmal:

| Rolle | GET-Pfad |
| --- | --- |
| Admin | `/v1/organization/projects/{project_id}` |
| Admin | `/v1/organization/projects/{project_id}/service_accounts` |
| Admin | `/v1/organization/projects/{project_id}/api_keys?owner_project_access=any` |
| Admin | `/v1/organization/projects/{project_id}/spend_limit` |
| Canary | `/v1/models` |
| Canary | `/v1/agents/{agent_id}` |

Der bestehende DT-017A-Transport erlaubt zusätzlich ausschließlich den exakt an
`credential_ref` gebundenen optionalen API-Key-Metadaten-GET; der Runner benötigt
ihn nicht. Alle Pfade bleiben ausschließlich unter `https://api.openai.com`.
Keine Redirects, Retries, Pagination, freien Header oder Request-Bodies. Verifizierte
TLS-Verbindung und konfigurierte Proxy-/CA-Einstellungen bleiben erhalten; es
gibt keinen direkten Fallback. Größen-/DNS-/TCP-/TLS-/Lesezeitgrenzen stammen aus
DT-017A/DT-017. Fehlerantworten und Redirectziele werden nicht ausgegeben.

## Report und verbleibende Live-Blocker

stdout enthält genau ein sortiertes JSON-Objekt mit festen Statuswerten und
Booleans. Keine Secrets, Secretdigests, Header, Providertexte oder Rohantworten
werden persistiert. Exitcode **2** bedeutet stets NO-GO, auch nach erfolgreicher
Erhebung. `outcome=COLLECTED` bezeichnet einen abgeschlossenen Erhebungsversuch;
einzelne Gates können weiterhin fehlen. Nur die jeweiligen `checks` bewerten
Evidence. Fehler blockieren ohne Exception oder Traceback.

Nur `account_project_binding`, `spend_controls`, `agent_configuration` und bei
unabhängiger externer Scope-Evidence `credential_scope` können PASS erreichen.
Die Evidence muss auch bei Reportabschluss noch aktuell sein. Der Spend-GET
belegt lediglich den beobachteten Projektwert; verzögerte Providerdurchsetzung
ersetzt kein lokales Budget und keinen exklusiven Grant.

Die übrigen Gates bleiben fehlend: aktueller unabhängiger Providervertrag,
Secret-Store-Attestation, tatsächliche Session-Environment-Konfiguration,
unabhängige Realtransport-Attestation, dauerhaftes Journal, exklusiver
Single-Canary-Grant und jeweils frische Create-/Submit-Operatorfreigabe.
Der CLI fehlt außerdem absichtlich eine Scope-Adapter-Ladefunktion; reale
Scope-Evidence erfordert die vertrauenswürdige Python-Integration.
Es wurden für DT-017B keine echten Provider-Reads oder Mutationen ausgeführt.
Ein unabhängiger Review und manueller Merge bleiben erforderlich.
Der bestehende Namespace-/Bubblewrap-Skip ist weiterhin kein Isolationsnachweis.

Immer: **`real_submissions=0`, `LIVE=NO-GO`, `live_authorized=false`.**

**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**
