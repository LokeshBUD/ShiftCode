import unittest
import calculator


class CalculatorTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(calculator.add(2, 3), 5)

    def test_divide_preserves_py2_floor_semantics(self):
        # calculator.py has no `from __future__ import division`, so under the
        # original Python 2 code `7 / 2` floor-divides to 3, not 3.5. A faithful
        # migration must preserve this exact behavior (use `//`), not silently
        # switch to Python 3's true-division semantics for bare `/`.
        self.assertEqual(calculator.divide(7, 2), 3)

    def test_sum_dict(self):
        self.assertEqual(calculator.sum_dict({"a": 1, "b": 2, "c": 3}), 6)

    def test_safe_divide_by_zero(self):
        self.assertIsNone(calculator.safe_divide(1, 0))


if __name__ == "__main__":
    unittest.main()
