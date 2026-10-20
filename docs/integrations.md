# Schnittstellen, Kosten und technische Einschränkungen

Prüfstand: 20. Oktober 2026. Geprüft wurden Repository-Metadaten, tatsächliche
lokale CLI-Hilfe und offizielle Dokumentation, bevor die Adapter implementiert wurden.

## Tatsächlich geprüft

| Schnittstelle | Beobachtung | Aussagegrenze |
| --- | --- | --- |
| Privates `oxfrd1337/developer-team` | Zugriff und Standardbranch `main` vorhanden; Repository-Auto-Merge bei der Bestandsaufnahme deaktiviert | Bestehender Einrichtungszugang ist keine produktive Merger-Identität |
| Codex CLI | `codex-cli 0.163.0`; `codex cloud` als experimentell gekennzeichnet | CLI-Vertrag kann sich ändern |
| Cloud-Submit | Hilfe zeigt `cloud exec --env ENV_ID --branch BRANCH --attempts N QUERY` | Kein entfernter Entwicklungsauftrag gestartet |
| Cloud-Status/Diff | Hilfe für `cloud status TASK_ID`, `cloud diff TASK_ID`; `cloud list --json` verfügbar | Keine vollständige maschinenlesbare Ergebniskette für Rollen verifiziert |
| Anmeldung | `codex login status` meldete ChatGPT-Anmeldung | Beweist weder Projektfreigabe noch verfügbare Cloud-Limits oder isolierte Reviewer |
| GitHub REST | PR-Erstellung, Check-Runs, Branch Protection und SHA-gebundener Merge dokumentiert | Adapterverträge sind mit nachgebildeten Antworten getestet; Live-Merge nicht ausgeführt |

Der Probe-Befehl wiederholt ausschließlich Versions-, Hilfe- und Anmeldestatusprüfung.
Der Gateway baut echte CLI-Aufrufe mit einem Versuch auf und verweigert sie im
Testmodus. Ein unbekanntes Receipt-Format ist ein unklarer Submit-Ausgang und löst
keine automatische Wiederholung aus. Ein Receipt enthält `verified_execution=False`;
es ist weder ein abgeschlossener Task noch ein Review-Beleg.

Der beobachtete CLI-Einstieg ist die Grundlage des Cloud-Gateways. Ein eigenständiger
stabiler Cloud-REST-Vertrag für die gesamte hier benötigte Nachweiskette wurde in
dieser Prüfung nicht nachgewiesen. Es werden keine vermuteten Endpunkte verwendet.
Der lokale Codex-SDK-/`codex exec`-Betrieb ist nicht automatisch eine Codex-Cloud-
Integration und wird im Bootstrap nicht als Ersatznachweis ausgegeben.

Offizielle Referenzen:

- [Codex-CLI-Befehle](https://developers.openai.com/codex/cli/reference/): Cloud-Auftrag, Umgebung und CLI-Scripting.
- [Codex-Authentifizierung](https://developers.openai.com/codex/auth/): ChatGPT-Anmeldung für Cloud; lokale API-Key-Nutzung ist davon zu unterscheiden.
- [Codex Cloud](https://developers.openai.com/codex/cloud/): Cloud-Umgebungen und Repositoryzugriff.
- [GitHub: Pull-Request-REST-API](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request): Merge mit erwartetem HEAD-SHA und möglichen Konfliktantworten.
- [GitHub: geschützte Branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches): Schutzregeln und Herkunft von Pflichtchecks.
- [GitHub: Pflichtchecks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks): Belege müssen zum aktuellen Commit gehören.

## Noch fehlende produktive Integrationen

- Isolierte Cloud-Rollenläufe samt Task-Lifecycle, Timeouts und kontrolliertem Recovery.
- Sicherer Ergebnis-/Diff-Import mit exaktem Commitbezug und tatsächlichem Testlauf.
- Vertrauenswürdige getrennte QA-/Security-Attestierungen und vollständige Kriteriennachweise.
- Prüfung der tatsächlichen Laufidentität und freigegebenen Controller-/Workflow-Version;
  Check-Name und gemeinsame Actions-App-ID reichen nicht.
- Ein projektbeschränkter Merger ohne schreibbaren Agenten-Checkout und ohne Bypassrechte.
- Verifizierte Regeln für zusätzliche GitHub-Pläne, Rulesets, Merge Queues und Enterprise-Hosts.

Die letzten Punkte sind Sperrgründe. Sie werden nicht durch ein `enabled=true`
oder eine angenommene Anmeldung ersetzt. Der lokale Engine-Treiber unterstützt
derzeit ausschließlich simulierte Agenten und simulierte Delivery bei aktivem Testmodus.

## Kosten

Die lokale Demo benötigt nur die vorhandene Python-/Git-Laufzeit. Es werden keine
externen Dienste, zusätzlichen OpenAI-API-Schlüssel, Datenbanken als Dienst oder
dauerhaften Worker angelegt. SQLite und die Laufzeitmodule stammen aus der Standardbibliothek.
Entwicklungswerkzeuge sind versioniert und keine Produktivabhängigkeiten.

Spätere Codex-Cloud-Arbeit verbraucht je nach ChatGPT-Plan/Workspace und Limits
enthaltenes Nutzungskontingent oder freigegebene zusätzliche Credits. Ein vorhandenes
Abo bedeutet keine unbegrenzte kostenfreie Automatisierung. GitHub Actions in privaten
Repositories kann enthaltene Minuten und Artefaktspeicher nutzen bzw. zusätzliche
Kosten verursachen. Schutzfunktionen können einen geeigneten GitHub-Plan verlangen.
Aktuelle Konditionen vor Aktivierung anhand der eigenen Kontoeinstellungen prüfen;
hier wird kein Kostenplan gebucht und kein fester Preis versprochen.

Ein normaler synthetischer Lauf benötigt vier logische Agentenaufrufe nach der
Planungsbündelung. Korrekturen führen zu erneuter Entwicklung und erneuten Prüfungen;
die realen Cloud-Kosten hängen von Kontextgröße, Laufzeit und Wiederholungen ab.
Budgets begrenzen die Zahl der Korrekturen und Schritte. Ein späterer produktiver
Treiber benötigt zusätzlich ein explizites Zeit-/Kostenlimit und begrenzte Statusabfragen.

## Laufzeitgrenzen

Python 3.11+; POSIX-Prozessgruppen und `fcntl`-Sperren machen den aktuellen lokalen
Treiber zu einer Linux/macOS-Anwendung. Zielsprachen sind davon unabhängig, ihre
Toolchains müssen aber gesondert bereitstehen. Windows-Controller benötigen einen
anderen Runner-/Lock-Adapter. Es gibt noch keine verteilte Warteschlange, keinen
hochverfügbaren Controller und keine allgemeine Sandbox. Diese Infrastruktur ist
für den synthetischen ersten Aufbau nicht erforderlich.
