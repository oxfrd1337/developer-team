# DT-014 V0.1 – Read-only Verifikation der Agents-API-Live-Voraussetzungen

Stand: 23.10.2026 · Issue #27 · Basis `main`: `6fab98f12de2c486393d623cd8b759776a66fbe8`.

## Ziel

DT-014 ergänzt den in DT-013 eingeführten Offline-Preflight um einen Prüfer für **extern
erhobene, sanitierte und zeitlich begrenzte Read-only-Nachweise**. Der neue Baustein
`developer_team/agents_readonly_verification.py` enthält bewusst **keinen produktiven
Provideradapter**. Er liest keine Credentials, ruft keine API auf und kann weder einen
Agents-Turn starten noch abbrechen.

Das höchste Ergebnis lautet `READ_ONLY_VERIFIED`. Auch dann bleiben
`live: NO-GO` und `live_authorized: false`.

## Aktuell verifizierte öffentliche Vertragslage

Die offizielle Agents-API-Dokumentation beschreibt getrennte Turn-Endzustände
`agent.session.turn.completed`, `agent.session.turn.failed` und
`agent.session.turn.cancelled`; `agent.session.idle` allein ist kein Erfolgsnachweis.
Für Folgeeingaben wird ein gespeicherter `Idempotency-Key` verwendet; bei unklarer
Antwort soll derselbe Schlüssel für denselben logischen Submit wiederverwendet werden.

Die OpenAI-RBAC-Dokumentation beschreibt, dass bei Projekt-API-Keys sowohl die
Berechtigungen des Keys als auch passende Projekt-/Benutzerrechte berücksichtigt werden.
Ein öffentlicher Dokumentationsnachweis beweist daher nicht, dass ein konkreter Key oder
ein konkretes Projekt richtig konfiguriert ist.

Projekt- und Organisations-Hard-Spend-Limits können API-Traffic bei Erreichen des
verfolgten Limits mit `429` blockieren. Die Durchsetzung ist laut Dokumentation nicht
sofortig; geringe Überschreitungen sind möglich. Deshalb wird ein dokumentiertes
Hard-Limit nicht als absoluter Kostenstopp modelliert.

Offizielle Quellen, Stand 23.10.2026:

- https://developers.openai.com/api/docs/guides/agents-api/sessions
- https://developers.openai.com/api/docs/guides/rbac
- https://developers.openai.com/api/docs/guides/spend-limits

## Evidenzmodell

Vier Gates werden getrennt bewertet:

1. `provider_project_binding`
2. `credential_scope`
3. `cancel_terminal_contract`
4. `billing_controls`

Jeder Nachweis trägt Quelle, Beobachtungszeit, Ablaufzeit, Verifier, Claim und
Projektbindung. Accountbezogene Gates akzeptieren nur die Quelle
`account_readonly_observation`; öffentliche Dokumentation kann diese Gates nicht
ersetzen. Der Cancel-/Terminal-Vertrag akzeptiert dagegen ausschließlich
`official_documentation` unter `developers.openai.com`.

Nachweise verfallen. Die aktuelle V0.1 akzeptiert höchstens 60 Sekunden Zukunftsabweichung
und maximal 3.600 Sekunden TTL. Fehlende, doppelte, abgelaufene, widersprüchliche oder an
ein anderes Projekt gebundene Evidenz führt fail-closed zu `BLOCKED`.

## Geheimnisse

Das Evidenzschema enthält kein Feld für API-Key, Bearer-Token oder Credentialmaterial.
Zusätzliche Felder werden generisch abgelehnt und nicht in den Report gespiegelt.
Der Verifier selbst hat keine Netzwerk-, Datei-, Environment- oder Prozessschnittstelle
für Providerzugriffe.

## Aussagegrenzen

Ein vollständiger synthetischer Satz erzeugt:

```text
decision      = READ_ONLY_VERIFIED
live          = NO-GO
operator_gate = PENDING_SEPARATE_APPROVAL
real_submissions = 0
```

Das bedeutet nur, dass die sanitierte Evidenzstruktur formal vollständig und aktuell ist.
Es ist **keine** Providerattestierung für Live, kein Credentialtest, kein Billing-Hardstop,
keine Cancel-Bestätigung und keine Startfreigabe.

## Tests

```sh
python -m unittest tests.test_agents_readonly_verification -v
python -m unittest discover -s tests -t . -v
```

Die Negativtests prüfen unter anderem:

- fehlende und doppelte Gates;
- falsche Projektbindung;
- abgelaufene, zukünftige oder überlange Evidenz;
- selbst behauptete Verifier;
- öffentliche Dokumentation als unzulässigen Ersatz für Accountnachweise;
- falsche Claims;
- eingeschleuste Secret-Felder ohne Echo;
- ungültige Projektkennungen;
- keinen Netzwerk-, Prozess-, Datei- oder Environmentzugriff;
- keine CLI-Schalter für Live, Force, Approval, API-Key, Submit oder Cancel.

## Noch offen für echten DT-014-Betrieb

V0.1 prüft Read-only-Evidenz, **erhebt sie aber nicht aus einem echten OpenAI-Konto**.
Für eine tatsächliche Accountbeobachtung wird ein separat kontrollierter read-only
Adapter oder eine verbundene Plattformintegration benötigt. Dieser Adapter darf nur
sanitierte Metadaten liefern und muss unabhängig geprüft werden.

Bis dieser Accountnachweis tatsächlich vorliegt, bleibt der operative Stand trotz
synthetischem `READ_ONLY_VERIFIED`: **Live NO-GO**.

Nach erfolgreichem Review von DT-014 kann DT-015 die technische Kapsel für exakt einen
echten Canary vorbereiten. Auch DT-015 darf ohne erneute ausdrückliche Betreiberfreigabe
keinen kostenpflichtigen Start auslösen.
