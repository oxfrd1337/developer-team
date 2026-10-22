# DT-008: Betreiberanleitung für genau einen späteren Piloten

**Heute: NO-GO. Nicht auf „Start task“ klicken und keine Freigabe erteilen.**
Die bestehende Cloudumgebung erfüllt die unabhängig prüfbaren Anforderungen derzeit
nicht. Auch ein grüner Draft-PR hebt die technische Startsperre nicht auf.
Es muss nichts am iPhone in ein Terminal kopiert werden.

## Jetzt die eine Entscheidung treffen

Im Draft-PR [Betriebsweg und Kostenrahmen](dt-008.md) lesen. Entscheiden, ob die
externe administrierte Architektur beauftragt werden soll oder der Pilot gestoppt bleibt.
Die Vorlage plant 8–16 Stunden Einrichtung, eine Stunde Beaufsichtigung sowie höchstens
5 EUR Infrastruktur und 5 USD Modellnutzung für einen Piloten; das sind beantragte
Grenzen und keine bestätigten Preise. Es erfolgt keine Bestellung durch diesen Auftrag.
Keine zusätzliche Anmeldung, API-Keybeschaffung oder Änderung von GitHub-Rechten
ist für das Lesen/Review dieses PR nötig.

## Vor einem späteren Start vom technischen Betreiber abnehmen lassen

Der technische Betreiber muss nach ausdrücklicher Infrastrukturentscheidung die reale
Integration in die vorhandene Engine herstellen und deren Nachweise liefern. Kein
alternativer Startbefehl, keine SQL-/JSON-Änderung und kein Entfernen der DT-008-Sperre
ist eine zulässige Betriebsmaßnahme. Die folgenden Schritte sind ein bedingter
Abnahmeablauf; heute existiert **kein freigegebener Live-Startbefehl**.

1. Persönliches Review und gesonderte Mergefreigabe für den vorbereitenden Code durchführen.
   Merge und Pilotfreigabe sind zwei verschiedene Vorgänge. Diesen Draft-PR nicht automatisch
   mergen. Nach späterer Integration muss der dann aktuelle Mergecommit erneut geprüft sein.
2. Vom technischen Betreiber **ein ausgefülltes Laufblatt** erhalten: genaues Repo und
   Commit/Configdigest, eine Run-ID, vier attestierte Rollen-VM-/Taskumgebungs-IDs,
   Datum/Start/Ende, Nutzungsobergrenze und Name der Person mit echter Stoppmöglichkeit.
   Diese Werte sind jetzt nicht verfügbar und werden nicht geraten. Für die bestehende
   Cloudroute gibt es derzeit keine gültigen vier attestierten Cloud-IDs.
3. Im Web die unabhängigen Nachweise mit diesem Laufblatt vergleichen lassen: strikter
   Branch-/Rulesetschutz, unveränderliche QA/Security-Quellen, externer Controller mit
   Journal/Audit, Secret-/Netzgrenzen, real getesteter externer Stop samt Cleanup und
   hartes Ressourcen-/Verbrauchsbudget. Screenshots oder grünes Task-JSON allein reichen
   nicht. Der Betreiber unterschreibt das Prüfprotokoll außerhalb aller Rollen-Workspaces.
   Zugang zu eigenen Einstellungen und tatsächlicher Restquote muss der Betreiber vor Ort
   bestätigen; allgemeine Produktdokumentation oder CI kann diese Kontodaten nicht liefern.
4. Der technische Betreiber führt den lesenden Preflight aus und legt den vollständigen
   Bericht im Laufblatt vor. **Die DT-008-Version liefert immer BLOCKED/NO-GO, Exitcode 2.**
   Sie ist jetzt reproduzierbar mit `python -m developer_team.preflight`.
   Erst eine später geprüfte echte Integration könnte GO-CANDIDATE ergeben. Das wäre
   nur eine Empfehlung zur manuellen Entscheidung, noch kein Startrecht.
5. Erst bei vollständiger Abnahme den separat stehenden Mustersatz mit tatsächlichen
   Werten bestätigen. Niemand darf diesen Text vorab als erteilte Freigabe speichern.

## Mustersatz — keine erteilte Freigabe

> Ich genehmige separat genau einen beaufsichtigten Pilotlauf für
> oxfrd1337/developer-team, Commit [40-stellige SHA], Configdigest [Digest], Run [ID],
> mit Orchestrator/Architektur, Developer, QA und Security in den attestierten
> Umgebungen [vier tatsächliche Cloud-IDs oder vier externe VM-/Service-IDs und
> ausdrücklicher Betriebsweg]. Schreibbar sind ausschließlich
> pilot_project/calculator.py, pilot_project/tests/test_calculator.py und
> pilot_project/usage.md; QA/Security lesen denselben versiegelten HEAD ohne Source-
> oder fremde Evidenzschreibrechte. Höchstens vier einmalige Aufgaben, keine Reparatur
> oder Wiederholung, maximal 600 Sekunden ab [Startzeit mit Zeitzone], Ende spätestens
> [Endzeit mit Zeitzone]. Zulässig sind höchstens [bestätigtes Nutzungslimit und
> harter Kostenbetrag/Währung]; verantwortlich für Aufsicht und Abbruch ist [Name],
> erreichbar über [vereinbarter Kanal]. Kein Merge, Deployment, weiterer Repozugriff,
> Kauf oder Rechtewechsel. Bei Kontrollverlust endet die Freigabe sofort; unklare
> Submission wird nicht wiederholt. Der externe Stopp- und Cleanupnachweis [Referenz]
> liegt vor. Diese Freigabe gilt nur einmal und verfällt zur genannten Endzeit.

## Ablauf während des später genehmigten Laufs

Der technische Betreiber bedient die später abgenommene Integration; die Aufsicht
bleibt am Rechner. Die bestehende Engine verwendet das feste synthetische Pilotprojekt
im selben Repo. Orchestrator/Architektur erstellt den Plan, Developer liefert den Patch.
Der Controller prüft Dateigrenzen und führt die lokalen Pilot-Akzeptanz-/Unittests
unabhängig aus. Anschließend prüfen QA und Security getrennt exakt denselben neuen
HEAD. Jeder Rollenauftrag verbraucht eines der vier Einmalkontingente. Ein Befund
beendet diesen Minimalpiloten; weitere Korrekturen benötigen einen neuen Auftrag.
Der Abschluss besteht aus Patch, Tests, beiden extern geprüften Reviews und
Auditbericht. Ein PR darf höchstens als manuell zu prüfender Draft vorliegen.
Es gibt weder automatischen Merge noch Deployment.

## Sofort stoppen und Incident behandeln

Absolute Stoppkriterien: unbekannte/doppelte Task-ID, anderer HEAD/Configdigest/Repo,
fehlendes Journal oder Netzverbindung zur Kontrolle, abgelaufene Genehmigung,
Budget-/Zeitgrenze, nicht lesbarer Status, Scopeverletzung, Secretzugriff,
fehlender Reviewer oder fehlgeschlagener lokaler Test.

1. Aufsicht sagt „STOP“ an die benannte Abbruchperson. Diese stoppt neue Submissions
   und sperrt die externe Modellservice-Lease; keine Retry-/Resume-/Apply-Schritte.
2. Abbruchperson nutzt den **vorher abgenommenen externen Supervisor**, beendet alle
   vier Rolleninstanzen und dokumentiert terminale Provider-/Servicezustände sowie
   Ressourcen-/Credential-Cleanup. Eine lokale Zeitüberschreitung oder ein beendetes
   Terminal bestätigt weder Remote-Cancel noch Kostenstopp.
3. Bei unbekanntem Empfang: Intent/Run-ID und vorhandene Task-ID sichern, Status über
   den autorisierten Betreiberkanal abgleichen, keine zweite Submission. Ist der Zustand
   weiter unklar, bleibt es ein offener Incident. Die heutige CLI besitzt keinen
   belegten Cancel-Befehl; kein erfundener Befehl darf verwendet werden. Bei einem
   unerwarteten echten Cloudauftrag muss die Aufsicht im authentifizierten Cloud-Web
   den konkreten Auftrag prüfen und gegebenenfalls den Provider-Support einschalten;
   ein UI-Klick ohne bestätigten Endzustand ist kein Stopnachweis.
4. Externe Logs ohne Roh-Credentials sichern. Ungeprüfte Ergebnisse nicht importieren.
   Kontrollierten Arbeitsbranch verwerfen, unveränderten geprüften main verwenden;
   nichts wurde gemergt/deployed und benötigt daher kein Produktionsrollback.
5. Verbrauch und restliche Prozesse unabhängig abgleichen. Ein Neustart benötigt neue
   Run-ID, frische Nachweise und neue separate Freigabe; keine automatische Recovery.

Vor einem echten Lauf muss die benannte Abbruchperson dieses Verfahren am realen
Betriebsweg bestätigt haben. **Diese Bestätigung fehlt heute.**

## Auswertung

Run-/Task-IDs, genehmigte und tatsächliche Start-/Endzeit, vier Rollenresultate,
Controller-/Entwicklungs-/Review-SHAs, lokale Testergebnisse, Scopevergleich,
Verbrauch, Stop/Cleanup und jede Abweichung in einem extern verwahrten Abschlussblatt
zusammenführen. Nur unabhängige Belege zählen. Ein erfolgreicher Minimalpilot erteilt
keine Freigabe für weitere Projekte, wiederholte Läufe oder automatische Merges.
