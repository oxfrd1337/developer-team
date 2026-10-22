# DT-013 V0.1 – Offline-Preflight vor einem späteren Agents-API-Canary

Stand: 23.10.2026 · Issue #21.

## Zweck

DT-013 ergänzt nach DT-012 eine **rein lokale, fail-closed Entscheidungsschicht**. Sie prüft,
ob ein Betreiberentscheid für genau einen später separat freizugebenden synthetischen
Agents-API-Canary vollständig und intern konsistent beschrieben ist.

Der Baustein `developer_team/agents_canary_preflight.py` startet **keine** Provider-Sitzung,
liest keine Credentials, führt keine Netzwerk-, Datei-, Shell-, Prozess- oder GitHub-Aktion
aus und erzeugt keinerlei Live- oder Merge-Autorität.

Ein erfolgreicher Report bedeutet ausschließlich:

`READY_FOR_SEPARATE_LIVE_DECISION`

Er bedeutet ausdrücklich **nicht**, dass ein API-Projekt, ein Geldlimit, Credentials,
Datenresidenz, Remote-Stopp oder Provideridentität technisch verifiziert wurden.

## Eingabevertrag

Die Eingabe ist ein einzelner nativer Python-`str` mit UTF-8-JSON. Vor dem JSON-Parsing
werden sowohl Zeichen- als auch Bytegröße auf 8.192 begrenzt. Doppelte JSON-Schlüssel,
nicht standardkonforme Zahlen, unbekannte Felder und falsche Typen werden abgewiesen.

Das JSON muss exakt diese Felder enthalten:

| Feld | Verpflichtende Bedeutung |
| --- | --- |
| `schema_version` | exakt Integer `1` |
| `purpose` | exakt `synthetic_read_only_canary` |
| `provider` | exakt `openai_agents_api` |
| `api_project_reference` | kompakter, nicht geheimer Bezeichner; kein API-Key |
| `operator_reference` | kompakter Betreiberbezeichner |
| `grant_reference` | kompakter Referenzbezeichner für diesen Entscheid |
| `synthetic_data_only` | exakt `true` |
| `repository_content_allowed` | exakt `false` |
| `github_write_allowed` | exakt `false` |
| `subagents_allowed` | exakt `false` |
| `deployment_allowed` | exakt `false` |
| `us_data_residency_acknowledged` | exakt `true` |
| `zero_data_retention_unavailable_acknowledged` | exakt `true` |
| `separate_api_billing_acknowledged` | exakt `true` |
| `credential_location` | exakt `external_controller` |
| `canary_count` | exakt Integer `1` |
| `project_hard_limit_claim_usd_cents` | positiver lokaler Claim |
| `session_spend_limit_usd_cents` | positiver geplanter Sessionwert |
| `warning_threshold_claim_usd_cents` | positiver Warnschwellen-Claim |
| `live_start_authorized` | exakt `false` |

Budgetwerte sind auf höchstens 1.000.000 Cent begrenzt und müssen
`warning <= session <= project` erfüllen. Das lokale Oberlimit ist nur eine
Eingabegrenze des Validators und **keine** Budgetfreigabe.

Die drei Budgetfelder heißen bewusst `claim`, soweit der Offline-Prüfer den externen
Projektzustand nicht selbst attestieren kann.

## Beispiel

```python
import json
from developer_team.agents_canary_preflight import evaluate_canary_preflight

decision = {
    "schema_version": 1,
    "purpose": "synthetic_read_only_canary",
    "provider": "openai_agents_api",
    "api_project_reference": "project-test-001",
    "operator_reference": "operator-test",
    "grant_reference": "dt013-example",
    "synthetic_data_only": True,
    "repository_content_allowed": False,
    "github_write_allowed": False,
    "subagents_allowed": False,
    "deployment_allowed": False,
    "us_data_residency_acknowledged": True,
    "zero_data_retention_unavailable_acknowledged": True,
    "separate_api_billing_acknowledged": True,
    "credential_location": "external_controller",
    "canary_count": 1,
    "project_hard_limit_claim_usd_cents": 500,
    "session_spend_limit_usd_cents": 200,
    "warning_threshold_claim_usd_cents": 100,
    "live_start_authorized": False,
}

report = evaluate_canary_preflight(json.dumps(decision))
assert report["status"] == "READY_FOR_SEPARATE_LIVE_DECISION"
assert report["allowed_provider_starts"] == 0
assert report["live_authorized"] is False
assert report["merge_authorized"] is False
```

Für einen gültigen Entscheid wird zusätzlich ein deterministischer SHA-256-Digest über die
kanonische JSON-Darstellung erzeugt. Dieser Digest kann später zum Pinning eines separat
genehmigten Canary-Auftrags dienen; er attestiert keine externe Tatsache.

## Unveränderliche Autoritätsgrenzen

Sowohl bei `BLOCKED` als auch bei `READY_FOR_SEPARATE_LIVE_DECISION` bleiben:

- `provider_verified = false`
- `billing_verified = false`
- `credentials_verified = false`
- `data_residency_verified = false`
- `remote_stop_verified = false`
- `live_authorized = false`
- `merge_authorized = false`
- `allowed_provider_starts = 0`

DT-013 verändert nicht `Authority`, `Gate`, `Engine`, `Store`,
`CodexCloudGateway` oder GitHub-Workflows. Es gibt keinen CLI-Schalter zum Starten eines
Agents-API-Canarys.

## Tests

```sh
python -m unittest tests.test_agents_canary_preflight -v
python -m unittest discover -s tests -t . -v
```

Die Regressionen decken unter anderem ab:

- gültige Entscheidung und stabilen Digest,
- falsche Top-Level-Typen und fehlerhaftes JSON,
- doppelte JSON-Schlüssel,
- Zeichen-/UTF-8-Bytegrenzen,
- fehlende oder zusätzliche Felder,
- falsche native Typen einschließlich Bool-vs.-Integer,
- Geheimnis-ähnliche Referenzen,
- sämtliche Read-only-/Synthetik-/Daten-/Billing-Grenzen,
- genau einen Canary,
- Budgettypen, Obergrenze und Reihenfolge,
- unveränderlich fehlende externe Attestierungen und Providerstart-Autorität.

## Was DT-013 noch nicht erlaubt

Ein echter Agents-API-Canary bleibt eine **neue Betreiberentscheidung**. Vor einem
kostenpflichtigen Start müssen weiterhin außerhalb dieses Validators mindestens
tatsächlich geprüft werden:

1. konkretes OpenAI-API-Projekt und minimale Berechtigungen,
2. API-Key ausschließlich in einem vertrauenswürdigen externen Controller,
3. tatsächlich eingeschaltetes Projekt-Hard-Limit und Warnschwelle,
4. konkrete Session-`spend_control`-Grenze,
5. bewusste Akzeptanz der für den Test geltenden Datenbedingungen,
6. ein kontrollierter Runner mit Journal und eindeutiger Einmal-Start-Logik,
7. ausdrückliche Freigabe **genau dieses einen** kostenpflichtigen synthetischen Starts.

Danach wäre erst ein neuer, eng begrenzter Schritt zulässig, der die in DT-012
modellierten Session-/Turn-/Cancel-/Usage-Ereignisse gegen echte Providerbelege abgleicht.
