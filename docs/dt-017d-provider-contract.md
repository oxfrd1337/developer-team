# DT-017D: Least-Privilege- und Spend-Vertrag

Issue #42 korrigiert ausschließlich zwei Providervertragsabweichungen auf Basis
`afcad56fb67af71a9805173ab62fccaf7701bed9` (DT-017C).

## Dokumentationsprüfung vor Implementierung

Am 24.10.2026 wurden alle fünf im Issue verlinkten offiziellen Quellen gelesen.
Die relevanten Aussagen stimmen mit dem Issue überein:

- [Service-Account-Referenz](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/projects/subresources/service_accounts/methods/retrieve):
  Die Defaultrolle darf `owner`, `member` oder `none` sein.
- [Service Accounts mit Terraform](https://developers.openai.com/api/docs/guides/terraform/service-accounts):
  Least Privilege beginnt ohne Defaultrolle; eine Custom Project Role wird separat
  zugewiesen, im dokumentierten Beispiel über eine Gruppe. Ein scoped API-Key kann
  die Rechte weiter einschränken. Zusätzliche Member-/Owner-Rechte sind unnötig,
  wenn die Custom Role genügt.
- [RBAC](https://developers.openai.com/api/docs/guides/rbac): Effektive Rechte
  hängen von den zugewiesenen Rollen und den Key-Berechtigungen ab. Ein einzelner
  Rollenname oder erfolgreicher GET ist kein Nachweis des minimalen Gesamtscopes.
- [Admin APIs](https://developers.openai.com/api/docs/guides/admin-apis):
  `threshold_amount` wird in Cents angegeben.
- [Spend Limits](https://developers.openai.com/api/docs/guides/spend-limits):
  Projekt-Hard-Limits gelten für monatliche Projektkosten. Die Durchsetzung ist
  verzögert; geringe Überschreitungen sind möglich. Spend Alerts sind keine Caps.

Es wurden nur öffentliche Dokumentationsseiten gelesen, keine Provider-API-Endpunkte.
Es wurden keine Dokumentationsbeispiele ausgeführt.

## Vertrag

`account_project_binding` akzeptiert alle drei dokumentierten Defaultrollen bei
unverändert exakter Service-Account-/Key-Owner-/Projektbindung. Account und
Principal müssen weiterhin denselben Rollenwert tragen. Unbekannte Rollen,
Identitätsabweichungen und abgelaufene oder inaktive Bindungen blockieren.
Custom-Role-Berechtigungen werden nicht aus `none` abgeleitet.

`credential_scope` benötigt weiterhin getrennte, unabhängige Scope-Evidence und
einen gepinnten Verifier. Ohne diese bleibt der bestehende Diagnosestatus
`MISSING_OR_INVALID` (fehlende Evidence), auch bei erfolgreichen synthetischen GETs.

Collector und ReadOnlyVerifier verlangen denselben Bereich:
`binding.budget_cents <= project_limit_cents <= 100`. Der Collector behält den
tatsächlich beobachteten Integer-Cents-Wert. Bool, Float, String, Null, 0, Werte
unter dem Canary-Budget oder über 100 blockieren. USD, Monatsintervall, aktive
Hard-Limit-Durchsetzung und das strikte Evidence-Schema bleiben Pflicht;
normalisierte Evidence verlangt `enforcement_delayed=True`.

Für den vorgegebenen Sollzustand bleibt das lokale Canary-Budget bei **5 Cent**,
das äußere Projekt-Hard-Limit bei **100 Cent**. Das Projektlimit ersetzt weder das
lokale Budget noch den exklusiven Single-Canary-Grant. Es wird kein Limit verändert.

## Regressionen und Grenzen

`tests/test_provider_contract.py` ergänzt 13 Tests mit injizierten Wire-Fixtures
und gesperrten echten Sockets. Sie prüfen alle dokumentierten Rollen, unbekannte
Rollen, Rollen-Mismatch, unveränderte Identitätsbindung, fehlende Scope-Quelle oder
Verifier, getrennte synthetische Scope-Evidence, gültige äußere Limits und die
Negativmatrix unabhängig im Collector und im ReadOnlyVerifier.

Die bestehenden Tests ändern nur die durch Issue #42 überholten Negativerwartungen:
`none` mit passendem Principal und Limits über dem lokalen Budget sind zulässig;
unbekannte Rollen, Mismatch und Limits über 100 bleiben gesperrt.

Die vollständige bestehende CI bleibt unverändert: Python 3.11–3.13,
Ruff/Security/Format, Branch-Coverage mit mindestens 80 %, Wheel/SDist,
synthetischer Smoke, CLI-Interface-Probe ohne Login/Tasks und Checkpoint/Restore.

Keine echten Provider-GETs oder Mutationen, keine Credentials, kein Session-Create,
Message-Submit oder Cancel, keine Rollen-/Key-/Spend-Änderung. Unabhängiger Review
und manueller Merge bleiben erforderlich; fehlende Live-Evidence bleibt ein Blocker.
Kein Merge und kein Deployment durch diesen Arbeitsauftrag.

**real_submissions = 0 · LIVE = NO-GO · live_authorized = false.**

**OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.**
