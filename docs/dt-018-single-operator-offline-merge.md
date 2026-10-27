# DT-018 – Manuelle Einzelbetreiber-Freigabe für Offline-Code-Merges

**Antrag:** [Issue #50](https://github.com/oxfrd1337/developer-team/issues/50) · **Stand:** 25.10.2026 · **Geltung:** ausschließlich `oxfrd1337/developer-team`.

**Status nach Integration am 27.10.2026:** Dieser Governance-Text wurde mit [PR #51](https://github.com/oxfrd1337/developer-team/pull/51), Merge-Commit `9a0b497ab104216731828c03f9f63a92b080b491`, unter `main` aufgenommen. Seine **eigene** erstmalige Übernahme wurde ausschliesslich nach dem vorher bestehenden DT-010-Verfahren manuell angewiesen, **nicht** durch die hier erst neu eingefuehrte DT-018-Regel. Das Dokument ist **keine allgemeine Freigabe**: Jeder weitere Offline-Merge braucht eine neue, begrenzte Betreiberentscheidung; reale Provider-GETs, Runtime-Pins und Live bleiben separat gesperrt.

## 1. Zweck und erlaubte Wirkung

Dieses Verfahren ersetzt für einen **manuellen, ausschließlich offline/synthetisch geprüften Quellcode-Merge** die pauschale Pflicht, dass QA und Security ihren Bericht unter verschiedenen GitHub-Benutzerkonten veröffentlichen müssen. Der Betreiber kann das **nachvollziehbar als begrenztes Restrisiko** annehmen, wenn die technischen Prüfungen nachweisbar in getrennten Aufgaben erfolgt sind.

**Nicht geändert:** Der technische MergeGate, Credentials-/Rollenverträge, produktive Reviewerattestierungen, GitHub-Schutzregeln und der gesamte Agents-API-/Cloud-/Release-/Live-Freigabepfad. Die Regel ist eine menschliche Entscheidung über das Zusammenführen von Quellcode und **keine** Autorisierung, den Code mit echten Credentials, bezahlten Agenten oder Produktionssystemen auszuführen.

| Vorgang | Durch DT-018 zulässig? |
| --- | --- |
| Manueller GitHub-Merge eines offline geprüften PR nach dokumentierter Betreiberentscheidung | **Ja**, unter allen Anforderungen dieses Dokuments und GitHub-Schutzregeln |
| Manueller Merge geschützten Controller-/Security-Codes | **Nur** mit gesonderter expliziter Risikoentscheidung für den konkreten PR und HEAD |
| Automatischer Merge, Merge-Token, Release-Pin-Ausstellung, GitHub-Admin-Bypass | **Nein** |
| Echte Provider-GETs mit Secrets, Agents-API-Create/Submit/Cancel, kostenpflichtige Cloud-Tasks | **Nein** |
| Deployment, Host-/Rollenisolation attestieren, Live-/Go-Live-Freigabe | **Nein** |

## 2. Drei getrennte Arbeitsaufgaben; keine vorgetäuschte Identitätstrennung

1. **Developer:** Implementierung und Tests in einem genehmigten Scope auf einem separaten Branch; keine eigene QA-/Security-Freigabe.
2. **QA:** Ein eigener ausschließlich lesender Auftrag für den vollständigen, unveränderlichen PR-HEAD; eigene Nachweise inklusive zusätzlicher Regressionen/Negativfälle, Grenzen, Ergebnis und Verweis auf die Aufgabe.
3. **Security:** Ein weiterer eigener ausschließlich lesender Auftrag für exakt denselben HEAD; Trust-Grenzen, Secrets, Berechtigungen, Risiken und eigene Angriffs-/Negativtests dokumentieren.

QA/Security dürfen sich auf den Entwicklerbericht zur Orientierung beziehen, aber nicht dessen PASS als eigene Untersuchung übernehmen. **Getrennte Aufgaben, Modelle, Chatfenster oder Rollenbezeichnungen beweisen keine kryptografisch getrennten Identitäten, Cloud-Umgebungen oder Credentials.** Wenn beide GitHub-Kommentare von `oxfrd1337` stammen, lautet der formelle Nachweis weiterhin `FORMAL_REVIEWER_INDEPENDENCE = UNSUPPORTED`. Das darf nicht als `PASS` ausgegeben werden.

Die Ausnahme erlaubt allein die **bewusste Annahme dieser organisatorischen Restunsicherheit durch den Betreiber für den konkreten manuellen Offline-Merge**. Sie erstellt keine unabhängigen Review-Credentials und darf nicht vom automatischen Merger ausgewertet werden.

## 3. Pflichtnachweise vor einer Betreiberentscheidung

- **Identität des Änderungssatzes:** Repository, Zielbranch, PR-Nummer, Basis- und HEAD-Commit als vollständige SHA-40; vollständiger Diff inklusive neuer/gelöschter/umbenannter Dateien; freigegebener Scope und geänderte geschützte Pfade.
- **CI:** Alle vorgeschriebenen GitHub-Checks für den genau zugehörigen HEAD und – wenn GitHub einen synthetischen Testmerge prüft – dessen Eltern und Tree; Zahl der Tests, Skips, Coverage, Security-Lint, Build und Smoke. Kein bloßer Gesamtstatus.
- **QA + Security:** Je ein nachvollziehbarer eigener Bericht derselben vollen HEAD-SHA, eigenständige Negativprüfungen, genaue PASS-/FAIL-/UNSUPPORTED-Matrix und Hinweise, welche Schlussfolgerungen *nicht* belegbar sind.
- **Technische Sperrgründe:** Kein offenes relevantes technisches FAIL, keine ungeklärten P1/P2-Befunde, keine Secretoffenlegung und kein ungeprüfter oder veränderter Pflichtcode. Widersprüchliche, fehlende, nicht ausführbare oder veraltete Pflichtprüfungen sperren.
- **Schutzregel-Sicht:** GitHub-Branchschutz/Rulesets, Pflichtchecks, erforderliche Approval-Regeln und Merge-Berechtigungen in GitHub selbst manuell prüfen. Wenn der verwendete Connector diese Regeln nicht lesen kann, ist dies **kein PASS**; die Bestätigung muss außerhalb des Connectors erfolgen. Keine Admin-Bypass-Aktion.
- **Hostisolation:** Ein übersprungener Bubblewrap-/Sandbox-Test bleibt `HOST_ISOLATION_FOR_LIVE = UNSUPPORTED`. Für ausschließlich manuellen Quellcode-Merge muss die fehlende Runtime-Isolation ausdrücklich als **nicht abgenommen** protokolliert werden; für echte Agentenausführung bleibt sie ein Blocker.

Ein neuer Commit, Rebase, Zielbasiswechsel, andere Dateiliste oder geänderter Scope macht die bisherigen Bindungen **inhaltlich veraltet**. Bei technischen Änderungen beide Reviews, passende Tests und CI gegen den neuen Stand erneut prüfen. Reine Neuverknüpfung älterer Bericht-URLs ist unzulässig.

## 4. Geschützte Steuerungs- und Sicherheitsbereiche

Die geschützte Oberfläche aus `AGENTS.md`, `SECURITY.md` und `docs/security.md` bleibt bestehen, insbesondere `developer_team/`, `tests/`, `.github/`, `AGENTS.md`, `SECURITY.md`, Konfiguration, Provider-/Credential-/FD-/Scope-/Release-/Merge-Komponenten. **Diese PRs werden immer manuell gemergt**, niemals von Codex, einem Controller-Gate oder einer Release-Automation.

Bei Änderungen an dieser Oberfläche ist zusätzlich im Freigabetext konkret anzugeben, welche Trust Boundaries verändert wurden, was die Security-Abnahme technisch bestätigt hat, welche Aussagen nicht belegt sind und weshalb das Zusammenführen in `main` **keine** produktive Aktivierung darstellt. Der Betreiber kann eine Ausnahme auch bei grüner CI ablehnen.

**Die vorliegende Governance-Dokumentation selbst ist eine Änderung der Freigaberegel. Ihre erste Übernahme darf sich ausdrücklich nicht auf DT-018 stützen.**

## 5. Zeitlich und sachlich begrenzte Betreiberfreigabe

Die Freigabe ist **niemals allgemein oder dauerhaft**. Sie ist auf genau eine PR-/Basis-/HEAD-Kombination beschränkt und erfolgt erst nach unabhängiger Sichtung des vollständigen Änderungssatzes, der technischen Reviews und der tatsächlichen GitHub-Schutzregeln.

Vorlage für einen gesonderten, vom Betreiber bewusst bestätigten PR-Kommentar (**Platzhalter sind keine Freigabe**):

```text
ENTSCHEIDUNG: <MANUELLER_OFFLINE_MERGE_ERLAUBT | NICHT_ERLAUBT>
Verfahren: DT-018 / Einzelbetreiber, ausschließlich manueller Offline-Code-Merge
Repository: oxfrd1337/developer-team
PR: <Nummer und Link>
Zielbranch/Basis-SHA: main / <volle 40-stellige SHA>
PR-HEAD-SHA: <volle 40-stellige SHA>
Geprüfte Dateien/Trust-Grenzen: <Pfadliste und begrenzter Änderungszweck>
CI-Nachweis: <konkreter Run, sechs/erwartete Jobs, Tests, Skips>
QA-Auftrag/technisches Urteil: <Task-/Reviewlink und PASS>
Security-Auftrag/technisches Urteil: <Task-/Reviewlink und PASS>
Nicht belegte formale Revieweridentität: UNSUPPORTED; ausschließlich für diesen manuellen Offline-Code-Merge bewusst als Risiko angenommen
Nicht belegte Host-/Live-Isolation: UNSUPPORTED; keine produktive Abnahme
Offene technische Pflichtfehler/P1/P2: KEINE, sonst STOP
GitHub-Schutzregeln aktuell im UI geprüft: <Beleg/Ergebnis, niemals Bypass>
Freigebender Betreiber / UTC-Zeit / Referenz: <ausfüllen>
Keine Berechtigung für: Auto-Merge, Deployment, echte Provider-GETs, Agentenstart, LIVE, Admin-/Scope-/Spend-/Release-Pin-Änderungen
```

Eine separat formulierte aktuelle Betreiberentscheidung ist **fuer jeden neuen PR** erforderlich. Eine Zustimmung zum Entwurf oder zu einem anderen PR kann niemals als Merge- oder Releasefreigabe fuer einen neuen Stand wiederverwendet werden.

## 6. Manuelle Abschlussprüfung und Merge

1. **Unmittelbar vor dem Merge** PR-Status, Dateiliste, Basis-SHA, HEAD-SHA, vollständige CI-/Reviewzuordnung und GitHub-Schutzregeln erneut prüfen. Abweichung oder unbekannte Schutzregel: STOP.
2. Betreiber prüft und bestätigt oben genannte Entscheidung **für genau diesen Stand**. Bei GitHub-required Approvals, die mangels unabhängiger Personen nicht vorliegen, wird **nicht** mit Administratorrechten umgangen; der Merge bleibt blockiert, bis die reguläre Regel erfüllt oder durch getrenntes genehmigtes Governance-Verfahren angepasst wurde.
3. Nur der Betreiber führt den manuellen GitHub-Merge aus. Der Controller und diese Dokumentation führen keinen GitHub-Merge aus, vergeben keine Rechte, setzen keine Checks auf `PASS` und erzeugen keine Freigabe-Datei.
4. Nach dem Merge den tatsächlichen `main`-Commit und die betroffenen Issues dokumentieren. Ein Code-Merge lässt Runtime-/Host-/Cloud-/Release- oder Agents-API-Sperren unverändert. Freigabe für reale Read-only-Erhebung oder Live-Canary gehört in einen **separaten**, strengeren Prozess.

## 7. Historischer Einzelfall: PR #45 integriert, keine Live-Freigabe

Der ursprüngliche Draft [PR #45](https://github.com/oxfrd1337/developer-team/pull/45) wurde nach Aktualisierung auf die Zielbasis `9a0b497ab104216731828c03f9f63a92b080b491` neu geprüft. Geprüfter PR-HEAD `8146725af82cb5645ccb753fcd82ae1a29e6e199`, Tree `7f77d608776d8584924f5091ce5a3797eeab2535`.

- [Finale QA](https://github.com/oxfrd1337/developer-team/pull/45#issuecomment-6440044175) und [finale Security](https://github.com/oxfrd1337/developer-team/pull/45#pullrequestreview-5665877727): **technisches PASS fuer Offline/Synthetik**. Formale Revieweridentitaet weiterhin `UNSUPPORTED`; Bubblewrap-/Hostisolation fuer Live `UNSUPPORTED`.
- [CI am geprueften PR-HEAD](https://github.com/oxfrd1337/developer-team/actions/runs/40489665893): sechs erfolgreiche Pflichtchecks, je Python 3.11–3.13 **740 bestandene Tests + 1 Isolations-Skip**, 91 % Coverage.
- [Einmalige Betreiberanweisung und begrenzte Risikoannahme](https://github.com/oxfrd1337/developer-team/pull/45#issuecomment-6440370871). Der Squash-Merge fuehrte zu `main`-Commit `4ec29a0ee27b0c306c65b299834679e45704c7a9` mit exakt demselben Tree.

Dieser bereits abgeschlossene Fall ist **kein** Praezedenz-Merge-Token. Der durch DT-018 erlaubte organisatorische Offline-Merge beseitigt **keine** produktiven QA-/Reviewer-/Host-/Release-/Provider-/Operator-Gates. Ein neuer Commit oder eine neue Basis verlangt jeweils neue Nachweise und eine neue Betreiberentscheidung.

Die naechste reine Release-Vorpruefung ist in [DT-017 – Read-only-Release-Preflight](dt-017-readonly-release-preflight.md) erfasst. **Keine reale Providererhebung freigegeben. `LIVE=NO-GO`.**
