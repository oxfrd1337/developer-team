"""Ausgangstest; der Entwickler ergänzt konkrete Funktionstests."""

import unittest

from pilot_project.calculator import add


class InterfaceTests(unittest.TestCase):
    def test_interface_exists(self):
        self.assertTrue(callable(add))
