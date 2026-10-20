# Spätere Projektanbindung und Erstfreigabe

DT-001 bindet kein externes Projekt an. Die folgenden Schritte beschreiben den
späteren Betriebsaufbau. Bis zu einer ausdrücklichen Erstfreigabe bleiben Testmodus
und Live-Sperre bestehen; ein manueller Merge des Einrichtungs-PRs ist noch keine
Aktivierung des Systems.

1. **Bootstrap manuell prüfen.** Architektur, Grenzen, Tests und Schutzlogik prüfen;
   diesen PR ausschließlich manuell mergen. Eine feste Controller-Version außerhalb
   künftig bearbeiteter Projektbranches als Vertrauensbasis bestimmen.
2. **Cloud-Adapter vervollständigen.** Task-Lifecycle, begrenztes Polling/Deadline,
   Ergebnisnormalisierung, sicheren Diff-Import, exakten Commitbezug und getrennte
   schreibgeschützte Review-Umgebungen implementieren. Keine privaten oder
   undokumentierten Cloud-HTTP-Endpunkte erfinden.
3. **Nachweiskette implementieren.** Einen getrennten Collector für attestierte
   Test-, QA-, Security- und Abnahmeberichte mit geprüfter Rolle, Identität,
   Workflow-/Controller-Version, Commit, Basis, Konfiguration, Plan und Lauf entwickeln.
   Ein vom PR veränderbarer Actions-Job oder ein grüner Status allein genügt nicht.
4. **Synthetischen Cloud-Pilot ausführen.** Erst nach ausdrücklicher Freigabe ein
   isoliertes synthetisches GitHub-Projekt und Codex-Umgebungen einrichten. Echte
   positive und negative Fälle einschließlich Rechteverweigerung, Commitwechsel,
   manipuliertem Workflow, Abbruch und Selbstfreigabe prüfen. Dies ist noch nicht erfolgt.
5. **Ein einzelnes Zielprojekt autorisieren.** Eigentümer, Repository, Branch,
   Toolchain, AGENTS.md-Geltungsbereiche, Sicherheitsregeln und Pflichtprüfungen
   erfassen. `.developer-team/project.toml` aus der synthetischen Vorlage ableiten,
   prüfen und den effektiven Hash außerhalb des bearbeiteten Branches freigeben.
6. **Minimale Identitäten einrichten.** Nur dieses Repository für GitHub/Codex
   freigeben. Entwickler und PR-Schreiber erhalten keine Merge-Credentials;
   QA/Security erhalten getrennte schreibgeschützte Umgebungen; der Merger läuft
   ohne Projektcode und ohne Administrator-/Bypassrechte.
7. **GitHub-Regeln prüfen.** Pflichtchecks an vertrauenswürdige Herausgeber binden,
   strikte Aktualität und geschützte Basis erzwingen, veraltete Reviews verwerfen,
   Kontroll-/Sicherheitsänderungen durch manuelle Code-Owner-Reviews schützen.
   Plan- und Ruleset-Fähigkeiten prüfen. Unbekannte oder nicht unterstützte Regeln
   müssen weiterhin sperren. Der derzeitige Leser akzeptiert nur die dokumentierte
   klassische strikte Branch-Protection-Konfiguration.
8. **Ohne automatischen Merge starten.** Zunächst reale PRs mit manueller
   Freigabe prüfen. Laufzeit, Kosten, Kriterienqualität und Abbrüche beobachten.
9. **Auto-Merge separat aktivieren.** Erstfreigabe und einzelne Projektfreigabe
   ausdrücklich erteilen, den passenden Controllergrant hinterlegen und die
   Projektregel bewusst einschalten. Alle Nachweise müssen weiterhin aktuell und
   vollständig sein. Änderungen an Steuerung/Sicherheit bleiben manuell.

## Einmalige Betreiberberechtigungen

| Einrichtung | Einmalige Handlung / laufende Begrenzung |
| --- | --- |
| GitHub-Projekt | Eigentümer autorisiert exakt ein Repository; keine pauschale Organisationsfreigabe |
| GitHub Actions | Bestehende CI darf Leserechte und gegebenenfalls enthaltene Minuten nutzen; keine zusätzlichen Secrets im Bootstrap |
| GitHub-Regeln | Eigentümer richtet Schutzregeln manuell ein; der Betriebsmerger erhält kein Administrationsrecht |
| Codex Cloud | Geeigneter ChatGPT-Zugang, Anmeldung und Repository-/Umgebungsfreigabe; erforderliche Konto-/Workspace-Sicherheitsregeln erfüllen |
| Rollen | Separate Entwicklungs-/Review-Identitäten bzw. überprüfbare isolierte Rollenlaufzeiten einrichten |
| Merger | Projektbeschränktes kurzlebiges Credential getrennt vom Agenten; nur nach verifizierter Nachweiskette |
| Aktivierung | Erstfreigabe für das System und zusätzliche Auto-Merge-Freigabe für jedes einzelne Projekt |

DT-001 erstellt keine Tokens, ändert keine GitHub-Schutzregeln, aktiviert keine
Repository-Auto-Merge-Einstellung und richtet keine kostenpflichtige Infrastruktur ein.
Welche konkreten GitHub-App-Berechtigungen/Identitäten verfügbar sind, muss beim
späteren ausgewählten Projekt verifiziert werden; ein Konfigurationswunsch allein
beweist keine durchgesetzte Berechtigungstrennung.

## Rücknahme und Betrieb

Auto-Merge zuerst im Controllergrant und in der Projektfreigabe zurücknehmen;
Merger-Credential widerrufen, falls dessen Zustand unklar ist. Laufende Tasks anhand
der gespeicherten Referenzen abgleichen. Keine neue Berechtigung aus einem
Fehlerkorrektur-PR akzeptieren. Unterbrochene Seiteneffekte vor einem neuen Lauf
manuell abgleichen. Deployments sind auch nach Merge-Aktivierung nicht Bestandteil
des Entwicklerteams und benötigen einen gesonderten Auftrag.
