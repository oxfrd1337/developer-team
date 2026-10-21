# DT-001 · Übergabe

Historischer DT-001-Stand. Die aktuelle Erweiterung, erfolgreich geprüfte Funktionen,
fehlenden Rechte und Voraussetzungen des ersten echten Cloud-Tests stehen in
[DT-002 · Cloud-Integration](dt-002.md). Der DT-002-PR aktiviert keinen Produktivbetrieb.

Stand: 20. Oktober 2026. Der Einrichtungs-PR ist für eine manuelle Prüfung vorgesehen.
Er wird nicht automatisch gemergt. Das System bleibt ohne ausdrückliche Erstfreigabe
im sicheren Testmodus. Es wurde kein externes Projekt angebunden oder verändert.

## Implementierte Komponenten

Python-Kern ohne externe Laufzeitabhängigkeiten; fünf logische Rollen und austauschbare
Agenten-/Plattformverträge; versionierte strikte Projektkonfiguration; AGENTS.md und
Sicherheitsrichtlinien mit Hashbindung; persistenter Zustandsautomat und Ereignisjournal;
Korrekturbudgets, Prozesssperre und kontrollierte Unterbrechung; lokale Git- und
Testausführung für synthetische Projekte; unabhängiger QA-Prozess für das Beispiel;
Security-Testfälle; zentrale Merge-Prüfung; GitHub-REST- und experimenteller Codex-CLI-
Gateway; sichere CLI; GitHub Actions sowie Architektur-, Test-, Sicherheits-, Kosten-
und Betriebsdokumentation.

## Prüfungen

Die geforderten Fälle sind in [testing.md](testing.md) den Tests zugeordnet.
Lokal bestanden die synthetischen Ende-zu-Ende- und Negativtests, Ruff einschließlich
Sicherheitsregeln, Formatprüfung und Wheel-/SDist-Bau. Die Codex-Probe bestätigte
Version `0.163.0`, Cloud-Submit-/Status-/Diff-Hilfe und ChatGPT-Anmeldung.
Sie bestätigte **keinen** entfernten Rollenauftrag.

Die endgültige Testzahl, Abdeckung und der Status der entfernten GitHub-Actions-Läufe
werden in der PR-Beschreibung mit Commitbezug festgehalten. Ein erfolgreicher
synthetischer Review ist keine Behauptung eines durchgeführten Cloud-Reviews.

## Was bereits selbstständig arbeitet

Der sichere lokale Testtreiber durchläuft Planung, Architektur, echte Codeänderung,
Git-Commit, echte Pflichttests, separate QA-/Security-Prüfungen, begrenzte Korrekturen,
erneute Verifikation, simulierten PR und Merge-Gate ohne menschliche Zwischenfreigabe.
Negative Szenarien eskalieren mit konkreten Vorschlägen oder blockieren den Merge.
Pause/Fortsetzung invalidiert gespeicherte Prüfnachweise und vermeidet doppelte PRs.
Die Anforderungen und Agentenentscheidungen des Beispiels sind deterministisch
geskriptet; allgemeine natürliche Anforderungen werden noch nicht von Cloud-Agenten bearbeitet.

## Was produktiv noch fehlt

Echte isolierte Codex-Cloud-Rollenläufe mit überprüftem Ergebnisimport, Task-Lifecycle
und Zeit-/Kostenbudget; vertrauenswürdige unabhängige QA-/Security-Attestierungen und
Abnahmeberichte; Herkunftsprüfung der Workflow-/Controller-Version; durchgesetzte
Rollen- und Credential-Isolation; projektbeschränkter separater Merger; echter
synthetischer Cloud-Pilot mit positiven und negativen Fällen. Der Live-Collector
bleibt deshalb ausdrücklich unverifiziert und der Live-Treiber gesperrt.

## Einmalige Berechtigungen und nächste Schritte

Zuerst den Bootstrap manuell prüfen. Anschließend die fehlenden Integrationen in
gesonderten PRs vervollständigen und nach ausdrücklicher Freigabe einen synthetischen
Cloud-Pilot durchführen. Für jedes spätere Projekt sind Repository-/Umgebungsfreigabe,
minimale getrennte Identitäten und Schutzregeln einzeln einzurichten. Zugangsdaten
bleiben außerhalb der Repositories. Danach folgen die gesonderte Erstfreigabe des
Systems und eine ausdrückliche Auto-Merge-Freigabe des jeweiligen Projekts.

Die vollständige Reihenfolge und Berechtigungsmatrix stehen in
[onboarding.md](onboarding.md). Es werden weder zusätzliche API-Schlüssel noch
kostenpflichtige Dienste für die lokale Demo benötigt. Potenzielle spätere Codex-/
Actions-Nutzung und Planbeschränkungen sind in [integrations.md](integrations.md) erläutert.
