# Projektkonfiguration v1

Die vollständige ausführbare Referenz ist
[`examples/project.synthetic.toml`](../examples/project.synthetic.toml). Sie bezeichnet
ausschließlich `synthetic/calculator`, ein lokal erzeugtes Beispiel. Es gibt keine
Anbindung eines fremden Repositories.

Die spätere Standardposition im Zielprojekt ist `.developer-team/project.toml`.
Der vertrauenswürdige Controller liest eine vorab geprüfte Version und versiegelt
deren Hash zusammen mit den geltenden Anweisungen und Sicherheitsrichtlinien.
Die Datei ist eine Beschreibung des Projekts, keine Autorisierung.

| Bereich | Felder und Regeln |
| --- | --- |
| Wurzel | `schema_version = 1`; unbekannte Schlüssel und Versionen sind Fehler |
| `[project]` | `id`, `repository` als `owner/name`, `provider` (`local`/`github`), `base_branch`, `languages`; optionale `frameworks` |
| `[instructions]` | `files`, standardmäßig `AGENTS.md`; Dateien müssen existieren |
| `[security]` | `policy_files`, standardmäßig `SECURITY.md`; zusätzliche `protected_paths` |
| `[[checks]]` | Eindeutiger `name`, `kind` (`test`, `build`, `lint`), `argv` als Liste; `timeout_seconds` 1–1800, Standard 60; `required` standardmäßig `true` |
| `[merge]` | `enabled` standardmäßig `false`; `method`: `squash`, `merge`, `rebase` |
| `[limits]` | `max_repairs_per_class` 0–3, Standard 3; `max_steps` 10–100, Standard 60 |
| `[delivery]` | `test_paths` und `documentation_paths`; beide müssen im gemeinsamen Änderungssatz vorkommen |

Mindestens eine verpflichtende Prüfung vom Typ `test` ist erforderlich. Befehle sind
sprachunabhängig und werden als Argumentliste ohne implizite Shell ausgeführt.
Ein Projekt kann später beispielsweise `cargo test --locked`, `npm test`, `go test`
oder einen eigenen Build-Runner konfigurieren. Das installiert keine Toolchain und
bestätigt keine echte Anbindung dieser Technologien. Lokale Demos bleiben beim
synthetischen Python-Fixture.

`required = false` bedeutet informativ: Diese Prüfung erzeugt keine verpflichtende
Merge-Evidenz. Ein nicht ausführbarer Pflichtbefehl ist `unknown` und eskaliert,
statt drei sinnlose Codeänderungen anzustoßen. Ein Exitcode 0 muss beim Onboarding
als aussagekräftige Testausführung validiert werden; kein universeller Runner kann
aus dem Exitcode allein Testanzahl oder fachliche Vollständigkeit ableiten.

Pfade sind relative POSIX-Pfade ohne `..`, absolute Pfade oder Backslashes.
Muster verwenden Python-`fnmatch`-Semantik. `tests/**` umfasst den Testbaum;
`README.md` ist eine explizite Dokumentationsdatei. `.github/**`,
`.developer-team/**`, root-/verschachtelte `AGENTS.md` und `SECURITY.md` sind stets
geschützt. Konfigurierte Anweisungs- und Richtliniendateien sind ebenfalls geschützt;
der Controller darf diese Mindestmenge nicht durch Projektregeln verkleinern.

Alle versionierten verschachtelten `AGENTS.md` werden mit ihrem Pfad eingelesen.
Eine unter `src/` abgelegte Datei gilt nur für diesen Teilbaum. Ein Adapter muss
diese Geltungsbereiche beim Promptaufbau bewahren. Anweisungen dürfen weder
Berechtigungen erteilen noch übergeordnete Controllerregeln abschwächen. Symlinks,
fehlende Pflichtdateien, mehr als 100 Anweisungsdateien oder Dateien über 64 KiB
führen im synthetischen Treiber zum Abbruch.

Der effektive Konfigurationshash bindet den normalisierten Projektinhalt und alle
eingelesenen Richtliniendateien. Der `ProjectGrant` des Controllers muss genau zu
Projekt-ID, Repository und diesem Hash passen. Eine geänderte Projektdatei kann
deshalb weder eine neue Merge-Erlaubnis noch alte Review-Belege übernehmen.
Credentials, Tokens, Umgebungs-IDs für reale Projekte und Autorisierungsgrants
gehören nicht in diese Datei. Reale Rollen-Umgebungen werden später separat durch
den Betreiber freigegeben.
