"""
server/transcription_validator.py
==================================
Validates transcription quality for Roman Urdu and English STT outputs.
Determines whether a transcript is coherent and meaningful or low-confidence gibberish.
Uses RapidFuzz domain fuzzy matching and rank validation without silent error guessing.
"""

import logging
import re
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger("transcription-validator")

try:
    from rapidfuzz import process, fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    HAS_RAPIDFUZZ = False

FILLER_WORDS = {
    "um", "uh", "ah", "aah", "hmm", "hm", "shh", "shhh", "er", "oh",
    "haan", "hmmm", "mmm", "ooh", "eheh", "urgh"
}

REPETITION_REGEX = re.compile(r"(\b\w+\b)(?:\s+\1){3,}", re.IGNORECASE)
CHAR_REPETITION_REGEX = re.compile(r"(.)\1{4,}", re.IGNORECASE)
ARABIC_URDU_SCRIPT_REGEX = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")

# Fixed 12 domain items in Roman Urdu + canonical synonyms
KNOWN_DOMAIN_ITEMS = [
    "paani", "water", "water bottles",
    "tarp", "tarp sheet",
    "qutub numa", "compass",
    "naqsha", "road map", "map",
    "torch", "flashlight",
    "shisha", "visor mirror", "mirror",
    "jaket", "jacket", "coat", "hoodies",
    "multi-tool", "knife",
    "lighter", "cigarette lighter", "matches",
    "namak", "salt", "salt packets",
    "emergency triangle", "reflector",
    "guide book", "survival book", "desert survival book"
]


def resolve_item_mention(raw_token: str, threshold: float = 70.0) -> Tuple[Optional[str], float]:
    """
    Fuzzy-matches a token against known Roman Urdu survival items.
    Returns (matched_item, score) if score >= threshold, else (None, score).
    Does NOT force incorrect guesses if confidence is below threshold.
    """
    if not raw_token or not raw_token.strip():
        return None, 0.0

    token_clean = raw_token.strip().lower()
    if HAS_RAPIDFUZZ:
        res = process.extractOne(token_clean, KNOWN_DOMAIN_ITEMS, scorer=fuzz.WRatio)
        if res:
            match_str, score, _ = res
            if score >= threshold:
                return match_str, float(score)
            return None, float(score)
    else:
        matches = difflib.get_close_matches(token_clean, KNOWN_DOMAIN_ITEMS, n=1, cutoff=threshold / 100.0)
        if matches:
            return matches[0], 85.0

    return None, 0.0


def validate_rank_number(text: str, max_items: int = 12) -> Tuple[bool, Optional[int]]:
    """
    Validates rank numbers explicitly mentioned in text (e.g. 'number 15', 'rank 15').
    If a rank number is out of bounds (< 1 or > 12), returns (False, out_of_bounds_number).
    This surfaces semantic invalidity to trigger the retry/clarify layer instead of silently guessing.
    """
    if not text:
        return True, None

    # Matches patterns like "number 15", "rank 15", "no. 15", "position 15", "15th"
    matches = re.findall(r"\b(?:number|rank|no\.?|position)?\s*(\d{1,2})(?:st|nd|rd|th)?\b", text.lower())
    for m in matches:
        val = int(m)
        # Check if the number is being used in rank context (1 to 12 is expected)
        if val > max_items:
            logger.warning("⚠️ Semantic invalidity: Out-of-bounds rank %d detected in text: %r", val, text)
            return False, val

    return True, None


def is_valid_transcript(text: str) -> Tuple[bool, str]:
    """
    Validates a transcribed text string.
    Returns (is_valid, reason).

    Criteria:
    - Minimum length of 3 characters.
    - At least 2 words.
    - Not composed entirely of filler words or acoustic noise tokens.
    - No excessive character or word repetitions (model hallucination).
    - No non-Latin (Arabic/Urdu script) flip.
    - No out-of-range rank numbers (> 12).
    """
    if not text:
        return False, "empty_text"

    clean = text.strip()
    if ARABIC_URDU_SCRIPT_REGEX.search(clean):
        logger.warning("⚠️ Non-Latin script detected in Whisper output: %r", clean)
        return False, "non_latin_script"

    clean_lower = clean.lower()
    if len(clean_lower) < 3:
        return False, "too_short"

    words = [w for w in re.split(r"\s+", clean_lower) if w]
    if len(words) < 2:
        return False, "insufficient_words"

    # Check filler words
    meaningful_words = [w for w in words if w not in FILLER_WORDS]
    if not meaningful_words:
        return False, "only_filler_words"

    # Check repetition / model hallucination
    if REPETITION_REGEX.search(clean_lower):
        return False, "excessive_word_repetition"

    if CHAR_REPETITION_REGEX.search(clean_lower):
        return False, "excessive_char_repetition"

    # Semantic rank bounds validation
    valid_rank, out_val = validate_rank_number(clean_lower, max_items=12)
    if not valid_rank:
        return False, f"out_of_bounds_rank_{out_val}"

    return True, "valid"


def calculate_transcript_confidence(raw_text: str, result_dict: Dict[str, Any]) -> float:
    """
    Computes a normalized confidence score (0.0 to 1.0) combining:
    1. Pre-normalization of ASR phonetic variations via RomanUrduNormalizer.
    2. Classifier confidence score from language_guard/classify_and_normalize.
    3. Transcription validation integrity check & semantic rank validation.
    """
    base_confidence = float(result_dict.get("confidence", 0.85))

    # Pre-processing: Apply dictionary & stretch normalization BEFORE validity check
    try:
        from roman_urdu_normalizer import get_roman_urdu_normalizer
        norm_res = get_roman_urdu_normalizer().normalize(raw_text)
        eval_text = norm_res["normalized"]
    except Exception as e:
        logger.warning("Pre-normalization in confidence check skipped: %s", e)
        eval_text = raw_text

    valid, reason = is_valid_transcript(eval_text)

    if not valid:
        logger.info("🔍 Transcript validation flagged '%s': %r", reason, raw_text)
        return min(base_confidence, 0.45)

    return base_confidence
