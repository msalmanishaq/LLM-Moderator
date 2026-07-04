"""
server/semantic_validator.py
=============================
Semantic Validation Layer for Roman Urdu & English ASR Pipeline.
Validates messages based on SEMANTIC CONTENT (Items, Ranks, Guidance Requests) rather than acoustic confidence alone.
"""

import logging
import re
from typing import Tuple, Optional, List, Dict, Any

logger = logging.getLogger("semantic-validator")

try:
    from rapidfuzz import process, fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    HAS_RAPIDFUZZ = False

# Domain items (Roman Urdu + English variations)
DOMAIN_ITEMS = [
    # Water
    "paani", "water", "panni", "pani", "water bottles",
    # Tarp
    "tarp", "tarap", "trap", "tarp sheet",
    # Mirror
    "aaina", "mirror", "shisha", "cosmetic mirror", "visor mirror",
    # Compass
    "compass", "kompas", "qutub numa",
    # Map
    "map", "naqsha", "mapi", "road map",
    # Flashlight
    "flashlight", "torch", "flashlite", "light",
    # Lighter/Matches
    "lighter", "match", "matches", "machis", "fire",
    # Knife/Multi-tool
    "knife", "chaku", "multi-tool", "multitol", "churi",
    # Salt
    "salt", "namak", "sort", "salt packets",
    # Jacket/Coat
    "jacket", "jaket", "coat", "coart", "hodie", "winter coat",
    # Guide Book
    "book", "kitab", "guide", "survival book", "guide book",
    # Emergency Triangle
    "triangle", "triangal", "reflector", "emergency triangle",
    # Parachute
    "parachute", "peerasho", "parashoot",
    # Plastic Sheet
    "plastic", "sheet", "parasheet", "plastic sheet",
    # Space Blanket
    "blanket", "space blanket"
]

GUIDANCE_PHRASES = [
    "kya karna hai", "guide kar", "smjha do", "help", "batao",
    "kaise karna", "kya karne", "kya karein", "guide me", "samjha do",
    "shuru kaise", "kaise rank", "kya cheez hai"
]

RANK_PATTERNS = [
    r'(?:number|rank|no\.?|#|position)?\s*(\d{1,2})',
    r'(\d{1,2})(?:st|nd|rd|th)?\s*(?:number|rank)?'
]

WORD_RANK_MAP = {
    'pehla': 1, 'pehlay': 1, 'first': 1, 'one': 1, 'ek': 1, 'aik': 1,
    'doosra': 2, 'doosri': 2, 'second': 2, 'two': 2, 'do': 2,
    'teesra': 3, 'teesri': 3, 'third': 3, 'three': 3, 'teen': 3,
    'chautha': 4, 'chauthi': 4, 'fourth': 4, 'four': 4, 'chaar': 4, 'char': 4,
    'paanchwa': 5, 'paanchwi': 5, 'fifth': 5, 'five': 5, 'paanch': 5, 'panch': 5,
    'chhata': 6, 'chhati': 6, 'sixth': 6, 'six': 6, 'che': 6, 'chah': 6,
    'satwa': 7, 'satwi': 7, 'seventh': 7, 'seven': 7, 'saat': 7,
    'aathwa': 8, 'aathwi': 8, 'eighth': 8, 'eight': 8, 'aath': 8,
    'nowa': 9, 'nowi': 9, 'ninth': 9, 'nine': 9, 'nau': 9, 'no': 9,
    'daswa': 10, 'daswi': 10, 'tenth': 10, 'ten': 10, 'das': 10,
    'gyarhwa': 11, 'gyarhwi': 11, 'eleventh': 11, 'eleven': 11, 'gyarah': 11,
    'barhwa': 12, 'barhwi': 12, 'twelfth': 12, 'twelve': 12, 'barah': 12
}


def extract_items(text: str, threshold: float = 70.0) -> List[Tuple[str, float]]:
    """Extract all domain items from text using RapidFuzz matching."""
    if not text:
        return []
    matches = []
    seen = set()
    words = re.findall(r'\b[a-zA-Z0-9_\-]+\b', text.lower())
    
    # Also check multi-word phrases in text
    text_lower = text.lower()
    for item in DOMAIN_ITEMS:
        if " " in item and item in text_lower:
            if item not in seen:
                seen.add(item)
                matches.append((item, 100.0))

    for word in words:
        if len(word) < 2:
            continue
        if HAS_RAPIDFUZZ:
            res = process.extractOne(word, DOMAIN_ITEMS, scorer=fuzz.WRatio)
            if res and res[1] >= threshold:
                matched_item, score, _ = res
                if matched_item not in seen:
                    seen.add(matched_item)
                    matches.append((matched_item, float(score)))
        else:
            matches_list = difflib.get_close_matches(word, DOMAIN_ITEMS, n=1, cutoff=threshold / 100.0)
            if matches_list and matches_list[0] not in seen:
                seen.add(matches_list[0])
                matches.append((matches_list[0], 85.0))

    return matches


def extract_rank(text: str) -> Optional[int]:
    """Extract rank number from text (1-12)."""
    if not text:
        return None
    text_lower = text.lower()

    # 1. Check digit patterns (e.g. number 1, rank 2, 1st, #1)
    for pattern in RANK_PATTERNS:
        matches = re.findall(pattern, text_lower)
        for m in matches:
            try:
                val = int(m)
                if 1 <= val <= 12:
                    return val
            except ValueError:
                pass

    # 2. Check Roman Urdu & English rank words (e.g. pehla, doosra, first, one)
    words = re.findall(r'\b[a-zA-Z]+\b', text_lower)
    for word in words:
        if word in WORD_RANK_MAP:
            return WORD_RANK_MAP[word]

    return None


def detect_guidance_request(text: str) -> bool:
    """Check if user is asking for guidance or task explanation."""
    if not text:
        return False
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in GUIDANCE_PHRASES)


def validate_semantic_content(text: str) -> Dict[str, Any]:
    """
    Validate message based on SEMANTIC CONTENT rather than acoustic confidence.
    Returns a dict with validation results.
    """
    result: Dict[str, Any] = {
        "valid": False,
        "items": [],
        "rank": None,
        "guidance_request": False,
        "rejection_reason": None,
        "confidence": 0.0,
    }

    if not text or not text.strip():
        result["rejection_reason"] = "no_semantic_content"
        return result

    # Check for guidance request
    result["guidance_request"] = detect_guidance_request(text)
    if result["guidance_request"]:
        result["valid"] = True
        result["confidence"] = 100.0
        return result

    # Extract items & rank
    result["items"] = extract_items(text)
    result["rank"] = extract_rank(text)

    # Determine validity
    if result["items"] and result["rank"]:
        result["valid"] = True
        result["confidence"] = min(100.0, len(result["items"]) * 30 + 40)
        return result

    if result["items"] and not result["rank"]:
        result["valid"] = False
        result["rejection_reason"] = "missing_rank"
        result["confidence"] = min(100.0, len(result["items"]) * 20 + 20)
        return result

    if result["rank"] and not result["items"]:
        result["valid"] = False
        result["rejection_reason"] = "missing_item"
        result["confidence"] = min(100.0, 30)
        return result

    # No items, no rank
    result["valid"] = False
    result["rejection_reason"] = "no_semantic_content"
    result["confidence"] = 0.0
    return result


def get_validation_response(result: Dict[str, Any]) -> Dict[str, str]:
    """
    Generate appropriate, helpful response based on validation result.
    """
    if result.get("guidance_request"):
        return {
            "type": "guidance",
            "message": "Aapko desert survival items ko 1 se 12 tak rank karna hai, jahan 1 sab se ahem hai. Har ek item par apni rai share karein. Jaise 'paani number 1'."
        }

    if result.get("valid"):
        item = result["items"][0][0] if result["items"] else "item"
        rank = result["rank"]
        return {
            "type": "acknowledge",
            "message": f"Acha, aap ne {item} ko #{rank} rakhna hai. Baqi items par kya khayal hai?"
        }

    if result.get("rejection_reason") == "missing_rank":
        items = ", ".join([i[0] for i in result["items"]])
        return {
            "type": "clarification",
            "message": f"Aap ne {items} ki baat ki. Kya yeh kis rank par aana chahiye? Jaise 'paani number 1'."
        }

    if result.get("rejection_reason") == "missing_item":
        rank = result["rank"]
        return {
            "type": "clarification",
            "message": f"Aap ne rank #{rank} kaha. Kya yeh kis item ke liye hai? Jaise 'paani number 1'."
        }

    return {
        "type": "repeat",
        "message": "Maaf kijiye, mujhe samajh nahi aaya. Kya aap items ko rank kar sakte hain? Jaise 'paani number 1'."
    }
