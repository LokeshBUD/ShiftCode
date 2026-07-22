import unittest

import mypkg


class ProcessTest(unittest.TestCase):
    def test_process_doubles_values(self):
        self.assertEqual(mypkg.process({"a": 1, "b": 2}), {"a": 2, "b": 4})
