# DT-013 V0.1 – Fail-Closed Offline-Preflight für einen späteren Agents-API-Live-Canary

Stand: 23.10.2026 · Issue #25 · Basis `main`: `5ce6943062baf391bb4cb7e47dcaa4bb8a03eb8c`.

## Ziel

DT-013 ergänzt DT-012 um eine **rein lokale strukturelle Vorprüfung** für den späteren, separat freizugebenden ersten Agents-API-Live-Canary. Der neue Baustein `developer_team/agents_live_preflight.py` prüft ausschließlich einen vom Betreiber beschriebenen Plan. Er liest keine API-Credentials, keine Umgebungsvariablen, keine Dateien und keinen Providerzustand und führt keinen Netzwerk-, GitHub-, Repository-, Prozess- oder API-Schreibzugriff aus.

Ein erfolgreiches Ergebnis heißt ausschließlich `offline_preflight: PASS`. Es bleibt immer bei `live: NO-GO`, `live_authorized: false`, `github_write_authorized: false` und `merge_authorized: false`. Ein Offline-PASS ist ausdrücklich **keine** Live-Freigabe und keine Provider-, Billing-, Credential- oder Cancel-Attestierung.

## Fail-Closed-Vertrag

Der Prüfer akzeptiert nur exakt das definierte Schema. Fehlende oder zusätzliche Felder, unbekannte Typen, unsichere Schreib-/Merge-Optionen, mehr als ein Submit, parallele Läufe, fehlende Budgetwerte oder selbst behauptete externe Verifikation führen zu `BLOCKED`. Es gibt keine stillen Defaults.

Der Plan muss unter anderem festlegen:

- genau einen synthetischen, read-only Canary;
- ausschließlich synthetische, nicht sensible Daten;
- Credentials nur über einen externen Secret Store, ohne Credentialmaterial im Plan;
- genau einen Submit und genau einen parallelen Lauf;
- keine GitHub-/Repository-Schreibrechte und keinen Auto-Merge;
- einen positiven Canary-Budgetwert, der das angegebene Projekt-Hard-Limit nicht übersteigt;
- Provideridentität, Cancel-/Terminal-Reconciliation und Billing-Limit weiterhin als **extern vor Live zu verifizieren**.

Die Budgetprüfung validiert nur Struktur und Verhältnis der angegebenen Centwerte. Sie bewertet **nicht**, ob der gewählte Betrag wirtschaftlich angemessen ist, und bestätigt nicht, dass ein Provider-Hard-Limit tatsächlich eingerichtet oder wirksam ist.

## Geheimnisse und Eingaben

Das Schema besitzt kein Feld für API-Key, Token oder andere Secrets. Zusätzliche Felder werden generisch mit `missing_or_unexpected_fields` abgelehnt; Werte oder Feldnamen werden nicht in den Report gespiegelt. Der Referenzplan enthält ausschließlich künstliche Kennungen.

## Offline-Ausgabe

Ein strukturell vollständiger Referenzplan ergibt:

```text
offline_preflight = PASS
live              = NO-GO
real_submissions  = 0
next_action       = MANUAL_EXTERNAL_VERIFICATION_AND_SEPARATE_APPROVAL_REQUIRED
```

Unvollständige oder unsichere Pläne ergeben `offline_preflight: BLOCKED` und `FIX_PLAN_AND_RERUN_OFFLINE`.

Auch bei `PASS` bleiben folgende externe Gates offen:

1. Provideridentität und API-Projektbindung,
2. Credential-Scope und tatsächlicher Secret Store,
3. Provider-Cancel und Terminal-Reconciliation,
4. Billing-Limit und Usage-Beobachtung,
5. gesonderte Betreiberfreigabe für exakt einen echten Start.

## Ausführung

Der eingebaute Referenzlauf ist ausschließlich synthetisch:

```sh
python -m developer_team.agents_live_preflight --synthetic-reference
```

Er liefert einen strukturellen Offline-PASS, beendet sich aber absichtlich mit Exitcode `2`, weil weiterhin `live: NO-GO` gilt. Ohne `--synthetic-reference` wird kein Plan angenommen und der Lauf bleibt `BLOCKED`.

Gezielte Tests:

```sh
python -m unittest tests.test_agents_live_preflight -v
python -m unittest discover -s tests -t . -v
```

## Negativ- und Sicherheitsfälle

`tests/test_agents_live_preflight.py` prüft unter anderem:

- fehlende Felder ohne Default-Fallback;
- zusätzlich eingeschleustes `api_key`-Material ohne Echo in der Ausgabe;
- Credentialmaterial im Plan;
- nicht synthetische oder sensible Daten;
- GitHub-/Repository-Schreibrechte und Auto-Merge;
- boolesche Werte anstelle echter Integer-Grenzen;
- mehr als einen Submit oder parallelen Lauf;
- ungültige oder widersprüchliche Budgetgrenzen;
- selbst behauptete Provider-/Cancel-/Billing-Verifikation;
- abweichende Residenz-/ZDR-Annahmen;
- ungültige Planobjekte;
- keine Netzwerk-, Prozess-, Datei- oder Environment-Zugriffe während der Bewertung;
- keine CLI-Flags `--live`, `--force`, `--approval`, `--api-key` oder `--credential`.

## Aussagegrenzen und nächster Schritt

DT-013 schafft nur eine deterministische, reproduzierbare Offline-Schranke vor einem möglichen Live-Schritt. Der neue Baustein ist **kein Agents-API-Adapter** und besitzt keine Fähigkeit, einen echten Turn zu starten, abzubrechen, zu bezahlen oder zu attestieren. DT-012 bleibt der synthetische Lifecycle-Replay; DT-013 prüft davor den strukturellen Betreiberplan.

Nach einem grünen PR und separater Review wäre DT-014 der nächste Schritt: externe, read-only Verifikation der tatsächlich benötigten Live-Voraussetzungen, weiterhin ohne automatischen Start. Erst danach kann eine gesonderte Entscheidung über exakt einen kostenpflichtigen Canary getroffen werden.
