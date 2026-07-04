"""
server/tests/test_roman_urdu_normalizer.py
============================================
Unit tests for the Roman Urdu Normalization Layer.
Validates dictionary lookups, stretch letter reduction, technical term protection,
punctuation cleanup, audit logging, and latency bounds (<50ms).
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from roman_urdu_normalizer import get_roman_urdu_normalizer


class TestRomanUrduNormalizer(unittest.TestCase):

    def setUp(self):
        self.normalizer = get_roman_urdu_normalizer()

    def test_dictionary_normalization(self):
        res = self.normalizer.normalize("mje lg rha ha")
        self.assertEqual(res["normalized"], "mujhe lag raha hai")
        self.assertGreater(len(res["changes"]), 0)

        res = self.normalizer.normalize("ap kaha ho")
        self.assertEqual(res["normalized"], "aap kahan ho")

    def test_code_mixed_technical_term_protection(self):
        res = self.normalizer.normalize("hm AI project pr kam kr rhy hn")
        self.assertIn("AI", res["normalized"])
        self.assertEqual(res["normalized"], "hum AI project par kaam kar rahe hain")

        res = self.normalizer.normalize("Accessibility Office sy bat hui")
        self.assertEqual(res["normalized"], "Accessibility Office se baat hui")

        res = self.normalizer.normalize("Python API ka issue ha")
        self.assertEqual(res["normalized"], "Python API ka issue hai")

    def test_stretch_letter_reduction(self):
        res = self.normalizer.normalize("bohaaaat acha ha")
        self.assertIn("bohat", res["normalized"])

        res = self.normalizer.normalize("pleeease help krna")
        self.assertIn("please", res["normalized"])

        # Legitimate double letters preserved
        res = self.normalizer.normalize("good see look")
        self.assertEqual(res["normalized"], "good see look")

    def test_numbers_versions_protection(self):
        res = self.normalizer.normalize("Python 3.12 aur GPT-4.1 100% sahi hai")
        self.assertIn("Python 3.12", res["normalized"])
        self.assertIn("GPT-4.1", res["normalized"])
        self.assertIn("100%", res["normalized"])

    def test_punctuation_and_latency(self):
        res = self.normalizer.normalize("mje,, lg rha... ha!!")
        self.assertLess(res["processing_time_ms"], 50.0)
        self.assertNotIn(",,", res["normalized"])
        self.assertNotIn("...", res["normalized"])


if __name__ == "__main__":
    unittest.main()
