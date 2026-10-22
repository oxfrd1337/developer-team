"""Funktionstests für die künstliche Pilotaddition."""

import unittest
from decimal import Decimal
from fractions import Fraction

from pilot_project.calculator import add


class AdditionTests(unittest.TestCase):
    def test_integer_addition(self):
        for a, b, expected in (
            (2, 3, 5),
            (-2, -3, -5),
            (-7, 4, -3),
            (0, 0, 0),
            (0, 8, 8),
            (8, 0, 8),
            (10**100, 1, 10**100 + 1),
        ):
            with self.subTest(a=a, b=b):
                result = add(a, b)
                self.assertEqual(result, expected)
                self.assertIs(type(result), int)

    def test_float_and_mixed_addition(self):
        for a, b, expected in (
            (1.25, 2.5, 3.75),
            (-1.5, -2.25, -3.75),
            (-1.5, 2, 0.5),
            (2, -1.5, 0.5),
            (0.0, 0, 0.0),
            (0, 0.0, 0.0),
            (0.0, -2.5, -2.5),
            (-2.5, 0.0, -2.5),
        ):
            with self.subTest(a=a, b=b):
                result = add(a, b)
                self.assertEqual(result, expected)
                self.assertIs(type(result), float)

    def test_preserves_python_float_rounding(self):
        self.assertEqual(add(0.1, 0.2), 0.1 + 0.2)

    def test_rejects_booleans_in_either_position(self):
        for value in (True, False):
            for a, b in ((value, 1), (1, value), (value, value)):
                with self.subTest(a=a, b=b), self.assertRaises(TypeError):
                    add(a, b)

    def test_rejects_other_types_in_either_position(self):
        for value in (
            "2", b"2", None, [], {}, (), set(), object(),
            1 + 2j, Decimal("2"), Fraction(1, 2),
        ):
            for a, b in ((value, 1), (1, value), (value, value)):
                with self.subTest(a=a, b=b), self.assertRaises(TypeError):
                    add(a, b)
