# Sicherheitsrichtlinie

DT-001 ist ein ausführbarer Testaufbau, keine aktivierte Produktionsplattform.
Alle Demo-Agenten und Demo-PRs sind synthetisch. Testprozesse und lokale Git-Commits
werden tatsächlich ausgeführt. Cloud-Aufträge, produktive Reviews, automatische
GitHub-Merges und Deployments sind nicht aktiviert.

Der lokale Runner verarbeitet ausschließlich die vertrauenswürdigen synthetischen
Fixtures dieses Repositories. Er entfernt geerbte Zugangsdaten aus der Prozessumgebung,
verwendet keine implizite Shell und beendet Prozessgruppen bei Zeitüberschreitung.
Er ist **keine Betriebssystem-Sandbox**: Dateisystem und Netz müssen vor fremdem Code
durch eine getrennte Laufzeitumgebung eingeschränkt werden.

Entwickler, Reviewer und Merger dürfen produktiv weder Credentials noch schreibbare
Arbeitsverzeichnisse teilen. Autorisierungen und freigegebene Controller-Versionen
müssen außerhalb eines bearbeiteten Projektbranches liegen. Die In-Memory-Nachweise
des Testtreibers bieten keine kryptografische Identitätsprüfung oder Prozessisolation.

Änderungen an Steuerung, Tests der Schutzmechanismen, Workflows, Projektanbindung,
Konfiguration, Sicherheitsregeln, AGENTS.md und Berechtigungen werden manuell gemergt.
Ein erfolgreicher CI-Lauf ist keine Erlaubnis zur Selbstfreigabe.

Keine Secrets im Repository, keine Administrator-/Bypass-Fallbacks, kein automatisches
Deployment. GitHub-Zugriffe erfolgen nur auf ein einzeln autorisiertes Repository.
Fehlende GitHub-Planfunktionen, unbekannte Regeln oder fehlende Nachweise sperren.

Sicherheitsprobleme dem Repository-Eigentümer über einen verfügbaren privaten
GitHub-Kanal melden. Keine Zugangsdaten oder ausnutzbaren privaten Details öffentlich
veröffentlichen. Eine veröffentlichte Sicherheitskontaktadresse ist noch nicht eingerichtet.

Details: [Berechtigungen und Vertrauensgrenzen](docs/security.md).
