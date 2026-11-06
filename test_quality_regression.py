import unittest
from scripts.quality_regression import compare


class RegressionTests(unittest.TestCase):
    def test_inherited_failure_is_not_a_new_regression(self):
        self.assertEqual(compare({'Q1':5},{'Q1':5}),[])
        self.assertEqual(compare({'Q1':1},{'Q1':5}),[])
        self.assertEqual(compare({'Q1':6},{'Q1':5}),['Q1'])

    def test_changed_questions_fail_closed(self):
        with self.assertRaises(ValueError):
            compare({'Q2':1},{'Q1':1})
