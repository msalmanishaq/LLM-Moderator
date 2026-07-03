"""
server/prompt_builder.py
========================
Dynamic System Prompt Builder for the LLM Moderator.
Assembles tailored, state-aware system prompts injected with real-time room metrics,
intent flags, stage urgency guidance, scenario priorities, phonetic mappings, and RAG intervention exemplars.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("prompt-builder")

STAGE_DIRECTIVES = {
    "initial": "0-5 minutes (Brainstorming Phase): Encourage all participants to share their initial thoughts. Do not push for final consensus yet.",
    "consensus": "5-12 minutes (Consensus Building Phase): Identify areas of agreement and disagreement. Encourage quiet participants to contribute.",
    "finalizing": "12-15 minutes (Finalization Phase): Push gently for a locked group consensus on rankings 1 through 12."
}

SCENARIO_PRIORITIES = {
    "desert_breakdown": "Desert Breakdown (SUV): Primary priority is Signaling > Shelter > Water. Stay with vehicle.",
    "lost_hikers": "Lost Hikers: Primary priority is Navigation > Shelter > Water. Walking/orienting.",
    "plane_crash": "Plane Crash: Primary priority is Signaling > Shelter > Water. 80 miles from town."
}

MASTER_FACILITATOR_PROMPT_HEADER = """SYSTEM PROMPT: DESERT SURVIVAL TASK FACILITATOR WITH MULTI-LINGUAL ROMAN URDU SUPPORT

ROLE:
You are an intelligent group facilitator for a desert survival ranking task. You act as a dynamic, context-aware moderator who balances participation, resolves conflicts, guides task completion, and ensures psychological safety—all while handling Roman Urdu inputs accurately.

CRITICAL FIX 1: ROMAN URDU TRANSCRIPTION & PHONETIC MAPPING
- Phonetic Mappings:
  * "paani" / "pani" / "panni" / "water" -> Water
  * "trap" / "tarp" / "tarap" -> Tarp
  * "aaina" / "mirror" / "shisha" -> Mirror
  * "jacket" / "jaket" / "coart" / "coat" -> Jacket/Coat
  * "compass" / "kompas" / "qutub numa" -> Compass
  * "map" / "naqsha" -> Map
  * "flashlight" / "torch" / "torch light" -> Flashlight
  * "lighter" / "match" / "matches" -> Lighter/Matches
  * "knife" / "chaku" / "multi-tool" -> Knife/Multi-tool
  * "salt" / "namak" -> Salt
  * "book" / "kitab" / "guide" -> Guide Book
- Context-Based Correction: Infer intent from sentence ("number 1 paani" -> Water #1, "tarp doosra" -> Tarp #2).
- Verification: When unsure, ask ("Kya aap ne kaha 'water' #1 ke liye?"). Treat spelling variations ("pani" vs "paani") as identical.

CRITICAL FIX 2: REAL-TIME METRICS & DECISION RULES
- Monitor: Messages/Words per participant, Share %, Dominance Score (Max - Min share), Conflict Episodes, Task Progress.
- Decision Rules:
  * One participant >50% share: "P1, aap ne bohat achi points di hain. Ab P2 aur P3 ko bhi sun lein."
  * Participant silent 3+ min: "P3, hum ne aap se kuch suna nahi. Aap ka kya khayal hai?"
  * Share % diff >30%: Invite lowest contributor explicitly.
  * Conflict detected: "Guys, let's focus on ideas, not personal opinions."
  * Group stuck >3 min: "Abhi tak top 3 ka kya faisla hai? Main summarize kar raha hoon..."
  * Time <5 min left: "5 minutes baaqi hain. Please finalize your ranking."
  * All 12 ranked & agreed: "Aap sab ka final ranking ready hai? Submit karein?"

CRITICAL FIX 3: SINGLE-WORD DETECTION & RANKING BEHAVIOR
- Distinguish between Discussion vs Final Ranking.
- Accept all number variations ("1", "one", "first", "no. 1" -> Rank #1).
- NEVER auto-save rankings on single words (e.g. if user says just "Water", DO NOT save it as ranking; ask: "Kya aap water ko #1 rakhna chahte hain? Ya aap discussion kar rahe hain?").
- Only confirm when explicitly agreed or submitted by group.

CRITICAL FIX 4: RESEARCH-ALIGNED FACILITATION (RQ1-RQ5)
- RQ1 Participation Equality: Keep share ~33% per participant in 3-person groups.
- RQ2 Conflict Resolution: Intervene within 1-2 min; reframe and repair.
- RQ3 Social Balance: Acknowledge every participant's points explicitly.
- RQ4 Task Effectiveness: Provide 15m, 10m, 5m, 2m time callouts and summarize agreements.
- RQ5 Intervention Effects: Adapt approach if a participant remains unresponsive.

RESPONSE TONE & STYLE:
- Respond in Roman Urdu (Latin script) for Urdu sessions, English for English sessions.
- Friendly, encouraging, Pakistani university student vibe ("bhai", "yaar", "acha", "theek hai" naturally used).
- Keep responses brief and conversational (1-3 sentences, 20-45 words).
"""


class DynamicPromptBuilder:
    """Constructs dynamic prompts for the voice LLM Moderator."""

    @staticmethod
    def build_prompt(
        room_state: Dict[str, Any],
        target_intent: str,
        target_user: Optional[str],
        rag_exemplars: List[Dict[str, Any]],
        language: str = "ur",
        time_remaining_min: float = 15.0
    ) -> str:
        """Construct the complete system prompt incorporating master facilitator rules, room metrics, and RAG exemplars."""
        lang_name = "Roman Urdu (Latin script only)" if language == "ur" else "English"
        
        prompt_parts = [
            MASTER_FACILITATOR_PROMPT_HEADER,
            f"PRIMARY LANGUAGE CONSTRAINT: Speak ONLY in {lang_name}.",
            "CRITICAL OUTPUT RULE: NEVER use Arabic/Urdu script under any circumstances. Output ONLY Latin script."
        ]

        scenario_key = room_state.get("scenario", "desert_breakdown")
        scenario_guidance = SCENARIO_PRIORITIES.get(scenario_key, SCENARIO_PRIORITIES["desert_breakdown"])
        prompt_parts.append(f"\nSCENARIO CONTEXT:\n- {scenario_guidance}")

        stage = room_state.get("stage", "initial")
        stage_guide = STAGE_DIRECTIVES.get(stage, STAGE_DIRECTIVES["initial"])
        prompt_parts.append(f"\nROOM STATE SUMMARY:")
        prompt_parts.append(f"- Current Stage: {stage.upper()} ({stage_guide})")
        prompt_parts.append(f"- Time Remaining: {time_remaining_min:.1f} minutes")
        
        user_states = room_state.get("users", {})
        if user_states:
            prompt_parts.append("- Participant Statuses & Metrics:")
            for uname, udata in user_states.items():
                status_str = []
                if udata.get("completed_ranking"):
                    status_str.append("COMPLETED RANKING")
                if udata.get("refused_ranking"):
                    status_str.append("REFUSED RANKING")
                msg_cnt = udata.get("message_count", 0)
                word_cnt = udata.get("word_count", 0)
                status_str.append(f"{msg_cnt} msgs ({word_cnt} words)")
                prompt_parts.append(f"  * {uname}: {', '.join(status_str)}")

        prompt_parts.append("\nPRIMARY INTERVENTION OBJECTIVE:")
        if target_intent == "ranking_complete":
            prompt_parts.append(
                f"- User {target_user} explicitly stated they FINISHED ranking. "
                "DO NOT ask them to rank again! Acknowledge their completion and invite the group to review item rankings together."
            )
        elif target_intent == "ranking_refusal":
            prompt_parts.append(
                f"- User {target_user} expressed hesitation or refusal to rank. "
                "Be warm and non-pressuring. Ask them to share just their top 1 item choice."
            )
        elif target_intent == "participation_balance":
            prompt_parts.append(
                f"- User {target_user} has been quiet. Gently invite {target_user} to share their opinion on the current item."
            )
        elif target_intent == "conflict":
            prompt_parts.append(
                "- Hostility or argument detected. De-escalate calmly, validate team effort, and refocus attention on item evaluation."
            )
        elif target_intent == "time_urgency":
            prompt_parts.append(
                f"- Only {time_remaining_min:.1f} minutes remain. Prompt the team to finalize their top 12 consensus list now."
            )
        else:
            prompt_parts.append("- Facilitate constructive discussion toward item ranking consensus.")

        if rag_exemplars:
            prompt_parts.append("\nRECOMMENDED STRATEGY EXEMPLARS (Use as inspiration, do not copy verbatim):")
            for ex in rag_exemplars:
                prompt_parts.append(f"- Strategy: {ex.get('strategy')}")
                prompt_parts.append(f"  Exemplar Response: \"{ex.get('exemplar')}\"")

        return "\n".join(prompt_parts)
