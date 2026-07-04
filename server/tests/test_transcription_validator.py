"""
server/tests/test_transcription_validator.py
============================================
Unit tests for simple transcription validator.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from transcription_validator import (
    is_valid_transcript,
    calculate_transcript_confidence,
    get_word_count,
    is_guidance_request
)


class TestTranscriptionValidator(unittest.TestCase):

    def test_valid_transcripts(self):
        valid, reason = is_valid_transcript("Acha, mera ranking yeh hai")
        self.assertTrue(valid)
        self.assertEqual(reason, "valid")

        valid, reason = is_valid_transcript("کیوں کرنا ہے")
        self.assertTrue(valid)
        self.assertEqual(reason, "valid")

    def test_invalid_transcripts(self):
        valid, reason = is_valid_transcript("")
        self.assertFalse(valid)
        self.assertEqual(reason, "empty")

    def test_guidance_detection(self):
        self.assertTrue(is_guidance_request("kya karna hai yahan"))
        self.assertTrue(is_guidance_request("guide kar do"))
        self.assertTrue(is_guidance_request("کیا کرنا"))

    def test_confidence_calculation(self):
        conf = calculate_transcript_confidence("hello", {"confidence": 0.95})
        self.assertEqual(conf, 0.95)


if __name__ == "__main__":
    unittest.main()
