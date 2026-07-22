import unittest

import module_a


class RunTest(unittest.TestCase):
    def test_run_doubles_values(self):
        self.assertEqual(module_a.run([1, 2, 3]), [2, 4, 6])
