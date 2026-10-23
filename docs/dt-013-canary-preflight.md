# DT-013 – Offline-Preflight vor einem später separat freizugebenden Agents-API-Canary

Stand: 23.10.2026 · Issue #23.

**DT-013 führt keinen Provideraufruf aus.** Der neue Baustein prüft ausschließlich lokal,
ob ein Betreiberentscheid für genau einen späteren synthetischen Agents-API-Canary
vollständig, eng begrenzt und an einen konkreten Controllerstand gebunden ist.

Ein erfolgreiches Ergebnis lautet `OFFLINE_PREFLIGHT_PASS`. Es bedeutet ausschließlich,
dass die lokalen Claims formal zusammenpassen. Es ist **keine** Bestätigung eines
OpenAI-Projekts, eines API-Schlüssels, eines tatsächlichen Hard-Spend-Limits, der
Datenresidenz, einer Remote-Stoppfunktion oder eines gestarteten Canarys.

## Eingabevertrag

`evaluate_canary_preflight(...)` akzeptiert nur ein exakt natives Python-`dict`
mit exakt 24 Feldern. Python-Unterklassen und zusätzliche Felder werden abgewiesen.
Die Implementierung unterstützt ausdrücklich CPython 3.11, 3.12 und 3.13.

Vor der ersten Schlüsseliteration gelten:

- maximal 24 sichtbare Felder,
- maximal 4.096 Bytes laut `dict.__sizeof__`,
- nur exakt native String-Schlüssel,
- exakter Schemasatz.

Damit werden auch stark aufgeblähte native Dictionaries nach vielen Einfügungen und
Löschungen vor der eigentlichen Feldverarbeitung blockiert.

## Verbindliche Claims

Der Betreiberentscheid enthält unter anderem:

- eindeutige `approval_id` und `canary_id`,
- den erwarteten 40-stelligen Controller-SHA,
- Providerpfad `agents_api`,
- Ausstellungs- und Ablaufzeit,
- Betreiber-Budgetobergrenze,
- geplantes Session-`spend_control`-Limit,
- behaupteten Projekt-Hard-Cap und Warnschwelle,
- ausdrückliche Bestätigung, dass Hard-Cap und Warnschwelle eingerichtet wurden,
- Zustimmung zu US-Datenresidenz und fehlendem ZDR für diesen rein synthetischen Test,
- ausschließlich synthetische Daten,
- read-only,
- genau eine Session,
- kein GitHub-Write,
- keine Subagenten,
- kein Deployment,
- kein Merge,
- Credentials außerhalb der Agentenumgebung.

Die Betreiberfreigabe darf höchstens eine Stunde gültig sein.

## Unabhängige Controllergrenzen

Die Funktion übernimmt wichtige Grenzen **nicht** aus dem Betreiberobjekt selbst:

- `expected_controller_sha` muss separat übergeben werden und exakt übereinstimmen.
- `controller_max_session_usd_cents` wird separat übergeben.
- Das Session-Limit darf weder diese Controllergrenze noch die Betreiberobergrenze
  oder den behaupteten Projekt-Hard-Cap überschreiten.
- Die Warnschwelle darf den behaupteten Projekt-Hard-Cap nicht überschreiten.

Der resultierende `approval_digest` bindet den kompletten Betreiberentscheid,
den separat erwarteten Controller-SHA und die separate Controller-Sessiongrenze.

## Ausgabe und Autoritätsgrenzen

Bei gültiger Eingabe wird ein Bericht mit

`status = OFFLINE_PREFLIGHT_PASS`

und einem deterministischen SHA-256-`approval_digest` erzeugt.

Unabhängig vom Ergebnis bleiben folgende Felder immer `false`:

- `provider_verified`
- `billing_verified`
- `credentials_verified`
- `data_residency_verified`
- `remote_stop_verified`
- `live_authorized`
- `merge_authorized`

Zusätzlich bleiben

- `separate_live_approval_required = true`
- `one_use_consumption_required = true`

Ein späterer Provideradapter müsste den Digest vor jedem externen Write dauerhaft und
atomar als genau einmal verwendbaren Intent konsumieren. **DT-013 implementiert diese
Live-Konsumierung absichtlich noch nicht.**

## Tests

Die neue lokale Testsuite prüft unter anderem:

- gültigen, autoritätslosen PASS-Bericht,
- deterministische Digest-Bindung,
- falsche und zusätzliche Felder,
- Dict-Unterklassen,
- benutzerdefinierte Schlüsseltypen ohne Callbackausführung im Prüfer,
- Sparse/Tombstone-Dictionaries,
- falsche Controller-SHAs,
- abgelaufene oder zu lange Freigaben,
- Operator-, Controller- und Projekt-Budgetgrenzen,
- strikte Bool- und Centtypen,
- sämtliche Safety-Flags fail-closed,
- nicht unterstützte Python-Runtimes,
- unveränderte Eingabeobjekte,
- niemals gesetzte Live-/Merge-Autorität.

Lokal wurde die neue Datei unter CPython 3.13.5 mit 20/20 Testmethoden erfolgreich
ausgeführt. Die vollständige Repository-CI auf Python 3.11/3.12/3.13 wird separat am
Draft-PR ausgewertet.

## Was DT-013 ausdrücklich nicht tut

- keine OpenAI- oder andere Provider-API aufrufen,
- keinen API-Key lesen oder speichern,
- kein API-Projekt prüfen,
- kein Geldlimit konfigurieren,
- keine Session starten,
- keinen Abbruch auslösen,
- kein GitHub-Repository verändern,
- keine QA-/Security-Agenten starten,
- keine Live-Freigabe erzeugen,
- keinen Merge freigeben.

## Nächster Schritt nach erfolgreichem Review

Nach unabhängiger QA- und Security-Prüfung dieses Offline-Bausteins kann separat
entschieden werden, ob ein nächster PR die **persistente Einmal-Konsumierung eines
Approval-Digests im bestehenden RunStore** vorbereitet.

Auch dieser nächste Schritt muss noch ohne Providerstart möglich sein. Ein echter,
kostenpflichtiger Agents-API-Canary bleibt bis zu einer neuen ausdrücklichen
Betreiberfreigabe gesperrt.
