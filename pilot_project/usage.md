# Künstlicher Pilot: Addition

`add(a, b)` addiert zwei Werte vom Typ `int` oder `float`, auch gemischt,
einschließlich negativer Zahlen und Null. Zusätzliche Abhängigkeiten sind nicht nötig.

```python
from pilot_project.calculator import add

add(2, 3)       # 5
add(-1.5, 2)    # 0.5
add(0, 0)      # 0
```

Die Funktion verwendet normale Python-Addition: Zwei `int` ergeben einen `int`,
bei Beteiligung eines `float` entsteht ein `float` mit üblicher Gleitkommarundung
(zum Beispiel `add(0.1, 0.2) == 0.30000000000000004`).

`bool` und alle anderen Typen (etwa Zeichenketten, `None`, komplexe Zahlen,
`Decimal` oder `Fraction`) lösen an jeder Argumentposition `TypeError` aus.
Es findet keine automatische Umwandlung statt: `add("2", 3)` und `add(True, 1)`
sind ungültig.

Tests vom Repository-Hauptverzeichnis aus starten:

```sh
python -m unittest pilot_project.acceptance -v
python -m unittest discover -s pilot_project/tests -v
python -m unittest discover -s tests -t . -v
```
