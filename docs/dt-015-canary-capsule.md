# DT-015 V0.1 – Single-Canary-Kapsel mit Idempotency, Journal und Operator-Gate

Stand: 23.10.2026 · Issue #29 · Basis `main`: `aad8e5c05856f460ba7bbec50e1cae36a4d883a7`.

## Ziel

DT-015 baut auf DT-012 bis DT-014 auf und ergänzt einen **persistierbaren
Dry-run-Zustandsautomaten** für genau einen späteren Agents-API-Canary. Der Baustein
`developer_team/agents_canary_capsule.py` besitzt keinen Provideradapter und kann
keinen echten Turn starten, abbrechen oder bezahlen.

V0.1 modelliert:

- stabilen Intent und Idempotency-Key;
- Projekt- und Planbindung;
- lokales Budget;
- strukturell geprüften Operator-Grant;
- genau einen synthetischen Submit-Versuch;
- unklaren Submissionstatus ohne blindes Resubmit;
- Session-/Turn-Reconciliation;
- Cancel-Request getrennt vom Terminalnachweis;
- getrennte Terminalzustände completed, failed und cancelled;
- Usage-Beobachtung getrennt vom Terminalzustand;
- JSON-serialisierbaren Journalzustand.

## Operator-Grant

Der Grant enthält exakt:

- `grant_id`
- `intent_id`
- `project_ref`
- `max_budget_cents`
- `issued_at`
- `expires_at`
- `mode = single-canary-preauthorization`
- `source = external-operator-gate`

Intent, Projekt und Budget müssen zur Kapsel passen. Der Grant darf höchstens 3.600
Sekunden gültig sein und muss zum Zeitpunkt der Transition noch gültig sein.

**Wichtig:** Der Grant ist in DT-015 V0.1 nur ein strukturell geprüftes Modell. Er ist
keine kryptografische Betreiberattestierung und erzeugt keine Live-Autorität.
`live_authorized` bleibt immer `false`.

## Einmal-Submit und Unknown-Recovery

Die Kapsel erlaubt genau eine Transition
`record_synthetic_submit_attempt(...)`. Diese Funktion führt **keinen** Netzwerkcall
aus und erhöht `real_submissions` nicht.

Nach `SUBMISSION_UNCERTAIN` ist ein zweiter Submit nicht erlaubt. Ein später
rekonstruierter Session-/Turn-Bezug kann über `bind_synthetic_session(...)` gebunden
werden, ohne den Submit-Zähler zu verändern. Das bildet die Fail-closed-Regel ab:
bei unklarer Antwort zuerst rekonstruieren, nicht blind erneut senden.

## Cancel und Terminalstatus

`request_synthetic_cancel(...)` setzt nur `cancel_requested = true`.
Erst ein getrennt beobachteter Terminalzustand kann als
`agent.session.turn.cancelled` gespeichert werden. Ebenso bleiben
`completed` und `failed` eigene Terminalarten.

Auch dieser Terminalstatus ist in DT-015 nur synthetischer Controllerzustand und keine
Providerattestierung.

## Budget

`budget_cents` ist eine lokale Kapselgrenze. Der strukturelle Grant muss mindestens
dieses Budget abdecken. Beobachtete synthetische Usage über dem lokalen Budget wird
abgelehnt.

Diese Grenze ist **kein Ersatz** für das in DT-014 dokumentierte Provider-Hard-Limit
und bestätigt keine tatsächliche Abrechnung oder sofortige Providerabschaltung.

## Persistenz und Manipulationsschutz

Der Zustand ist vollständig JSON-serialisierbar. Beim Wiederladen prüft
`validate_capsule(...)` das feste Schema, Referenzen, Digest, Zähler, Terminalwerte,
Journal und alle Autoritätsflags.

V0.1 enthält bewusst keine kryptografische Signatur des Zustands. Manipulierte
Autoritätsflags oder `real_submissions != 0` werden abgewiesen; eine echte externe
Authentizitätsbindung bleibt Aufgabe eines späteren kontrollierten Controllers.

## Unveränderliche Sicherheitsgrenzen

In jedem gültigen DT-015-Zustand gilt:

```text
real_submissions             = 0
live_authorized              = false
github_write_authorized      = false
repository_write_authorized  = false
merge_authorized             = false
provider_adapter_present     = false
live                          = NO-GO
```

Ein erfolgreicher Dry-run ist keine Live-Freigabe.

## Tests

```sh
python -m unittest tests.test_agents_canary_capsule -v
python -m unittest discover -s tests -t . -v
```

Die neue Negativmatrix prüft unter anderem:

- falsche, abgelaufene, doppelte und projektfremde Grants;
- Grant-Budget kleiner als Kapselbudget;
- genau einen Submit;
- Unknown ohne Resubmit und anschließende Reconciliation;
- Cancel-Request ohne Terminalbestätigung;
- getrennte completed/failed/cancelled-Terminals;
- Usage vor Terminal und Budgetüberschreitung;
- partielle Sessionbindung;
- manipulierte Autoritätsflags und Real-Submission-Zähler;
- eingeschleuste Secret-Felder ohne Echo;
- keine Mutation des Eingangszustands;
- keine Netzwerk-, Prozess-, Datei- oder Environmentzugriffe;
- keine CLI-Schalter für Live, Force, Approval, API-Key, Submit oder Cancel.

## Nächster Schritt

Nach grünem DT-015-Review kann DT-016 einen **separaten, streng begrenzten
Provideradapter** entwerfen. Ein echter kostenpflichtiger Start ist nicht Bestandteil
von DT-015 und darf auch in DT-016 erst nach einer erneuten ausdrücklichen
Betreiberfreigabe für genau einen Canary erfolgen.
