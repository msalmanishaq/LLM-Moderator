"""
server/tests/test_semantic_validator.py
========================================
Unit tests for Semantic Validation Layer (server/semantic_validator.py).
Tests content-based validation (items, ranks, guidance requests) over acoustic confidence.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from semantic_validator import (
    validate_semantic_content,
    extract_rank,
    extract_items,
    detect_guidance_request,
    get_validation_response
)


class TestSemanticValidator(unittest.TestCase):

    def test_valid_ranking(self):
        """Test that perfect ranking inputs are accepted."""
        text = "mujhe sab se pehle lgta hai kh water bottle aany chahiye number 1 pr"
        result = validate_semantic_content(text)
        self.assertTrue(result["valid"])
        self.assertIsNotNone(result["rank"])
        self.assertEqual(result["rank"], 1)
        self.assertGreater(len(result["items"]), 0)

    def test_guidance_request(self):
        """Test that guidance requests are detected and accepted."""
        text = "moderator yhan ph kya karna hai"
        result = validate_semantic_content(text)
        self.assertTrue(result["valid"])
        self.assertTrue(result["guidance_request"])

    def test_missing_rank(self):
        """Test that messages with item but no rank get proper response."""
        text = "water bottle aana chahiye"
        result = validate_semantic_content(text)
        self.assertFalse(result["valid"])
        self.assertEqual(result["rejection_reason"], "missing_rank")
        self.assertGreater(len(result["items"]), 0)
        
        resp = get_validation_response(result)
        self.assertEqual(resp["type"], "clarification")

    def test_missing_item(self):
        """Test that messages with rank but no item get proper response."""
        text = "number 1"
        result = validate_semantic_content(text)
        self.assertFalse(result["valid"])
        self.assertEqual(result["rejection_reason"], "missing_item")
        self.assertEqual(result["rank"], 1)

        resp = get_validation_response(result)
        self.assertEqual(resp["type"], "clarification")

    def test_word_ranks(self):
        """Test word-based rank extraction (pehla, doosra, etc.)."""
        self.assertEqual(extract_rank("paani pehla number"), 1)
        self.assertEqual(extract_rank("tarp doosri position"), 2)
        self.assertEqual(extract_rank("compass teesra item"), 3)

    def test_phonetic_corruption(self):
        """Test that phonetic corruptions are still semantically validated."""
        from transcription_validator import process_stt_output
        res = process_stt_output("number one water bottle")
        self.assertTrue(res["semantic_valid"])
        self.assertEqual(res["rank"], 1)


if __name__ == "__main__":
    unittest.main()
