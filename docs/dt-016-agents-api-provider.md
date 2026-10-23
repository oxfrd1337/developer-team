# DT-016 V0.1 – Streng begrenzter Agents-API-Provideradapter

Stand: 23.10.2026 · [Issue #31](https://github.com/oxfrd1337/developer-team/issues/31) ·
Basis `main`: `7e3412b3a45db00b10d098600f39b367457fbaa7`.
Maßgeblich ist außerdem der
[Architekturkommentar vom 23.10.2026](https://github.com/oxfrd1337/developer-team/issues/31#issuecomment-6358264174).

**Entwicklungsstand: real_submissions = 0, Live weiterhin NO-GO.**
**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**

## Zweck und unveränderte Grenzen

DT-012 bleibt ein synthetischer Replay, DT-013 eine strukturelle Planprüfung,
DT-014 eine Prüfung sanitierter Evidenz und DT-015 eine reine Dry-run-Kapsel.
Diese Module und ihre Tests werden nicht geändert und erteilen keine Live-Autorität.

`developer_team/adapters/agents_api.py` ergänzt einen separaten Provideradapter mit
expliziten Wire-Requests. Er ist weder an Engine, Rollenketten, CLI noch bestehende
Cloud-Gateways angeschlossen. Es gibt keine freie Prompt-/Task-Schnittstelle und keine
Live-/Force-/Approval-Schalter. Einziges Arbeitsinput ist die feste synthetische
Rechenfrage `CANARY_MESSAGE`. Toolliste und Subagents werden bei Session-Erstellung
ausdrücklich deaktiviert; Credentials, Vaults und Repositories werden nicht übergeben.
Der Adapter enthält keine GitHub-, Repository-, Merge- oder Deploymentoperation.

## Korrekturen der drei blockierenden Reviews in PR #32

Ausgangs-HEAD: `49c1e32274448a92ab4a1f0cac643d2380fe51a1`.
Die Korrekturen bleiben auf `dt-016-agents-api-provider`; die Review-Threads werden
nicht durch die Implementierung selbst als gelöst markiert.

| Review-Befund | Konkrete Korrektur | Regressionen |
| --- | --- | --- |
| [Hosted-Environment unzureichend begrenzt](https://github.com/oxfrd1337/developer-team/pull/32#discussion_r4356706786) | `CanaryBinding.environment_configuration` setzt `network.access=disabled`, leere Domainlisten, `container_size=small`, deaktivierten Desktop und leere Pakete/Skills/Plugins/Dateien/Capabilities. `_session` prüft die effektive Response strikt und persistiert die Environment-ID gemeinsam mit der Session-ID. | `HostedEnvironmentReviewTests`: aktiviertes, eingeschränktes, fehlendes oder widersprüchliches Netz; andere/fehlende Containergröße; zusätzliche Capabilities; Drift vor Submit und bei Reconciliation. |
| [Saved-Agent-Drift](https://github.com/oxfrd1337/developer-team/pull/32#discussion_r4356706790) | `CanaryBinding.model` ist Pflicht. `agent_configuration` überschreibt Modell, Instructions, Tools, Subagents, Reasoning, Service Tier und Textformat vollständig. Der Bindungsdigest umfasst beide kompletten Konfigurationen. `_session` prüft die tatsächlich zurückgemeldeten Werte ohne Default-Fallback. | `SavedAgentReviewTests`: geänderter Saved Agent wird übersteuert; ignorierte Pins, fehlende Werte, verschachtelte Defaults und spätere Drift sperren; alter Permit/Grant/Journalzustand gilt nicht für eine neue Konfiguration. |
| [Kostenfreigabe vor Session-Create fehlt](https://github.com/oxfrd1337/developer-team/pull/32#discussion_r4356706798) | `ExternalPermit` verlangt eigene frische, digestgebundene Freigaben für Create und Submit; auch Cancel besitzt eine eigene aktuelle Operationsfreigabe. `_request` fragt den externen Gate nach den dauerhaften Journalupdates direkt vor jedem POST erneut ab. `_authorize` prüft mit der Uhrzeit nach Rückkehr des Verifiers. | `FreshCreationApprovalReviewTests`: fehlende, alte, zukünftige, falsch typisierte oder falsch gebundene Freigaben sowie Verfall/Widerruf während Journalarbeit und verzögertem Verifier; Freigaben sind zwischen Operationen nicht austauschbar. |

Der Container wird ausschließlich als neue Inline-Konfiguration angefordert; weder eine
Template-ID noch eine vorgewärmte Environment-ID wird übergeben. Die Response muss
`small`, `network={access: disabled, allowed_domains: []}` und den abgeschalteten Desktop
explizit bestätigen. Fehlende oder unbekannte Werte und zusätzliche operative Felder
sperren. Die öffentliche Response gibt keine Environment-Variablenwerte zurück; ihr
Fehlen ist kein externer Secret-Store-Nachweis. Die Request-Variablen sind explizit leer.
Prompt-Instruktionen werden **nicht** als technische Netzwerk- oder Schreibgrenze gewertet.

Mit `agent_id` überschreiben laut öffentlichem Vertrag nur mitgesendete Agent-Felder die
gespeicherten Werte. Deshalb werden alle auswirkungsrelevanten Felder ausdrücklich
mitgesendet: das extern zu prüfende gebundene Modell, `reasoning={effort: low, summary: null}`,
`service_tier=default`, Textformat `text` mit `verbosity=low` sowie leere Tools und
deaktivierte Subagents. Die Response muss für deaktivierte Subagents zusätzlich
`max_concurrent_subagents=null` melden. Nur die beschreibenden Identitätsfelder `id` und
optional `name` bleiben außerhalb dieses Konfigurationsvergleichs; die Agent-ID wird
gesondert gebunden geprüft. Das Modell wird nicht automatisch ausgewählt. Tests verwenden
ausschließlich einen erfundenen Modellnamen. Kompatibilität, Verfügbarkeit und Kosten
eines echten Modells bleiben externe Live-Gates.

Alte Bindungsdigests, Permits und Journale ohne Environment-ID werden nicht automatisch
migriert oder neu vorbereitet. Der Controller muss einen widersprüchlichen Altzustand
extern klären. Ein SHA-256-Digest bindet die Konfiguration strukturell und ersetzt keine
unabhängige Betreiberattestierung.

## Getrennte Provideroperationen

| Methode | Wire-Vertrag | Dauerhaft reservierter Zustand |
| --- | --- | --- |
| `create_session()` | `POST /v1/agents/sessions`, ohne `input`/`events`, `stream=false`, gebundene Agent-ID, `spend_control.limit` in USD-Cent und synthetische Digest-Metadaten | `SESSION_UNCERTAIN` vor dem Request; geprüfte Session-ID danach als `SESSION_READY` persistieren |
| `submit_canary()` | Erst Session und leere Turnliste lesend prüfen; danach genau eine feste `agent.session.input.message` über `POST …/{session_id}/events`, mit gespeichertem `Idempotency-Key` | `MESSAGE_UNCERTAIN` vor dem Request; HTTP 202 ergibt ausschließlich `MESSAGE_ACCEPTED` |
| `reconcile()` | `GET /v1/agents/sessions`, `GET …/{session_id}` und/oder `GET …/{session_id}/turns` | Eindeutig rekonstruierte Session bzw. genau ein projekt-/agent-/sessiongebundener Turn |
| `cancel()` | Bekannten Turn erneut lesen, dann `agent.session.input.cancel` über `POST …/{session_id}/events` | `CANCEL_UNCERTAIN` vor dem Request; HTTP 202 ergibt ausschließlich `CANCEL_REQUESTED` |

Für Session-Erstellung wird **kein** undokumentierter Idempotency-Key behauptet.
Auch das Erstellen einer Hosted-Session kann Ressourcen provisionieren und Kosten
verursachen; deshalb benötigt bereits Create externe Prüfung, einen Operator-Grant und
eine eigene unmittelbare Einzelfreigabe (`create_approved_at`).
Es wurde ausschließlich gegen Fixtures ausgeführt.

Die dokumentierte Message-Idempotency erlaubt Wiederholungen mit exakt gleicher Session,
Nachricht und gleichem Key. DT-016 wählt die strengere zulässige Variante: **keine
Wiederholung**, ausschließlich lesende Reconciliation. Der eine logische Submit bleibt
auch bei Timeout, 401/403/429/5xx, Verbindungsabbruch oder verlorenem Receipt verbraucht.
Es gibt weder Backoff noch automatischen Retry oder weitere Arbeitseingaben.

Nach unklarer Session-Erstellung wird eine begrenzte Sessionliste nach dem vorab
gespeicherten Bindungsdigest durchsucht. Nur genau ein passender, leerer und untätiger
Kandidat darf gebunden werden. Kein Treffer, mehrere Treffer, zusätzliche Turns oder
eine unvollständige Seite erfordern externe Rekonstruktion/Betreiberentscheidung;
ein weiterer Create ist gesperrt. Es wird keine Vollständigkeit einer Teilseite behauptet.

## Autorisierung und Geheimnisse

Die Defaults `transport=None` und `gate=None` sperren sämtliche Provideroperationen
vor Journal- oder Transportzugriff. Es existiert kein eingebauter HTTP-Client, SDK-Aufruf,
Credentialloader oder produktiver Aussteller von Freigaben. Ein späterer kontrollierter
Runner muss einen unabhängig geprüften Transport und `ExternalGate` explizit injizieren.
Diese Abhängigkeiten sind vertrauenswürdiger Controllercode, keine Sandbox für beliebige
Pythonobjekte und keine aus JSON, TOML, Umgebungsvariablen oder Receipts geladene Autorität.

`ExternalPermit` ist ausschließlich der sanitierte Rückgabevertrag dieses externen
Verifiers. Das Dataclass-Objekt und seine booleschen Felder sind selbst keine
kryptografische Attestierung. Ein selbst gebauter Gate-Callback beweist keine
Kontokonfiguration. DT-013-/014-Berichte und DT-015-Grants werden nicht als Permit akzeptiert.

Create und Submit benötigen frische unabhängige Nachweise für:

- genau `https://api.openai.com`, ein Projekt, eine Agent-ID, einen Intent, Plan,
  Idempotency-Key und die feste Nachricht;
- dieselbe Projektbindung des Keys und genau die erforderlichen minimalen effektiven
  Key- **und** Projekt-/Benutzerrechte, einschließlich Stop-/Lesefähigkeit;
- externen Secret Store, tatsächlich beobachtete Spend Controls und den aktuellen Vertrag;
- sicher geprüfte Agentenkonfiguration und verifizierten externen Einmal-Grant mit Budget;
- vor Session-Create und erstem Message-Submit jeweils eine eigene ausdrückliche
  Betreiberfreigabe, höchstens 60 Sekunden alt und nicht vor dem zugehörigen Grant erteilt.
  `create_approved_at`/`submit_approved_at` und die jeweiligen
  `*_approval_binding_digest`-Felder dürfen zwischen Operationen nicht ausgetauscht werden.

Jeder Provider-POST prüft seine Operationsfreigabe unmittelbar nach den Journalupdates
erneut. Auch Cancel verlangt `cancel_approved_at` samt identischem Bindungsdigest mit
höchstens 60 Sekunden Alter. Seine Stopfreigabe ist unabhängig von abgelaufenen
Start-Grants und erlaubt keinen neuen Start. Rein lesende Reconciliation braucht keine
neue Kostenfreigabe. Fehlt die frische Freigabe oder verfällt sie während der Vorbereitung,
erfolgt kein POST. Ein bereits reservierter Unknown-Zustand bleibt konservativ gesperrt;
er wird nicht automatisch zurückgesetzt. Auch ein langsamer externer Verifier verlängert
das Freigabefenster nicht, da mit der Uhrzeit nach seiner Rückkehr validiert wird.

Die Capabilitynamen im Pythonvertrag sind lokale Normalisierungen; der externe Verifier
muss die tatsächlichen OpenAI-Rechte korrekt darauf abbilden. Die Evidenz-TTL ist auf
3.600 Sekunden begrenzt; zukünftige/abgelaufene/widersprüchliche Nachweise sperren.

Der Transport injiziert ein Credential ausschließlich außerhalb des Adapters. State,
Requestmodell und Reports enthalten keinen API-Key oder Authorization-Header. Providertexte,
Fehlerkörper, Header und Exceptiontexte werden weder gespeichert noch geloggt oder verkettet.
Öffentliche Reports enthalten keine Session-/Turn-IDs, Keys oder Metadaten. Unerwartete
Secret-Felder im Journal werden generisch abgewiesen; Objektrepräsentationen verbergen Inhalte.

## Journal, Budget und Ressourcen

`SQLiteCanaryJournal` erhält eine exklusive Controllerverbindung, keinen Repositorypfad.
Der Betreiber muss die Datenbank außerhalb des Zielrepositories verwahren. Die einzelne
Datenbank bindet genau einen Intent; atomare Compare-and-swap-Updates verhindern konkurrierende
Reservierungen. Schlüssel, Nachrichtendigest und Ressourcenlimits werden vor dem ersten
Providerkontakt persistiert. Schema, Bindungen, Zähler und Zustandskonsistenz werden beim
Wiederladen geprüft. Ein fehlendes Journal wird nicht automatisch neu vorbereitet.

Die externen Vertrauensgrenzen bleiben bestehen: SQLite ist weder eine Signatur noch ein
Rollbackschutz gegen den Datenbankeigentümer. Verlust, Kopieren, Austausch oder Zurücksetzen
des Journals benötigt externe Klärung. Ein produktiver Controller muss exklusive
Session-Eigentümerschaft und globale Einmaligkeit über seine Instanzen hinweg gewährleisten.

Das lokale Canary-Budget liegt zwischen 1 und 100 USD-Cent und wird an den externen
Grant und ein nachgewiesenes Projekt-Hard-Limit gebunden. Die Session muss ihr identisches
`spend_control.limit` zurückmelden. `spend_control.consumed` wird getrennt als bestmögliche
Kostenbeobachtung gespeichert; Tokenzahlen werden nicht in erfundene Centwerte umgerechnet.
Bei ausgeschöpftem Budget ist ein Message-Submit gesperrt. Spend Controls wirken nicht
sofortig und können geringfügig überschritten werden. Die lokale Grenze ist kein
garantierter Abrechnungshardstop. Lesen und Cancel brauchen nach Ablauf des Start-Grants
oder Budgetüberschreitung weiterhin gültige Projekt-/Scope-Nachweise, keine neue Startfreigabe.
Cancel benötigt außerdem seine eigene frische Stopfreigabe.

Standardgrenzen: 5 Sekunden pro Request, 65.536 Responsebytes, 8.192 Bytes je verarbeitetem
Session-/Turnobjekt, 20 Datensätze pro Seite und insgesamt 16 Requests einschließlich
Create, Submit, Reconciliation und Cancel. Konfigurationen dürfen maximal 30 Sekunden,
65.536/8.192 Bytes, 20 Datensätze und 32 Requests wählen. Grenzen werden im Journal gebunden
und können bei Neustart nicht erhöht werden. Doppelte JSON-Keys, ungültige UTF-8-/JSON-Werte,
zu viele Felder, Seiten mit `has_more=true` und Übergrößen sperren.

Der Transportvertrag verlangt inkrementelle Bytegrenzen, absolute Deadlines und keine
Redirects oder versteckten Retries. Zusätzlich begrenzt der Adapter seine eigene Wartezeit
auch gegenüber einem fehlerhaften injizierten Transport und verwirft späte Antworten.
Ein blockierter Daemon-Worker ist damit weder beendet noch eine Remoteaktion abgebrochen;
der persistierte Unknown-Zustand verhindert erneutes Senden. Der externe Transport muss
seine Ressourcen selbst beenden. Bei ausgeschöpftem Requestbudget ist externes Eingreifen
erforderlich; es gibt keinen unbeschränkten Poll-/Stop-Fallback.

## Terminalnachweis und Tests

Nur der konkrete gespeicherte Turn mit Status `completed`, `failed` oder `cancelled` wird
auf die drei getrennten `agent.session.turn.*`-Terminalarten abgebildet. Session-`idle`,
HTTP 202 und ein Cancel-Request sind kein Terminalnachweis. Fremde/mehrere Turns,
Subagent-Turns, widersprüchliche Terminals und Terminalregressionen sperren. Wiederholtes
Lesen desselben Terminalstatus bleibt erlaubt. Ein Terminal ersetzt keine Kostenprüfung.

100 DT-016-Tests (65 ursprüngliche und 35 Review-Regressionen) prüfen die Vertrags- und
Negativmatrix, einschließlich echter lokaler
SQLite-Neustarts, konkurrierender Verbindungen, fehlgeschlagener Write-ahead-/Receipt-Commits,
verlorener Antworten und blockierter Transportworker. Sämtliche Providerantworten und
Seiteneffekte sind Fixtures. Bestehende 371 Testmethoden bleiben unverändert.

```sh
python -m unittest tests.test_agents_api tests.test_agents_api_journal tests.test_agents_api_review -v
python -m unittest discover -s tests -t . -v
python -m ruff check developer_team tests
python -m ruff format --check --diff developer_team tests
python -m coverage run --branch -m unittest discover -s tests -t . -v
python -m coverage report --fail-under=80
python -m build --no-isolation
```

Die unveränderte Repository-CI prüft Python 3.11–3.13, Coverage >= 80 %, Build, Smoke,
Codex-Hilfe ohne Login/Tasks und Checkpoint-Wiederaufnahme. Tatsächlich beobachtete
Ergebnisse und der exakte PR-HEAD werden im PR dokumentiert. Die lokale Umgebung blockiert
Paketdownloads; fehlende lokale Werkzeuge werden nicht als bestanden ausgewiesen.

## Offene Live-Gates / DT-017

Es fehlen weiterhin reale kontrollierte Kontonachweise zu Projekt, effektiven Key-Rechten,
Secret Store, Spend Controls und deren Grenzen, geprüfter externer Runner/Transport,
unabhängiger Operator-Grant und die neue ausdrückliche Einmal-Startfreigabe.
Kein CI-PASS, Draft-PR, Review oder Merge erteilt diese Freigabe. Kein echter Canary,
kein Merge und kein Deployment gehören zu DT-016. DT-017 bleibt die separat freizugebende
kontrollierte Abnahme einschließlich Reconciliation sowie Terminal- und Kostenprüfung.

Öffentliche Vertragsquellen, am 23.10.2026 lesend geprüft:

- [Session-Lifecycle, Message-Idempotency und Cancel](https://developers.openai.com/api/docs/guides/agents-api/sessions)
- [Session-Create einschließlich SpendControl](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/create)
- [Effektive Hosted-Environment- und Agent-Konfiguration](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/methods/create)
- [Hosted-Sandboxes und technische Netzwerkpolicy](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted)
- [Gespeicherte Agenten und Session-Overrides](https://developers.openai.com/api/docs/guides/agents-api/configuration)
- [Events: Idempotency-Key und HTTP-202-Grenze](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/subresources/events/methods/create)
- [Persistierte Turns und getrennte Terminalstatus](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/subresources/turns/methods/list)
- [Effektive Projekt-/Key-Rechte](https://developers.openai.com/api/docs/guides/rbac)
- [Spend Limits und verzögerte Durchsetzung](https://developers.openai.com/api/docs/guides/spend-limits)
