"""
server/intent_classifier.py
============================
Semantic Intent Classifier for Roman Urdu and English user messages.
Uses Sentence-Transformers embeddings (all-MiniLM-L6-v2) with cosine similarity
matching against semantic intent anchors. Falls back gracefully to regex/keyword
similarity if sentence-transformers is loading or unavailable.
"""

import logging
import re
from typing import Dict, Any, List, Tuple
import numpy as np

logger = logging.getLogger("intent-classifier")

# Anchor phrases per intent category (Roman Urdu + English)
INTENT_ANCHORS = {
    "ranking_complete": [
        "main apni ranking complete kar chuka hoon",
        "meri rating poori ho gayi hai",
        "mein ne apni list final kar li hai",
        "i have completed my ranking",
        "my list is finished",
        "mujhe aur rank nahi karna ho gaya mera",
        "sab items set ho gaye hain mere",
        "done with my ranking",
        "mene 12 items rank kar diye hain"
    ],
    "ranking_refusal": [
        "main ranking nahi karunga",
        "mujhe ranking nahi karni",
        "main kuch bhi rank nahi karna chahta",
        "i refuse to rank these items",
        "i will not do any ranking",
        "chalo yaar mujh se ranking nahi hoti",
        "fazool hai main nahi list bana raha",
        "i don't care about this list"
    ],
    "conflict": [
        "chup kar jao fazool baatein kar rahe ho",
        "tum pagal ho kya",
        "bakwas mat karo",
        "shut up you don't know anything",
        "stop talking nonsense",
        "tumhari wajah se time waste ho raha hai",
        "idiot bad dimag"
    ],
    "dominant_behavior": [
        "meri baat suno main decision lunga",
        "jo main bol raha hoon wahi final hai",
        "bas meri list ko copy kar lo sab",
        "my ranking is the only right one",
        "do what i say without asking"
    ],
    "question": [
        "kya karna hai is stage pe",
        "renge mein kya karna hai",
        "what item should we rank next",
        "how much time is left",
        "chamak kalo kya kehte hain",
        "can someone explain this item",
        "guide kar dio kya karne is mein",
        "guide kar do kya karna hai",
        "moderator aik baar sab ko guide kar do ke ranking kaise karni hai",
        "moderator humein guide karein yahan pe kya karna hai"
    ],
    "guidance_request": [
        "guide kar dio kya karne is mein",
        "guide kar do ke ranking kaise karni hai",
        "moderator guide karein yahan pe kya karna hai",
        "kaise rank karein guide kar do",
        "is mein kya karna hai moderator",
        "explain how to rank items"
    ]
}

class IntentClassifier:
    """Semantic Intent Classifier using Sentence-Transformers with fallback."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self.anchor_embeddings: Dict[str, np.ndarray] = {}
        self._init_model()

    def _init_model(self):
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Initializing SentenceTransformer model: %s", self.model_name)
            self.model = SentenceTransformer(self.model_name)
            
            # Precompute anchor embeddings for instant cosine similarity
            for intent, anchors in INTENT_ANCHORS.items():
                embeddings = self.model.encode(anchors, normalize_embeddings=True)
                self.anchor_embeddings[intent] = embeddings
            logger.info("Semantic intent anchors successfully precomputed.")
        except Exception as e:
            logger.warning("SentenceTransformers initialization fallback to heuristic matcher: %s", e)
            self.model = None

    def classify(self, text: str, language: str = "ur") -> Dict[str, Any]:
        """Classify user text into semantic intent."""
        if not text or not text.strip():
            return {"intent": "normal", "confidence": 1.0, "method": "default"}

        text_clean = text.strip()

        # 1. High-precision semantic embedding classification
        if self.model and self.anchor_embeddings:
            try:
                user_embedding = self.model.encode([text_clean], normalize_embeddings=True)[0]
                best_intent = "normal"
                max_score = 0.0

                for intent, anchor_matrix in self.anchor_embeddings.items():
                    # Cosine similarity (dot product of normalized vectors)
                    similarities = np.dot(anchor_matrix, user_embedding)
                    top_score = float(np.max(similarities))
                    if top_score > max_score:
                        max_score = top_score
                        best_intent = intent

                # Threshold for semantic match
                if max_score >= 0.55:
                    return {
                        "intent": best_intent,
                        "confidence": round(max_score, 3),
                        "method": "sentence_transformer"
                    }
            except Exception as ex:
                logger.error("Error during embedding classification: %s", ex)

        # 2. Fallback Regex / Keyword Pattern Matcher
        return self._heuristic_classify(text_clean)

    def _heuristic_classify(self, text: str) -> Dict[str, Any]:
        lower = text.lower()
        
        # Conflict / Hostility
        if re.search(r"\b(chup|pagal|bakwas|fazool|shut up|nonsense|idiot)\b", lower):
            return {"intent": "conflict", "confidence": 0.85, "method": "heuristic"}
            
        # Completion
        if re.search(r"\b(complete|poori|final|kar chuka|kar chuki|done)\b", lower) and re.search(r"\b(rank|ranking|list|rating|items)\b", lower):
            return {"intent": "ranking_complete", "confidence": 0.85, "method": "heuristic"}

        # Refusal
        if re.search(r"\b(nahi|nahin|not|refuse)\b", lower) and re.search(r"\b(rank|ranking|list|rating)\b", lower):
            return {"intent": "ranking_refusal", "confidence": 0.85, "method": "heuristic"}

        # Guidance Request
        if re.search(r"\b(guide|kya karna|kaise rank|ranking kaise|samjha|batao)\b", lower):
            return {"intent": "guidance_request", "confidence": 0.85, "method": "heuristic"}

        # Question
        if "?" in lower or re.search(r"\b(kya|kaise|kuyun|what|how|why)\b", lower):
            return {"intent": "question", "confidence": 0.75, "method": "heuristic"}

        return {"intent": "normal", "confidence": 0.50, "method": "heuristic"}


# Singleton Instance
_intent_classifier_instance = None

def get_intent_classifier() -> IntentClassifier:
    global _intent_classifier_instance
    if _intent_classifier_instance is None:
        _intent_classifier_instance = IntentClassifier()
    return _intent_classifier_instance
