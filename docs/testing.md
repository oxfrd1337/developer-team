# Teststrategie

Die Tests benötigen keine GitHub-/OpenAI-Credentials und rufen keine externen
Projekt-APIs auf. Git und Python-Prozesse arbeiten nur in temporären synthetischen
Repositories. Adaptertests verwenden ausdrücklich nachgebildete CLI-/REST-Antworten.
Eine positive simulierte Merge-Entscheidung erhöht lediglich einen lokalen Zähler;
sie führt weder `git merge` noch einen API-Aufruf aus.

DT-002 ergänzt `tests/test_cloud.py` mit kontrollierten CLI-/Ref-Testadaptern,
echten temporären Git-Importen und lokalen Testprozessen. Lifecycle, Reviewtrennung,
Wiederaufnahme mit neuem Controller, Korrekturen und Merge-Sperre sowie die Grenzen
der Testaussagen sind in [dt-002.md](dt-002.md) dokumentiert. Auch diese Tests starten
keine echten Cloud-Tasks und benötigen keine Freigabe mit Kosten-/Schreibwirkung.

```sh
python -m unittest discover -s tests -t . -v
.venv/bin/python -m coverage run --branch -m unittest discover -s tests -t . -v
.venv/bin/python -m coverage report --fail-under=80
.venv/bin/python -m ruff check developer_team tests
.venv/bin/python -m ruff format --check developer_team tests
.venv/bin/python -m build --no-isolation
```

## Abdeckung der geforderten Fälle

| Anforderung | Nachweis |
| --- | --- |
| Vollständiger Ablauf | Echte synthetische Code-/Test-/Dokumentationscommits, Testprozesse, zwei getrennte Review-Aufrufe, simulierter PR und simulierter Merge bei ausschließlich im Test gesetzter Freigabe |
| Testfehler korrigieren | Falsche Rechenoperation scheitert am Test, wird einmal korrigiert und erneut geprüft |
| QA erfolgreich | Separater Prozess prüft positive/negative/Float-Werte und falsche Eingabetypen |
| QA fehlgeschlagen | Entwickler-Tests übersehen boolesche Eingaben; QA erkennt sie, korrigiert oder eskaliert nach drei Korrekturen |
| Security-Konflikt | Synthetischer Berechtigungsmarker wird korrigiert; verbotene Dummy-`.env` eskaliert direkt |
| Veraltete Nachweise | Falscher HEAD, Basis-, Konfigurations-, Plan-/Laufhash und abgelaufener Plattformzustand blockieren |
| Fehlende Rechte | Fehlende Entwicklungs-/PR-/Merge-/Cloud-Berechtigung verhindert die jeweilige Aktion |
| Unterbrechung | KeyboardInterrupt, unvollständiges Intent, sichere Pause/Fortsetzung und keine doppelte PR-Erstellung |
| Begrenzte Korrekturen | Exakt maximal drei Korrekturen; Gesamtbudget bleibt bei Fortsetzung erhalten |
| Unzulässiger Auto-Merge | Bootstrap, fehlende Erstfreigabe, geschützte Pfade, gefälschte/fehlende/doppelte Belege, unklare Regeln und simulierte Cloud-Belege sperren |

Weitere Prüfungen betreffen strikte TOML-Typen, alternative Sprach-/Frameworknamen,
individuelle Befehle, verschachtelte AGENTS.md, geschützte Umbenennungen, Symlinks,
fehlende Richtlinien, Prozess-Timeout mit Kindprozessen, Secret-Umgebungsfilter und
die exklusive Laufsperre. Ein Test verändert den Code während QA; der Controller
erkennt den unreinen Checkout und verwirft die Freigabe.

Die GitHub-Vertragstests prüfen App-Bindung, übersprungene Checks, Administratorrechte,
Fork-/Projektverwechslung, unvollständige Dateilisten, unbekannte Branch Protection,
Remote-SHA-Prüfung, PR-Idempotenz und den SHA im Merge-Payload. Ein Payload-Test nutzt
bewusst ein nachgebildetes positives Gate; er beweist keinen produktiven GitHub-Merge.
Codex-Vertragstests prüfen Testmodussperre, Projektgrant, getrennte Umgebungen,
einen Versuch pro Auftrag, nicht vertrauenswürdige Receipts und Argumentvalidierung.

## Reproduzierbare Demos

`python -m developer_team demo --scenario NAME` kennt:

| Szenario | Erwartetes Ergebnis im unveränderten DT-001-Modus |
| --- | --- |
| `happy` | Prüfungen erfolgreich, simulierter PR, Merge wegen Erstfreigabeschutz blockiert |
| `test-fix` | Ein Testfehler behoben, danach wie `happy` |
| `qa-fix` | Ein QA-Randfall behoben, danach wie `happy` |
| `qa-fail` | QA nach drei Korrekturen eskaliert, kein PR |
| `security-fix` | Ein Sicherheitsbefund behoben, alle Prüfungen erneut ausgeführt |
| `security-conflict` | Nicht behebbarer Richtlinienkonflikt eskaliert, kein PR |
| `protected-change` | Veränderung an AGENTS.md sperrt zusätzlich den Merge |
| `stale-evidence` | Abweichender Plattform-HEAD sperrt zusätzlich den Merge |
| `missing-permission` | Entwicklung vor dem ersten Schreibzugriff verweigert |
| `interrupted` | Lauf als unterbrochen protokolliert, keine automatische Wiederholung |
| `repair-limit` | Permanenter Testfehler nach drei Korrekturen eskaliert |

Die internen positiven Merge-Tests erstellen eine ausschließlich lokale Testfreigabe
mit `safe_test_mode=True`. Dieses Testobjekt aktiviert kein Repository und ist kein
CLI-Schalter. Die Demo schreibt weder reale PRs noch externe Branches.

## GitHub Actions und Aussagegrenzen

`ci.yml` prüft Python 3.11, 3.12 und 3.13 auf Ubuntu: Lint mit Sicherheitsregeln,
Formatierung, Tests mit Branch-Messung, mindestens 80 % Gesamtabdeckung, Wheel/SDist
und einen sicheren Smoke-Lauf. Actions sind auf Commit-SHAs gebunden. Der Job hat nur
`contents: read`, keine persistierten Checkout-Credentials, keine Secrets und keine
Merge-/Deploy-Schritte. Der synthetische Report wird sieben Tage als Artefakt aufbewahrt.

Abdeckung misst ausgeführten Code und ersetzt keine unabhängige Sicherheitsbewertung.
Diese CI-Jobs bestätigen weder eine produktive Cloud-Ausführung noch isolierte
KI-Reviews. Tatsächlich gelaufene lokale und entfernte Prüfungen werden separat in
[handover.md](handover.md) dokumentiert. Ein CI-Lauf kann in einem privaten Repository
an Actions-Freigabe, Budget oder Planvorgaben scheitern; das wird nicht als Testpass gewertet.
