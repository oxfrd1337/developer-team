# Sicherheit und Berechtigungen

Der Standard ist gesperrt: `safe_test_mode=True`, `first_release_approved=False`,
`bootstrap=True` und projektspezifisch `merge.enabled=false`. Die Demo besitzt
keine Merge-Berechtigung. Es gibt keine Deployment-Funktion und keinen Merge-Workflow.
Eine grüne CI-Prüfung hebt diese Sperren nicht auf.

## Vertrauensgrenzen

Der Controller verwendet eine **manuell freigegebene, fest gebundene Version** der
Steuerungssoftware. Er darf die Merge-Entscheidung nicht aus dem gerade zu prüfenden
PR-Branch importieren. Projektkonfiguration und AGENTS.md liefern Anweisungen, aber
keine Rechte. Projektgrants liegen außerhalb des bearbeiteten Checkouts und gelten
nur für eine Projekt-ID, ein Repository und einen effektiven Konfigurationshash.

| Bereich | Zulässige Rechte im späteren Betrieb | Ausgeschlossen |
| --- | --- | --- |
| Planung/Architektur | Ausgewähltes Repository lesen | Schreiben, Merge, Secrets |
| Entwickler | Isolierter Arbeitsbaum, Schreiben auf freigegebene Entwicklungsbranches | Geschützte Basis schreiben, Reviews ausstellen, Merge-Credentials |
| QA | Unveränderlichen Commit und Testbelege lesen, eigene Review-Attestierung ausstellen | Implementierung oder Entwicklernachweise ändern |
| Security | Unveränderlichen Commit und Richtlinien lesen, eigene Attestierung ausstellen | Rechte oder Richtlinien ändern |
| PR-Schreiber | PR im ausgewählten Repository anlegen | Andere Projekte, geschützte Basis schreiben |
| Merger | Checks/PRs/Regeln lesen, nach Gate mit `sha` mergen | Codeausführung aus dem PR, Administrator-/Regel-Bypass, Deployment |

GitHub bietet nicht für jede Operation ein perfekt aufgeteiltes Tokenrecht: Der
Merge-Endpunkt benötigt `Contents: write`; ein solches Token ist technisch auch
zu anderen Inhaltsänderungen fähig. Deshalb muss es in einem getrennten Dienst oder
Job ohne Checkout/Agenten-Code liegen, auf ein Repository beschränkt und durch
GitHub-Regeln begrenzt sein. Der Adapter ist eine zusätzliche Kontrolle, keine
Behauptung einer vom Token selbst erzwungenen ausschließlichen Merge-Erlaubnis.

Keine Tokens, Passwörter, Private Keys oder kopierte ChatGPT-Anmeldedateien im
Repository. Bestehende GitHub-/Codex-Anmeldungen werden über die vorgesehenen
CLIs genutzt. Logs enthalten in der Demo keine vollständigen Testausgaben, sondern
deren Hash und Exitstatus. Laufdaten können Anforderungen und Projektnamen enthalten
und sind als interne Daten zu behandeln. Produktiv sind Aufbewahrung, Dateirechte,
Secret-Redaktion und getrennte kurzlebige Credentials zusätzlich durchzusetzen.

## Bedingungen der Merge-Prüfung

Alle Bedingungen müssen positiv nachgewiesen sein:

- Explizite Erstfreigabe, kein Bootstrap und Freigabe des einzelnen Projekts in
  Konfiguration **und** getrenntem Controllergrant.
- Passende Repository-, Konfigurations- und Merge-Berechtigung.
- Offener, nicht als Entwurf markierter PR mit vollständiger Dateiliste.
- Alle Pflichtprüfungen erfolgreich; genau ein vertrauenswürdiger Beleg je Pflichtart.
- QA, Security und Abnahme erfolgreich, vollständige Kriterienabdeckung und keine
  blockierenden Befunde, auch nicht in zusätzlichen Berichten.
- Jeder Beleg gehört zu genau demselben Repository, HEAD, Basis-Commit,
  Konfigurationshash, Planhash und Lauf. Veraltete Belege verfallen nach Änderungen.
- Entwickler-, QA- und Security-Identitäten unterscheiden sich.
- Plattformzustand höchstens 60 Sekunden alt, keine unbekannten Berechtigungen
  oder Schutzregeln. Der GitHub-Adapter prüft unmittelbar vor dem Merge erneut.
- Tests und Dokumentation stehen im selben Änderungssatz.
- Keine Änderung geschützter Steuerungs- oder Sicherheitskomponenten.

Der GitHub-Leser prüft benannte Check-Runs einschließlich App-ID, HEAD, Status
`completed` und Ergebnis `success`. `skipped` und `neutral` werden nicht akzeptiert.
Der gegenwärtige Schutzadapter verlangt klassische strikte Branch Protection,
App-gebundene Pflichtchecks, Durchsetzung auch für Administratoren und GitHubs
positiven Mergezustand. Nicht lesbare Regeln, Rulesets-only/Queue-Sonderfälle oder
fehlende Planfunktionen werden nicht als erfüllt angenommen. Die abschließende
GitHub-Anfrage enthält den erwarteten HEAD-SHA und nutzt keinen Bypass.

Ein erfolgreicher Check-Run allein genügt dennoch nicht für fachliche Kriterien
und unabhängige Reviews. Deshalb liefert der mitgelieferte Live-Collector immer
`integration_verified=False`. Vor produktiver Freigabe muss ein separater Collector
die Rolle, tatsächliche Laufidentität, freigegebene Workflow-/Controller-Version,
unveränderliche Artefakte und Kriterienabdeckung aus attestierten Review-Berichten
prüfen. Die gemeinsame GitHub-Actions-App-ID allein unterscheidet keine sicheren
Review-Jobs von einem durch einen PR veränderten Workflow.

## Schutz vor Selbstfreigabe

`.github/`, `.developer-team/`, AGENTS.md, SECURITY.md, zusätzliche Richtlinien und
projektdefinierte Steuerungsdateien sind geschützt. Für dieses Repository umfasst
die Schutzfläche auch `developer_team/`, Schutztests, Beispiele, Paket-/Toolkonfiguration
und Onboarding. Umbenennungen berücksichtigen den alten und neuen Pfad. Solche
Änderungen dürfen nie vom eigenen automatischen Mergepfad freigegeben werden;
sie benötigen eine manuelle Prüfung und einen manuellen Merge.

Zusätzlich muss die produktive `RuntimePolicy.controller_repository` das vom Betreiber
festgelegte Steuerungsrepository benennen. Sämtliche Änderungen an diesem Repository
erfordern unabhängig von Dateimustern einen manuellen Merge. Eine unbekannte
Controller-Repository-Identität blockiert den Live-Merge ebenfalls.

Im Testmodus sind Rollenidentitäten und Belegregistrierung nur logische Trennung
innerhalb des vertrauenswürdigen Testtreibers. Eine In-Memory-Receipt beweist keinen
Cloud-Ursprung und schützt nicht gegen bösartigen Code im Controllerprozess.
Der lokale Runner ist keine Sandbox. Produktive Unabhängigkeit erfordert getrennte
Credentials, schreibgeschützte Review-Umgebungen, Netzwerk-/Dateisystemgrenzen und
ein vom Projektcode nicht änderbares Merger-Artefakt.
