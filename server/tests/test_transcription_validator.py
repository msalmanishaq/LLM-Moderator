"""
server/tests/test_transcription_validator.py
============================================
Unit tests for transcription integrity validator.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from transcription_validator import is_valid_transcript, calculate_transcript_confidence, correct_phonetic_hallucinations


class TestTranscriptionValidator(unittest.TestCase):

    def test_valid_transcripts(self):
        valid, reason = is_valid_transcript("Acha, mera ranking yeh hai")
        self.assertTrue(valid)
        self.assertEqual(reason, "valid")

        valid, reason = is_valid_transcript("I think water is most important")
        self.assertTrue(valid)
        self.assertEqual(reason, "valid")

    def test_invalid_transcripts(self):
        # Too short / insufficient words
        valid, reason = is_valid_transcript("hi")
        self.assertFalse(valid)
        self.assertIn(reason, ("too_short", "insufficient_words"))

        # Filler only
        valid, reason = is_valid_transcript("um ah haan")
        self.assertFalse(valid)
        self.assertEqual(reason, "only_filler_words")

        # Excessive repetition
        valid, reason = is_valid_transcript("hello hello hello hello hello")
        self.assertFalse(valid)
        self.assertEqual(reason, "excessive_word_repetition")

    def test_confidence_calculation(self):
        conf = calculate_transcript_confidence("um ah", {"confidence": 0.95})
        self.assertLess(conf, 0.70)

    def test_phonetic_corrections(self):
        self.assertEqual(correct_phonetic_hallucinations("number one piano jo hai"), "number one water jo hai")
        self.assertEqual(correct_phonetic_hallucinations("Peerasho number do pe aana chahiye"), "parachute number do pe aana chahiye")
        self.assertEqual(correct_phonetic_hallucinations("main doosri tatti jo hai woh lighter pe doonga"), "main doosri priority jo hai woh lighter pe doonga")
        self.assertEqual(correct_phonetic_hallucinations("number aik pushch city"), "number aik flashlight")


if __name__ == "__main__":
    unittest.main()
