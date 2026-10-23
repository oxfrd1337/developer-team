# DT-017 – Kontrollierte Vorbereitung der realen Agents-API-Abnahme

Issue #34; Basis ausschließlich `main` bei
`60905b6a7b464e8d57a75cee06e8dd759587e44c` (DT-016).

**real_submissions = 0 · LIVE = NO-GO**

**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**

## Implementierter Pfad und Vertrauensgrenzen

`agents_acceptance.AcceptanceController` verbindet die unveränderte DT-016-Kapsel
mit einem festen HTTPS-Transport, sanitierter Accountprüfung, dauerhaftem
Operator-Halt und einer getrennten Cleanup-Anforderung. Keine CLI-Aktivierung,
keine Engine-Anbindung und kein Start aus CI. Python 3.11–3.13, nur Standardbibliothek
zur Laufzeit. DT-014 und DT-015 bleiben unverändert.

Der Controller benötigt drei **unabhängig kontrollierte Integrationen**:

1. `collector.read(binding, check)` erhebt lesend aktuelle Account-/Dashboard- bzw.
   offizielle Vertragsnachweise und liefert `Observation`. Kein JSON-Report,
   Agentenergebnis oder selbst attestierter CI-Lauf darf diese Integration ersetzen.
2. `secret_store.with_authorization(expected_identity, send)` injiziert den Header nur in
   den vertrauenswürdigen Wire-Code und liefert ausschließlich `WireResponse` zurück.
   `FDSecretStore` implementiert dies für einen bereits extern geöffneten, privaten,
   regulären Dateideskriptor desselben Betriebssystembenutzers. Kein Pfad-/Env-Lookup,
   kein öffentlicher Credential-Getter, keine Key-Erstellung/Rotation. Der Betreiber
   muss FD und Store außerhalb von Chat, Git, Repository, Prompt und Logs verwahren.
3. `operator_broker.read_approval(binding, operation, challenge)` liefert eine extern
   verifizierte `OperatorApproval` ausschließlich nach ausdrücklicher neuer Zustimmung.
   Es gibt absichtlich keinen Standardbroker und keinen eingebauten Zustimmungsdialog.

Diese Pythonobjekte sind vertrauenswürdiger Controllercode, keine Sandbox für
beliebige Callbacks. Ein selbst gebauter Collector oder `broker_verified=True` ist
kein unabhängiger Kontonachweis. Der Collector muss reale Key-, Projekt-, Benutzer-
und gegebenenfalls Organisationsrollen korrekt auf die **lokalen** DT-016-Capabilities
abbilden. Es werden keine unbestätigten OpenAI-Permissionnamen oder Account-Endpunkte
erfunden. Account-/Adminbeobachtung verwendet bei Bedarf eine getrennte lesende
Betreiberidentität; der Canary-Key bekommt dafür keine zusätzlichen Rechte.

## Reviewkorrekturen für PR #35

Beide Inline-Befunde werden als Merge-Blocker behandelt; die Implementierung löst die
Threads nicht selbst. Die alten allein projektgebundenen Store-Verträge und der
Transport-PASS aufgrund des Python-Typs sind entfernt.

`CredentialIdentity` ist unveränderlich und enthält ausschließlich nicht geheime
Projekt-, Credential-, Service-Account- und Handlereferenzen, den vollständigen
Canary-Bindungsdigest sowie ursprüngliche Provisionierungs-/Ablaufzeiten. Identitäten
sind höchstens 300 Sekunden gültig; fehlende, zusätzliche, fremde, zukünftige oder
veraltete Identitäten sperren. Die frische Account-, Scope- und Store-Evidence muss
exakt denselben Identitätsdigest bestätigen. Der Transport pinnt die tatsächliche
Store-Identität bei Konstruktion; Controller, Handleprobe und Wire prüfen sie erneut.
Ein nachträglicher Austausch von Store oder Identität führt zu NO-GO.

`FDSecretStore` bindet die unveränderliche Identität an genau einen extern geöffneten
Deskriptor. Geräte-/Inode-/Größen-/Änderungsmetadaten werden bei Provisionierung fixiert
und vor sowie nach dem begrenzten Credentiallesen geprüft. Dateiaustausch, Änderung
oder Umbelegung des Deskriptors erfordert einen neuen extern provisionierten Handle
und neue Evidence; keine automatische Rotation. Es wird kein Secret-Fingerprint
veröffentlicht. Der externe Provisionierer muss die tatsächliche Key-/Principal-
Zuordnung korrekt ermitteln; beliebiger Pythoncode mit gefälschten Metadaten ist
keine unabhängige Vertrauensquelle. Tests verwenden nur synthetische Keymarker.

## Sanitierte Accountprüfung

`ReadOnlyVerifier.inspect(binding, now)` prüft jedes Gate getrennt. `Observation`
enthält Check, Bindungsdigest, Beobachtungs-/Ablaufzeit, Quellenklasse, Verifierreferenz
und strikt normalisierte Fakten. Maximal 300 Sekunden alt/gültig, keine zukünftigen
Beobachtungen. Nach langsamen Collectors wird gegen die aktuelle Endzeit erneut geprüft.
Zusatzfelder, fehlende Fakten, Typverwechslungen wie `True` statt `1`, Drift und fremde
Bindungen sperren ohne Echo der Eingangswerte.

| Gate | Erforderliche normalisierte Fakten |
| --- | --- |
| provider_contract_current | offizieller Ursprung, DT-016-Vertrag, kostenwirksames Create und verzögerte Spend-Durchsetzung ausdrücklich bestätigt |
| account_project_binding | exaktes Projekt und Credentialprojekt, Service-Account-, Credential- und Handlereferenz sowie Identitätsdigest |
| credential_scope | Key-, Principal- und effektive Rechte jeweils exakt minimale DT-016-Capabilities, keine zusätzlichen Rechte; gleicher Credential-Identitätsdigest |
| spend_controls | aktuell beobachtetes Projektlimit gleich dem gebundenen Budget; verzögerte Durchsetzung bestätigt |
| secret_store | externer lesbarer Store, Ausschluss aus Chat/Git/Prompts/Logs; gleicher Credential-Identitätsdigest und zusätzlich lesende Probe des injizierten Handles ohne Socket |
| agent_configuration | Agent-ID, verfügbares und zugelassenes Modell, Digest der vollständig gepinnten Konfiguration |
| environment_configuration | Digest, network=disabled, container_size=small |
| single_canary_grant | exakte Bindung/Budget, ein Create/eine Nachricht, externe exklusive Eigentümerschaft, Grantreferenz und ursprünglicher Grantzeitraum (höchstens 3.600 Sekunden) |

`transport_implementation` bewertet ausschließlich die lokale technische Verfügbarkeit.
Daraus entsteht **keine** `real_transport`-Attestation. Ohne unabhängigen frischen
Read-only-Transportnachweis gilt `real_transport=MISSING_OR_INVALID` und `LIVE=NO-GO`.
Der Nachweis muss als eigene `Observation` mit Quelle `controlled_transport_readonly`
vorliegen: exakt `https://api.openai.com`, Projekt, Credential-/Service-Account-/Handle-
Referenz und vollständiger Identitätsdigest, Route-Digest, geprüfte TLS-/Hostname-Regeln,
gesperrte Redirects, `read_only=true`, `probe_method=GET`, Bindungsdigest und frischer
Beobachtungs-/Ablaufzeitraum (höchstens 300 Sekunden). Zusatzfelder und abweichende
Werte sperren. Die Quellenklasse allein ersetzt keine unabhängig kontrollierte Erhebung.

Der Route-Digest bindet die im Transport gepinnte Proxyroute, Wire-Instanz, TLS-/Origin-
Regeln und Phasentimeouts. Ein anderer Wire-Handle, eine andere Konfiguration oder ein
Controller-Neustart benötigt einen neuen Nachweis. Änderungen an der Proxyumgebung
ändern den bereits gepinnten Transportweg nicht. Der externe Prüfer kann den exakt
vorgesehenen Transport mit einem bestehenden festen DT-016-Session-GET/List-GET prüfen;
kein Session-Create und kein anderer mutierender Aufruf ist dafür nötig. Der Controller
stellt keine eigene Attestation aus und startet keine automatische Providerprobe.

`durable_journal` verlangt einen vorhandenen gebundenen Dateidatenbank-Slot,
SQLite `synchronous=FULL` und Journalmodus DELETE oder WAL. In-Memory, fehlende,
ausgetauschte oder beschädigte Slots sperren. Die Verbindung muss für den
Wire-Worker mit `check_same_thread=False` geöffnet und exklusiv vom Controller
verwaltet werden. Datenbank und Deskriptor gehören außerhalb des Zielrepositories;
Rollback-/Kopierschutz und globale Einmaligkeit bleiben externe Betreiberpflichten.
`prepare()` ist ausschließlich die einmalige explizite Provisionierung eines neuen
Intents, niemals automatische Wiederherstellung verlorener Zustände.

Der Report zeigt alle Vorbedingungen und die lokale Transportverfügbarkeit einzeln;
beide Freigaben bleiben im Report ausdrücklich fehlend:

```text
fresh_create_approval = MISSING
fresh_submit_approval = MISSING
LIVE = NO-GO
```

Er gibt keine Freigaben aus und enthält keine Credentials, Header, Account-/Session-IDs
oder Provider-Rohtexte. Die Operator-Challenge ist eine lokale Zufallsreferenz,
kein Secret und allein keine Freigabe.

## HTTPS-Transport

`adapters.agents_https.HardenedHTTPS` erlaubt ausschließlich den DT-016-Vertrag
unter exakt `https://api.openai.com`: Session-Create mit allen Pins ohne Nachricht,
feste Canary-Message, Cancel sowie begrenzte Session-/Turn-GETs. Exakte Header,
Projekt, Idempotency-Key und kanonische Bodies werden vor dem Storezugriff geprüft.
Es gibt keine freie URL-, Methoden-, Header- oder Prompt-Schnittstelle und keine
GitHub-/Repository-Schreibfunktion.

Der Standard-Wire verwendet TLS mit Hostname-/Zertifikatsprüfung und System-CA-Trust.
Ein konfigurierter HTTPS-Proxy wird als HTTP-CONNECT-Proxy berücksichtigt; unzulässige
Proxyformen sperren ohne direkten Fallback. Redirects werden nicht verfolgt, Fehlerkörper
und sämtliche Responseheader verworfen, Mutationen niemals wiederholt. Connect und Read
sind jeweils auf höchstens zwei Sekunden voreingestellt; die absolute DT-016-Deadline
begrenzt zusätzlich DNS, TLS, Header und inkrementelles Lesen. Die komplette
DNS-/TCP-/TLS-Phase und die komplette Read-Phase haben jeweils eine eigene absolute
Deadline. Header einschließlich Statuszeile maximal 8.192 Bytes, Body maximal
65.536 Bytes, Requestbudget unverändert im Journal gebunden. Implizites Wiederverbinden
nach einem Verbindungsabbruch ist deaktiviert.

Bei Gesamt-Timeout wird die Verbindung beendet und eine verspätete Antwort verworfen.
Ein im Betriebssystem hängender DNS-Worker kann erst nach Rückkehr beendet werden;
er prüft Deadline/Abbruch **vor** jeder späteren Requestübermittlung. Abbruch bedeutet
keinen nachgewiesenen Provider-Cancel. Der dauerhaft reservierte Unknown-Zustand bleibt
bestehen und erlaubt nur Reconciliation. Auch nach Store- oder Wirefehlern verlassen
nur feste Fehlercodes die Grenze, ohne Exceptionverkettung oder Secret-Rohtext.

## Späterer separat freizugebender Ablauf

1. Externe Integrationen prüfen/reviewen, exklusiven Journal-Slot einmalig provisionieren.
2. `review('create_session')` prüft alle Vorbedingungen und persistiert eine neue
   unvorhersagbare Challenge. Es erfolgt **kein POST**.
3. Unmittelbar danach muss der unabhängige Operatorbroker eine neue Zustimmung für
   exakt Bindung, Operation und Challenge ausstellen. Höchstens 60 Sekunden gültig.
   Ein Merge, ein vorheriger Kommentar oder ein gespeicherter Report genügt nicht.
4. Erst der separate Aufruf `execute('create_session')` kann genau eine leere Session
   erstellen. Vor jedem POST werden Evidenz und Zustimmung nach den Journalwrites
   sowie nochmals am Wire geprüft. Session-/Environment-ID werden dauerhaft gebunden.
5. `review('submit_canary')` liest effektive Session-/Agent-/Environmentkonfiguration
   und leere Turns erneut. Erst danach entsteht eine **neue sessiongebundene** Challenge.
   Alte Create-Zustimmung ist für Submit ungültig. Wieder expliziter Operator-Halt.
6. Nach separater frischer Submit-Zustimmung sendet `execute('submit_canary')` genau die
   feste DT-016-Nachricht für 2+2 → 4. Kein automatischer Übergang von Create zu Submit.
7. `reconcile()` führt jeweils nur einen budgetierten lesenden Schritt aus; bei
   unbekanntem Create oder Submit gibt es keine zweite Session/zweite logische Nachricht.
   DT-016 prüft den konkreten Turnterminal und beobachteten Spend getrennt. Ein lokaler
   Poll-Loop darf das persistierte Requestbudget nicht erweitern.
8. Cancel hat eine eigene frische Stopzustimmung. Lesen und Stop bleiben unabhängig
   von abgelaufenen Start-Grants oder fehlender Start-Spend-Evidenz; aktuelle gemeinsame
   Account-/Scope-/Contract-/Secretnachweise bleiben erforderlich.
9. Nach eindeutigem Terminal und Kostenbeobachtung persistiert `request_cleanup()`
   genau eine Cleanup-Anforderung. Sie führt keinen DELETE aus und meldet ausdrücklich
   `REQUESTED_NOT_CONFIRMED`. Ein externer Betreiber muss diese Anforderung gesondert
   bedienen und die tatsächliche Ressourcenfreigabe bestätigen. Kein automatischer Retry.

Kosten sind Best-Effort-Beobachtungen, kein garantierter Null-Overrun. Token-/Modellusage,
Antwortinhalt und abschließende Rechnung müssen bei der späteren realen Abnahme zusätzlich
extern dokumentiert werden; ein terminaler Turn allein beweist nicht das erwartete Ergebnis.

## Reale Verifikation und verbleibende Live-Blocker

In dieser Entwicklung wurden ausschließlich öffentliche Dokumentationsseiten lesend
konsultiert. **Kein OpenAI-Konto, Projekt, Key, Modellzugang, Saved Agent, Secret Store,
Spend-Limit oder realer Transport wurde gegen den Provider verifiziert.** Alle positiven
Kontonachweise und HTTP-Antworten der Tests sind synthetisch; kein echter Provider-POST.

Vor einem Live-GO fehlen weiterhin reale frische Account-/Scope-/Spend-/Modell-/Agent-
Nachweise, ein unabhängig geprüfter Collector und Operatorbroker, extern provisionierter
Secret Store, exklusives produktives Journal/globaler Einmal-Grant, kontrollierte
Transportabnahme, neue Create-Zustimmung und später neue Submit-Zustimmung. Cleanup-
Bestätigung sowie reale Usage-/Kosten-/Antwortabnahme sind nach dem separaten Canary offen.

Aktuelle offizielle Quellen (23.10.2026):

- [Sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions)
- [Saved-Agent-Overrides](https://developers.openai.com/api/docs/guides/agents-api/configuration)
- [Hosted Sandbox: small=1 GB, network disabled, Cleanup](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted)
- [Effektive Rollen und Rechte](https://developers.openai.com/api/docs/guides/rbac)
- [Spend Controls](https://developers.openai.com/api/docs/guides/spend-limits)
- [Preisübersicht](https://developers.openai.com/api/docs/pricing)

Die öffentlichen Quellen sind kein Accountnachweis und werden nicht als gespeicherte
Live-Evidenz in den Controller übernommen. Die Preisangabe aus Issue #34 ist kein
Kostenversprechen; unmittelbar vor Live ist der aktuelle Preis erneut zu prüfen.

## Offline-Validierung

```sh
python -m unittest tests.test_agents_acceptance tests.test_agents_https -v
python -m unittest discover -s tests -t . -v
python -m ruff check developer_team tests
python -m ruff format --check --diff developer_team tests
python -m coverage run --branch -m unittest discover -s tests -t . -v
python -m coverage report --fail-under=80
python -m build --no-isolation
```

Die bestehenden sechs CI-Jobs bleiben credentialfrei, provider-mutationsfrei und ohne
Merge oder Deployment. Tatsächlich ausgeführte Tests, offene Hostchecks, CI-Run und
exakter HEAD werden im Draft-PR dokumentiert. Kein Merge und kein Deployment in dieser Phase.
