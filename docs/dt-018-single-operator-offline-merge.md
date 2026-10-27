# DT-018 – Manuelle Einzelbetreiber-Freigabe für Offline-Code-Merges

**Antrag:** [Issue #50](https://github.com/oxfrd1337/developer-team/issues/50) · **Stand:** 25.10.2026 · **Geltung:** ausschließlich `oxfrd1337/developer-team`.

**WICHTIG: Dieser Text ist bis zum eigenständigen, ausdrücklich manuell freigegebenen Merge des Governance-PRs nur ein Vorschlag.** Weder die Aufnahme eines Issues noch der PR selbst, grüne CI oder eine Codex-Antwort bewirken eine Freigabe. Die neue Regel darf ihre eigene Übernahme nicht autorisieren.

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

Eine separat formulierte aktuelle Betreiberentscheidung ist nötig; eine Chatnachricht über den **Entwurf** dieses Verfahrens ist weder die Übernahme des Verfahrens noch die Freigabe von PR #45.

## 6. Manuelle Abschlussprüfung und Merge

1. **Unmittelbar vor dem Merge** PR-Status, Dateiliste, Basis-SHA, HEAD-SHA, vollständige CI-/Reviewzuordnung und GitHub-Schutzregeln erneut prüfen. Abweichung oder unbekannte Schutzregel: STOP.
2. Betreiber prüft und bestätigt oben genannte Entscheidung **für genau diesen Stand**. Bei GitHub-required Approvals, die mangels unabhängiger Personen nicht vorliegen, wird **nicht** mit Administratorrechten umgangen; der Merge bleibt blockiert, bis die reguläre Regel erfüllt oder durch getrenntes genehmigtes Governance-Verfahren angepasst wurde.
3. Nur der Betreiber führt den manuellen GitHub-Merge aus. Der Controller und diese Dokumentation führen keinen GitHub-Merge aus, vergeben keine Rechte, setzen keine Checks auf `PASS` und erzeugen keine Freigabe-Datei.
4. Nach dem Merge den tatsächlichen `main`-Commit und die betroffenen Issues dokumentieren. Ein Code-Merge lässt Runtime-/Host-/Cloud-/Release- oder Agents-API-Sperren unverändert. Freigabe für reale Read-only-Erhebung oder Live-Canary gehört in einen **separaten**, strengeren Prozess.

## 7. Konkreter Bezug: Draft-PR #45

Der [DT-017E-Draft-PR #45](https://github.com/oxfrd1337/developer-team/pull/45) hat technisch erfolgreiche neue [QA](https://github.com/oxfrd1337/developer-team/pull/45#issuecomment-6390675382)- und [Security](https://github.com/oxfrd1337/developer-team/pull/45#pullrequestreview-5640523882)-Berichte zum HEAD `225613d0c8114c3f9389da7b44dbaca404d337cc`. Der [CI-Lauf](https://github.com/oxfrd1337/developer-team/actions/runs/40140172442) hatte sechs erfolgreiche Jobs, je Python-Version 740 bestandene Tests und einen übersprungenen Hostisolationstest. Die formale Revieweridentität und die Host-/Live-Isolation bleiben `UNSUPPORTED`.

**Diese Fakten sind keine ausgefüllte Betreiberfreigabe.** Weil PR #45 geschützten Provider-/Credential-/Runner-Code ändert, benötigt er die zusätzliche manuelle Sicherheitsrisikoannahme; selbst ein späterer Offline-Merge gibt keinen realen Providerlauf frei. Ein vorheriger Merge dieses Governance-PRs in `main` würde außerdem die Basis von PR #45 ändern: CI-/Reviewbezüge vor einer anschließenden Entscheidung erneut prüfen und bei Stale-Befunden neu abnehmen.

**Status bis zu gesonderten Entscheidungen:** DT-018-Vorschlag noch nicht aktiv; PR #45 nicht zur automatischen Freigabe berechtigt; `LIVE=NO-GO`.