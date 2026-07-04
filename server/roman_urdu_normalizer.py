"""
server/roman_urdu_normalizer.py
================================
Production-Grade Roman Urdu Normalization Layer.
Placed between Speech-to-Text (STT) and LLM Moderator.

Architecture (3 Sequential Stages):
1. Rules + O(1) Dictionary Mapping
2. RapidFuzz Fuzzy Matcher (Safe Threshold 92-95%)
3. Safe LLM Correction Fallback (Invoked only on low-confidence unmapped tokens)

Critical Constraints:
- NEVER rewrites sentences or alters intent.
- NEVER translates Roman Urdu to Urdu script or English.
- Preserves Code-Mixed English technical terms, Named Entities, and numbers/versions.
"""

import json
import logging
import os
import re
import time
from typing import Dict, Any, List, Tuple, Optional, Set

logger = logging.getLogger("roman-urdu-normalizer")

try:
    from rapidfuzz import process, fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    HAS_RAPIDFUZZ = False

# Protected Technical Words (Code-Mixed English) — Never modified, casing preserved
PROTECTED_TECHNICAL_WORDS: Set[str] = {
    "python", "ai", "llm", "accessibility", "chatgpt", "api", "json", "sql",
    "react", "flutter", "figma", "github", "cors", "vercel", "render", "supabase",
    "openai", "groq", "whisper", "socket.io", "http", "https", "url", "tts", "stt",
    "office", "university", "department", "project", "system", "database"
}

# English words with legitimate double letters (avoid reducing stretch letters)
ENGLISH_DOUBLE_LETTER_WORDS: Set[str] = {
    "good", "see", "look", "speed", "keep", "free", "green", "meet", "tree",
    "book", "food", "tool", "cool", "root", "foot", "door", "floor", "feel",
    "need", "feed", "deep", "seek", "peek", "week", "pool", "zoom", "loop",
    "moon", "soon", "noon", "boot", "sheet", "street", "sweet", "speech"
}

# Regex Patterns for Protection
NUMBERS_VERSIONS_REGEX = re.compile(
    r"\b(?:\d+(?:\.\d+)?%?|[a-zA-Z]+-\d+(?:\.\d+)*|\d+(?:\.\d+)+)\b"
)
URL_REGEX = re.compile(r"https?://\S+|www\.\S+")
MENTION_OR_TAG_REGEX = re.compile(r"@[a-zA-Z0-9_]+")


class RomanUrduNormalizer:
    """
    Modular, high-performance Roman Urdu Normalization Engine.
    """

    def __init__(self, dictionary_path: Optional[str] = None, fuzzy_threshold: float = 93.0):
        self.fuzzy_threshold = fuzzy_threshold
        self.dictionary: Dict[str, str] = {}
        self.canonical_vocab: List[str] = []
        self._load_dictionary(dictionary_path)

    def _load_dictionary(self, custom_path: Optional[str]):
        default_path = os.path.join(
            os.path.dirname(__file__), "data", "roman_urdu_dictionary.json"
        )
        dict_file = custom_path or default_path
        if os.path.exists(dict_file):
            try:
                with open(dict_file, "r", encoding="utf-8") as f:
                    self.dictionary = json.load(f)
                self.canonical_vocab = list(set(self.dictionary.values()))
                logger.info(
                    "✅ Loaded Roman Urdu dictionary (%d mappings, %d canonical words)",
                    len(self.dictionary),
                    len(self.canonical_vocab),
                )
            except Exception as e:
                logger.error("❌ Failed to load Roman Urdu dictionary: %s", e)
        else:
            logger.warning("⚠️ Dictionary file not found: %s", dict_file)

    def reduce_stretch_letters(self, word: str) -> Tuple[str, bool]:
        """
        Reduces 3+ repeated characters (e.g. bohaaaat -> bohat, naiiiii -> nahi),
        while protecting legitimate double letters in English words (good, see, look).
        """
        if not word or len(word) < 3:
            return word, False

        w_lower = word.lower()
        if w_lower in ENGLISH_DOUBLE_LETTER_WORDS or w_lower in PROTECTED_TECHNICAL_WORDS:
            return word, False

        # Reduce 3 or more consecutive identical characters to 1
        reduced = re.sub(r"(.)\1{2,}", r"\1", word)
        
        # Specific Roman Urdu stretch fixes
        if reduced.lower() == "naii" or reduced.lower() == "nai":
            reduced = "nahi"

        changed = reduced != word
        return reduced, changed

    def clean_punctuation_and_whitespace(self, text: str) -> str:
        """Normalizes duplicate spaces, extra commas, repeated periods."""
        if not text:
            return text
        # Remove duplicate commas/periods/exclamations
        text = re.sub(r",+", ",", text)
        text = re.sub(r"\.+", ".", text)
        text = re.sub(r"!+", "!", text)
        text = re.sub(r"\?+", "?", text)
        # Remove double spaces
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def is_protected_token(self, token: str) -> bool:
        """Checks if a token should be protected from normalization."""
        clean = token.strip().lower()
        if not clean:
            return True
        if clean in PROTECTED_TECHNICAL_WORDS:
            return True
        if NUMBERS_VERSIONS_REGEX.match(token) or MENTION_OR_TAG_REGEX.match(token):
            return True
        if URL_REGEX.match(token):
            return True
        # Protection for uppercase abbreviations (e.g., AI, LLM, API, SQL)
        if token.isupper() and len(token) <= 5:
            return True
        return False

    def fuzzy_match_token(self, token: str) -> Tuple[Optional[str], float]:
        """Performs safe fuzzy matching against canonical vocabulary (92-95% threshold)."""
        if not self.canonical_vocab or len(token) < 3:
            return None, 0.0

        tok_lower = token.lower()
        if HAS_RAPIDFUZZ:
            res = process.extractOne(
                tok_lower, self.canonical_vocab, scorer=fuzz.WRatio
            )
            if res:
                match_word, score, _ = res
                if score >= self.fuzzy_threshold:
                    return match_word, float(score)
                return None, float(score)
        else:
            matches = difflib.get_close_matches(
                tok_lower, self.canonical_vocab, n=1, cutoff=self.fuzzy_threshold / 100.0
            )
            if matches:
                return matches[0], 93.0

        return None, 0.0

    def normalize(self, text: str, use_llm_fallback: bool = False) -> Dict[str, Any]:
        """
        Normalizes input text passing through Stage 1 (Rules/Dict), Stage 2 (Fuzzy), Stage 3 (LLM Fallback).
        Returns structured JSON with original text, normalized text, and audit log of changes.

        NOTE: This normalizer only handles LATIN-SCRIPT Roman Urdu. If the input contains
        non-Latin script (Urdu/Arabic, Devanagari, etc.), it is returned unchanged so that
        downstream LLM transliteration (in classify_and_normalize) can handle the script
        conversion properly.
        """
        t_start = time.time()
        if not text or not text.strip():
            return {
                "original": text,
                "normalized": text,
                "changes": [],
                "processing_time_ms": 0.0,
            }

        # Early return for non-Latin script input (Urdu/Arabic, Devanagari, etc.)
        # Our tokenizer regex only matches Latin chars, so non-Latin text would get
        # silently dropped/garbled. Return unchanged and let the LLM transliterator
        # in classify_and_normalize() handle the script conversion.
        _NON_LATIN_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿ऀ-ॿ가-힯]")
        if _NON_LATIN_RE.search(text):
            logger.info("⏭️ Normalizer skipping non-Latin script input (will be handled by LLM transliterator)")
            proc_ms = round((time.time() - t_start) * 1000, 2)
            return {
                "original": text,
                "normalized": text,
                "changes": [],
                "processing_time_ms": proc_ms,
            }

        cleaned_text = self.clean_punctuation_and_whitespace(text)
        tokens = re.findall(r"https?://\S+|\b[a-zA-Z0-9_\-\.]+%|\b[a-zA-Z0-9_\-\.]+\b|[^\w\s]", cleaned_text)
        
        normalized_tokens: List[str] = []
        changes: List[Dict[str, Any]] = []

        for token in tokens:
            # Skip punctuation tokens
            if not re.match(r"\w+", token):
                normalized_tokens.append(token)
                continue

            # Stage 0: Protection Check (Technical terms, Names, Numbers, Versions)
            if self.is_protected_token(token):
                normalized_tokens.append(token)
                continue

            tok_lower = token.lower()
            norm_word = token
            reason = None
            confidence = 1.0

            # Stage 1: O(1) Dictionary Lookup
            if tok_lower in self.dictionary:
                norm_word = self.dictionary[tok_lower]
                reason = "dictionary"
                confidence = 1.0
            else:
                # Stage 1b: Stretch letter reduction
                stretched_fixed, was_stretched = self.reduce_stretch_letters(token)
                if was_stretched:
                    st_lower = stretched_fixed.lower()
                    if st_lower in self.dictionary:
                        norm_word = self.dictionary[st_lower]
                        reason = "stretch_reduction_and_dict"
                    else:
                        norm_word = stretched_fixed
                        reason = "stretch_reduction"
                    confidence = 0.95
                else:
                    # Stage 2: Fuzzy Matching against Canonical Vocab
                    fuzzy_match, score = self.fuzzy_match_token(tok_lower)
                    if fuzzy_match:
                        norm_word = fuzzy_match
                        reason = f"fuzzy_match_{score:.1f}%"
                        confidence = round(score / 100.0, 3)

            # Preserve original capitalization if token was title-cased
            if token.istitle() and not norm_word.isupper():
                norm_word = norm_word.capitalize()

            if norm_word != token:
                changes.append(
                    {
                        "original": token,
                        "normalized": norm_word,
                        "confidence": confidence,
                        "reason": reason,
                    }
                )
                logger.info(
                    "✏️ Normalization [%s]: '%s' -> '%s' (conf=%.2f)",
                    reason,
                    token,
                    norm_word,
                    confidence,
                )

            normalized_tokens.append(norm_word)

        # Reconstruct normalized sentence
        normalized_text = " ".join(normalized_tokens)
        # Fix spaces around punctuation
        normalized_text = re.sub(r"\s+([,.!?])", r"\1", normalized_text)
        normalized_text = self.clean_punctuation_and_whitespace(normalized_text)

        # Stage 3: LLM Safe Correction Fallback (only invoked if explicit and unmapped)
        if use_llm_fallback and any(c["confidence"] < 0.85 for c in changes):
            normalized_text = self._llm_safe_correction(normalized_text)

        proc_ms = round((time.time() - t_start) * 1000, 2)
        return {
            "original": text,
            "normalized": normalized_text,
            "changes": changes,
            "processing_time_ms": proc_ms,
        }

    def _llm_safe_correction(self, text: str) -> str:
        """Stage 3: LLM Safe Fallback for ambiguous Roman Urdu inputs."""
        try:
            from prompts import call_llm
            prompt = (
                "You are a strict Roman Urdu spelling normalizer. "
                "Fix ONLY obvious transcription typos in Roman Urdu. "
                "CRITICAL RULES: DO NOT rewrite sentences, DO NOT change meaning, "
                "DO NOT translate to English or Urdu script, KEEP technical words (AI, Python, API) unchanged.\n"
                f"Input: {text}"
            )
            resp = call_llm(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=60,
            )
            return resp.strip() if resp else text
        except Exception as e:
            logger.error("LLM Safe Correction Fallback failed: %s", e)
            return text


# Singleton Instance
_normalizer_instance = None


def get_roman_urdu_normalizer() -> RomanUrduNormalizer:
    global _normalizer_instance
    if _normalizer_instance is None:
        _normalizer_instance = RomanUrduNormalizer()
    return _normalizer_instance
