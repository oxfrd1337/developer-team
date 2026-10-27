# DT-017 – Release-Vorprüfung für den Read-only-Providerlauf (NO-GO)

**Zweck:** ausschließlich die Freigabefähigkeit einer späteren kontrollierten, lesenden Provider-Evidence-Erhebung vorbereiten. Diese Anleitung **autorisiert keinen OpenAI-API-Aufruf**, keinen Secret-Zugriff, keinen neuen Runner-/Release-Pin und keinen Agents-API-Canary. Die tatsächlich gültige Basis muss unmittelbar vor jeder späteren Entscheidung neu ermittelt werden.

**Historischer Prüf-Snapshot vom 27.10.2026, vor diesem Dokumentations-PR:** `main` = `4ec29a0ee27b0c306c65b299834679e45704c7a9`, Tree `7f77d608776d8584924f5091ce5a3797eeab2535`. `main` war geschützt und hatte sechs an GitHub Actions gebundene Pflichtchecks. Dies ist **keine Release-Pin-Attestation**: Nach jedem weiteren Commit, auch einem reinen Dokumentations-Merge mit anderem Commit-/Tree-Hash, sind Quelle, Inventar und sämtliche zeitgebundenen Nachweise neu zu binden.

## 1. Bereits belegt: ausschließlich Software- und Offline-Scope

- [DT-017E PR #45](https://github.com/oxfrd1337/developer-team/pull/45) wurde manuell mit Squash-Commit `4ec29a0ee27b0c306c65b299834679e45704c7a9` in `main` integriert. Der zusammengeführte Baum entspricht dem geprüften PR-Baum; die QA-/Security-Sicht bezog sich auf den PR-HEAD `8146725af82cb5645ccb753fcd82ae1a29e6e199`.
- [QA](https://github.com/oxfrd1337/developer-team/pull/45#issuecomment-6440044175) und [Security](https://github.com/oxfrd1337/developer-team/pull/45#pullrequestreview-5665877727) waren im synthetischen Offline-Scope technisch PASS. [CI](https://github.com/oxfrd1337/developer-team/actions/runs/40489665893) am PR-HEAD: sechs erfolgreiche Jobs; je Python 3.11–3.13: **740 bestandene Tests + ein Bubblewrap-Hostisolations-Skip**, Coverage 91 %. Der Skip und die formale Trennung der GitHub-Revieweridentitaeten bleiben **UNSUPPORTED**, nicht PASS.
- [DT-018](dt-018-single-operator-offline-merge.md) betrifft nur die ausdruecklich begrenzte menschliche Offline-Code-Mergeentscheidung und **keine** Release- oder Live-Autorisierung.

## 2. Nachweismatrix: keine stillschweigenden PASS-Werte

| Gate / Voraussetzung | Aktuelle Aussage |
| --- | --- |
| Quellcodeintegration DT-017E | Belegt fuer den historischen oben genannten Codebaum, nicht fuer reale Ausfuehrung |
| Exakter finaler Commit, Tree, vollstaendiges Releaseinventar und Runner-SHA256 | Fuer die spaetere Releaseentscheidung **neu, unabhaengig und bytegenau nachzuweisen** |
| Bestehender `RUNNER_SHA256` im Broker | **Absichtlich alt**; sperrt den neuen Runner vor Secret-Auswahl; niemals eigenmaechtig ersetzen |
| Externer Release-Pin (`commit`, `tree`, `inventory_sha256`) | **MISSING** fuer den aktuellen freizugebenden Stand; keine Selbst-Pin-Ausstellung |
| `account_project_binding`, `credential_scope`, `spend_controls` | **MISSING_OR_INVALID** ohne frische externe reale Account-/Scope-/Spend-Evidence |
| `provider_contract_current`, `agent_configuration` | **MISSING_OR_INVALID** ohne aktuelle unabhaengige Pruefung/gebundenen Saved Agent |
| `secret_store`, `real_transport`, `environment_configuration` | **MISSING_OR_INVALID** ohne externe Laufzeit-/Transport-/Environment-Evidence |
| `durable_journal`, `single_canary_grant` | **MISSING_OR_INVALID** ohne belastbare externe Nachweise |
| `fresh_create_approval`, `fresh_submit_approval` | **MISSING**; diese Zustimmungen sind nie Teil eines Read-only-Laufs |
| Host-Isolation fuer Live | **UNSUPPORTED** (CI-Bubblewrap-Skip) |
| Provider-Abfragen / Mutationen in dieser Vorpruefung | **0 / 0**; `real_submissions=0`, `LIVE=NO-GO`, `live_authorized=false` |

Die Matrix ist eine **Nachweislueckenliste**, kein erzeugter Gate-Report aus einem echten Provider-Run und keine Behauptung, der Provider sei auf diesem Stand tatsaechlich befragt worden.

## 3. Ausschliesslich lesende Release-Vorpruefung (noch ohne Secrets)

1. **Zielstand einfrieren:** gegen das geschuetzte `main` exakten Commit, Tree, alle getrackten Dateiblobs und lokalen Checkout feststellen. Neu hinzugekommene Commits oder neue Branches duerfen nicht durch alte Reviews/Pins freigegeben werden.
2. **Inventar extern verifizieren:** In einem vertrauenswuerdigen sauberen, credentialfreien Checkout den **vollstaendigen** getrackten Inventarhash einschliesslich aller Runtime-/Security-/Policy-Module und den SHA-256-Wert der aktuell vorliegenden Runner-Datei kontrolliert bestimmen. Keine Datei als Ausnahme auslassen. Die Beschreibung der lesenden Inventarfunktion steht in [DT-017C](dt-017c-local-readonly-broker.md#exakte-release-bindung). Das Ergebnis ist eine Messung, **keine** Freigabe und **kein** neuer Pin.
3. **Code- und Trust-Grenzen pruefen:** finalen Release-Commit und Runner/Prepare/Collector/HTTPS/Verifier/Scope/Pin-Vertrag gegen den bereits attestierten Tree abgleichen. Keine Codeaenderung oder Replay eines alten QA-PASS als aktuelles Release-Approval.
4. **Externen Entscheider einbeziehen:** Eine davon unabhaengige Releasefreigabe muss die exakten Hashes und die Vertrauensanker der Host-/Python-/Git-Umgebung explizit bestaetigen. Erst ein gesondert autorisierter, kontrollierter Vorgang darf den externen Pin `0400` bereitstellen und den Runner-Pin anpassen, soweit technisch erforderlich. **Dieser Dokumentations-PR tut beides nicht.**
5. **Operator-/Provider-Voraussetzungen separat pruefen:** bereits vorhandene und getrennte Admin-/Canary-Identitaeten, korrekt gebundener Account, exakt freigegebene Key-Rechte und echtes Scope-Readback, Budget, Modell, Saved Agent sowie Host-/Secret-/Transportnachweise. Credential-Dateien bleiben lokal, regulaer, owner-only und **exakt `0600`**; sie werden niemals in Chat, GitHub, CI, argv, stdin, env oder Logs kopiert. Fehlt eine Voraussetzung: **HALT**.
6. **Noch keine echten GETs:** erst nach einer **zusaetzlichen ausdruecklichen Freigabe fuer genau den realen, rein lesenden lokalen Versuch** darf der bestehende Helper aus [DT-017E](dt-017e-safe-diagnostics.md#betreiberanleitung-ein-offizieller-diagnoseaufruf) am exakt gepinnten sauberen Release verwendet werden. Er ist auf maximal **vier Admin- und zwei Canary-GETs** begrenzt, ohne Redirects/Retry/Mutationen. Nur der sanitisierte Report ist relevant; fehlende oder ungueltige Gates bleiben gesperrt. `COLLECTED` ist kein `PASS`.
7. **Ergebnis getrennt abnehmen:** Erst reale, frische und unabhaengig bestaetigte Daten duerfen in die [DT-017-Gates](dt-017-controlled-acceptance.md) einfließen. Kein Auto-Create, kein agentischer Lauf, kein Session-POST. Fuer einen spaeteren Canary sind **zwei weitere getrennte** frische Betreiberentscheidungen (Create, Submit) notwendig. Hostisolation und produktive Kosten-/Stop-/Journalgrenzen bleiben eigene Nachweise.

## 4. Aufgaben und klare Stop-Grenze

- [Issue #38 – DT-017B](https://github.com/oxfrd1337/developer-team/issues/38#issuecomment-6441737932): technischer Read-only-Runner und unabhängige Release-Vorpruefung; keine neue Implementierungs-Issue erzeugen.
- [Issue #34 – DT-017](https://github.com/oxfrd1337/developer-team/issues/34#issuecomment-6441739315): gesamte Live-Gate-Matrix, separate spaetere Canary-Entscheidungen. Issues #47/#48 bleiben als historische Review-Nachweise mit formaler Identitaetsgrenze erhalten.
- Bei fehlender externer Freigabe, falscher Rolle, unbekannter Scope-Attestation, unpassendem Pin, geaenderter SHA oder ungepruefter Hostgrenze: **STOP, kein stilles Umgehen**.

**Kein Deployment, kein produktiver Key-/Spend-/Scope-Write, kein POST, kein Live. `real_submissions=0 · LIVE=NO-GO · live_authorized=false`. OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**
