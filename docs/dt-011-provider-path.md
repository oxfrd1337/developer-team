# DT-011 V0 – Betriebsweg zur echten, kontrollierten Agentenautomatisierung

Stand: 22.10.2026 · [Issue #17](https://github.com/oxfrd1337/developer-team/issues/17) · Controller-Basis `6385b53a9926a91350f01158126489284d5c9526`.

**Entscheidungsstand: GO nur für die Vorbereitung eines *separat freizugebenden*, rein synthetischen, lesenden Provider-Canarys. LIVE-/Produktivbetrieb bleibt NO-GO.** Dieses Dokument implementiert keine API-Anbindung, startet keine Agenten, bucht keine API-Ausgaben und erteilt keine Freigaben. Es ist eine betreiberlesbare Entscheidungsvorlage für die nächste eigenständige Freigabe.

## 1. Was wir schon haben und was wirklich fehlt

[DT-010](dt-010-manual-workflow.md) liefert einen funktionsfähigen, geprüften, manuell beaufsichtigten Ablauf mit vier Rollenvorlagen, Gate 0–3 und einem rein offline prüfenden Übergabeformat. [DT-008](dt-008.md) sperrt den experimentellen `codex cloud`-CLI-Gateway produktiv und begründet das fehlende Remote-Stopp-/Rollen-/Kontingentvertrauen. Die dortige Untersuchung ist **historisch** auf den Cloud-CLI-Vertrag bezogen; sie ist kein automatisch gültiges negatives Urteil über die neu dokumentierte **Agents API**.

Der Wunsch ist, eine Anforderung **einmal** freizugeben und anschließend Planung, Entwicklung sowie getrennte QA-/Security-Prüfungen kontrolliert ablaufen zu lassen. Nicht das Kopieren der vier Prompts ist das eigentliche Problem, sondern ein nachweisbar administrierter Betriebsweg: feste Git-Commits, getrennte Rollenberechtigungen, durables Journal, überprüfbare Abbrüche, tatsächliche Kostenkontrolle und GitHub-Regeln. Bestehende `engine.py`, `store.py`, `authority.py` und `gate.py` dürfen dafür nicht durch einen zweiten Controller ersetzt werden.

## 2. Drei tatsächliche Betriebswege

| Weg | Was ist heute erreichbar? | Zusätzliche Voraussetzungen / Grenzen | Empfehlung |
| --- | --- | --- | --- |
| A – Codex Cloud manuell, DT-010 | Vier bewusst einzeln gestartete und geprüfte Aufträge über die bisherige Codex-Oberfläche; bekanntes Verfahren | Keine automatisch attestierten Cloud-Rollen; im Repo gesperrter echter Cloud-CLI-Gateway; hoher manueller Aufwand. Ein ChatGPT-Abonnement ersetzt keine programmierbare Schnittstelle. | **Sicherer Rückfallweg**, bis B oder C real geprüft und freigegeben ist |
| B – Offizielle OpenAI Agents API | Dokumentierte verwaltete Agentensitzungen, Unteragenten, Events, Sitzungsfortsetzung und Cancel-Ereignis; konfigurierbares Session-`spend_control` | Separates OpenAI-API-Projekt, Autorisierung und **verbrauchsabhängige API-Abrechnung**; derzeit **nur US-Datenresidenz und kein ZDR** für die Agents API. Unabhängige Rollen-/Host-/Credential-Isolation ist nicht durch bloße Subagent-IDs bewiesen. | **Bevorzugter Gegenstand des nächsten begrenzten Canarys**, nur nach gesonderter Daten-/Kostenentscheidung |
| C – Eigener Runner mit Codex SDK / app-server | Programmierbarer lokaler Prozess und Task-/Thread-Lifecycle; existierenden Codex-Login/Abrechnungsweg separat klären | Isolierte Hostumgebungen, Secrets, Egress, journalisierte Stopps/Leases, verifizierte Reviewer und Betriebsverantwortung müssten wir selbst aufbauen und abnehmen; ChatGPT-Login heißt nicht automatisch kostenfreier/geeigneter Serverbetrieb. | Alternative, wenn B wegen Datenhaltung, Konditionen oder Kontrollen nicht zulässig ist |

**Nicht verwechseln:** Die Agents API ist **nicht** der frühere `codex cloud exec --env ...`-CLI-Aufruf. Ihre Sitzung, Abbruch- und Abrechnungsfunktionen ersetzen nicht die gesonderte Prüfung der GitHub- und Hostkontrollen. Die Managed-Agents-API ist noch nicht mit diesem Konto, einer Projektberechtigung, einem echten Geldlimit oder einer echten Sandbox geprüft worden.

## 3. Was an der offiziellen Agents API konkret neu ist

- **Start / Status:** Eine API-Sitzung erhält eine `session_id`; einzelne Turns und Ergebnisse sind abrufbar. Streams und Webhooks können Fortschritt anzeigen. Nach Verbindungsabbruch soll die vorhandene Sitzung abgefragt und **nicht blind neu gestartet** werden.
- **Abbruch:** Das dokumentierte Ereignis `agent.session.input.cancel` fordert den Abbruch des aktuellen Turns an. Erst ein überprüfter `cancelled`-/anderer terminaler Zustand **plus** Kontrolle möglicher Tool-Nebenwirkungen und abgerechneter Nutzung bestätigt den tatsächlichen Abschluss. Eine gesendete Anfrage ist keine bestätigte Fernabschaltung.
- **Mehrere Agenten:** `multi_agent.enabled` und `max_concurrent_subagents` erlauben Delegation. **Eigenes Kontextfenster ist nicht gleich isolierter Host, eigenes Secret, eigener unveränderlicher Git-Checkout oder unabhängige Prüferidentität.** Die spätere echte QA und Security brauchen getrennte, attestierbar read-only Laufumgebungen und eigene, beschränkte Identitäten – möglicherweise separate Sessions statt nur interner Subagents.
- **Idempotenz und Wiederaufnahme:** Die offizielle Sitzungsanleitung beschreibt gespeicherte Sitzungs-/Turn-IDs und Idempotenzschlüssel für Folgeeingaben. Vor einem Erstsubmit muss das bestehende `RunStore`-Intent dauerhaft gespeichert sein. Unklarer Empfang: STOP, vorhandene Sitzungen/Turns abgleichen, **keinen** automatischen zweiten kostenpflichtigen Start.
- **Kosten:** Bei der Session-Erstellung kann `spend_control.limit` in **USD-Cent** angegeben werden. Dokumentierte verbrauchte Session-Beträge sind **best effort**. Zusätzlich soll ein **vom Betreiber bestätigtes API-Projekt-Hard-Spend-Limit** und eine Warnschwelle vorliegen. Ein Projekt-Hard-Limit ist laut OpenAI **nicht augenblicklich** wirksam; geringe Überschreitungen sind möglich. Weder Zeitlimit noch Token-/Taskzahl dürfen als absolute Geldgarantie ausgegeben werden.
- **Berechtigungen:** Die offizielle Schnellstartanleitung nennt ein eigenes API-Projekt und die Berechtigungen `api.agents.read`, `api.agents.write` und `api.responses.write`. Der Anwendungsschlüssel bleibt **außerhalb** jeder vom Modell bearbeitbaren Umgebung; keine Schlüsselkopie in GitHub, Prompt, Log oder Sandbox. Nur eine extern vertrauenswürdige Controllerkomponente darf Provideraktionen starten/abbrechen.
- **Daten:** Laut aktuellem offiziellen Produktstand unterstützt die Agents API **Datenresidenz nur in den USA** und **kein Zero Data Retention**. Eine spätere Übertragung privater Quelltexte oder betrieblicher Informationen braucht eine gesonderte Daten-/Vertragsentscheidung; DT-011 erlaubt keinerlei Upload. Ein erster Canary darf ausschließlich **frei erfundene, nicht sensible Testtexte** enthalten.
- **Technische Durchsetzung:** Managed Sandbox ist nicht automatisch eine nachgewiesene unabhängige Reviewer-VM; GitHub `main.protected=false`, fehlende Deployment-Audit-Endpunkte und unbestätigte Kostengrenzen bleiben reale NO-GO-Punkte für autonomen produktiven Code-Merge.

## 4. Kleinstmöglicher zukünftiger Ablauf – ohne zweiten Orchestrator

```text
Ein Betreiberentscheid + konkreter Laufgrant (separate Freigabe)
  -> bestehender Controller: dauerhaftes RunStore-Intent, Scope/Commit/SHA festnageln
  -> genehmigter Provider: eindeutige Session-/Turn-ID, gesonderte Kosten-/Zeitgrenzen
  -> Orchestrator/Architektur liefert Kriterien und Änderungsplan
  -> Developer nur im synthetischen freigegebenen Dateiscope
  -> unabhängige Tests am versiegelten Commit
  -> QA in unabhängig begrenzter, read-only Prüfumgebung am selben Commit
  -> Security separat read-only am selben Commit + unabhängige Provenienz
  -> GitHub-PR-Gegenprüfung: Repo/HEAD/Basis/Dateien/Checks/Schutzregeln aktuell
  -> STOP oder konkrete Benutzerentscheidung zum späteren MANUELLEN Merge
```

Dies ist ein **Zielbild**, keine heute verfügbare Funktion. Der produktive `CodexCloudGateway.submit()`/`collect()` bleibt bedingungslos gesperrt; ein neuer API-Adapter darf bei künftiger Entwicklung weder den vorhandenen Gate-/Authority-Pfad umgehen noch Fake-Providerbelege als echte Attestierung ausgeben. Alle Repositorys außerhalb des rein synthetischen Testumfangs bleiben ausgeschlossen.

## 5. Objektiv prüfbare Gate-Liste vor einem bezahlten Canary

**Gate B0 – Betreiber- und Datenentscheid (noch offen):**

1. Anbieterweg B (Agents API) **und** das separat abgerechnete API-Projekt ausdrücklich freigeben; tatsächliche Projektberechtigung und die Bedingungen des API-Zugangs prüfen. Diese Prüfung kann nicht aus einem ChatGPT-Abonnement abgeleitet werden.
2. Bewusst bestätigen, dass der geplante Canary ausschließlich erfundene synthetische Texte verwendet, und die **US-Datenresidenz / fehlendes ZDR** für genau diesen Test akzeptieren. Noch keine privaten Repositories oder Kundendaten senden.
3. Einen konkreten maximalen Kostenrahmen in USD, eine Session-`spend_control.limit`, einen *tatsächlich eingeschalteten* Projekt-Hard-Cap und Warnschwellen vorab festlegen und prüfen. Eine mögliche kurzzeitige Kostenüberschreitung explizit berücksichtigen. **In DT-011 wird kein Betrag angenommen oder aktiviert.**
4. Prüfen, wo der vertrauenswürdige Controller und die API-Berechtigung laufen sollen. Falls noch nicht vorhanden: erst minimalen administrierten Betriebsweg einrichten; keine API-Keys in Agent-Workspaces ablegen.

**Gate B1 – genau ein künftig gesondert freigegebener Canary (noch NICHT freigegeben):**

1. Nur **eine** beschränkte **read-only** Sitzung mit frei erfundenem Text starten, zunächst **ohne** GitHub-Schreibwerkzeuge, ohne echtes Repository-Material, ohne Deploy- oder Mergeberechtigungen und ohne automatische Subagenten-Starts.
2. Tatsächlichen `session_id`, Turnstatus, Events, Nutzungs-/Kosteninformationen und Provideraccountbezug extern dokumentieren. Ein synthetischer Debug-Text oder eigener `PASS`-Claim genügt nicht.
3. Den Abbruchvertrag nach einem **vorher festgelegten Testverfahren** gesondert auslösen und den resultierenden terminalen Zustand abgleichen; bei unklarer Antwort weitere Starts sofort sperren.
4. Unbekanntes Ergebnis / Timeout: journalisieren und extern rekonstruieren; keine neuen Sessions ohne eindeutiges Wissen über den vorherigen Zustand.
5. Ergebnisbericht `PASS|FAIL|UNSUPPORTED` mit belastbaren Belegen; **kein automatisches GO** für die vier produktiven Rollen. Für die nächste Phase sind separate technische Rollengrenzen, Snapshot-/Audit- und GitHub-Merge-Gates zu attestieren.

**Gate B2 – Voraussetzung für irgendeine spätere Autonomie (gesperrt):**

- Nachweisbar voneinander isolierte Developer-, QA- und Security-Rollen mit eigenen read-only bzw. eingeschränkten Schreibrechten; keine Selbstabnahme.
- GitHub-Schutzregeln für `main` technisch aktiviert und attestiert. Bei privatem Repository gegebenenfalls passender GitHub-Plan. **Nicht** das private Repository ohne neue ausdrückliche Erlaubnis öffentlich machen.
- Verifizierter kompletter PR-HEAD/CI-/Deployment-Nachweis, belastbare Remote-Stopp-/Kostenkontrolle, abgesicherter unveränderlicher Controller und Review-Collector; separate Erstfreigabe jedes späteren externen Projekts.
- Automatisches Zusammenführen von PRs bleibt unabhängig davon eine **gesonderte** Betreiberentscheidung. Bis dahin Merge immer manuell.

## 6. Konkrete Empfehlung / nächster entscheidbarer Schritt

**Jetzt:** Diesen rein dokumentarischen DT-011-V0-Nachweis als Draft-PR prüfen, **ohne** ihn als Betriebsfreigabe zu behandeln.

**Danach nur auf neue ausdrückliche Betreiberentscheidung:** Zuerst **einen** eng begrenzten, selbst dokumentierten API-Canary gemäß Gate B0/B1 anstreben, weil seine offiziellen Session-/Turn-/Cancel-/Ausgabenlimits gegenüber dem historischen Cloud-CLI-Vertrag überprüfbar beschrieben sind. Ist die separate API-Abrechnung, US-Datenresidenz oder sicherer externer Controller nicht akzeptabel, bleibt **DT-010 (manueller Betrieb)** gültig und Weg C wird nur mit konkretem eigenem Host-/Isolation-/Kostenplan bewertet.

So entsteht erstmals ein **nachweisbarer Entscheidungsweg zur echten Automatisierung**, statt weitere künstliche Controller-Simulationen zu bauen. Ein erfolgreiches DT-011-V0-Dokument ist **keine** live validierte API-Verbindung und kein finales Security-PASS.

## Quellen und Aussagegrenzen (öffentlich, Stand 22.10.2026)

1. [Agents API: Funktionen, Preise, US-Residenz und fehlendes ZDR](https://developers.openai.com/api/docs/guides/agents-api/overview).
2. [Sessions: idempotente Eingaben, Wiederaufnahme, Cancel-Event](https://developers.openai.com/api/docs/guides/agents-api/sessions).
3. [Multi-agent: Subagent-Koordination](https://developers.openai.com/api/docs/guides/agents-api/multi-agent).
4. [API-Referenz: Session-Erstellung und `spend_control`](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/create).
5. [OpenAI API: organisatorische und Projekt-Hard-Spend-Limits](https://developers.openai.com/api/docs/guides/spend-limits).
6. [Agents API: Sandbox- und Secret-Sicherheit](https://developers.openai.com/api/docs/guides/agents-api/environments/security).
7. [Codex SDK/app-server: abweichende Integrationswege](https://developers.openai.com/blog/codex-as-a-platform).
8. [GitHub: Branchschutz in privaten Repositories](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

Alle Punkte sind **Dokumentationsbelege**, nicht live getestete Eigenschaften des Benutzerkontos oder des Zielrunners. Unbekannte Account-/Providerzustände bleiben `UNSUPPORTED`. 
