"""
server/transcription_validator.py
==================================
Simple transcription validation module.
No fuzzy logic, no semantic validation, no script bias.
Accepts any text with content and lets the LLM Moderator handle understanding.
"""

import logging

logger = logging.getLogger("transcription-validator")


def is_valid_transcript(text: str) -> tuple:
    """
    Simple validation: check if text has content.
    Returns: (is_valid, reason)
    """
    if not text or not text.strip():
        return False, "empty"

    # Accept ANY text with content (any script, any language)
    if len(text.strip()) >= 1:
        return True, "valid"

    return False, "empty"


def calculate_transcript_confidence(raw_text: str, result_dict: dict) -> float:
    """Simple confidence calculation."""
    if not raw_text or not raw_text.strip():
        return 0.0
    return float(result_dict.get("confidence", 0.95))


def get_word_count(text: str) -> int:
    """Simple word count."""
    if not text:
        return 0
    return len(text.split())


def is_guidance_request(text: str) -> bool:
    """Simple guidance request detection - hint for LLM."""
    if not text:
        return False
    guidance_phrases = ["kya karna", "guide", "help", "smjha", "batao", "کیا کرنا"]
    text_lower = text.lower()
    return any(p in text_lower for p in guidance_phrases)
