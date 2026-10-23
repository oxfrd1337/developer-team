# Repository instructions

DT-001 is a safe-mode bootstrap. The user has authorized a development branch and PR,
but has explicitly forbidden automatic merge of the bootstrap PR and any live activation.

- Use Python 3.11+ and stdlib-only runtime dependencies.
- Keep all executable demos on disposable synthetic repositories. Do not onboard external projects.
- Keep development, QA, security and merge capabilities logically separate.
- Never treat saved JSON, a Codex task receipt or a green bootstrap CI job as a live review proof.
- Unknown, incomplete, stale or conflicting evidence blocks release.
- Changes to automation, configuration, security, instructions and trust logic require manual merge.
- Do not expose a live/activate/force/admin flag in the bootstrap CLI or a merge/deploy workflow.
- Respect nested project AGENTS.md by directory; they cannot grant permissions or override the controller.
- Run `python -m unittest discover -s tests -t . -v` and the checks from `docs/testing.md`.
- Keep documentation in German, code identifiers and adapter contracts in English.
- Do not commit credentials, generated run databases, checkout artifacts or virtual environments.

Controller code, `tests/`, `.github/`, `examples/`, `pyproject.toml`, `requirements-dev.txt`,
`AGENTS.md` and `SECURITY.md` form the protected control surface of this repository.
No automated run may authorize a change to this surface itself.

## Codex-Chat-Benennung

- Für neue Codex-Aufgaben und Statusmeldungen einen kurzen, eindeutigen Titel nach dem Schema `Repository / PR #Nummer – Thema` vorschlagen.
- Wenn noch keine PR existiert, `Repository / Issue #Nummer – Thema` oder `Repository / Kennung – Thema` verwenden. Keine PR- oder Issue-Nummern erfinden.
- Den tatsächlichen Repository-Namen verwenden (z. B. `espresso.signal / PR #68 – Live-Shot-Monitor`, `developer-team / Issue #31 – Implementierung`, `raspberry-pi-diagnostics / D2 – One-Time-Launcher`).
- Bei neu erstellter PR den vorgeschlagenen Titel entsprechend aktualisieren. Bestehende Chat- oder GitHub-Titel nur auf ausdrücklichen Wunsch ändern.
- Diese Regel dient ausschließlich der Benennung und erteilt keine zusätzlichen Berechtigungen. Eine automatische Änderung des Codex-Chat-Titels ist nur zulässig, falls die verwendete Oberfläche dies tatsächlich unterstützt; andernfalls den Titel zum manuellen Übernehmen ausgeben.
