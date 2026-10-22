# DT-012 V0.1 – Synthetischer Lebenszyklusprüfer für den ersten Agents-API-Canary

Stand: 22.10.2026 · [Issue #19](https://github.com/oxfrd1337/developer-team/issues/19) · Basis `main`: `2d3f2b96704cbb323a11d68d095781cf8fa508cd`.

**Ergebnis ist Software zur lokalen Prüfung künstlicher Ereignisfolgen, kein echter API-Adapter.**
Der Baustein `developer_team/agents_canary_replay.py` unterstützt künftig eine API-Anbindung bei der Bewertung von Einmal-Starts, Wiederaufnahme, Abbruchstatus und Kostenbeobachtung. Er kann **keine** Sitzung starten, abbrechen, bezahlen, authentifizieren oder als freigegeben attestieren.

## Warum das ein technischer Schritt ist

[DT-010](dt-010-manual-workflow.md) ermöglicht vier einzeln beaufsichtigte Codex-Aufträge. [DT-011](dt-011-provider-path.md) identifiziert die offizielle Agents API als möglichen künftigen programmierbaren Betriebsweg, aber noch ohne Kontofreigabe, API-Projekt und Kostenrahmen. Nun ist die bis dahin nur beschriebene **Lebenszyklusfolge ausführbar und mit Negativtests prüfbar**.

Dieses Modul nutzt ausschließlich Python-Standardbibliothek und hat bewusst **keine** Abhängigkeit zu OpenAI SDK, Credentialdateien, Umgebungsvariablen, Shell, Git, Netzwerk, SQLite oder GitHub. Es verändert nicht die bestehenden Controller-, Engine-, Gateway- oder Gate-Berechtigungen.

## Normalisierte synthetische Ereignisse

Die Eingabe besteht aus maximal 64 flachen Python-`dict`-Objekten. Jedes Ereignis benötigt exakt seine vorgegebene Feldmenge; Textwerte sind kompakte Kennungen, keine Modellprompts oder Provider-Token.

Pro Ereignis sind höchstens vier Felder (`MAX_EVENT_FIELDS`) und höchstens **1.024 Bytes native Dict-Speichergröße** (`MAX_EVENT_DICT_BYTES`) erlaubt. Nach der exakten nativen `dict`-Typprüfung greifen beide Grenzen **vor der ersten Schlüsseliteration, jedem Ereignis-Lookup und jeder Mengenbildung**. Die Feldanzahl allein genügt nicht: Viele Einfügungen und anschließende Löschungen können trotz nur drei oder vier sichtbarer Felder eine große interne Tabelle mit gelöschten Einträgen (Tombstones) zurücklassen. Der direkte Aufruf `dict.__sizeof__(event)` erkennt deren Kapazität ohne Iteration und ohne Python-Callbacks des Ereignisses, seiner Schlüssel oder Werte. Zu viele sichtbare Felder ergeben `too_many_event_fields`; eine übergroße Tabelle ergibt `event_dict_too_large`, im Replay jeweils kontrolliert `BLOCKED`.

**Runtime-Annahme:** Dieser Replay unterstützt dafür ausdrücklich **CPython 3.11, 3.12 und 3.13**. Dort berechnet die native Dict-Methode die Größe in konstantem Aufwand aus internen Metadaten; private Schlüssel-/Indextabellen werden einschließlich ungenutzter Kapazität mitgezählt. Gemeinsam genutzte Schlüsseltabellen von Instanz-Dictionaries werden von CPython teilweise separat bilanziert, sind in diesen Versionen aber auf 30 Schlüssel begrenzt. Kompakte native Ereignisse mit drei oder vier Feldern bleiben innerhalb des Budgets; auch native Instanz-Dictionaries und allgemeine Schlüsseltabellen werden berücksichtigt. Auf anderen Implementierungen oder Python-Versionen erfolgt vor dieser Größenprüfung und jeder Ereignisiteration eine kontrollierte Ablehnung mit `unsupported_dict_runtime`. Die unveränderte CI-Matrix führt dieselben Regressionen unter allen drei unterstützten Versionen aus.

Garantiert wird die Grenze für den von `dict.__sizeof__` gemeldeten Wert und damit begrenzte zusätzliche Tabellenverarbeitung im Prüfer, **kein rekursives 1.024-Byte-Gesamtspeicherlimit**: Schlüssel-/Wertobjekte, separat bilanzierte gemeinsame Tabellen, GC-/Allocator-Overhead und Prozessspeicher sind nicht Bestandteil dieser Messgröße. Es wird vor der Ablehnung weder eine Kopie noch eine kompaktierte Tabelle erzeugt.

Nach den Ressourcenkontrollen müssen sämtliche Schlüssel exakt native `str` sein; `str`-Unterklassen und andere Python-Schlüssel werden weiterhin vor Schlüsselvergleichen, Hash-Lookups oder Mengenbildung abgewiesen. Benutzerdefinierte `__eq__`-/`__hash__`-Methoden werden dabei nicht aufgerufen. Der Ereignistyp muss ebenfalls exakt `str` sein und wird vor seinem Schema-Lookup auf höchstens 28 Zeichen begrenzt. Übergrößen und ungültige Schlüssel ergeben kontrolliert `BLOCKED`.

| Ereignis | Benötigte Felder außer `type` | Bedeutung |
| --- | --- | --- |
| `intent_recorded` | `intent_id`, `idempotency_key` | Vom externen Betreiber/Controller vor jedem Sendeversuch dauerhaft dokumentierter Laufintent (hier nur nachgespielt) |
| `submit_attempted` | dieselben | Maximal ein Sendeversuch für exakt denselben Intent/Schlüssel |
| `submission_uncertain` | dieselben | Antwort unklar: **nicht** blind erneut senden; nur ursprünglichen Vorgang extern rekonstruieren |
| `session_receipt` | `session_id`, `turn_id` | Behaupteter Sitzungs- und Turnbezug nach einem Submit |
| `cancel_requested` | dieselben | Nur behauptete Abbruchanforderung, **kein** Nachweis der erfolgreichen Fernabschaltung |
| `agent.session.idle` | dieselben | Höchstens einmal pro Turn; vor Terminal kein Abschlussbeleg, nach Terminal bleibt dessen Behauptung erhalten |
| `agent.session.turn.completed` | dieselben | Behauptetes erfolgreiches Terminalereignis |
| `agent.session.turn.failed` | dieselben | Behauptetes fehlgeschlagenes Terminalereignis |
| `agent.session.turn.cancelled` | dieselben | Behauptetes abgebrochenes Terminalereignis; ohne Providerattestierung weiterhin unbestätigt |
| `usage_observed` | dieselben plus `amount_usd_cents` | Nur normalisierte künstliche Kostenbehauptung nach Terminalevent; kein tatsächliches Abrechnungslimit oder Rechnungsbeleg |

Das Schema ist ein **lokaler Reduktionsvertrag**, nicht das rohe API-/Webhook-JSON. Ereignisnamen orientieren sich an den offiziell dokumentierten Turns; `intent_recorded`, `session_receipt` und `usage_observed` sind **eigene, synthetische Normalisierungen**, keine behaupteten OpenAI-Webhooknamen. Ein späterer Adapter muss erst echte Providerobjekte und deren Herkunft extern überprüfen, bevor er sie abbildet.

Ein zweites `agent.session.idle` für denselben Turn ergibt immer `BLOCKED`, auch wenn `cancel_requested`, ein Terminalereignis oder `usage_observed` zwischen den beiden Idle-Ereignissen liegt. Ein einzelnes Idle ohne Terminal bleibt `INCOMPLETE`; ein einzelnes Idle nach Terminal bleibt erlaubt und erhält `SYNTHETIC_TERMINAL_OBSERVED`. Cancel-, Terminal- und Usage-Ereignisse setzen die Idle-Dublettensperre nicht zurück.

**Wichtig:** Der erwartete `intent_id` und `idempotency_key` müssen dem Replay unabhängig übergeben werden; sie dürfen nicht aus dem zu prüfenden Trace übernommen werden. API-Dokumentation empfiehlt für Folgeeingaben den gespeicherten `Idempotency-Key`-Header. Ein identischer Schlüssel beweist allein **keine** erfolgreiche einmalige Session-Erstellung und liefert keine echten Abbruchgarantien.

## Ausgaben und Grenzen

- `BLOCKED`: unerlaubte/zusätzliche Felder, falsche Bindungen, Wiederholungsversuch, doppelte Ereignisse, unerlaubte Reihenfolge oder Ressourcenverletzung.
- `INCOMPLETE`: bislang keine behauptete echte Turn-Terminalmeldung; auch ein gemeldetes Idle oder `cancel_requested` fällt hierunter. Nach `submission_uncertain` lautet die Handlungsanweisung `STOP_AND_RECONCILE_EXTERNALLY`, niemals „erneut submitten“.
- `SYNTHETIC_TERMINAL_OBSERVED`: lokal syntaktisch stimmige Terminalbehauptung. **Weder** ein extern verifizierter Turn noch eine API-, Sicherheits-, Kosten- oder Mergefreigabe; auch das Endereignis `failed` ergibt diesen strukturellen Replaystatus und wird gesondert als `terminal_kind_claimed` sichtbar.
- Bei **allen** Ereignisfolgen sind `provider_verified`, `cancel_verified`, `billing_verified`, `live_authorized` und `merge_authorized` **konstant `false`**. Ohne unabhängigen Remote-Nachweis werden keine Berechtigungen erzeugt.
- Maximal 64 Ereignisse, begrenzte Kennungen und ein Betrag-Feld als nichtnegative ganze Centzahl sind reine Ressourcen-/Schema-Schutzmaßnahmen. Es gibt keinen Datei-/FIFO-Reader. Es wird kein lokales Persistenzjournal erzeugt.

Die Grenzen beschränken die zusätzliche Verarbeitung im Replay. Bereits außerhalb des Prüfers vom Aufrufer erzeugte große Pythonobjekte können nicht rückwirkend speicherbegrenzt werden; ihre vorherige Speicherbelegung und Aufbaukosten bleiben bestehen. Auch beim vorherigen Erzeugen eines `dict` ausgeführte Schlüssel-Callbacks liegen außerhalb dieser Prüfung. Der Replay ist keine Sandbox für den aufrufenden Pythoncode; die Eingabe darf während der Prüfung nicht nebenläufig verändert werden. Exakte native Typprüfungen schützen auch die vorangestellten Listen-/Objektoperationen sowie Ereignistypen, Referenzen, Betreiberkennungen und Beträge vor benutzerdefinierten Methoden.

## Lokale Verwendung (synthetisch, kostenlos)

In einem ausgecheckten Repository über Python, ohne API-Projekt oder API-Key:

```python
from developer_team.agents_canary_replay import replay_canary_trace

events = [
    {"type": "intent_recorded", "intent_id": "demo", "idempotency_key": "key1"},
    {"type": "submit_attempted", "intent_id": "demo", "idempotency_key": "key1"},
    {"type": "session_receipt", "session_id": "fake-session", "turn_id": "fake-turn"},
    {"type": "agent.session.turn.cancelled", "session_id": "fake-session", "turn_id": "fake-turn"},
]

report = replay_canary_trace(
    events, expected_intent_id="demo", expected_idempotency_key="key1"
)
assert report["status"] == "SYNTHETIC_TERMINAL_OBSERVED"
assert report["cancel_verified"] is False
assert report["live_authorized"] is False
```

Tests (keine API-Aufrufe):

```sh
python -m unittest tests.test_agents_canary_replay -v
python -m unittest discover -s tests -t . -v
```

Die Negativtests prüfen doppelte/unbekannte Submits, falsche ID-/Turnbindungen, nur angeforderten Abbruch, Idle ohne Terminalstatus, Terminalkonflikte, fingierte Rechte, Kostenfelder, unerwartete Nested Objects, zu große Eingaben und den Verzicht auf Netzwerk-/Shell-/Dateizugriff. S1-Regressionen umfassen weiterhin 4.096 und 65.536 Zusatzfelder sowie Ereignistypen mit 29, 4.096 und 65.536 Zeichen; überwachte Schema-/Mengenoperationen dürfen vor der Ablehnung nicht aufgerufen werden. S1-R1 ergänzt native Tabellen nach 256, 4.096, 65.536 und 262.144 Löschungen mit jeweils drei und vier verbleibenden Feldern: Ein Opcode-Wächter verhindert bereits das Erreichen der ersten Iteration über das aufgeblähte Ereignis. Weitere Regressionen prüfen kompakte Drei-/Vierfeld- und Instanz-Dictionaries, die benachbarten realen Tabellenkapazitäten unterhalb/oberhalb der 1.024-Byte-Grenze, Callbackfreiheit der Größenprüfung und Ablehnung nicht unterstützter Runtimes. Alle bisherigen 56 Replay-Testmethoden bleiben unverändert erhalten, einschließlich der S2-Callbacktests und sämtlicher Q1-Idle-Dublettenfälle. S2 ersetzt sämtliche Schema-Schlüssel durch `str`-Unterklassen, zählt Callbacks und aktiviert gezielt auslösende Vergleichs-/Hash-Exceptions. Weitere Typnegativtests decken Container, Werte und Betreiberkennungen ab. GitHub-CI wird separat am neuen HEAD kontrolliert.

## Konkreter nächster Schritt – neue Betreiberentscheidung nötig

Für genau **einen** echten rein synthetischen, lesenden Agents-API-Canary wäre gesondert nötig:

1. Ein OpenAI-API-Projekt mit bewusst freigegebener separater Abrechnung und auf ein Testprojekt eingeschränkten Rechten. Den API-Key **nie in diesen Chat, GitHub, Codex-Task oder Prompt kopieren**; nur in einem passend isolierten externen Controller verwalten.
2. Ein vorher vereinbartes **Ausgabenbudget** und tatsächlich konfigurierter Projekt-Hard-Spend-Limit sowie eine Warnschwelle. Die Plattform weist darauf hin, dass Hardlimits nicht sofort durchgesetzt werden können; ein Überschreiten um geringe Beträge ist möglich.
3. Ausdrückliche Entscheidung zur **US-Datenresidenz ohne Zero Data Retention** für **rein erfundene und nicht sensible Testdaten**, keinerlei private Projekt-, Kunden- oder Geschäftsdaten.
4. Ein kontrollierter externer Runner, der nur den ersten **read-only** Canary nach Laufgrant startet, mit getrenntem Journal und nachprüfbarem Stoppreport. Keine automatische QA-/Security-Taskkette und kein GitHub-Write.
5. Erneut ausdrückliche Freigabe für den **einzelnen kostenpflichtigen Start**. DT-012 setzt das nicht um, und der bisherige produktive `CodexCloudGateway.submit()/collect()` bleibt bedingungslos gesperrt.

Offizielle Informationsquellen: [Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview), [Sessions / Idempotency / Cancel](https://developers.openai.com/api/docs/guides/agents-api/sessions), [Quickstart mit Projektberechtigungen](https://developers.openai.com/api/docs/guides/agents-api/quickstart), [Spend Limits](https://developers.openai.com/api/docs/guides/spend-limits).

**Beweisaussage dieses PR:** Das synthetische Szenario ist strukturiert reproduzierbar. Keine echte Cloudlaufzeit, keine Provideridentität, kein Geldlimit, keine Hostisolierung und keine tatsächliche Remote-Stoppfunktion wurden dadurch bewiesen.
