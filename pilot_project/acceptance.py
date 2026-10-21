"""Unveränderliche Betreiberprüfungen für die künstliche Pilotanforderung."""

import unittest

from pilot_project.calculator import add


class AcceptanceTests(unittest.TestCase):
    def test_numbers(self):
        for a, b, expected in ((2, 3, 5), (-2, -3, -5), (1.5, 2, 3.5), (0, 0, 0)):
            with self.subTest(a=a, b=b):
                self.assertEqual(add(a, b), expected)

    def test_rejects_non_numbers(self):
        for value in (True, False, "2", None, [], {}):
            for a, b in ((value, 1), (1, value)):
                with self.subTest(a=a, b=b), self.assertRaises(TypeError):
                    add(a, b)
