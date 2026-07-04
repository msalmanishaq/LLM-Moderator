"""
server/tests/test_intent_classifier.py
=======================================
Unit tests for intent classification across Roman Urdu and English inputs.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from intent_classifier import get_intent_classifier

class TestIntentClassifier(unittest.TestCase):

    def setUp(self):
        self.classifier = get_intent_classifier()

    def test_ranking_completion(self):
        res = self.classifier.classify("Main apni ranking complete kar chuka hun", language="ur")
        self.assertEqual(res["intent"], "ranking_complete")

    def test_ranking_refusal(self):
        res = self.classifier.classify("Main kuch nahin sochta aur main kuch bhi rank nahin karunga", language="ur")
        self.assertEqual(res["intent"], "ranking_refusal")

    def test_conflict(self):
        res = self.classifier.classify("Chup kar jao, fazool baatein kar rahe ho", language="ur")
        self.assertEqual(res["intent"], "conflict")

    def test_question(self):
        res = self.classifier.classify("Chamak kalo kya kehte hain? Renge mein kya karna hai?", language="ur")
        self.assertIn(res["intent"], ("question", "guidance_request"))

if __name__ == "__main__":
    unittest.main()
