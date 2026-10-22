"""Addition für die vollständig künstliche Pilotaufgabe."""


def add(a, b):
    """Addiere int und float; bool und andere Typen lösen TypeError aus."""
    for value in (a, b):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("add erwartet int oder float, keine booleschen Werte")
    return a + b
