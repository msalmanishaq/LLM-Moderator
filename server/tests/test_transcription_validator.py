"""
server/tests/test_transcription_validator.py
============================================
Unit tests for transcription integrity validator, fuzzy domain matching & rank validation.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from transcription_validator import (
    is_valid_transcript,
    calculate_transcript_confidence,
    resolve_item_mention,
    validate_rank_number
)


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

    def test_out_of_bounds_rank_validation(self):
        valid, reason = is_valid_transcript("number 15 pe book rakhte hain")
        self.assertFalse(valid)
        self.assertEqual(reason, "out_of_bounds_rank_15")

        valid_flag, val = validate_rank_number("rank 14", max_items=12)
        self.assertFalse(valid_flag)
        self.assertEqual(val, 14)

    def test_fuzzy_domain_item_resolution(self):
        match, score = resolve_item_mention("paani", threshold=70.0)
        self.assertIsNotNone(match)
        self.assertIn(match, ("paani", "water", "water bottles"))

        match, score = resolve_item_mention("qutub numa", threshold=70.0)
        self.assertIsNotNone(match)
        self.assertEqual(match, "qutub numa")

    def test_confidence_calculation(self):
        conf = calculate_transcript_confidence("um ah", {"confidence": 0.95})
        self.assertLess(conf, 0.70)


if __name__ == "__main__":
    unittest.main()
