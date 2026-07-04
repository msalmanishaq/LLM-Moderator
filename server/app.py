from __future__ import annotations
import os
import sys

# Eventlet monkey-patching breaks on Python 3.12+ (ssl.wrap_socket removed). Default to threading there.
_socketio_async_mode = os.getenv("SOCKETIO_ASYNC_MODE", "").strip().lower()
if _socketio_async_mode not in ("eventlet", "threading"):
    _socketio_async_mode = (
        "threading" if sys.version_info >= (3, 12) else "eventlet"
    )

if _socketio_async_mode == "eventlet":
    import eventlet

    eventlet.monkey_patch()

# Windows consoles often default to cp1252; keep emoji log lines from crashing stderr.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ============================================================
# LLM Moderator Server with Supabase Integration - RESEARCH VERSION
# WITH DESERT SURVIVAL TASK AND ACTIVE/PASSIVE MODERATION
# Following exact experiment design specifications
# ============================================================

import uuid
import logging
import time
import threading
import json
import csv
import random
import re
import hashlib
import traceback  # Add this line
from functools import wraps
from collections import OrderedDict
from io import BytesIO, StringIO
from typing import Dict, List, Any, Optional, Set
from datetime import datetime, timezone

from flask import Flask, request, send_file, jsonify, make_response, Response, stream_with_context
from flask_socketio import SocketIO, join_room, emit
from flask_cors import CORS
from dotenv import load_dotenv

# ============================================================
# Import Supabase Client
# ============================================================
from supabase_client import (
    get_or_create_room,
    get_room,
    update_room_status,
    update_room_participant_count,
    add_participant,
    get_participants,
    get_participant_by_socket,
    get_participant_by_username,
    get_next_participant_name,
    add_message,
    get_chat_history,
    create_session,
    end_session,
    supabase,
    create_room as supabase_create_room,
    analyze_student_behavior,
    save_room_metrics,
    log_moderator_intervention,
    analyze_conflict_episodes,
    upload_voice_staging,
    finalize_voice_recording,
    get_voice_recordings_for_room,
    download_voice_object,
    persist_moderator_tts,
    check_required_schema,
    voice_recording_file_exists,
)
from audio_export import concat_clips, assembly_available, AudioAssemblyError

# ============================================================
# Import Research Metrics
# ============================================================
from research_metrics import (
    calculate_gini_coefficient,
    calculate_entropy,
    detect_conflict_episodes,
    message_suggests_interpersonal_conflict,
    recent_multispeaker_tension,
    discussion_appears_off_task,
    intervention_followup_seconds,
)

# ============================================================
# Import Task System (Desert Survival)
# ============================================================
from data_retriever import (
    get_data,
    format_story_block,
    get_story_intro_html,
    get_task_items,
    compare_with_expert_ranking,
    resolve_task_data_from_room,
    pin_task_data_for_room,
    get_pinned_or_resolve_task_data,
    get_canonical_items_for_room,
    clarify_alias_against_list,
)

# ============================================================
# Import Prompt Functions
# ============================================================
from prompts import (
    generate_active_moderator_response,
    generate_passive_moderator_response,
    generate_personalized_feedback,
    get_random_ending,
    check_inappropriate_language,
    get_language_severity,
    get_template_message,
    get_fallback_feedback,
    get_active_invite_phrase,
    detect_language,
    detect_language_from_messages,
    normalize_roman_urdu,
    roman_to_urdu_script,
    classify_and_normalize,
    enforce_pakistani_roman_urdu,
    roman_urdu_spoken_intro,
    LANG_EN,
    LANG_ROMAN_URDU,
    LANG_MIXED,
)
from room_state import (
    get_room_state,
    update_room_state,
    record_intervention,
    room_state_brief,
    reset_room_state,
    set_room_language,
    get_pinned_language,
)
from event_log import (
    log_event,
    log_failure,
    experiment_condition,
    finalize_session,
)
from language_guard import sanitize_to_supported

# ============================================================
# Logger Setup
# ============================================================
DEBUG_LOG_FILE = "server_debug.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(DEBUG_LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger("LLM_MODERATOR")
logger.info("="*60)
logger.info("🚀 LLM Moderator Research Server Starting")
logger.info("="*60)

# ============================================================
# App Setup
# ============================================================
load_dotenv()

# Get frontend URL first (needed for CORS and redirects)
FRONTEND_ENV = os.getenv(
    "FRONTEND_URL",
    "https://llm-moderator-main-s6bx.vercel.app",
).strip()

# Parse comma-separated list of origins for CORS configuration
origins_set = {"http://localhost:3000"}
for url in FRONTEND_ENV.split(","):
    url = url.strip()
    if url:
        if url.endswith("/"):
            url = url[:-1]
        origins_set.add(url)

# Always explicitly allow all known frontend deployment URLs to prevent CORS blockages
origins_set.add("https://llm-moderator-main-s6bx.vercel.app")
origins_set.add("https://llm-moderator-main-do.vercel.app")
origins_set.add("https://llm-moderator-39gf.vercel.app")

allowed_origins = list(origins_set)

# Define FRONTEND_URL as the primary single origin for link/redirect generation
FRONTEND_URL = FRONTEND_ENV.split(",")[0].strip()
if FRONTEND_URL.endswith('/'):
    FRONTEND_URL = FRONTEND_URL[:-1]

logger.info(f"🔒 CORS allowed origins: {allowed_origins}")

app = Flask(__name__)
# Explicitly allow the custom X-Admin-Token header on preflight, or the browser blocks
# the actual admin GET after the OPTIONS (symptom: only OPTIONS in the log, no GET).
CORS(
    app,
    resources={r"/*": {"origins": allowed_origins}},
    allow_headers=["Content-Type", "X-Admin-Token", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
)

socketio = SocketIO(
    app,
    cors_allowed_origins=allowed_origins,
    async_mode=_socketio_async_mode,
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25,
)
@socketio.on('connect')
def handle_connect():
    logger.info(f"🔌 SOCKET CONNECTED: {request.sid} from origin: {request.headers.get('Origin', 'Unknown')}")
    emit('connected', {'data': 'Connected successfully'})

@socketio.on('connect_error')
def handle_connect_error(error):
    logger.error(f"❌ SOCKET CONNECT ERROR: {error}")

@socketio.on("disconnect")
def handle_disconnect():
    """Clear socket_id on disconnect so we do not target dead connections; swallow teardown errors."""
    sid = getattr(request, "sid", None) or ""
    try:
        logger.info(f"🔌 Client disconnected: {sid}")
        participant = get_participant_by_socket(sid) if sid else None
        if participant and participant.get("id"):
            supabase.table("participants").update(
                {
                    "socket_id": None,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", participant["id"]).execute()
    except Exception as e:
        # Avoid noisy tracebacks during WSGI/socket teardown (e.g. write before start_response).
        logger.debug(f"Disconnect cleanup (non-critical): {e}")
# Add after your socketio initialization
@socketio.on('ping')
def handle_ping(data):
    """Respond to client pings to keep connection alive"""
    emit('pong', {'timestamp': data.get('timestamp', 0)})

# Add this middleware to keep responses alive
@app.after_request
def add_keep_alive_headers(response):
    response.headers.add('Connection', 'keep-alive')
    response.headers.add('Keep-Alive', 'timeout=60, max=1000')
    return response
# ============================================================
# Room State Management
# ============================================================
active_monitors: Dict[str, threading.Thread] = {}
room_sessions: Dict[str, str] = {}  # room_id -> session_id
research_timers: Dict[str, threading.Thread] = {}  # room_id -> timer thread
# Wall-clock zero for the 15-minute research block (set when task goes active, not room creation)
room_research_session_started_at: Dict[str, float] = {}
room_last_expert_tip: Dict[str, float] = {}
room_expert_tip_message_key: Dict[str, str] = {}
room_active_moderator_aux: Dict[str, Dict[str, Any]] = {}
last_item_clarification_at: Dict[str, float] = {}
# One 5-min and one 1-min warning per room across timer + active + passive threads
room_time_warning_5min_claimed: Dict[str, bool] = {}
room_time_warning_1min_claimed: Dict[str, bool] = {}
# Per-room locks that serialise start_task_for_room calls so two concurrent
# join_room background tasks can't both pass the status check and spawn
# duplicate moderator threads. dict.setdefault is atomic under CPython's GIL.
_room_task_locks: Dict[str, threading.Lock] = {}

# In-memory "task already started" guard. Set under the per-room task lock the instant a
# room passes the 3-participant gate, BEFORE any DB write. This is what prevents a double
# task-start / double intro, so update_room_status('active') no longer has to sit on the
# critical path ahead of the intro broadcast (a failed status write can't cause a re-start).
_tasks_started: Set[str] = set()

# Per-room wake events. The moderator loop waits on this with a timeout instead of a
# blind sleep, so send_message can nudge it the INSTANT a student speaks — dropping
# reactive-reply detection latency from up-to-the-poll-interval to ~0. The timeout still
# fires for time-based interventions (silence / time warnings), so the moderation cadence
# and every intervention condition are unchanged; only detection latency improves.
room_moderator_wake: Dict[str, threading.Event] = {}


def _get_wake_event(room_id: str) -> threading.Event:
    """Return the room's wake event (created once; setdefault is GIL-atomic)."""
    return room_moderator_wake.setdefault(room_id, threading.Event())


def nudge_moderator(room_id: str) -> None:
    """Wake the room's moderator loop now — a student just spoke. Best-effort."""
    if not room_id:
        return
    try:
        _get_wake_event(room_id).set()
    except Exception:
        pass


# Per-room locks guarding the "who replies to this user turn" claim. The synchronous
# @mention path (socket-handler thread) and the woken monitor loop (its own thread) can
# both look at the same latest user message; without a claim they'd each generate a reply
# → duplicate moderator voice. _claim_reply_to() lets exactly ONE of them win per message.
_room_mod_claim_lock: Dict[str, threading.Lock] = {}


def _claim_reply_to(room_id: str, msg_id: Any) -> bool:
    """Atomically claim the moderator's reply to user message `msg_id` for this room.
    Returns True for the first caller (which should generate the reply) and False for any
    later caller racing on the same message (which must NOT also reply). Claim state is the
    existing `last_at_mod_reply_for_msg_id` aux field, so it stays compatible with the
    loop's own dedup checks."""
    if not room_id or not msg_id:
        return True  # nothing to dedup against → preserve prior behavior
    lock = _room_mod_claim_lock.setdefault(room_id, threading.Lock())
    aux = room_active_moderator_aux.setdefault(room_id, {})
    with lock:
        if str(aux.get("last_at_mod_reply_for_msg_id") or "") == str(msg_id):
            return False
        aux["last_at_mod_reply_for_msg_id"] = str(msg_id)
        return True


def claim_session_time_warning(room_id: str, kind: str) -> bool:
    """Return True if this code path may emit that warning (first claimant wins). kind: '5' or '1'."""
    reg = room_time_warning_5min_claimed if kind == "5" else room_time_warning_1min_claimed
    if reg.get(room_id):
        return False
    reg[room_id] = True
    return True


def _active_moderator_student_msg_ratio(
    messages: List[Dict[str, Any]], lookback: int = 100
) -> float:
    """Moderator_msg_count / max(student_msg_count, 1). Target ≤ 0.15 (RQ1)."""
    if not messages:
        return 0.0
    slice_msgs = messages[-lookback:] if len(messages) > lookback else messages
    mod = sum(1 for m in slice_msgs if m.get("username") == "Moderator")
    stu = sum(
        1
        for m in slice_msgs
        if m.get("username") not in ("Moderator", "System", None, "")
    )
    if stu == 0:
        return 0.0
    return mod / stu


_ACTIVE_INVITE_LINES = (
    "{name}, we'd love your take—what's one item you'd rank higher or lower?",
    "{name}, what do you think matters most for survival here?",
    "Jump in when you can, {name}—any item you want the group to weigh?",
    "{name}, a quick thought on the ranking would help the group.",
)

_ACTIVE_FOLLOWUP_LINES = (
    "{name}, still with us? Even a one-line ranking preference helps.",
    "{name}, no pressure—just share whichever item feels strongest to you.",
    "{name}, checking in: any item you want to push back on?",
)

_ACTIVE_FOLLOWUP_DEEP_LINES = (
    "{name}, we value your input—what's at least one item you'd put near the top?",
    "{name}, even a single priority (e.g. “1. water”) helps lock the ranking.",
    "{name}, quick check: which item feels most urgent for survival to you?",
)


def _pick_phrase(templates: tuple, name: str) -> str:
    return random.choice(templates).format(name=name)


def _room_minutes_elapsed(room: Dict[str, Any], now: Optional[float] = None) -> int:
    """Whole minutes since room creation."""
    if now is None:
        now = time.time()
    created_at_val = room.get("created_at")
    if not created_at_val:
        return 0
    try:
        if isinstance(created_at_val, str):
            cv = created_at_val.replace("Z", "+00:00")
            created_at_dt = datetime.fromisoformat(cv)
            return max(0, int((now - created_at_dt.timestamp()) / 60))
        if isinstance(created_at_val, (int, float)):
            return max(0, int((now - float(created_at_val)) / 60))
    except Exception:
        pass
    return 0


def _research_session_minutes_elapsed(
    room_id: str, room: Dict[str, Any], now: Optional[float] = None
) -> int:
    """Minutes since the research block started (3 participants ready), not room creation."""
    if now is None:
        now = time.time()
    start = room_research_session_started_at.get(room_id)
    if start is not None:
        return max(0, int((now - float(start)) / 60))
    return _room_minutes_elapsed(room, now)


def _session_start_timestamp(room_id: str, room: Optional[Dict[str, Any]]) -> float:
    """Unix time for silence idle baseline (task start if known, else room creation)."""
    st = room_research_session_started_at.get(room_id)
    if st is not None:
        return float(st)
    return _room_created_timestamp(room)


def collect_discussed_canonical_items(
    messages: List[dict], canonical_items: List[str]
) -> set:
    """Distict official item lines explicitly referenced in student chat."""
    out: set = set()
    for m in messages:
        if m.get("username") in ("Moderator", "System"):
            continue
        low = (m.get("message") or "").lower()
        for item in canonical_items:
            il = item.lower()
            if len(il) >= 6 and il in low:
                out.add(item)
    return out


def trailing_student_streak(messages: List[dict]) -> tuple:
    """How many consecutive student messages at the end, same speaker (moderator breaks)."""
    streak_user = None
    streak = 0
    for m in reversed(messages):
        u = m.get("username")
        if u in ("Moderator", "System"):
            break
        if u is None:
            continue
        if streak_user is None:
            streak_user = u
            streak = 1
        elif u == streak_user:
            streak += 1
        else:
            break
    return streak_user, streak


def record_first_mention(
    attribution: Dict[str, str],
    speaker: Optional[str],
    text: str,
    canonical_items: List[str],
) -> None:
    """First speaker to mention an item/topic wins (research attribution)."""
    if not speaker or speaker in ("Moderator", "System"):
        return
    low = (text or "").lower()
    for item in canonical_items:
        il = item.lower()
        if len(il) >= 6 and il in low:
            attribution.setdefault(il[:48], speaker)
            return
    for topic in (
        "water",
        "mirror",
        "flashlight",
        "tarp",
        "compass",
        "map",
        "knife",
        "lighter",
        "jacket",
        "salt",
        "blanket",
        "parachute",
    ):
        if topic in low:
            attribution.setdefault(topic, speaker)
            return


# Summon the moderator on any mention of "moderator" (with or without the @), in
# English or Roman Urdu — e.g. "moderator", "@moderator", "moderator kya khayal hai".
_MODERATOR_MENTION_RE = re.compile(r"\bmoderator\b", re.IGNORECASE)


def _mentions_moderator(text: str) -> bool:
    return bool(text and _MODERATOR_MENTION_RE.search(text))


def enforce_response_length(text: str, max_words: int = 55) -> str:
    """Cap a moderator line to at most `max_words` words (a safety net; the prompts already
    aim for ~25 words / 1-3 sentences). Returns the text unchanged when it's already within
    budget — so it's a no-op for short canned lines. When it must trim, it prefers to end at
    the last sentence boundary inside the budget to avoid a mid-sentence cut, falling back to
    a clean word-boundary cut with an ellipsis. Markdown (**bold**) is preserved.

    Defensive by design: any unexpected input is returned best-effort rather than raising,
    because this runs inside the moderator loop where an exception would skip the rest of the
    tick.
    """
    try:
        if not text:
            return text or ""
        words = str(text).split()
        if max_words is None or max_words <= 0 or len(words) <= max_words:
            return str(text).strip()
        clipped = " ".join(words[:max_words]).strip()
        # Prefer ending on a complete sentence within the budget.
        for end in (". ", "! ", "? "):
            idx = clipped.rfind(end)
            if idx >= len(clipped) * 0.6:  # only if it keeps most of the content
                return clipped[: idx + 1].strip()
        # Otherwise a clean word-boundary cut with an ellipsis.
        return clipped.rstrip(",;:—- ") + "…"
    except Exception:
        # Never let a formatting helper break moderator generation.
        return str(text).strip() if text else ""


def chat_socket_payload(sender: str, message: str, **extra: Any) -> dict:
    """Stable chat event payload with id (dedup on client)."""
    payload: dict = {
        "id": extra.pop("id", None) or str(uuid.uuid4()),
        "sender": sender,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    }
    payload.update(extra)
    return payload


def send_moderator_message(
    room_id: str,
    text: str,
    msg_type: str = "moderator",
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Unified helper to record, synthesize TTS audio, and emit a moderator message.
    1. Saves message to DB via add_message.
    2. Synthesizes & persists TTS audio using persist_moderator_tts (skipping if < 20 chars).
    3. Emits receive_message payload and moderator_audio event for active voice playback.
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return {}

    # Save message row
    saved_msg = add_message(room_id, "Moderator", clean_text, msg_type)
    msg_id = saved_msg.get("id") if isinstance(saved_msg, dict) else None

    # Synthesize & persist TTS for messages >= 20 characters
    audio_record = None
    if clean_text and len(clean_text) >= 20 and msg_id:
        try:
            from supabase_client import persist_moderator_tts
            audio_record = persist_moderator_tts(room_id, str(msg_id), clean_text)
            if audio_record:
                logger.info(f"🔊 Synthesized & persisted moderator TTS for msg_id={msg_id} ({len(clean_text)} chars)")
        except Exception as tts_err:
            logger.warning(f"⚠️ Moderator TTS generation failed: {tts_err}")

    # Build socket payload
    extra = metadata or {}
    if audio_record:
        extra["audio_url"] = audio_record.get("audio_url")
        extra["storage_path"] = audio_record.get("storage_path")

    payload = chat_socket_payload("Moderator", clean_text, **extra)
    if msg_id:
        payload["id"] = msg_id

    socketio.emit("receive_message", payload, room=room_id)

    # Emit explicit moderator_audio event for active voice playback client hooks
    if audio_record and audio_record.get("audio_url"):
        socketio.emit("moderator_audio", {
            "room_id": room_id,
            "message_id": msg_id,
            "audio_url": audio_record.get("audio_url"),
            "text": clean_text
        }, room=room_id)

    return payload


# Rolling per-room language state, updated gradually from STUDENT messages so the
# moderator/TTS don't flip language on a single noisy message. "mixed" counts toward
# Roman Urdu for voice routing (Pakistani code-switching reads better in the Urdu voice).
# NOTE: in-memory + process-local (fine for the single-worker setup; would move to a
# shared store if running multiple workers).
room_language_votes: Dict[str, Dict[str, float]] = {}
_stt_retry_tracker: Dict[str, int] = {}


def update_room_language(room_id: str, language: str, confidence: float = 1.0) -> None:
    """Add a weighted vote for a room's language from one student message."""
    if not room_id or language not in (LANG_EN, LANG_ROMAN_URDU, LANG_MIXED):
        return
    bucket = room_language_votes.setdefault(room_id, {LANG_EN: 0.0, LANG_ROMAN_URDU: 0.0})
    key = LANG_EN if language == LANG_EN else LANG_ROMAN_URDU  # mixed → urdu bucket
    bucket[key] += max(0.0, min(1.0, confidence)) or 1.0


def get_room_language(room_id: str) -> Optional[str]:
    """Return the room's language. An explicit join-time pin is AUTHORITATIVE; otherwise
    fall back to the rolling vote tally."""
    pinned = get_pinned_language(room_id)
    if pinned:
        return pinned
    bucket = room_language_votes.get(room_id)
    if not bucket:
        return None
    total = bucket[LANG_EN] + bucket[LANG_ROMAN_URDU]
    if total <= 0:
        return None
    # English wins ties (conservative default); Roman Urdu needs a clear majority.
    return LANG_ROMAN_URDU if bucket[LANG_ROMAN_URDU] > bucket[LANG_EN] else LANG_EN


def get_room_primary_language(room_id: str, room: Optional[Dict[str, Any]] = None) -> str:
    """A room's primary language for the moderator/intro.

    Priority: explicit join-time pin (in-memory) → rooms.primary_language (DB, survives
    restart) → detection from recent STUDENT messages → "en". Returns "roman_urdu"/"en".
    """
    pinned = get_pinned_language(room_id)
    if pinned:
        return "roman_urdu" if pinned in ("roman_urdu", "mixed") else "en"
    db_lang = (room or {}).get("primary_language") if room else None
    if db_lang in ("en", "roman_urdu"):
        return db_lang
    try:
        history = get_chat_history(room_id, limit=10) or []
        student_msgs = [
            m for m in history
            if m.get("username") not in ("Moderator", "System", None, "")
            and (m.get("message_type") or "chat") in ("chat", "chat_flagged")
        ]
        return detect_language_from_messages(student_msgs)
    except Exception as e:
        logger.warning(f"Could not detect room language for {room_id}: {e}")
        return "en"


def get_expert_ranking_opinion(item_label: str) -> Optional[str]:
    """Short expert-style survival perspective for a scenario item (neutral, educational)."""
    low = item_label.lower()
    if "water" in low or "quart" in low:
        return (
            "💧 Water is usually the highest priority in desert heat — even mild dehydration "
            "impairs judgment quickly."
        )
    if "mirror" in low or "cosmetic" in low:
        return (
            "🪞 A mirror is an excellent lightweight signal for aircraft; many expert rankings "
            "place it very high for rescue visibility."
        )
    if "flashlight" in low or "battery" in low:
        return (
            "🔦 Flashlights help at night for signaling and camp tasks, but batteries are finite — "
            "compare that to passive signaling tools."
        )
    if "plastic" in low or "sheet" in low:
        return (
            "🟠 A large plastic sheet can provide shade, collect dew/rain, and improve visibility "
            "depending on color."
        )
    if "match" in low:
        return (
            "🔥 Matches are useful if you have fuel and fire safety; in dry desert conditions "
            "their value depends on what you can burn."
        )
    if "coat" in low or "winter" in low:
        return (
            "🧥 A coat matters for cold desert nights when temperatures can drop sharply after sunset."
        )
    if "salt" in low or "tablet" in low:
        return (
            "🧂 Salt tablets without enough water can worsen dehydration — experts often rank them "
            "lower unless water is abundant."
        )
    if "knife" in low:
        return (
            "🔪 A knife is versatile for gear repair, shelter, and first aid; usefulness is high "
            "but not always above water and rescue signaling."
        )
    if "parachute" in low:
        return (
            "🪂 Parachute fabric can be shelter or signal material; expert lists vary based on "
            "whether rescue or self-extraction is the plan."
        )
    if "book" in low or "edible" in low:
        return (
            "📖 Field guides look helpful, but misidentifying plants is dangerous — many expert "
            "rankings place this lower than water, signaling, and shelter."
        )
    if "compass" in low:
        return (
            "🧭 A compass mainly helps if the group chooses to move; staying put is often safer "
            "when lost and awaiting rescue."
        )
    if "map" in low:
        return (
            "🗺️ Like a compass, a map helps navigation — value drops if the plan is to stay in place "
            "and signal rescuers."
        )
    return None

# ============================================================
# Groq Client Setup
# ============================================================
groq_client = None
openai_client = None

# Try to initialize OpenAI first
try:
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if openai_api_key:
        from openai import OpenAI
        # Bound every call: the SDK default is a 600 s timeout × 2 retries, so a single
        # stalled STT/TTS/LLM request would pin a server thread for ~30 min and starve
        # the (concurrency-limited) dev server. 30 s / 1 retry caps worst-case at ~60 s.
        openai_client = OpenAI(api_key=openai_api_key, timeout=30.0, max_retries=1)
        logger.info("✅ OpenAI client initialized (timeout=30s, retries=1)")
    else:
        logger.warning("⚠️ OPENAI_API_KEY not found")
except ImportError:
    logger.warning("⚠️ openai package not installed")
except Exception as e:
    logger.error(f"❌ Error initializing OpenAI client: {e}")

# Try Groq as fallback
try:
    from groq import Groq
    groq_api_key = os.getenv("GROQ_API_KEY")
    if groq_api_key:
        # Same rationale as the OpenAI client: bound hangs so one slow LLM call can't
        # hold a worker thread and stall transcription/voice for everyone.
        groq_client = Groq(api_key=groq_api_key, timeout=20.0, max_retries=1)
        logger.info("✅ Groq client initialized as fallback (timeout=20s, retries=1)")
    else:
        logger.warning("⚠️ GROQ_API_KEY not found")
except ImportError:
    logger.warning("⚠️ groq package not installed")
except Exception as e:
    logger.error(f"❌ Error initializing Groq client: {e}")

# ============================================================
# TTS Voice Provider Setup (swappable via TTS_PROVIDER env)
# ============================================================
from voice_providers import get_voice_provider, VoiceProviderError

voice_provider = None
try:
    voice_provider = get_voice_provider()
    logger.info(f"✅ TTS voice provider initialized: {voice_provider.name}")
except VoiceProviderError as e:
    logger.warning(f"⚠️ TTS voice provider unavailable: {e}")
except Exception as e:
    logger.error(f"❌ Error initializing TTS voice provider: {e}")

# Per-language provider cache. Roman Urdu prefers Uplift (better pronunciation);
# English uses OpenAI. Providers are built lazily and reused. If a provider is
# missing credentials it simply isn't cached, and /tts falls back to OpenAI.
_tts_provider_cache: Dict[str, Any] = {}


def _get_tts_provider(name: str):
    """Return a cached TTS provider by name, or None if it can't be built."""
    if name in _tts_provider_cache:
        return _tts_provider_cache[name]
    try:
        provider = get_voice_provider(name)
    except Exception as e:
        logger.warning(f"⚠️ TTS provider {name!r} unavailable: {e}")
        provider = None
    _tts_provider_cache[name] = provider
    return provider


def synthesize_for_language(text: str, language: Optional[str]) -> bytes:
    """Synthesize `text` choosing Uplift/OpenAI using the unified tts_manager."""
    from tts.tts_manager import tts_manager
    from tts.language import detect_language
    from config import TTSConfig
    
    lang = language or detect_language(text)
    prefer_uplift = lang in ("roman_urdu", "urdu", "mixed", "ur", "sd")
    force_uplift = prefer_uplift and TTSConfig.FORCE_UPLIFT_FOR_URDU
    
    if prefer_uplift:
        logger.info(f"[TTS] routing Urdu to tts_manager (lang={lang!r})")
        audio = tts_manager.synthesize(text, language=lang)
        if audio:
            return audio
            
        if force_uplift:
            logger.error("[TTS] Uplift failed and FORCE_UPLIFT_FOR_URDU is set — NOT using OpenAI fallback")
            raise VoiceProviderError("Uplift synthesis failed (FORCE_UPLIFT_FOR_URDU=true)")
            
        logger.warning("[TTS] Uplift failed → falling back to OpenAI")
        log_failure(None, "tts_provider_fallback", error="Uplift synthesis failed", recovery="used openai voice")
        
    # Standard English / fallback synthesis
    audio = tts_manager.synthesize(text, language=lang)
    if audio:
        return audio
        
    raise VoiceProviderError("No usable TTS provider succeeded")


def synthesize_for_language_streaming(text: str, language: Optional[str]):
    """Generator version of synthesize_for_language — yields MP3 chunks.
    Simply yields the synthesized bytes at once.
    """
    yield synthesize_for_language(text, language)


# ============================================================
# Server-side TTS audio cache (process-wide) with in-flight de-duplication
# ------------------------------------------------------------
# Every participant's browser runs its own voice queue, so all 3 request /tts for the
# SAME moderator line — that's N identical OpenAI syntheses for one sentence, and 3N
# across rooms that share a task intro. This cache collapses them to ONE: the first
# caller synthesizes while concurrent callers for the same (language, text) WAIT on the
# in-flight result; later callers hit the cache instantly. Bounded LRU. Fully
# transparent — any miss, timeout, or error falls through to a normal synthesis, so it
# can never break or change what is spoken.
# ============================================================
_TTS_CACHE_MAX = 512
# How long a concurrent caller waits for an in-flight synthesis before synthesizing itself.
# Must exceed the slowest provider (Uplift Urdu + transliteration can take tens of seconds),
# otherwise the 3 participant requests for one moderator line each give up and re-synthesize,
# tripling Uplift load and the latency. Generous so the de-dup actually de-dups.
_TTS_INFLIGHT_WAIT_S = 70.0
_tts_audio_cache: "OrderedDict[str, bytes]" = OrderedDict()
_tts_inflight: Dict[str, threading.Event] = {}
_tts_cache_lock = threading.Lock()


def _tts_cache_key(text: str, language: Optional[str]) -> str:
    return hashlib.sha1(f"{language or ''}\x00{text}".encode("utf-8")).hexdigest()


def synthesize_for_language_cached(text: str, language: Optional[str]) -> bytes:
    """synthesize_for_language() fronted by the shared cache + in-flight de-dup."""
    key = _tts_cache_key(text, language)

    with _tts_cache_lock:
        cached = _tts_audio_cache.get(key)
        if cached is not None:
            _tts_audio_cache.move_to_end(key)  # LRU touch
            logger.info(f"[TTS] cache HIT ({language}, {len(cached)} bytes)")
            return cached
        ev = _tts_inflight.get(key)
        owner = ev is None
        if owner:
            ev = threading.Event()
            _tts_inflight[key] = ev

    if owner:
        logger.info(f"[TTS] cache MISS → synthesizing ({language}, {len(text)} chars)")
        try:
            audio = synthesize_for_language(text, language)
            # Only cache PLAUSIBLE audio. Caching a tiny/empty result (e.g. a provider that
            # 200s with a non-audio body) would pin a permanently-silent clip for this text
            # and serve it to every participant + manual replays. Too-small results are
            # returned once but not cached, so a later attempt can recover.
            if audio and len(audio) >= 512:
                with _tts_cache_lock:
                    _tts_audio_cache[key] = audio
                    _tts_audio_cache.move_to_end(key)
                    while len(_tts_audio_cache) > _TTS_CACHE_MAX:
                        _tts_audio_cache.popitem(last=False)  # evict oldest
            else:
                logger.warning(f"[TTS] NOT caching implausible audio ({len(audio or b'')} bytes)")
            return audio
        finally:
            with _tts_cache_lock:
                _tts_inflight.pop(key, None)
            ev.set()  # release any waiters (cache hit if we succeeded, else they retry)

    # Someone else is already synthesizing this exact line — wait for their result.
    logger.info(f"[TTS] in-flight WAIT (≤{_TTS_INFLIGHT_WAIT_S}s) for owner ({language})")
    _tw = time.time()
    if ev.wait(timeout=_TTS_INFLIGHT_WAIT_S):
        with _tts_cache_lock:
            cached = _tts_audio_cache.get(key)
            if cached is not None:
                _tts_audio_cache.move_to_end(key)
                logger.info(f"[TTS] in-flight WAIT done in {time.time() - _tw:.1f}s → using owner's result")
                return cached
        logger.warning(f"[TTS] owner finished in {time.time() - _tw:.1f}s but cached nothing → re-synthesizing")
    else:
        logger.warning(f"[TTS] in-flight WAIT TIMED OUT after {_TTS_INFLIGHT_WAIT_S}s → re-synthesizing (owner still slow)")
    # Owner timed out or failed — synthesize independently (rare; keeps us non-blocking).
    return synthesize_for_language(text, language)


def prewarm_tts_async(text: str, language: Optional[str]) -> None:
    """Best-effort background warm of the TTS cache (e.g. the deterministic task intro),
    so the first participant's /tts is a cache hit instead of a cold synthesis."""
    if not text or not text.strip():
        return

    def _run():
        try:
            synthesize_for_language_cached(text, language)
            logger.info(f"🔥 TTS prewarmed ({language}, {len(text)} chars)")
        except Exception as e:
            logger.debug(f"TTS prewarm skipped: {e}")

    threading.Thread(target=_run, name="tts-prewarm", daemon=True).start()

# ============================================================
# Register Admin API Blueprint
# ============================================================
from admin_api import admin_bp, get_setting_value, prefetch_settings

app.register_blueprint(admin_bp)
logger.info("✅ Admin API registered at /admin")

# ============================================================
# Configuration - Load from Database
# ============================================================
logger.info("📝 Loading configuration from database...")
# Pull every setting in ONE query up front; the ~16 get_setting_value() calls
# below then read from the in-process cache instead of one round-trip each.
prefetch_settings()

# ── Schema preflight ─────────────────────────────────────────────────────────
# A session must not run on an un-migrated DB (it would lose data silently). We
# check once at startup and gate /join on it; ALLOW_UNMIGRATED=true bypasses (dev).
ALLOW_UNMIGRATED = os.getenv("ALLOW_UNMIGRATED", "false").strip().lower() in ("1", "true", "yes", "on")
PREFLIGHT = {"ok": True, "missing": []}
try:
    PREFLIGHT = check_required_schema()
    if PREFLIGHT["ok"]:
        logger.info("✅ Preflight: all required tables present (DB migrated)")
    else:
        logger.error(
            "❌ Preflight: MISSING schema %s — sessions will be REFUSED at /join "
            "(set ALLOW_UNMIGRATED=true to bypass in dev)", PREFLIGHT["missing"]
        )
except Exception as e:
    logger.warning(f"⚠️ Preflight check could not run: {e}")

WELCOME_MESSAGE = get_setting_value("WELCOME_MESSAGE", "Welcome everyone! I'm the Moderator.")
LLM_PROVIDER = get_setting_value("LLM_PROVIDER", "groq")
GROQ_MODEL = get_setting_value("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_TEMPERATURE = get_setting_value("GROQ_TEMPERATURE", 0.7)
GROQ_MAX_TOKENS = get_setting_value("GROQ_MAX_TOKENS", 2000)

# Research settings - FROM YOUR EXPERIMENT DESIGN
# Timers are env-/settings-configurable: env var wins, then the `settings` DB table,
# then the historical default. Voice rooms (speaking latency > typing) get separate
# windows; their defaults fall back to the text values so nothing changes until set.
def _research_setting_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is not None and str(raw).strip() != "":
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            logger.warning("Bad int for env %s=%r; using settings/default", name, raw)
    val = get_setting_value(name, None)
    if val is not None:
        try:
            return int(float(val))
        except (TypeError, ValueError):
            logger.warning("Bad int for setting %s=%r; using default", name, val)
    return default


def _research_setting_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is not None and str(raw).strip() != "":
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    val = get_setting_value(name, None)
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
    return default


# Text (typing-latency) windows — historical defaults preserved.
SILENCE_THRESHOLD_SECONDS = _research_setting_int("SILENCE_THRESHOLD_SECONDS", 90)
SILENCE_FOLLOWUP_SECONDS = _research_setting_int("SILENCE_FOLLOWUP_SECONDS", 180)
SILENCE_FOLLOWUP_THIRD_SECONDS = _research_setting_int("SILENCE_FOLLOWUP_THIRD_SECONDS", 270)
SILENCE_REINVITE_GAP_SECONDS = _research_setting_int("SILENCE_REINVITE_GAP_SECONDS", 90)

# Voice (speaking-latency) windows — default to the text values until configured.
SILENCE_THRESHOLD_SECONDS_VOICE = _research_setting_int(
    "SILENCE_THRESHOLD_SECONDS_VOICE", SILENCE_THRESHOLD_SECONDS
)
SILENCE_FOLLOWUP_SECONDS_VOICE = _research_setting_int(
    "SILENCE_FOLLOWUP_SECONDS_VOICE", SILENCE_FOLLOWUP_SECONDS
)
SILENCE_FOLLOWUP_THIRD_SECONDS_VOICE = _research_setting_int(
    "SILENCE_FOLLOWUP_THIRD_SECONDS_VOICE", SILENCE_FOLLOWUP_THIRD_SECONDS
)
SILENCE_REINVITE_GAP_SECONDS_VOICE = _research_setting_int(
    "SILENCE_REINVITE_GAP_SECONDS_VOICE", SILENCE_REINVITE_GAP_SECONDS
)

# RQ5 intervention→student response window (seconds), text and voice variants.
INTERVENTION_FOLLOWUP_WINDOW_SECONDS = _research_setting_float(
    "INTERVENTION_FOLLOWUP_WINDOW_SECONDS", 180.0
)
INTERVENTION_FOLLOWUP_WINDOW_SECONDS_VOICE = _research_setting_float(
    "INTERVENTION_FOLLOWUP_WINDOW_SECONDS_VOICE", INTERVENTION_FOLLOWUP_WINDOW_SECONDS
)

# A room is treated as "voice" when this share of student messages were spoken.
VOICE_ROOM_MIN_SHARE = _research_setting_float("VOICE_ROOM_MIN_SHARE", 0.5)

DOMINANCE_THRESHOLD = 0.5  # 50% of recent messages - if one person contributes >50%, balance
TIME_WARNING_MINUTES = 5  # Warn when 5 minutes remaining


def _message_input_mode(msg: Dict[str, Any]) -> str:
    """'voice' or 'text' from messages.metadata.input_mode (default 'text')."""
    meta = msg.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = None
    if isinstance(meta, dict) and meta.get("input_mode") in ("voice", "text"):
        return meta["input_mode"]
    return "text"


def _room_is_voice_mode(messages: List[Dict[str, Any]]) -> bool:
    """True if ≥ VOICE_ROOM_MIN_SHARE of student messages were sent via voice input."""
    student = [
        m for m in messages
        if m.get("username") not in ("Moderator", "System", None, "")
    ]
    if not student:
        return False
    voice = sum(1 for m in student if _message_input_mode(m) == "voice")
    return (voice / len(student)) >= VOICE_ROOM_MIN_SHARE

logger.info(f"📝 Config: LLM Provider={LLM_PROVIDER}, Model={GROQ_MODEL}")
logger.info(
    "📝 Research Settings: Silence=%ss followup=%ss third=%ss Dominance=%s%%",
    SILENCE_THRESHOLD_SECONDS,
    SILENCE_FOLLOWUP_SECONDS,
    SILENCE_FOLLOWUP_THIRD_SECONDS,
    int(DOMINANCE_THRESHOLD * 100),
)
logger.info(f"📝 Frontend URL: {FRONTEND_URL}")

# ============================================================
# Admin auth — require X-Admin-Token == ADMIN_TOKEN (fail closed if unset)
# ============================================================
def require_admin_token(f):
    """Guard app-level /admin routes. Blueprint routes use admin_bp.before_request."""
    @wraps(f)
    def _wrapped(*args, **kwargs):
        if request.method == "OPTIONS":  # let CORS preflight through
            return ("", 204)
        expected = os.getenv("ADMIN_TOKEN")
        provided = request.headers.get("X-Admin-Token")
        if not expected or provided != expected:
            logger.warning("🔒 Rejected admin request to %s (bad/missing X-Admin-Token)", request.path)
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return _wrapped


# ============================================================
# Export Data Endpoints
# ============================================================

@app.route("/admin/rooms/<room_id>/export/messages", methods=["GET"])
@require_admin_token
def export_room_messages(room_id: str):
    """Export room messages in JSON, CSV, or TSV format"""
    try:
        format_type = request.args.get('format', 'json').lower()
        
        # Get messages from database
        messages_response = supabase.table('messages').select('*').eq('room_id', room_id).order('created_at').execute()
        messages = messages_response.data if messages_response.data else []

        if not messages:
            return jsonify({"error": "No messages found"}), 404

        # Surface input_mode (text/voice) as a top-level field/column for analysis.
        for _m in messages:
            _m["input_mode"] = _message_input_mode(_m)
        
        # Get room info for filename
        room_response = supabase.table('rooms').select('id, created_at').eq('id', room_id).single().execute()
        room = room_response.data if room_response.data else {}
        
        # Format based on requested type
        if format_type == 'json':
            return jsonify({
                "room_id": room_id,
                "exported_at": datetime.now().isoformat(),
                "message_count": len(messages),
                "messages": messages
            })
        
        elif format_type == 'csv':
            output = StringIO()
            if messages:
                all_keys = set()
                for msg in messages:
                    all_keys.update(msg.keys())
                fieldnames = sorted(all_keys)
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(messages)
            
            csv_data = output.getvalue()
            output.close()
            
            response = make_response(csv_data)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=room_{room_id}_messages_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            return response
        
        elif format_type == 'tsv':
            output = StringIO()
            if messages:
                all_keys = set()
                for msg in messages:
                    all_keys.update(msg.keys())
                fieldnames = sorted(all_keys)
                writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter='\t')
                writer.writeheader()
                writer.writerows(messages)
            
            tsv_data = output.getvalue()
            output.close()
            
            response = make_response(tsv_data)
            response.headers['Content-Type'] = 'text/tab-separated-values'
            response.headers['Content-Disposition'] = f'attachment; filename=room_{room_id}_messages_{datetime.now().strftime("%Y%m%d_%H%M%S")}.tsv'
            return response
        
        else:
            return jsonify({"error": f"Unsupported format: {format_type}. Use json, csv, or tsv"}), 400
    
    except Exception as e:
        logger.error(f"❌ Error exporting messages: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/admin/rooms/<room_id>/export/full", methods=["GET"])
@require_admin_token
def export_room_full(room_id: str):
    """Export complete room data including participants and sessions"""
    try:
        format_type = request.args.get('format', 'json').lower()
        
        # Get all room data
        room_response = supabase.table('rooms').select('*').eq('id', room_id).single().execute()
        room = room_response.data if room_response.data else {}
        
        participants_response = supabase.table('participants').select('*').eq('room_id', room_id).order('joined_at').execute()
        participants = participants_response.data if participants_response.data else []
        
        messages_response = supabase.table('messages').select('*').eq('room_id', room_id).order('created_at').execute()
        messages = messages_response.data if messages_response.data else []
        for _m in messages:
            _m["input_mode"] = _message_input_mode(_m)

        sessions_response = supabase.table('sessions').select('*').eq('room_id', room_id).execute()
        sessions = sessions_response.data if sessions_response.data else []

        _voice_msgs = sum(1 for _m in messages
                          if _m.get("username") not in ("Moderator", "System", None, "")
                          and _m.get("input_mode") == "voice")
        _text_msgs = sum(1 for _m in messages
                         if _m.get("username") not in ("Moderator", "System", None, "")
                         and _m.get("input_mode") == "text")

        data = {
            "room": room,
            "participants": participants,
            "messages": messages,
            "sessions": sessions,
            "export_info": {
                "exported_at": datetime.now().isoformat(),
                "room_id": room_id,
                "total_participants": len(participants),
                "total_messages": len(messages),
                "total_sessions": len(sessions),
                "voice_message_count": _voice_msgs,
                "text_message_count": _text_msgs,
            }
        }
        
        if format_type == 'json':
            return jsonify(data)
        
        elif format_type == 'csv':
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['Room ID', 'Room Status', 'Room Mode', 'Created At', 
                           'Participant Count', 'Message Count', 'Session Count'])
            writer.writerow([
                room.get('id', ''),
                room.get('status', ''),
                room.get('mode', ''),
                room.get('created_at', ''),
                len(participants),
                len(messages),
                len(sessions)
            ])
            
            csv_data = output.getvalue()
            output.close()
            
            response = make_response(csv_data)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=room_{room_id}_full_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            return response
        
        else:
            return jsonify({"error": f"Unsupported format: {format_type}"}), 400
    
    except Exception as e:
        logger.error(f"❌ Error exporting full room data: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# Helper: Get Room Task Data
# ============================================================
def get_room_task_data(room_id: str) -> Optional[Dict[str, Any]]:
    """Pinned scenario for this room (same item strings everywhere)."""
    room = get_room(room_id)
    if not room:
        logger.warning(f"⚠️ No room found {room_id}")
        return None
    return get_pinned_or_resolve_task_data(room_id)


# ============================================================
# Auto-ranking from chat (RQ4 — no UI submission)
# ============================================================
_RANK_CHAT_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:^|\n)\s*(\d{1,2})\s*[\.\)]\s*([^\n]+)", re.MULTILINE),
    re.compile(
        r"(?:^|\n)\s*(\d{1,2})(?:st|nd|rd|th)\b\s*[:=\-]?\s*([^\n]+)",
        re.MULTILINE | re.IGNORECASE,
    ),
)


def _match_fragment_to_canonical(
    fragment: str, canonical_items: List[str]
) -> Optional[str]:
    frag = " ".join((fragment or "").split())
    if len(frag) < 2:
        return None
    fl = frag.lower()
    for c in canonical_items:
        if c.lower() == fl:
            return c
    loose = [
        c
        for c in canonical_items
        if fl in c.lower() or c.lower() in fl
    ]
    if len(loose) == 1:
        return loose[0]
    return None


def _collect_rank_slots_from_chat(
    room_id: str, canonical: List[str]
) -> Dict[int, str]:
    """Map rank 1..N → canonical item (later chat wins)."""
    slots: Dict[int, str] = {}
    if not canonical:
        return slots
    n = len(canonical)
    messages = get_chat_history(room_id, limit=400)
    for msg in messages:
        u = msg.get("username")
        if u in ("Moderator", "System", None, ""):
            continue
        text = msg.get("message") or ""
        for pat in _RANK_CHAT_LINE_PATTERNS:
            for m in pat.finditer(text):
                try:
                    r = int(m.group(1))
                except (TypeError, ValueError):
                    continue
                if r < 1 or r > n:
                    continue
                raw = (m.group(2) or "").strip()
                raw = re.split(r"[\n;•]", raw, maxsplit=1)[0].strip()
                canon = _match_fragment_to_canonical(raw, canonical)
                if canon:
                    slots[r] = canon
    return slots


def extract_ranking_strict_from_chat(room_id: str) -> Optional[List[str]]:
    """Full ranking only if chat supplies 1..N with N unique canonical items."""
    td = get_pinned_or_resolve_task_data(room_id)
    canonical = get_task_items(td) or []
    if len(canonical) < 2:
        return None
    n = len(canonical)
    slots = _collect_rank_slots_from_chat(room_id, canonical)
    if len(slots) < n:
        return None
    for r in range(1, n + 1):
        if r not in slots:
            return None
    ordered = [slots[r] for r in range(1, n + 1)]
    if len(set(ordered)) != n:
        return None
    return ordered


def extract_ranking_merged_from_chat(room_id: str) -> Optional[List[str]]:
    """Merge explicit ranks from chat; fill gaps in canonical item-list order."""
    td = get_pinned_or_resolve_task_data(room_id)
    canonical = get_task_items(td) or []
    if len(canonical) < 2:
        return None
    n = len(canonical)
    slots = _collect_rank_slots_from_chat(room_id, canonical)
    out: List[str] = []
    used: Set[str] = set()
    for r in range(1, n + 1):
        c = slots.get(r)
        if c and c in canonical and c not in used:
            out.append(c)
            used.add(c)
        else:
            nxt = next((x for x in canonical if x not in used), None)
            if not nxt:
                return None
            out.append(nxt)
            used.add(nxt)
    return out if len(out) == n and len(used) == n else None


def _persist_room_ranking(room_id: str, ranking: List[str]) -> None:
    """Persist a room's final ranking, tolerant of schema drift.

    Writes `final_ranking` + `ranking_submitted_at`. If the deployed `rooms` table is missing
    the `ranking_submitted_at` column (observed schema drift), PostgREST rejects the whole
    batch — which would also drop `final_ranking`. So on that specific failure we retry with
    `final_ranking` alone, guaranteeing the ranking itself is never lost (everything else
    derives the boolean `ranking_submitted` from `final_ranking`). Other errors propagate.
    """
    payload = {
        "final_ranking": json.dumps(ranking),
        "ranking_submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table("rooms").update(payload).eq("id", room_id).execute()
    except Exception as e:
        msg = str(e).lower()
        if "ranking_submitted_at" in msg or "column" in msg or "pgrst204" in msg or "schema cache" in msg:
            logger.warning(
                "⚠️ rooms.ranking_submitted_at column missing — persisting final_ranking only "
                "(add the column in Supabase to record the timestamp): %s", e
            )
            supabase.table("rooms").update(
                {"final_ranking": json.dumps(ranking)}
            ).eq("id", room_id).execute()
        else:
            raise


def save_auto_ranking(room_id: str, ranking: List[str], source: str) -> bool:
    try:
        _persist_room_ranking(room_id, ranking)
        td = get_room_task_data(room_id) or get_data()
        comparison = compare_with_expert_ranking(ranking, td)
        logger.info(
            "📋 Auto-ranking saved (%s) room=%s… accuracy=%.1f%%",
            source,
            room_id[:8],
            float(comparison["accuracy_percentage"]),
        )
        socketio.emit(
            "ranking_submitted",
            {
                "success": True,
                "message": "Ranking recorded from chat",
                "auto": True,
            },
            room=room_id,
        )
        return True
    except Exception as e:
        logger.error("❌ save_auto_ranking failed: %s", e, exc_info=True)
        return False


# ============================================================
# RESEARCH TIMER - 15 Minute Session Timer
# ============================================================
def start_research_timer(room_id: str):
    """15 minutes from research start: milestone warnings, auto-ranking from chat, session end."""

    existing = research_timers.get(room_id)
    if existing is not None and existing.is_alive():
        logger.warning(
            "⏰ Research timer already running for room %s — not starting another",
            room_id[:8],
        )
        return

    def timer_loop():
        rid = room_id[:8]
        logger.info("⏰ Timer thread started for room %s…", rid)
        logger.info("⏰ Room %s…: sleep 9m → 6 min remaining warning", rid)
        time.sleep(9 * 60)
        room = get_room(room_id)
        if room and room.get("status") == "active":
            logger.info("⏰ Room %s…: sending 6-min warning", rid)
            lang = get_room_primary_language(room_id)
            if lang in ("roman_urdu", "ur", "mixed"):
                reminder = "⏰ **6 minute baaqi hain!** 12 items ki ek mutfiq final ranking par kaam jaari rakhein."
            else:
                reminder = "⏰ **6 minutes remaining!** Keep working toward **one agreed ranking of all 12 items**."
            add_message(room_id, "Moderator", reminder, "system")
            socketio.emit(
                "receive_message",
                chat_socket_payload("Moderator", reminder),
                room=room_id,
            )

        logger.info("⏰ Room %s…: sleep 4m → 2 min remaining + auto-rank attempt", rid)
        time.sleep(4 * 60)
        room = get_room(room_id)
        if room and room.get("status") == "active":
            logger.info("⏰ Room %s…: 2-min milestone", rid)
            lang = get_room_primary_language(room_id)
            if lang in ("roman_urdu", "ur", "mixed"):
                urgent = "⚠️ **2 minute baaqi hain!** Baraye meharbani apni final ranking (1 se 12) jald mukammal karein."
                ok = "📋 **Aap ki discussion se final ranking tay kar li gayi hai.** Session yahan khatam hota hai—shukriya."
            else:
                urgent = "⚠️ **2 minutes remaining!** I'm **inferring a ranking from your chat**—use lines like **`1. item`** … **`12. item`** with the official names when you can."
                ok = "📋 **Final ranking inferred from your discussion.** Ending the session now—thank you."
            add_message(room_id, "Moderator", urgent, "system")
            socketio.emit(
                "receive_message",
                chat_socket_payload("Moderator", urgent),
                room=room_id,
            )
            strict = extract_ranking_strict_from_chat(room_id)
            if strict and save_auto_ranking(room_id, strict, "timer_2min_strict"):
                add_message(room_id, "Moderator", ok, "system")
                socketio.emit(
                    "receive_message",
                    chat_socket_payload("Moderator", ok),
                    room=room_id,
                )
                time.sleep(3)
                try:
                    handle_end_session(
                        {
                            "room_id": room_id,
                            "sender": "system",
                            "reason": "auto_ranking",
                        }
                    )
                except Exception as e:
                    logger.error("Early handle_end_session after auto-rank: %s", e)
                return

        logger.info("⏰ Room %s…: sleep 1m → last minute", rid)
        time.sleep(1 * 60)
        room = get_room(room_id)
        if room and room.get("status") == "active":
            logger.info("⏰ Room %s…: last-minute warning", rid)
            last_push = (
                "⏰ **LAST MINUTE!** The server will **save a ranking from your chat** when time expires."
            )
            add_message(room_id, "Moderator", last_push, "system")
            socketio.emit(
                "receive_message",
                chat_socket_payload("Moderator", last_push),
                room=room_id,
            )

        logger.info("⏰ Room %s…: sleep 1m → time's up", rid)
        time.sleep(1 * 60)
        room = get_room(room_id)
        if room and room.get("status") == "active":
            logger.info("⏰ Room %s…: time's up — merged ranking + end", rid)
            merged = extract_ranking_merged_from_chat(room_id)
            if not merged:
                td_fallback = get_pinned_or_resolve_task_data(room_id)
                fb = get_task_items(td_fallback) or get_task_items(get_data())
                if len(fb) >= 2:
                    merged = list(fb)
            if merged:
                save_auto_ranking(room_id, merged, "timer_end_merged")
            else:
                logger.error("⏰ Room %s…: could not build any ranking list", rid)
            final_msg = "⏰ **Time's up!** Session ending. Thank you for participating."
            add_message(room_id, "Moderator", final_msg, "system")
            socketio.emit(
                "receive_message",
                chat_socket_payload("Moderator", final_msg),
                room=room_id,
            )
            time.sleep(2)
            try:
                handle_end_session(
                    {"room_id": room_id, "sender": "system", "reason": "time_expired"}
                )
            except Exception as e:
                logger.error("Auto handle_end_session failed: %s", e)

    thread = threading.Thread(target=timer_loop, daemon=True)
    thread.start()
    research_timers[room_id] = thread
    logger.info("⏰ Research timer registered for room %s (15m chain)", room_id[:8])

# ============================================================
# Helper: Start Task
# ============================================================
def start_task_for_room(room_id: str):
    """Start desert survival task for a room when conditions are met.

    Serialised per room so two concurrent join_room background tasks can't
    both pass the 'status == waiting' check and spawn duplicate threads.
    """
    lock = _room_task_locks.setdefault(room_id, threading.Lock())
    with lock:
        _start_task_for_room_impl(room_id)


def _start_task_for_room_impl(room_id: str) -> None:
    """Inner body of start_task_for_room; caller holds the per-room lock."""
    try:
        _t_impl0 = time.time()  # latency anchor: lock acquired → first stages
        room = get_room(room_id)
        if not room:
            logger.error(f"❌ Room {room_id} not found")
            return

        participants = get_participants(room_id)
        student_count = len(participants)
        logger.info(
            f"⏱️ [LAT] gating reads (get_room+get_participants) "
            f"+{int((time.time() - _t_impl0) * 1000)}ms ({student_count} students)"
        )

        logger.info(f"📊 Room {room_id}: {student_count} students, status={room['status']}")

        # RESEARCH: Only start when EXACTLY 3 participants
        if room['status'] == 'active':
            logger.info(f"ℹ️ Room {room_id} already active")
            return
        elif room['status'] == 'completed':
            logger.info(f"ℹ️ Room {room_id} already completed")
            return

        # RESEARCH: Wait for exactly 3 participants
        if student_count < 3:
            logger.info(f"ℹ️ Room {room_id} waiting for 3 participants (current: {student_count})")
            return

        # In-memory double-start guard (atomic under the per-room lock). This — not the DB
        # status flip — is the authoritative "already started" check, so all DB writes can
        # live AFTER the intro broadcast without risking a duplicate task/intro.
        if room_id in _tasks_started:
            logger.info(f"ℹ️ Task already started for room {room_id} (in-memory guard)")
            return
        _tasks_started.add(room_id)

        logger.info(f"🎬 Starting desert survival task for room {room_id} with {student_count} students")
        _t_task0 = time.time()  # latency-breakdown anchor (→ intro broadcast)

        task_data = resolve_task_data_from_room(room)   # in-memory, no DB
        pin_task_data_for_room(room_id, task_data)       # in-memory, no DB

        if not task_data:
            # Degenerate case (missing scenario). Keep prior behavior: flip status + create
            # the session row so the room isn't left stuck, but there's nothing to speak.
            logger.error(f"❌ No task data found for room {room_id}")
            update_room_status(room_id, 'active')
            room_research_session_started_at[room_id] = time.time()
            try:
                session = create_session(
                    room_id=room_id, mode=room['mode'],
                    participant_count=student_count,
                    story_id=room.get('story_id', 'desert_survival'),
                )
                room_sessions[room_id] = session['id']
            except Exception as _se:
                logger.error(f"create_session failed (no-task path): {_se}")
            return

        # ── CRITICAL PATH: get the moderator SPEAKING as fast as possible ───────────────
        # Everything the spoken intro needs (room language + task scenario) is already in
        # memory, so we synthesize + broadcast BEFORE any database write. The research
        # clock is an in-memory stamp (instant). All DB writes (status / session / chat
        # persist) are moved AFTER the broadcast so they can never delay speech.
        room_lang = get_room_primary_language(room_id)
        intro = get_story_intro_html(task_data, language=room_lang)
        room_research_session_started_at[room_id] = time.time()  # in-memory; clock = now

        # What the moderator SPEAKS. The visual card (intro) always stays in English. For a
        # Roman-Urdu room the moderator speaks a natural Pakistani Roman-Urdu task intro
        # instead of reading the English scenario aloud — item names live on the card in
        # canonical English (needed for research matching), so we never translate them.
        if room_lang == "roman_urdu":
            _n_items = len(task_data.get("items") or []) or 12
            spoken_intro = roman_urdu_spoken_intro(_n_items)
        else:
            spoken_intro = _clean_speakable(intro)
        _intro_lang = get_room_language(room_id) or detect_language(spoken_intro)

        # 1) Kick off TTS synthesis of the SPOKEN text FIRST (off-thread). Synthesis overlaps
        #    the broadcast + all DB writes; the in-flight de-dup collapses the 3 participant
        #    /tts requests onto this one job, so the first request is a warm/in-flight hit.
        try:
            prewarm_tts_async(spoken_intro, _intro_lang)
            logger.info(
                f"🔥 [LAT] intro TTS prewarm dispatched +{int((time.time() - _t_impl0) * 1000)}ms "
                f"({_intro_lang}, {len(spoken_intro)} chars, "
                f"spoken={'RU-template' if room_lang == 'roman_urdu' else 'card-text'})"
            )
        except Exception as _pw_ex:
            logger.debug(f"Intro TTS prewarm skipped: {_pw_ex}")

        # 2) BROADCAST the intro NOW — before ANY DB write. The card HTML stays English; for
        #    Roman Urdu we attach speak_text so the client SPEAKS the Roman-Urdu template
        #    instead of toSpeechText(card). (English rooms omit it → unchanged behavior.)
        _intro_extra = {"content_format": "html", "message_type": "task"}
        if room_lang == "roman_urdu":
            _intro_extra["speak_text"] = spoken_intro
        socketio.emit(
            "receive_message",
            chat_socket_payload("Moderator", intro, **_intro_extra),
            room=room_id,
        )
        logger.info(
            f"📋 [LAT] intro BROADCAST +{int((time.time() - _t_impl0) * 1000)}ms "
            f"(from lock acquire), +{int((time.time() - _t_task0) * 1000)}ms from task-start gate, "
            f"lang={room_lang}, spoken_lang={_intro_lang}"
        )

        # 3) ── OFF THE CRITICAL PATH: persistence + research setup (never blocks speech) ──
        #    Guarded so a DB hiccup can't stop the moderator loop from starting.
        try:
            update_room_status(room_id, 'active')
        except Exception as _us:
            logger.error(f"update_room_status failed (post-broadcast): {_us}")
        try:
            session = create_session(
                room_id=room_id, mode=room['mode'],
                participant_count=student_count,
                story_id=room.get('story_id', 'desert_survival'),
            )
            room_sessions[room_id] = session['id']
        except Exception as _se:
            logger.error(f"create_session failed (post-broadcast): {_se}")
        try:
            add_message(
                room_id=room_id, username="Moderator", message=intro,
                message_type="task",
                metadata={"content_format": "html", "kind": "task_intro"},
            )
        except Exception as _am:
            logger.error(f"intro add_message persist failed (post-broadcast): {_am}")
        logger.info(f"💾 [LAT] DB setup done +{int((time.time() - _t_impl0) * 1000)}ms (off critical path)")

        # 4) Start the research timer + moderator loop (status is 'active' by now).
        start_research_timer(room_id)
        if room['mode'] == 'passive':
            logger.info(f"🔴 Starting PASSIVE moderator for room {room_id}")
            start_passive_moderator(room_id)
        else:
            logger.info(f"🟢 Starting ACTIVE moderator for room {room_id}")
            start_active_moderator(room_id)

    except Exception as e:
        logger.error(f"❌ Error starting task for room {room_id}: {e}", exc_info=True)

# ============================================================
# ACTIVE MODERATOR - Complete Implementation
# ============================================================
def start_active_moderator(room_id: str):
    """Active moderator with proactive guidance as per experiment design"""
    existing = active_monitors.get(room_id)
    if existing is not None and existing.is_alive():
        logger.warning(
            "🟢 Active moderator already running for room %s — skipping duplicate start",
            room_id[:8],
        )
        return existing

    def monitor_loop():
        logger.info(f"🟢 ACTIVE moderator started for room {room_id}")

        _wake = _get_wake_event(room_id)
        last_intervention_time = time.time()
        last_dominance_check = time.time()
        last_silence_check = time.time()
        # Per-user cooldown for silence invites (re-invite allowed after gap; avoids one-and-done bug)
        last_silent_invite_at: Dict[str, float] = {}
        silent_followup_sent: Set[str] = set()
        silent_third_sent: Set[str] = set()
        # Track last time we sent a dominance message for each user
        last_dominance_message: Dict[str, float] = {}

        while True:
            try:
                # React the instant a student speaks (nudge_moderator sets the event), but
                # still wake every 5s for time-based checks (silence / time warnings). Same
                # cadence + conditions as a blind sleep(5) — just lower reactive latency.
                _wake.wait(timeout=5)
                _wake.clear()

                room = get_room(room_id)
                if not room or room.get('story_finished') or room['status'] == 'completed':
                    logger.info(f"⏹️ Active moderator stopped for room {room_id}")
                    break
                
                now = time.time()
                
                time_elapsed = _research_session_minutes_elapsed(room_id, room, now)
                time_remaining = max(0, 15 - time_elapsed)
                
                # Get recent messages for analysis. Fetch once (100) and slice the
                # last 50 — avoids a second identical query every 5s, per room.
                msgs_for_ratio = get_chat_history(room_id, limit=100)
                messages = msgs_for_ratio[-50:]
                mod_ratio = _active_moderator_student_msg_ratio(msgs_for_ratio)
                # Voice rooms get longer silence windows (speaking latency > typing).
                voice_mode = _room_is_voice_mode(msgs_for_ratio)
                skip_nonessential = mod_ratio > 0.15
                if skip_nonessential:
                    logger.debug(
                        "Moderator/student msg ratio %.2f — skipping non-essential nudges",
                        mod_ratio,
                    )

                # Get actual participants (excluding Moderator)
                all_participants = get_participants(room_id)
                participant_names = [p['username'] for p in all_participants if p['username'] != 'Moderator']
                lang = get_room_primary_language(room_id)

                # Refresh the full room_state from data already fetched this tick (no
                # extra query). The moderator reads this brief before generating below.
                try:
                    update_room_state(
                        room_id,
                        messages=messages,
                        participants=participant_names,
                        primary_language=get_room_language(room_id),
                        time_elapsed_min=time_elapsed,
                    )
                except Exception as _rs_ex:
                    logger.debug(f"room_state update skipped: {_rs_ex}")

                # If less than 3 participants, skip (shouldn't happen but just in case)
                if len(participant_names) < 3:
                    continue

                # 🔇 CORE RULE: the moderator is REACTIVE — it must not speak into a room
                # where the group hasn't said anything yet. No unprompted "nice momentum"
                # nudges. Wait until at least one student has actually spoken.
                student_msgs = [
                    m for m in messages
                    if m.get("username") not in ("Moderator", "System", None, "")
                ]
                if not student_msgs:
                    continue
                # No NEW student input since the moderator last spoke → skip PROACTIVE
                # nudges (appreciation/progress/momentum) so it can't talk to itself or
                # pile on repeated positivity. Reactive paths (mentions/questions/silence)
                # are handled by their own conditions below.
                _last_msg = messages[-1] if messages else {}
                moderator_spoke_last = _last_msg.get("username") in ("Moderator", "System")

                td_active = get_pinned_or_resolve_task_data(room_id)
                canonical_items = get_task_items(td_active)
                n_target = len(canonical_items) or 12

                _aux_template = {
                    "last_progress_summary_time": now,
                    "last_summary_discussed_len": 0,
                    "statement_attribution": {},
                    "last_attr_msg_id": None,
                    "last_turn_balance_msg_id": None,
                    "last_conflict_deescalation_id": None,
                    "last_drift_nudge_time": 0.0,
                    "last_at_mod_reply_for_msg_id": None,
                    "last_appreciation_sent": 0.0,
                }
                aux = room_active_moderator_aux.setdefault(room_id, dict(_aux_template))
                for _k, _v in _aux_template.items():
                    aux.setdefault(_k, _v)

                if messages:
                    lm = messages[-1]
                    mid = str(lm.get("id", ""))
                    if mid and mid != str(aux.get("last_attr_msg_id") or ""):
                        if lm.get("username") not in ("Moderator", "System"):
                            record_first_mention(
                                aux["statement_attribution"],
                                lm.get("username"),
                                lm.get("message") or "",
                                canonical_items,
                            )
                        aux["last_attr_msg_id"] = mid

                streak_user, streak = trailing_student_streak(messages)
                last_mid = str(messages[-1].get("id", "")) if messages else ""
                if (
                    not skip_nonessential
                    and streak >= 3
                    and streak_user
                    and last_mid
                    and last_mid != str(aux.get("last_turn_balance_msg_id") or "")
                    and now - last_intervention_time > 45
                ):
                    others = [p for p in participant_names if p != streak_user]
                    if others:
                        streak_tpl = random.choice(["turn_balance_streak_a", "turn_balance_streak_b"])
                        force_response = get_template_message(streak_tpl, lang, streak_user=streak_user, others=others[0])
                        send_moderator_message(room_id, force_response, "moderator")
                        log_moderator_intervention(
                            room_id, "force_turn_balance", streak_user,
                            reason=f"{streak_user} message streak >= 3",
                            research_question="RQ3",
                            expected_effect="Interrupt speaking streak and invite others"
                        )
                        aux["last_turn_balance_msg_id"] = last_mid
                        last_intervention_time = now

                # RQ2: Tone / conflict de-escalation (fast, <~1 min after tense exchange)
                # Isolated: a failure here must not skip the question-answering path below.
                try:
                    last_stu = next(
                        (
                            m
                            for m in reversed(messages)
                            if m.get("username") not in ("Moderator", "System", None, "")
                        ),
                        None,
                    )
                    if last_stu and now - last_intervention_time > 50:
                        mid_c = str(last_stu.get("id", ""))
                        tense = message_suggests_interpersonal_conflict(
                            last_stu.get("message", "")
                        ) or recent_multispeaker_tension(messages)
                        if tense and mid_c and mid_c != str(
                            aux.get("last_conflict_deescalation_id") or ""
                        ):
                            aux["last_conflict_deescalation_id"] = mid_c
                            line = get_template_message("conflict_deescalation", lang)
                            add_message(room_id, "Moderator", line, "moderator")
                            socketio.emit(
                                "receive_message",
                                chat_socket_payload("Moderator", line),
                                room=room_id,
                            )
                            log_moderator_intervention(
                                room_id,
                                "conflict_resolution",
                                last_stu.get("username"),
                                reason="Interpersonal conflict or multi-speaker tension detected",
                                research_question="RQ2",
                                expected_effect="De-escalate tension and prompt compromise"
                            )
                            last_intervention_time = now
                except Exception as _rq2_ex:
                    logger.error(f"⚠️ Conflict de-escalation (RQ2) skipped: {_rq2_ex}")

                # RQ4: Refocus when chat drifts off ranking / items (at most ~every 2 min)
                # Isolated: a failure here must not skip the question-answering path below.
                try:
                    if (
                        not skip_nonessential
                        and time_elapsed >= 4
                        and discussion_appears_off_task(messages, canonical_items)
                        and now - float(aux.get("last_drift_nudge_time") or 0) > 120
                        and now - last_intervention_time > 55
                    ):
                        aux["last_drift_nudge_time"] = now
                        line = get_template_message("drift_refocus", lang)
                        add_message(room_id, "Moderator", line, "moderator")
                        socketio.emit(
                            "receive_message",
                            chat_socket_payload("Moderator", line),
                            room=room_id,
                        )
                        log_moderator_intervention(
                            room_id, "discussion_drift", None,
                            reason="Discussion appears off-task based on recent student messages",
                            research_question="RQ4",
                            expected_effect="Refocus discussion on ranking desert items"
                        )
                        last_intervention_time = now
                except Exception as _rq4_ex:
                    logger.error(f"⚠️ Drift refocus (RQ4) skipped: {_rq4_ex}")
                
                # ===== ACTIVE MODERATOR RULES =====
                
                # RULE 0.5: Check for ranking disagreements (Priority 5 consensus de-escalation)
                try:
                    from room_state import get_latest_disagreement
                    disagreed_rank, items_involved = get_latest_disagreement(room_id)
                    if (
                        disagreed_rank
                        and now - float(aux.get("last_consensus_nudge_time") or 0) > 120
                        and now - last_intervention_time > 45
                    ):
                        aux["last_consensus_nudge_time"] = now
                        response = generate_active_moderator_response(
                            participants=participant_names,
                            chat_history=[{"sender": m['username'], "message": m['message']} for m in messages],
                            task_context=f"Desert survival ranking. {room_state_brief(room_id)}",
                            time_elapsed=time_elapsed,
                            last_intervention_time=int(now - last_intervention_time),
                            dominance_detected=None,
                            silent_user=None,
                            language=lang,
                            room_id=room_id,
                            intervention_type="ranking_disagreement"
                        )
                        if response and len(response.strip()) > 10:
                            add_message(room_id, "Moderator", response.strip(), "moderator")
                            socketio.emit(
                                "receive_message",
                                chat_socket_payload("Moderator", response.strip()),
                                room=room_id,
                            )
                            log_moderator_intervention(
                                room_id, "ranking_disagreement", None,
                                reason=f"Disagreement detected on Rank #{disagreed_rank} between {items_involved}",
                                research_question="RQ4",
                                expected_effect="Facilitate consensus on rank disagreement"
                            )
                            last_intervention_time = now
                            logger.info(f"✅ Sent ranking disagreement consensus nudge for Rank #{disagreed_rank}")
                except Exception as _rq4_dis_ex:
                    logger.error(f"⚠️ Ranking disagreement nudge skipped: {_rq4_dis_ex}")

                # RULE 1: Check for dominance (>50% of recent messages)
                if now - last_dominance_check > 30:  # Check every 30 seconds
                    dominant_user = check_dominance(room_id)
                    
                    # Only trigger if:
                    # 1. A dominant user is detected
                    # 2. We haven't intervened in the last 60 seconds (cooldown)
                    # 3. The dominant user is actually in the room
                    # 4. We haven't sent a dominance message to this user in the last 2 minutes
                    if (
                        not skip_nonessential
                        and dominant_user and 
                        dominant_user in participant_names and 
                        (now - last_intervention_time > 60) and
                        (dominant_user not in last_dominance_message or now - last_dominance_message.get(dominant_user, 0) > 120)):
                        
                        logger.info(f"👑 Dominance detected: {dominant_user}")
                        
                        # Get other participants (excluding the dominant one)
                        others = [p for p in participant_names if p != dominant_user]
                        
                        # Use LLM to generate a balanced response
                        if len(others) >= 1:
                            # Let the LLM generate a natural response
                            response = generate_active_moderator_response(
                                participants=participant_names,
                                chat_history=[{"sender": m['username'], "message": m['message']} for m in messages],
                                task_context=f"Desert survival ranking. {room_state_brief(room_id)}",
                                time_elapsed=time_elapsed,
                                last_intervention_time=int(now - last_intervention_time),
                                dominance_detected=dominant_user,
                                silent_user=None,
                                language=get_room_primary_language(room_id),
                                room_id=room_id,
                                intervention_type="balance_dominance"
                            )
                            
                            # If LLM fails, use fallback
                            if not response or len(response) < 10:
                                if len(others) >= 2:
                                    response = get_template_message(
                                        "dominance_fallback_a", lang,
                                        dominant_user=dominant_user,
                                        other0=others[0],
                                        other1=others[1]
                                    )
                                else:
                                    response = get_template_message(
                                        "dominance_fallback_b", lang,
                                        dominant_user=dominant_user,
                                        other0=others[0]
                                    )
                            
                            add_message(room_id, "Moderator", response, "moderator")
                            socketio.emit(
                                "receive_message",
                                chat_socket_payload("Moderator", response),
                                room=room_id,
                            )
                            
                            # Log intervention for research
                            log_moderator_intervention(
                                room_id, "balance_dominance", dominant_user,
                                reason=f"{dominant_user} has >50% of recent messages",
                                research_question="RQ3",
                                expected_effect="Invite other members to reduce speaker dominance"
                            )
                            last_intervention_time = now
                            last_dominance_message[dominant_user] = now
                            
                            logger.info(f"✅ Sent dominance balance message for {dominant_user}")
                    
                    last_dominance_check = now
                
                # RULE 2: Silence (2 min) + optional follow-up (3+ min idle after first ping)
                if now - last_silence_check > 30:
                    silence_handled = False
                    deep = check_silent_third_candidate(
                        room_id,
                        participant_names,
                        last_silent_invite_at,
                        silent_followup_sent,
                        silent_third_sent,
                        now,
                        voice=voice_mode,
                    )
                    if (
                        deep
                        and deep in participant_names
                        and (now - last_intervention_time > 45)
                    ):
                        line_d = get_active_invite_phrase("followup_deep", deep, lang)
                        add_message(room_id, "Moderator", line_d, "moderator")
                        socketio.emit(
                            "receive_message",
                            chat_socket_payload("Moderator", line_d),
                            room=room_id,
                        )
                        log_moderator_intervention(
                            room_id, "invite_silent_third", deep
                        )
                        silent_third_sent.add(deep)
                        last_silent_invite_at[deep] = now
                        last_intervention_time = now
                        silence_handled = True
                        logger.info("✅ Silence third nudge to %s", deep)

                    if not silence_handled:
                        follow = check_silent_followup_candidate(
                            room_id,
                            participant_names,
                            last_silent_invite_at,
                            silent_followup_sent,
                            now,
                            voice=voice_mode,
                        )
                        if (
                            follow
                            and follow in participant_names
                            and (now - last_intervention_time > 45)
                        ):
                            line_fu = get_active_invite_phrase("followup", follow, lang)
                            add_message(room_id, "Moderator", line_fu, "moderator")
                            socketio.emit(
                                "receive_message",
                                chat_socket_payload("Moderator", line_fu),
                                room=room_id,
                            )
                            log_moderator_intervention(
                                room_id, "invite_silent_followup", follow
                            )
                            silent_followup_sent.add(follow)
                            last_silent_invite_at[follow] = now
                            last_intervention_time = now
                            silence_handled = True
                            logger.info("✅ Silence follow-up to %s", follow)

                    if not silence_handled:
                        silence_threshold = (
                            SILENCE_THRESHOLD_SECONDS_VOICE if voice_mode
                            else SILENCE_THRESHOLD_SECONDS
                        )
                        reinvite_gap = (
                            SILENCE_REINVITE_GAP_SECONDS_VOICE if voice_mode
                            else SILENCE_REINVITE_GAP_SECONDS
                        )
                        silent_user = check_silence(room_id, voice=voice_mode)
                        if (
                            not silent_user
                            and len(messages) >= 8
                            and len(participant_names) >= 3
                        ):
                            counts = {p: 0 for p in participant_names}
                            for m in messages:
                                u = m.get("username")
                                if u in counts:
                                    counts[u] += 1
                            if len([u for u in participant_names if counts[u] > 0]) >= 2:
                                lag = min(participant_names, key=lambda u: counts[u])
                                hi, lo = max(counts.values()), counts[lag]
                                if hi - lo >= 3:
                                    last_ts: Optional[float] = None
                                    for m in reversed(messages):
                                        if m.get("username") == lag:
                                            try:
                                                last_ts = datetime.fromisoformat(
                                                    m["created_at"].replace(
                                                        "Z", "+00:00"
                                                    )
                                                ).timestamp()
                                            except Exception:
                                                last_ts = now
                                            break
                                    if last_ts is not None and (
                                        now - last_ts
                                    ) >= silence_threshold:
                                        if (
                                            now - last_silent_invite_at.get(lag, 0)
                                        ) > reinvite_gap:
                                            silent_user = lag
                                            logger.info(
                                                "🤫 Lagging participant: %s (%s vs %s msgs)",
                                                lag,
                                                lo,
                                                hi,
                                            )

                        if (
                            silent_user
                            and silent_user in participant_names
                            and (now - last_intervention_time > 60)
                            and (
                                now - last_silent_invite_at.get(silent_user, 0)
                                > reinvite_gap
                            )
                        ):

                            logger.info("🤫 Silence detected: %s", silent_user)

                            response = generate_active_moderator_response(
                                participants=participant_names,
                                chat_history=[
                                    {
                                        "sender": m["username"],
                                        "message": m["message"],
                                    }
                                    for m in messages
                                ],
                                task_context=f"Desert survival ranking. {room_state_brief(room_id)}",
                                time_elapsed=time_elapsed,
                                last_intervention_time=int(
                                    now - last_intervention_time
                                ),
                                dominance_detected=None,
                                silent_user=silent_user,
                                language=get_room_primary_language(room_id),
                                room_id=room_id,
                                intervention_type="invite_silent"
                            )

                            if not response or len(response) < 10:
                                response = get_active_invite_phrase(
                                    "invite", silent_user, lang
                                )

                            add_message(room_id, "Moderator", response, "moderator")
                            socketio.emit(
                                "receive_message",
                                chat_socket_payload("Moderator", response),
                                room=room_id,
                            )

                            log_moderator_intervention(
                                room_id, "invite_silent", silent_user,
                                reason=f"{silent_user} has been silent for {int(silence_threshold)}s+",
                                research_question="RQ1",
                                expected_effect="Invite quiet member to increase participation"
                            )
                            last_silent_invite_at[silent_user] = now
                            last_intervention_time = now
                            logger.info("✅ Sent invitation to %s", silent_user)

                    last_silence_check = now
                
                # RULE 3: Time-based prompts — single 5- and 1-min messages, ALL 12 items (deduped with research timer)
                if (
                    time_remaining <= 5
                    and time_remaining > 4
                    and now - last_intervention_time > 60
                    and claim_session_time_warning(room_id, "5")
                ):
                    response = get_template_message("time_warning_5m", lang)
                    add_message(room_id, "Moderator", response, "moderator")
                    socketio.emit(
                        "receive_message",
                        chat_socket_payload("Moderator", response),
                        room=room_id,
                    )
                    
                    log_moderator_intervention(
                        room_id, "time_warning", None,
                        reason="Time remaining <= 5 minutes",
                        research_question="RQ4",
                        expected_effect="Prompt final ranking submission near deadline"
                    )
                    last_intervention_time = now
                    logger.info(
                        f"✅ Sent time warning: {time_remaining} minutes remaining"
                    )

                if (
                    time_remaining <= 1
                    and time_remaining > 0
                    and now - last_intervention_time > 30
                    and claim_session_time_warning(room_id, "1")
                ):
                    response = get_template_message("time_warning_1m", lang)
                    add_message(room_id, "Moderator", response, "moderator")
                    socketio.emit(
                        "receive_message",
                        chat_socket_payload("Moderator", response),
                        room=room_id,
                    )
                    log_moderator_intervention(
                        room_id, "time_warning", None,
                        reason="Time remaining <= 1 minute",
                        research_question="RQ4",
                        expected_effect="Enforce clear chat before automated final ranking record"
                    )
                    last_intervention_time = now
                    logger.info("✅ Sent 1-minute warning (active)")
                
                # RULE 4: Answer questions about the task
                if messages and len(messages) > 0:
                    last_msg = messages[-1]
                    if last_msg.get('username') != 'Moderator':
                        lm_id_q = str(last_msg.get("id", ""))
                        msg_content = last_msg.get('message', '').lower()

                        # Check if it's a question (contains ? or question words)
                        is_question = False
                        if '?' in msg_content:
                            is_question = True
                        else:
                            question_words = ['what', 'how', 'why', 'when', 'where', 'which', 'who',
                                             'explain', 'help', 'confused', 'not sure', 'do we', 'should we',
                                             'can you', 'could you', 'would you', 'tell me', 'guide']
                            for word in question_words:
                                if word in msg_content:
                                    is_question = True
                                    break

                        # Also check for question phrases
                        question_phrases = ['what to do', 'what next', 'how to', 'what is', 'what are',
                                           'what should', 'how do', 'can you help', 'need help']
                        for phrase in question_phrases:
                            if phrase in msg_content:
                                is_question = True
                                break

                        # @moderator questions are handled immediately by the inline path
                        # in send_message_handler; exclude them here. _claim_reply_to() is
                        # the ATOMIC dedup — it claims the message id under a lock, so the
                        # inline path and this loop can never both answer the same turn (and
                        # the same question can't re-trigger on a later tick).
                        if (
                            is_question
                            and not _mentions_moderator(msg_content)
                            and (now - last_intervention_time > 30)
                            and _claim_reply_to(room_id, lm_id_q)
                        ):
                            logger.info(f"❓ Question detected from {last_msg.get('username')}: {msg_content[:100]}...")

                            response = generate_active_moderator_response(
                                participants=participant_names,
                                chat_history=[{"sender": m['username'], "message": m['message']} for m in messages],
                                task_context=f"Desert survival ranking. {room_state_brief(room_id)}",
                                time_elapsed=time_elapsed,
                                last_intervention_time=int(now - last_intervention_time),
                                dominance_detected=None,
                                silent_user=None,
                                language=get_room_primary_language(room_id),
                                room_id=room_id,
                                intervention_type="answer_question"
                            )

                            if response and len(response.strip()) > 10:
                                add_message(room_id, "Moderator", response.strip(), "moderator")
                                socketio.emit(
                                    "receive_message",
                                    chat_socket_payload("Moderator", response.strip()),
                                    room=room_id,
                                )
                                log_moderator_intervention(
                                    room_id, "answer_question", last_msg.get('username'),
                                    reason=f"Answered question: {msg_content[:50]}",
                                    research_question="RQ5",
                                    expected_effect="Directly answer user query"
                                )
                                last_intervention_time = now
                                logger.info(f"✅ Answered question from {last_msg.get('username')}: {response[:100]}...")
                            else:
                                fallback = get_template_message("qa_fallback_default", lang)

                                if 'time' in msg_content or 'minute' in msg_content:
                                    fallback = get_template_message("qa_fallback_time", lang, time_remaining=int(time_remaining))
                                elif 'item' in msg_content or 'rank' in msg_content:
                                    fallback = get_template_message("qa_fallback_item", lang)
                                
                                log_moderator_intervention(
                                     room_id, "answer_question", last_msg.get('username'),
                                     reason=f"Answered question fallback: {msg_content[:50]}",
                                     research_question="RQ5",
                                     expected_effect="Directly answer user query with fallback template"
                                 )

                                add_message(room_id, "Moderator", fallback, "moderator")
                                socketio.emit(
                                    "receive_message",
                                    chat_socket_payload("Moderator", fallback),
                                    room=room_id,
                                )
                                pass
                                last_intervention_time = now
                                logger.info(f"✅ Sent fallback answer to {last_msg.get('username')}")

                # RULE 4.25: Brief appreciation for substantive item-focused reasoning (low frequency)
                _app_sub = (
                    "because",
                    "since",
                    "rank",
                    "important",
                    "survival",
                    "mirror",
                    "water",
                    "tarp",
                    "sheet",
                    "compass",
                    "knife",
                    "flashlight",
                    "parachute",
                    "matches",
                    "coat",
                )
                if (
                    not skip_nonessential
                    and messages
                    and messages[-1].get("username") not in ("Moderator", "System", None, "")
                    and now - float(aux.get("last_appreciation_sent") or 0) > 95
                    and now - last_intervention_time > 55
                ):
                    _lm = messages[-1]
                    _lc = (_lm.get("message") or "").lower()
                    if len(_lc) >= 38 and any(s in _lc for s in _app_sub):
                        _resp_ap = generate_active_moderator_response(
                            participants=participant_names,
                            chat_history=[
                                {"sender": m["username"], "message": m["message"]}
                                for m in messages
                            ],
                            task_context=f"Desert survival ranking. {room_state_brief(room_id)}",
                            time_elapsed=time_elapsed,
                            last_intervention_time=int(now - last_intervention_time),
                            dominance_detected=None,
                            silent_user=None,
                            language=get_room_primary_language(room_id),
                            room_id=room_id,
                            intervention_type="appreciate"
                        )
                        if _resp_ap and len(_resp_ap.strip()) > 12:
                            add_message(
                                room_id, "Moderator", _resp_ap.strip(), "moderator"
                            )
                            socketio.emit(
                                "receive_message",
                                chat_socket_payload("Moderator", _resp_ap.strip()),
                                room=room_id,
                            )
                            log_moderator_intervention(
                                room_id,
                                "appreciate",
                                _lm.get("username"),
                                reason=f"Appreciate substantive item logic from {_lm.get('username')}",
                                research_question="RQ1",
                                expected_effect="Encourage contribution and build on ideas"
                            )
                            aux["last_appreciation_sent"] = now
                            last_intervention_time = now
                            logger.info(
                                "✅ Appreciation nudge after message from %s",
                                _lm.get("username"),
                            )

                # RULE 4.5: Occasional expert survival perspective when a specific item is discussed
                if (
                    not skip_nonessential
                    and messages
                    and len(messages) > 0
                ):
                    tip_msg = messages[-1]
                    if tip_msg.get("username") != "Moderator":
                        raw_tip = tip_msg.get("message", "")
                        low_tip = raw_tip.lower()
                        tip_fingerprint = (
                            f"{tip_msg.get('username')}|{tip_msg.get('created_at', '')}|{raw_tip[:160]}"
                        )
                        if room_expert_tip_message_key.get(room_id) != tip_fingerprint:
                            for item_label in canonical_items:
                                il = item_label.lower()
                                if len(il) >= 6 and il in low_tip:
                                    room_expert_tip_message_key[room_id] = tip_fingerprint
                                    opinion = get_expert_ranking_opinion(item_label)
                                    if opinion and (
                                        now - room_last_expert_tip.get(room_id, 0) > 90
                                    ) and (now - last_intervention_time > 50):
                                        ikey = il[:48]
                                        orig = aux["statement_attribution"].get(ikey)
                                        spk = tip_msg.get("username")
                                        prefix = ""
                                        if orig and orig != spk:
                                            prefix = f"As **{orig}** raised that item, "
                                        response = (
                                            prefix
                                            + f"📚 Expert perspective on “{item_label}”: {opinion}\n\n"
                                            "How does that fit with your group's ranking so far?"
                                        )
                                        add_message(
                                            room_id,
                                            "Moderator",
                                            response,
                                            "moderator",
                                        )
                                        socketio.emit(
                                            "receive_message",
                                            chat_socket_payload("Moderator", response),
                                            room=room_id,
                                        )
                                        log_moderator_intervention(
                                            room_id,
                                            "expert_item_hint",
                                            tip_msg.get("username"),
                                        )
                                        room_last_expert_tip[room_id] = now
                                        last_intervention_time = now
                                        logger.info(
                                            f"📚 Expert hint for item: {item_label[:50]}"
                                        )
                                    break
                
                # RULE 5: Periodic progress recap (every 5 min clock OR 3+ newly discussed items)
                discussed = collect_discussed_canonical_items(messages, canonical_items)
                time_since_recap = now - aux["last_progress_summary_time"]
                new_since_recap = len(discussed) - aux["last_summary_discussed_len"]
                if (
                    not skip_nonessential
                    and not moderator_spoke_last  # require NEW student input since we last spoke
                    and (time_since_recap >= 300 or new_since_recap >= 3)
                    and (now - last_intervention_time > 60)
                ):
                    mins = max(1, int(time_since_recap // 60))
                    summary_lines = [
                        "📊 **Progress update** (quick recap):",
                        f"- About **{mins}** min since the last progress check.",
                    ]
                    if discussed:
                        preview = ", ".join(sorted(discussed)[:5])
                        if len(discussed) > 5:
                            preview += "…"
                        summary_lines.append(
                            f"- Items clearly on the table in chat: {preview}"
                        )
                    gap = max(0, n_target - len(discussed))
                    summary_lines.append(
                        f"- Rough gauge: **{gap}** list item(s) not clearly discussed yet."
                    )
                    summary_lines.append(
                        f"- ⏰ About **{int(time_remaining)}** min left in the session."
                    )
                    summary = "\n".join(summary_lines)
                    add_message(room_id, "Moderator", summary, "moderator")
                    socketio.emit(
                        "receive_message",
                        chat_socket_payload("Moderator", summary),
                        room=room_id,
                    )
                    log_moderator_intervention(room_id, "progress_summary", None)
                    last_intervention_time = now
                    aux["last_progress_summary_time"] = now
                    aux["last_summary_discussed_len"] = len(discussed)
                    logger.info("✅ Sent structured progress summary")
                
            except Exception as e:
                logger.error(f"❌ Error in active moderator loop: {e}")
                logger.error(traceback.format_exc())
                time.sleep(5)
    
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()
    active_monitors[room_id] = thread
    logger.info(f"✅ ACTIVE moderator thread started for room {room_id}")
    return thread

# ============================================================
# PASSIVE MODERATOR — ultra-minimal (research condition)
# ============================================================
def _passive_dedupe_key(msg: Dict[str, Any]) -> str:
    """Stable id for deduping @moderator handling when DB id is missing."""
    mid = msg.get("id")
    if mid is not None and str(mid).strip() and str(mid) != "None":
        return str(mid)
    return "|".join(
        [
            str(msg.get("username") or ""),
            str(msg.get("created_at") or ""),
            (msg.get("message") or "")[:120],
        ]
    )


def start_passive_moderator(room_id: str):
    """Ultra-minimal: only @moderator (dynamic LLM) + one deduped 5-minute warning."""
    existing = active_monitors.get(room_id)
    if existing is not None and existing.is_alive():
        logger.warning(
            "🔴 Passive moderator already running for room %s — skipping duplicate start",
            room_id[:8],
        )
        return existing

    def monitor_loop():
        logger.info(f"🔴 PASSIVE moderator (minimal) for room {room_id}")
        # Do not use a single low cap for @moderator + warning — that silenced all pings after a few turns.
        passive_at_mention_replies = 0
        PASSIVE_MAX_AT_MENTIONS = 40
        last_passive_handled_key: Optional[str] = None
        five_min_warning_logged = False
        _wake = _get_wake_event(room_id)

        while True:
            try:
                # Wake immediately on a student message; 3s fallback for time-based checks.
                _wake.wait(timeout=3)
                _wake.clear()

                room = get_room(room_id)
                if not room or room.get("story_finished") or room.get("status") == "completed":
                    logger.info(f"⏹️ Passive moderator stopped for room {room_id}")
                    break

                now = time.time()
                time_elapsed = _research_session_minutes_elapsed(room_id, room, now)
                time_remaining = max(0, 15 - time_elapsed)

                all_parts = get_participants(room_id)
                participant_names = [
                    p["username"]
                    for p in all_parts
                    if p.get("username") not in ("Moderator", "System", None, "")
                ]

                messages = get_chat_history(room_id, limit=40)
                if messages:
                    last_msg = messages[-1]
                    dkey = _passive_dedupe_key(last_msg)
                    if last_msg.get("username") not in ("Moderator", "System"):
                        body = (last_msg.get("message") or "").lower()
                        if (
                            _mentions_moderator(body)
                            and dkey
                            and dkey != last_passive_handled_key
                        ):
                            if passive_at_mention_replies >= PASSIVE_MAX_AT_MENTIONS:
                                logger.warning(
                                    "⚠️ Passive @moderator cap reached for room %s",
                                    room_id,
                                )
                            else:
                                last_passive_handled_key = dkey
                                passive_at_mention_replies += 1

                                chat_for_llm = [
                                    {
                                        "sender": m.get("username") or "?",
                                        "message": m.get("message") or "",
                                    }
                                    for m in messages
                                    if m.get("username") not in ("Moderator", "System", None, "")
                                ]

                                resp = generate_passive_moderator_response(
                                    participants=participant_names,
                                    chat_history=chat_for_llm,
                                    last_user_message=last_msg.get("message") or "",
                                    time_elapsed=time_elapsed,
                                    language=get_room_language(room_id),
                                )
                                if not resp or len(resp.strip()) < 4:
                                    nitems = len(
                                        get_task_items(
                                            get_pinned_or_resolve_task_data(room_id)
                                        )
                                    )
                                    resp = (
                                        f"Rank all **{nitems}** items from most important (**1**) to least "
                                        f"(**{nitems}**). About **{int(time_remaining)}** min left."
                                    )

                                add_message(room_id, "Moderator", resp, "moderator")
                                socketio.emit(
                                    "receive_message",
                                    chat_socket_payload("Moderator", resp),
                                    room=room_id,
                                )
                                log_moderator_intervention(
                                    room_id,
                                    "passive_at_mention",
                                    last_msg.get("username"),
                                )
                                logger.info(
                                    "✅ Passive LLM reply to %s",
                                    last_msg.get("username"),
                                )
                            continue

                if (
                    4 < time_remaining <= 5
                    and not five_min_warning_logged
                    and claim_session_time_warning(room_id, "5")
                ):
                    five_min_warning_logged = True
                    warning = (
                        "⚠️ **5 minutes remaining!** Finalize your **complete ranking of all 12 items** "
                        "(1 = most important, 12 = least)."
                    )
                    add_message(room_id, "Moderator", warning, "system")
                    socketio.emit(
                        "receive_message",
                        chat_socket_payload("Moderator", warning),
                        room=room_id,
                    )
                    log_moderator_intervention(room_id, "time_warning_passive", None)
                    time.sleep(55)

            except Exception as e:
                logger.error(f"❌ Passive moderator error: {e}")
                logger.error(traceback.format_exc())
                time.sleep(5)

    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()
    active_monitors[room_id] = thread
    logger.info(f"✅ PASSIVE moderator thread started for room {room_id}")
    return thread

# ============================================================
# Helper Functions for Research
# ============================================================
def check_dominance(room_id: str) -> Optional[str]:
    """Check if any participant is dominating (>50% of recent messages)"""
    messages = get_chat_history(room_id, limit=20)
    
    if len(messages) < 8:  # Need at least 8 messages to detect dominance
        return None
    
    # Count messages in last 3 minutes
    now = time.time()
    cutoff = now - 180  # 3 minutes
    
    recent_counts = {}
    for msg in messages:
        if msg['username'] == 'Moderator':
            continue
        try:
            msg_time = datetime.fromisoformat(msg['created_at'].replace('Z', '+00:00')).timestamp()
            if msg_time > cutoff:
                recent_counts[msg['username']] = recent_counts.get(msg['username'], 0) + 1
        except:
            continue
    
    if not recent_counts:
        return None
    
    total = sum(recent_counts.values())
    if total < 5:  # Need at least 5 messages in last 3 minutes
        return None
    
    # Find if anyone has >50% AND has at least 3 messages
    for user, count in recent_counts.items():
        share = count / total
        if share > DOMINANCE_THRESHOLD and count >= 3:
            # Check if others have spoken - if only one person has spoken, that's not dominance, that's just low participation
            if len(recent_counts) >= 2:  # At least 2 people have spoken
                return user
    return None

def _room_created_timestamp(room: Optional[Dict]) -> float:
    """Unix time for room creation (fallback: now)."""
    if not room:
        return time.time()
    created_at_val = room.get("created_at")
    if not created_at_val:
        return time.time()
    try:
        if isinstance(created_at_val, str):
            return datetime.fromisoformat(
                created_at_val.replace("Z", "+00:00")
            ).timestamp()
        if isinstance(created_at_val, (int, float)):
            return float(created_at_val)
    except Exception:
        pass
    return time.time()


def check_silence(room_id: str, voice: bool = False) -> Optional[str]:
    """
    Triad rule: invite only if a participant has been quiet for the silence threshold (~1.5 min).
    `voice` selects the voice-room window. Per-user idle = time since their last student message;
    members who never spoke use time since room creation until their first message exists.
    """
    threshold = SILENCE_THRESHOLD_SECONDS_VOICE if voice else SILENCE_THRESHOLD_SECONDS
    participants = get_participants(room_id)
    student_names = [
        p["username"]
        for p in participants
        if p.get("username") and p["username"] not in ("Moderator", "System")
    ]
    if len(student_names) < 3:
        return None

    messages = get_chat_history(room_id, limit=500)
    now = time.time()
    room = get_room(room_id)
    session_start = _session_start_timestamp(room_id, room)

    last_student_msg_ts: Dict[str, float] = {}
    for msg in messages:
        u = msg.get("username")
        if u in ("Moderator", "System", None, ""):
            continue
        try:
            ts = datetime.fromisoformat(
                msg["created_at"].replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            continue
        if u not in last_student_msg_ts or ts > last_student_msg_ts[u]:
            last_student_msg_ts[u] = ts

    best_user: Optional[str] = None
    best_idle = -1.0
    for name in student_names:
        last_ts = last_student_msg_ts.get(name)
        if last_ts is None:
            idle = now - session_start
        else:
            idle = now - last_ts
        if idle < threshold:
            continue
        if idle > best_idle:
            best_idle = idle
            best_user = name

    return best_user


def check_silent_followup_candidate(
    room_id: str,
    participant_names: List[str],
    last_invite_at: Dict[str, float],
    followup_done: Set[str],
    now: float,
    voice: bool = False,
) -> Optional[str]:
    """
    Second nudge: invited once, still idle ≥ the follow-up window (~3 min),
    ≥75s since last silence message to them, follow-up not yet sent.
    `voice` selects the voice-room window.
    """
    followup_window = SILENCE_FOLLOWUP_SECONDS_VOICE if voice else SILENCE_FOLLOWUP_SECONDS
    if len(participant_names) < 3:
        return None
    messages = get_chat_history(room_id, limit=500)
    room = get_room(room_id)
    session_start = _session_start_timestamp(room_id, room)
    last_student_msg_ts: Dict[str, float] = {}
    for msg in messages:
        u = msg.get("username")
        if u in ("Moderator", "System", None, ""):
            continue
        try:
            ts = datetime.fromisoformat(
                msg["created_at"].replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            continue
        if u not in last_student_msg_ts or ts > last_student_msg_ts[u]:
            last_student_msg_ts[u] = ts

    best: Optional[str] = None
    best_idle = -1.0
    for name in participant_names:
        if name not in last_invite_at or name in followup_done:
            continue
        if now - last_invite_at.get(name, 0) < 75:
            continue
        last_ts = last_student_msg_ts.get(name)
        idle = (now - session_start) if last_ts is None else (now - last_ts)
        if idle < float(followup_window):
            continue
        if idle > best_idle:
            best_idle = idle
            best = name
    return best


def check_silent_third_candidate(
    room_id: str,
    participant_names: List[str],
    last_invite_at: Dict[str, float],
    followup_done: Set[str],
    third_done: Set[str],
    now: float,
    voice: bool = False,
) -> Optional[str]:
    """Third nudge: after second follow-up, still idle ≥ the third window. `voice` selects the voice window."""
    third_window = SILENCE_FOLLOWUP_THIRD_SECONDS_VOICE if voice else SILENCE_FOLLOWUP_THIRD_SECONDS
    if len(participant_names) < 3:
        return None
    messages = get_chat_history(room_id, limit=500)
    room = get_room(room_id)
    session_start = _session_start_timestamp(room_id, room)
    last_student_msg_ts: Dict[str, float] = {}
    for msg in messages:
        u = msg.get("username")
        if u in ("Moderator", "System", None, ""):
            continue
        try:
            ts = datetime.fromisoformat(
                msg["created_at"].replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            continue
        if u not in last_student_msg_ts or ts > last_student_msg_ts[u]:
            last_student_msg_ts[u] = ts

    best: Optional[str] = None
    best_idle = -1.0
    for name in participant_names:
        if name not in followup_done or name in third_done:
            continue
        if now - last_invite_at.get(name, 0) < 75:
            continue
        last_ts = last_student_msg_ts.get(name)
        idle = (now - session_start) if last_ts is None else (now - last_ts)
        if idle < float(third_window):
            continue
        if idle > best_idle:
            best_idle = idle
            best = name
    return best


# ============================================================
# Submit Ranking Endpoint
# ============================================================
@socketio.on("submit_ranking")
def handle_submit_ranking(data):
    """Handle final ranking submission from group"""
    room_id = data.get("room_id")
    ranking = data.get("ranking")  # List of items in ranked order
    
    logger.info(f"📊 Final ranking submitted for room {room_id}")
    
    try:
        # Save to database (schema-drift tolerant — never silently loses the ranking)
        _persist_room_ranking(room_id, ranking)

        td = get_room_task_data(room_id) or get_data()
        comparison = compare_with_expert_ranking(ranking, td)
        logger.info(f"📈 Ranking accuracy: {comparison['accuracy_percentage']:.1f}%")
        # RQ1–RQ5 room-level metrics are persisted in handle_end_session (single canonical row + participant_metrics)
        
        # Send confirmation
        socketio.emit("ranking_submitted", {
            "success": True,
            "message": "Ranking submitted successfully!"
        }, room=room_id)
        
    except Exception as e:
        logger.error(f"❌ Error saving ranking: {e}")
        socketio.emit("ranking_submitted", {
            "success": False,
            "message": "Failed to submit ranking"
        }, room=room_id)

# ============================================================
# Auto Room Assignment Endpoint
# ============================================================
@app.route("/join/<mode>")
def auto_join_room(mode: str):
    """Auto-assign user to available room or create new one"""
    logger.info(f"🔗 /join/{mode} - Auto-join request received")

    if mode not in ['active', 'passive']:
        logger.warning(f"⚠️ Invalid mode: {mode}")
        return jsonify({"error": "Invalid mode. Use 'active' or 'passive'"}), 400

    # Refuse to start a session on an un-migrated DB (would lose data silently).
    if not PREFLIGHT.get("ok") and not ALLOW_UNMIGRATED:
        logger.error("🚫 /join refused — DB not migrated: %s", PREFLIGHT.get("missing"))
        return jsonify({
            "error": "Database not migrated — session refused to protect data integrity.",
            "missing": PREFLIGHT.get("missing", []),
        }), 503

    try:
        # DEBUG: List all available rooms
        try:
            rooms_response = supabase.table("rooms").select("*").eq("mode", mode).in_("status", ["waiting", "active"]).execute()
            rooms = rooms_response.data or []
            logger.info(f"📋 Found {len(rooms)} rooms in '{mode}' mode:")
            for room in rooms:
                logger.info(f"   Room {room['id'][:8]}...: {room.get('participant_count', 0)}/3 participants, status={room['status']}")
        except Exception as e:
            logger.error(f"❌ Error listing rooms: {e}")

        task_data = get_data()
        story_id = task_data.get("task_id") or "desert_survival_plane_crash"
        logger.info(f"📚 Using task: {story_id}")

        # Get or create room
        room = get_or_create_room(mode=mode, story_id=story_id)
        room_id = room['id']
        pin_task_data_for_room(room_id, resolve_task_data_from_room(room))

        logger.info(f"✅ Room assigned: {room_id} (mode={mode}, participants={room.get('participant_count', 0)}/3)")

        # Generate a proper username
        user_name = f"Student_{random.randint(1000, 9999)}"
        
        # Return username in response
        redirect_url = f"{FRONTEND_URL}/chat/{room_id}?userName={user_name}"

        # Auto-start task when room is ready
        socketio.start_background_task(lambda: start_task_for_room(room_id))

        return jsonify({
            "room_id": room_id,
            "mode": room['mode'],
            "user_name": user_name,
            "redirect_url": redirect_url
        })

    except Exception as e:
        logger.error(f"❌ Error in auto_join_room: {e}", exc_info=True)
        return jsonify({"error": "Failed to assign room"}), 500

# ============================================================
# Get Room Info Endpoint
# ============================================================
@app.route("/api/room/<room_id>")
def get_room_info(room_id: str):
    """Get room information"""
    logger.info(f"ℹ️ Room info requested: {room_id}")

    try:
        room = get_room(room_id)
        if not room:
            logger.warning(f"⚠️ Room not found: {room_id}")
            return jsonify({"error": "Room not found"}), 404

        participants = get_participants(room_id)
        logger.info(f"✅ Room {room_id}: {len(participants)} participants")

        return jsonify({
            "room": room,
            "participants": participants,
            "participant_count": len(participants)
        })

    except Exception as e:
        logger.error(f"❌ Error getting room info: {e}", exc_info=True)
        return jsonify({"error": "Failed to get room info"}), 500


@app.route("/api/desert-items")
def get_desert_items_api():
    """Item list for UI; use ?room_id= for the exact strings pinned to that session."""
    room_id = (request.args.get("room_id") or "").strip()
    if room_id:
        bundle = get_canonical_items_for_room(room_id)
        items = bundle["items"]
        return jsonify(
            {
                "items": items,
                "count": len(items),
                "task_id": bundle.get("task_id"),
                "task_name": bundle.get("task_name"),
            }
        )
    items = get_task_items()
    return jsonify({"items": items, "count": len(items)})


# ============================================================
# Socket.IO Events — room lifecycle & messaging
# (connect/disconnect registered near socketio initialization)
# ============================================================
@socketio.on("create_room")
def create_room_handler(data):
    """Handle room creation"""
    user = data.get("user_name", "Student")
    mode = data.get("moderatorMode", "active")

    logger.info(f"🏗️ Creating room: user={user}, mode={mode}, sid={request.sid}")

    try:
        story_data = get_data()
        story_id = story_data.get("task_id") or "desert_survival_plane_crash"

        from supabase_client import create_room
        room = create_room(mode=mode, story_id=story_id)
        room_id = room['id']
        pin_task_data_for_room(room_id, story_data)

        logger.info(f"✅ Room created: {room_id}")

        participant = add_participant(
            room_id=room_id,
            username=user,
            socket_id=request.sid
        )
        logger.info(f"✅ Participant added: {user} → room {room_id}")

        join_room(room_id)

        # Tell the client immediately — do not block on welcome message DB write + broadcast.
        emit("joined_room", {"room_id": room_id}, to=request.sid)
        emit("room_created", {"room_id": room_id, "mode": mode}, to=request.sid)

        def _welcome_and_start_task():
            try:
                add_message(
                    room_id=room_id,
                    username="Moderator",
                    message=WELCOME_MESSAGE,
                    message_type="system",
                )
                socketio.emit(
                    "receive_message",
                    chat_socket_payload("Moderator", WELCOME_MESSAGE),
                    room=room_id,
                )
            except Exception as wel_exc:
                logger.error(f"❌ Welcome message failed for room {room_id}: {wel_exc}")
            try:
                start_task_for_room(room_id)
            except Exception as task_exc:
                logger.error(f"❌ start_task_for_room failed for {room_id}: {task_exc}")

        socketio.start_background_task(_welcome_and_start_task)

    except Exception as e:
        logger.error(f"❌ Error creating room: {e}", exc_info=True)
        emit("error", {"message": "Failed to create room"})

@socketio.on("join_room")
def join_room_handler(data):
    """Handle user joining existing room"""
    room_id = data.get("room_id")
    user_name = data.get("user_name")

    logger.info(f"🚪 Join room request: room={room_id}, user={user_name}, sid={request.sid}")

    try:
        room = get_room(room_id)
        if not room:
            logger.warning(f"⚠️ Room not found: {room_id}")
            emit("error", {"message": "Room not found"})
            return

        pin_task_data_for_room(room_id, resolve_task_data_from_room(room))

        # Language pin from the join-screen selector — AUTHORITATIVE for the moderator
        # and TTS from the very first turn (so "Hello" still gets a Roman-Urdu reply if
        # the group chose Roman Urdu). Falls back to any previously stored room language.
        join_lang = (data.get("language") or "").strip().lower()
        if join_lang not in ("en", "roman_urdu"):
            join_lang = room.get("primary_language") if room.get("primary_language") in ("en", "roman_urdu") else None
        if join_lang:
            set_room_language(room_id, join_lang)
            if room.get("primary_language") != join_lang:
                try:
                    supabase.table("rooms").update({"primary_language": join_lang}).eq("id", room_id).execute()
                except Exception as e:
                    logger.debug(f"primary_language persist skipped for {room_id}: {e}")
            logger.info(f"🗣️ Room {room_id} language pinned: {join_lang}")

        # Check if participant already exists in this room
        existing_participant = get_participant_by_username(room_id, user_name)
        if existing_participant:
            logger.info(f"👤 Participant {user_name} already in room {room_id}, reconnecting")
            # Update their socket ID
            supabase.table('participants').update({
                'socket_id': request.sid,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }).eq('id', existing_participant['id']).execute()
        else:
            # Add new participant
            participant = add_participant(
                room_id=room_id,
                username=user_name,
                socket_id=request.sid,
                display_name=user_name
            )
            logger.info(f"✅ New participant added: {user_name} → room {room_id}")

        join_room(room_id)

        # Dispatch the task-start check NOW (the participant is already persisted), so it
        # runs CONCURRENTLY with the chat-history fetch + emits below instead of after them.
        # For the 3rd join this shaves the get_chat_history + get_participants reads (~100-
        # 300ms) off the time-to-intro. It's a no-op for joins 1-2 and reconnects (gated by
        # the 3-participant check + in-memory start guard inside start_task_for_room).
        socketio.start_background_task(lambda: start_task_for_room(room_id))

        # Get chat history (private warnings only go to the targeted user)
        history = get_chat_history(room_id)
        chat_history = []
        for msg in history:
            mtype = msg.get("message_type") or "chat"
            meta = msg.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            elif meta is None:
                meta = {}
            if (
                msg.get("username") == "Moderator"
                and mtype == "moderator"
                and meta.get("trigger") == "inappropriate_language"
                and meta.get("target_user")
                and meta.get("target_user") != user_name
            ):
                continue
            entry = {
                "id": str(msg["id"]) if msg.get("id") is not None else None,
                "sender": msg["username"],
                "message": msg["message"],
                "timestamp": msg["created_at"],
                "message_type": mtype,
            }
            if meta.get("flagged"):
                entry["flagged"] = True
            if meta.get("content_format"):
                entry["content_format"] = meta["content_format"]
            if meta.get("flag_reason"):
                entry["flag_reason"] = meta["flag_reason"]
            if meta.get("input_mode"):
                entry["input_mode"] = meta["input_mode"]
            chat_history.append(entry)

        # Get current participants (deduplicated)
        participants = get_participants(room_id)
        participant_names = list(set([p['username'] for p in participants if p.get('username')]))
        
        # Always include the current user
        if user_name not in participant_names:
            participant_names.append(user_name)

        logger.info(f"📜 Sending {len(chat_history)} messages to {user_name}")
        logger.info(f"👥 Current participants: {participant_names}")

        emit("joined_room", {"room_id": room_id}, to=request.sid)
        emit("chat_history", {
            "chat_history": chat_history,
            "participants": participant_names
        }, to=request.sid)
        
        emit("participants_update", {
            "participants": participant_names,
            "new_user": user_name
        }, room=room_id)
        # (task-start was already dispatched above, right after the participant was persisted)

    except Exception as e:
        logger.error(f"❌ Error joining room: {e}", exc_info=True)
        emit("error", {"message": "Failed to join room"})

@socketio.on("send_message")
def send_message_handler(data):
    """Handle user message (with real-time inappropriate-language warnings)."""
    room_id = data.get("room_id")
    sender = data.get("sender")
    msg = (data.get("message") or "").strip()

    if not msg:
        return

    word_count = len(msg.split())
    logger.info(f"💬 Message from {sender} in room {room_id}: {msg[:50]}... (words: {word_count})")

    # Optional client-supplied metadata (e.g. voice input). Whitelist keys; text sends omit this.
    extra_meta: Dict[str, Any] = {}
    client_meta = data.get("metadata")
    if isinstance(client_meta, dict):
        im = client_meta.get("input_mode")
        if im in ("voice", "text"):
            extra_meta["input_mode"] = im
        sm = client_meta.get("stt_model")
        if isinstance(sm, str) and sm.strip():
            extra_meta["stt_model"] = sm.strip()[:64]

    # Voice-only fields (kept out of the message row; they live in voice_recordings).
    voice_audio_token = None
    voice_duration_ms = None
    voice_raw_transcript = None
    voice_mime = "audio/webm"
    if isinstance(client_meta, dict) and extra_meta.get("input_mode") == "voice":
        at = client_meta.get("audio_token")
        if isinstance(at, str) and at.strip():
            voice_audio_token = at.strip()[:80]
        d = client_meta.get("duration_ms")
        if isinstance(d, (int, float)) and d >= 0:
            voice_duration_ms = int(d)
        rt = client_meta.get("transcript_text")
        if isinstance(rt, str) and rt.strip():
            voice_raw_transcript = rt
        mt = client_meta.get("mime_type")
        if isinstance(mt, str) and mt.strip():
            voice_mime = mt.strip()[:100]

    # Feed the rolling room-language state from this STUDENT message. Voice messages
    # carry the LLM-classified language (+confidence) from /stt; text messages use the
    # cheap heuristic. The moderator + TTS read room state, not single messages — so a
    # lone noisy message can't flip the language.
    if sender not in ("Moderator", "System", None, ""):
        msg_lang = None
        msg_conf = 1.0
        if isinstance(client_meta, dict):
            ml = client_meta.get("language")
            if isinstance(ml, str) and ml.strip():
                msg_lang = ml.strip()
                mc = client_meta.get("confidence")
                if isinstance(mc, (int, float)):
                    msg_conf = float(mc)
        if not msg_lang:
            msg_lang = detect_language(msg)
        update_room_language(room_id, msg_lang, msg_conf)
        # Keep room_state language fresh after every message (cheap, no query). Full
        # derived state (dominant/silent/consensus/stage) refreshes on the monitor tick.
        try:
            rl = get_room_language(room_id)
            if rl:
                get_room_state(room_id)["primary_language"] = rl
        except Exception:
            pass

    def _finalize_voice(message_id):
        """At SEND time: move staged audio → {room_id}/{message_id}.webm + link a row.
        No-op for text messages (no audio_token), so they create no voice_recordings rows."""
        if not voice_audio_token or not message_id:
            return
        try:
            finalize_voice_recording(
                audio_token=voice_audio_token,
                room_id=room_id,
                message_id=str(message_id),
                transcript_text=voice_raw_transcript or msg,
                final_text=msg,
                duration_ms=voice_duration_ms,
                mime_type=voice_mime,
                stt_model=extra_meta.get("stt_model"),
            )
        except Exception as e:
            logger.error(f"❌ finalize_voice failed for {message_id}: {e}")

    try:
        room = get_room(room_id)
        if not room or room.get("story_finished"):
            logger.warning(f"⚠️ Cannot send message - room {room_id} finished or not found")
            return

        # Resolve any pending/active moderator intervention for this user or room
        try:
            from room_state import get_room_state
            st = get_room_state(room_id)
            pending = st.get("pending_interventions", [])
            now_time = time.time()
            
            # Clean up expired pending interventions (>180s)
            st["pending_interventions"] = [p for p in pending if now_time - p["timestamp"] <= 180]
            
            for p in list(st["pending_interventions"]):
                if p["target"] == sender or p["target"] is None:
                    latency = round(now_time - p["timestamp"], 2)
                    try:
                        supabase.table("moderator_interventions").update({
                            "participant_response": msg,
                            "latency_seconds": latency,
                            "success": True
                        }).eq("id", p["id"]).execute()
                    except Exception as ex:
                        logger.error(f"Failed to update success telemetry: {ex}")
                    st["pending_interventions"].remove(p)
                    break
        except Exception as ex:
            logger.error(f"Error resolving pending intervention: {ex}")

        # Resolve language and participants for personal target checks
        lang = get_room_primary_language(room_id)
        all_parts = get_participants(room_id)
        part_names = [p['username'] for p in all_parts if p['username'] != 'Moderator']

        is_inappropriate, bad_words = check_inappropriate_language(msg)
        if is_inappropriate:
            severity = get_language_severity(bad_words, message=msg, participants=part_names)
            logger.warning(
                f"⚠️ Inappropriate language from {sender}: {bad_words} (severity: {severity})"
            )
            
            # Reordered DB write to happen FIRST, preserving database chronology
            saved_row = add_message(
                room_id=room_id,
                username=sender,
                message=msg,
                message_type="chat_flagged",
                metadata={
                    "word_count": word_count,
                    "flagged": True,
                    "bad_words": bad_words,
                    "severity": severity,
                    "flag_reason": "inappropriate language",
                    **extra_meta,
                },
            )

            if severity == "HIGH":
                high_severity_response = get_template_message("inappropriate_warning_socket", lang)
                add_message(room_id, "Moderator", high_severity_response, "moderator")
                socketio.emit(
                    "receive_message",
                    chat_socket_payload("Moderator", high_severity_response),
                    room=room_id,
                )
                log_moderator_intervention(room_id, "high_severity_warning", sender, reason=f"Inappropriate language from {sender}: {bad_words}")

            if severity == "HIGH":
                warning_msg = (
                    "Your message contained inappropriate language. "
                    "Please keep our discussion professional, respectful, and focused on the "
                    "desert survival task. Continued violations may affect your participation."
                )
            elif severity == "MEDIUM":
                warning_msg = (
                    "Please use more professional language. Let's focus on the desert survival task."
                )
            else:
                warning_msg = (
                    "Please keep our discussion professional and focused on the task."
                )
            sample = bad_words[0] if bad_words else ""
            if sample:
                warning_msg += f" (detected: {sample})"

            warning_payload = {
                "message": warning_msg,
                "type": "language_warning",
                "severity": severity,
                "detected_words": bad_words,
            }
            participant_record = get_participant_by_username(room_id, sender)
            if participant_record and participant_record.get("socket_id"):
                sid = participant_record["socket_id"]
                socketio.emit("language_warning", warning_payload, room=sid)
                socketio.emit(
                    "warning_message",
                    {"message": warning_msg, "type": "language_warning"},
                    room=sid,
                )
                logger.info(f"📨 Sent language warning to {sender} (severity={severity})")

            log_moderator_intervention(room_id, "language_warning", sender, reason=f"Private warning to {sender} for {bad_words}")

            emit(
                "receive_message",
                chat_socket_payload(
                    sender,
                    msg,
                    id=str(saved_row.get("id", f"{room_id}_{sender}_{int(time.time() * 1000)}")),
                    flagged=True,
                    flag_reason="inappropriate language",
                    input_mode=extra_meta.get("input_mode"),
                ),
                room=room_id,
            )
            logger.info(f"✅ Flagged message from {sender} broadcast (severity={severity})")

            _finalize_voice(saved_row.get("id"))
            return

        saved_chat = add_message(
            room_id=room_id,
            username=sender,
            message=msg,
            message_type="chat",
            metadata={"word_count": word_count, **extra_meta},
        )

        _finalize_voice(saved_chat.get("id"))

        # Ground-truth event log (8.4), stamped with the immutable condition (8.2).
        log_event(room_id, "message", {
            "message_id": str(saved_chat.get("id")),
            "sender": sender,
            "input_mode": extra_meta.get("input_mode", "text"),
            "language": (client_meta or {}).get("language") if isinstance(client_meta, dict) else None,
            "word_count": word_count,
        }, condition=experiment_condition(room))

        emit(
            "receive_message",
            chat_socket_payload(
                sender,
                msg,
                id=str(saved_chat.get("id", f"{room_id}_{sender}_{int(time.time() * 1000)}")),
                input_mode=extra_meta.get("input_mode"),
            ),
            room=room_id,
        )

        # @mention → reply synchronously and immediately. Claim the turn FIRST (atomic)
        # so the monitor loop — which may be woken below — can never also answer it.
        if (
            room.get("mode") == "active"
            and _mentions_moderator(msg)
            and _claim_reply_to(room_id, saved_chat.get("id"))
        ):
            try:
                te = _research_session_minutes_elapsed(room_id, room)
                participants = get_participants(room_id)
                participant_names = [
                    p["username"]
                    for p in participants
                    if p.get("username") not in ("Moderator", "System", None, "")
                ]
                hist_msgs = get_chat_history(room_id, limit=45)
                chat_history = [
                    {"sender": m["username"], "message": m.get("message", "")}
                    for m in hist_msgs
                ]
                response = generate_active_moderator_response(
                    participants=participant_names,
                    chat_history=chat_history,
                    task_context=f"Desert survival ranking. {room_state_brief(room_id)}",
                    time_elapsed=te,
                    last_intervention_time=0,
                    dominance_detected=None,
                    silent_user=None,
                    language=get_room_primary_language(room_id),
                    room_id=room_id,
                    intervention_type="answer_question"
                )
                rsp = (response or "").strip()
                if len(rsp) > 8:
                    add_message(room_id, "Moderator", rsp, "moderator")
                    socketio.emit(
                        "receive_message",
                        chat_socket_payload("Moderator", rsp),
                        room=room_id,
                    )
                    log_moderator_intervention(
                        room_id, "answer_question", sender,
                        reason=f"Synchronous reply to @moderator mention from {sender}",
                        research_question="RQ5",
                        expected_effect="Respond to user query immediately"
                    )
            except Exception as atmod_ex:
                logger.error("Active @moderator inline reply failed: %s", atmod_ex)

        try:
            td = get_pinned_or_resolve_task_data(room_id)
            items = get_task_items(td)
            clar_item = clarify_alias_against_list(msg, items)
            if clar_item:
                nowc = time.time()
                if nowc - last_item_clarification_at.get(room_id, 0) > 90:
                    last_item_clarification_at[room_id] = nowc
                    clar_msg = get_template_message("item_clarification", lang, canon=clar_item)
                    add_message(room_id, "Moderator", clar_msg, "moderator")
                    socketio.emit(
                        "receive_message",
                        chat_socket_payload("Moderator", clar_msg),
                        room=room_id,
                    )
                    log_moderator_intervention(
                        room_id, "item_clarification", sender,
                        reason=f"Student used alias for item: {clar_item}",
                        research_question="RQ4",
                        expected_effect="Clarify official wording of survival item"
                    )
        except Exception as clar_ex:
            logger.debug(f"Item clarification skipped: {clar_ex}")

        # Wake the moderator loop to evaluate this turn NOW instead of waiting out its poll
        # interval. Done LAST — after any synchronous @mention/clarification reply has been
        # emitted — so the loop observes the moderator as the last speaker and never stacks
        # a second response on top of the one this handler just produced.
        nudge_moderator(room_id)

        logger.info(f"✅ Message sent to room {room_id}")

    except Exception as e:
        logger.error(f"❌ Error sending message: {e}", exc_info=True)

# ============================================================
# End Session Handler
# ============================================================
@socketio.on("end_session")
def handle_end_session(data):
    """End session, calculate research metrics, and send personalized feedback"""
    room_id = data.get("room_id")
    sender = data.get("sender", "user")
    
    logger.info(f"🏁 Ending session for room {room_id} initiated by {sender}")
    
    try:
        # ===== 1. GET ROOM INFO =====
        room = get_room(room_id)
        if not room:
            emit("error", {"message": "Room not found"})
            return

        # Freeze the research record FIRST (snapshot room_state + metrics + summary +
        # tidy rows + 'session' event), THEN free the in-memory state. Best-effort.
        try:
            _fin = finalize_session(room_id, session_id=room_sessions.get(room_id))
            logger.info(f"🧊 Session finalized for {room_id}: {_fin}")
        except Exception as _fe:
            logger.error(f"finalize_session error for {room_id}: {_fe}")
        try:
            reset_room_state(room_id)
        except Exception:
            pass

        # Get story info
        story_data = get_room_task_data(room_id)
        progress_percent = 100  # For desert survival, always 100% at end
        task_context = ""
        if story_data:
            task_context = (story_data.get("description") or "").strip()
        if not task_context:
            task_context = (
                "Desert survival task: your group discusses and ranks 12 items from "
                "most to least important for survival, then submits one consensus ranking."
            )
        
        # ===== 2. GET ALL DATA =====
        participants = get_participants(room_id)
        full_chat_history = get_chat_history(room_id)
        
        _non_participant = {"Moderator", "System"}
        participant_messages = [
            m for m in full_chat_history if m.get("username") not in _non_participant
        ]
        
        # ===== 3. CALCULATE RESEARCH METRICS =====
        # Include every enrolled student (0 messages if silent) for RQ1/RQ3 inclusion metrics.
        student_usernames = [
            p.get("username")
            for p in participants
            if p.get("username") and p.get("username") not in _non_participant
        ]
        message_counts = {u: 0 for u in student_usernames}
        word_counts = {u: 0 for u in student_usernames}
        for msg in participant_messages:
            username = msg.get("username")
            if username not in message_counts:
                message_counts[username] = 0
                word_counts[username] = 0
            message_counts[username] = message_counts.get(username, 0) + 1
            wc = len(msg.get("message", "").split())
            word_counts[username] = word_counts.get(username, 0) + wc
        
        total_messages = sum(message_counts.values())
        total_words = sum(word_counts.values())
        
        speaking_shares = {}
        if total_messages > 0:
            for user, count in message_counts.items():
                speaking_shares[user] = count / total_messages
        else:
            for user in message_counts:
                speaking_shares[user] = 0.0
        
        # Gini over speaking shares (including zeros for silent members)
        gini_coefficient = 0
        share_list = [speaking_shares[u] for u in sorted(speaking_shares.keys())]
        if len(share_list) >= 2:
            sorted_shares = sorted(share_list)
            n = len(sorted_shares)
            gini = 0.0
            for i, share in enumerate(sorted_shares):
                gini += (2 * i - n + 1) * share
            if sum(sorted_shares) > 0:
                gini_coefficient = gini / (n * sum(sorted_shares))
            gini_coefficient = max(0, min(gini_coefficient, 1))
        
        participation_entropy = calculate_entropy(share_list) if share_list else 0.0
        
        max_share = max(speaking_shares.values()) if speaking_shares else 0
        min_share = min(speaking_shares.values()) if speaking_shares else 0
        dominance_gap = max_share - min_share
        
        conflict_report = detect_conflict_episodes(room_id, full_chat_history)
        repair_times = [
            float(r["time_to_repair"])
            for r in conflict_report.get("repairs", [])
            if r.get("time_to_repair") is not None
        ]
        mean_time_to_repair = (
            sum(repair_times) / len(repair_times) if repair_times else None
        )
        
        # Calculate time to consensus (if ranking was submitted)
        time_to_consensus = None
        if room.get('ranking_submitted_at') and room.get('created_at'):
            try:
                start_time = datetime.fromisoformat(room['created_at'].replace('Z', '+00:00'))
                end_time = datetime.fromisoformat(room['ranking_submitted_at'].replace('Z', '+00:00'))
                time_to_consensus = int((end_time - start_time).total_seconds())
            except:
                time_to_consensus = None
        
        # ===== 4. SAVE RESEARCH METRICS TO DATABASE =====
        try:
            # Save room-level metrics
            metrics_data = {
                "room_id": room_id,
                "condition": room.get("mode"),
                "gini_coefficient": gini_coefficient,
                "participation_entropy": participation_entropy,
                "max_share": max_share,
                "min_share": min_share,
                "dominance_gap": dominance_gap,
                "total_messages": total_messages,
                "total_words": total_words,
                "conflict_count": conflict_report.get("conflict_count", 0),
                "repair_count": conflict_report.get("repair_count", 0),
                "repair_rate": conflict_report.get("repair_rate", 0.0),
                "ranking_submitted": bool(room.get("final_ranking")),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if mean_time_to_repair is not None:
                metrics_data["mean_time_to_repair_seconds"] = mean_time_to_repair
            
            # Add ranking accuracy if available
            if room.get('final_ranking'):
                from data_retriever import compare_with_expert_ranking

                ranking = json.loads(room.get('final_ranking'))
                td = get_room_task_data(room_id) or get_data()
                comparison = compare_with_expert_ranking(ranking, td)
                metrics_data["ranking_accuracy"] = comparison['accuracy_percentage']
            
            # Add time to consensus if available
            if time_to_consensus:
                metrics_data["time_to_consensus"] = time_to_consensus
            
            supabase.table("research_metrics").insert(metrics_data).execute()
            logger.info(f"📊 Saved research metrics for room {room_id}")
            
            metric_users = sorted(message_counts.keys())
            for user in metric_users:
                participant_data = {
                    "room_id": room_id,
                    "username": user,
                    "message_count": message_counts.get(user, 0),
                    "word_count": word_counts.get(user, 0),
                    "share_of_talk": speaking_shares.get(user, 0),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                supabase.table("participant_metrics").insert(participant_data).execute()

            if not metric_users:
                logger.info(
                    f"ℹ️ No enrolled participants in room {room_id} — skipping participant_metrics rows"
                )
            elif total_messages == 0:
                logger.info(
                    f"ℹ️ Room {room_id}: saved participant_metrics for {len(metric_users)} users "
                    f"(0 chat messages; shares and Gini reflect silence)"
                )
            else:
                logger.info(f"👥 Saved participant metrics for {len(metric_users)} users")

            try:
                analyze_conflict_episodes(room_id)
            except Exception as ex:
                logger.debug(f"Optional conflict_episodes persistence skipped: {ex}")

            try:
                inv_r = (
                    supabase.table("moderator_interventions")
                    .select("*")
                    .eq("room_id", room_id)
                    .execute()
                )
                rq5_window = (
                    INTERVENTION_FOLLOWUP_WINDOW_SECONDS_VOICE
                    if _room_is_voice_mode(full_chat_history)
                    else INTERVENTION_FOLLOWUP_WINDOW_SECONDS
                )
                rq5 = intervention_followup_seconds(
                    inv_r.data or [], full_chat_history, window_sec=rq5_window
                )
                logger.info("RQ5 intervention→student follow-up: %s", rq5)
            except Exception as rq5e:
                logger.debug("RQ5 latency summary skipped: %s", rq5e)
            
        except Exception as e:
            logger.error(f"❌ Failed to save research metrics: {e}")
        
        # ===== 5. GENERATE PERSONALIZED FEEDBACK =====
        room_lang = get_room_primary_language(room_id)
        chat_history_list = [
            {"sender": msg['username'], "message": msg['message']}
            for msg in full_chat_history
        ]

        def _row_meta(row: dict) -> dict:
            meta = row.get("metadata")
            if isinstance(meta, str):
                try:
                    return json.loads(meta) or {}
                except Exception:
                    return {}
            return meta or {}

        all_participants_data: List[dict] = []
        for participant in participants:
            un = participant.get("username")
            if un in ("Moderator", "System"):
                continue
            flagged_n = sum(
                1
                for m in participant_messages
                if m.get("username") == un and _row_meta(m).get("flagged")
            )
            all_participants_data.append(
                {
                    "name": participant.get("display_name", un),
                    "username": un,
                    "message_count": message_counts.get(un, 0),
                    "word_count": word_counts.get(un, 0),
                    "share_of_talk": speaking_shares.get(un, 0) * 100,
                    "toxic_count": flagged_n,
                }
            )

        all_participants_data.sort(
            key=lambda x: (x.get("message_count", 0), x.get("word_count", 0)),
            reverse=True,
        )

        feedbacks = {}

        for participant in participants:
            username = participant.get('username')
            display_name = participant.get('display_name', username)
            
            # Skip moderator
            if username == 'Moderator' or username == 'System':
                continue
            
            # Get this participant's metrics
            message_count = message_counts.get(username, 0)
            word_count = word_counts.get(username, 0)
            share_of_talk = speaking_shares.get(username, 0)

            inappropriate_count = 0
            for msg in participant_messages:
                if msg.get('username') == username:
                    is_bad, _ = check_inappropriate_language(
                        msg.get("message", ""), allow_casual_slang=True
                    )
                    if is_bad:
                        inappropriate_count += 1

            if message_count == 0:
                behavior_type = "passive"
            elif inappropriate_count > 0:
                behavior_type = "needs_improvement"
            elif message_count >= 5:
                behavior_type = "active"
            else:
                behavior_type = "moderate"

            logger.info(
                f"📝 Generating dynamic feedback for {username} "
                f"(type: {behavior_type}, inappropriate msgs: {inappropriate_count})"
            )

            feedback = None
            for attempt in range(3):
                try:
                    feedback = generate_personalized_feedback(
                        student_name=display_name,
                        message_count=message_count,
                        word_count=word_count,
                        share_of_talk=share_of_talk,
                        response_times=[],
                        story_progress=progress_percent,
                        hint_responses=0,
                        behavior_type=behavior_type,
                        toxic_count=inappropriate_count,
                        off_topic_count=0,
                        chat_history=chat_history_list,
                        story_context=task_context,
                        chat_sender_name=username,
                        all_participants_data=all_participants_data,
                        language=room_lang,
                    )
                    if feedback and len(feedback.strip()) > 100:
                        logger.info(f"✅ Quality feedback for {username} (attempt {attempt + 1})")
                        break
                    logger.warning(f"⚠️ Feedback too short for {username}, retrying...")
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"❌ Feedback attempt {attempt + 1} for {username}: {e}")
                    if attempt == 2:
                        feedback = get_fallback_feedback(
                            display_name, message_count, inappropriate_count, language=room_lang
                        )
                    else:
                        time.sleep(1)

            if not feedback or len((feedback or "").strip()) <= 100:
                feedback = get_fallback_feedback(
                    display_name, message_count, inappropriate_count, language=room_lang
                )

            # Apply vocabulary filter if the language is Roman Urdu
            if room_lang in ("roman_urdu", "urdu", "mixed") and feedback:
                feedback = enforce_pakistani_roman_urdu(feedback)
                
            # Pre-warm the TTS cache with the appropriate voice selection
            try:
                from tts.tts_manager import tts_manager
                tts_manager.synthesize(feedback, language=room_lang)
            except Exception as tts_err:
                logger.debug(f"Feedback pre-warm TTS skipped: {tts_err}")

            feedbacks[username] = feedback
            
            # METHOD 1: Direct socket delivery (most reliable)
            delivery_success = False
            try:
                participant_record = get_participant_by_username(room_id, username)
                if participant_record and participant_record.get('socket_id'):
                    socketio.emit(
                        "session_ended",
                        {
                            "feedback": feedback, 
                            "room_id": room_id,
                            "username": username,
                            "stats": {
                                "message_count": message_count,
                                "word_count": word_count,
                                "share_of_talk": round(share_of_talk * 100, 1)
                            }
                        },
                        room=participant_record['socket_id']
                    )
                    logger.info(f"📨 Sent direct feedback to {username}")
                    delivery_success = True
            except Exception as e:
                logger.warning(f"⚠️ Failed to send direct feedback to {username}: {e}")
            
            # METHOD 2: Broadcast to room as backup (if direct failed)
            if not delivery_success:
                try:
                    socketio.emit(
                        "session_ended",
                        {
                            "feedback": feedback, 
                            "room_id": room_id,
                            "username": username,
                            "stats": {
                                "message_count": message_count,
                                "word_count": word_count,
                                "share_of_talk": round(share_of_talk * 100, 1)
                            },
                            "broadcast": True
                        },
                        room=room_id
                    )
                    logger.info(f"📢 Broadcast feedback for {username} as fallback")
                except Exception as e:
                    logger.error(f"❌ Failed to broadcast feedback for {username}: {e}")
        
        logger.info(f"📊 Feedback generated for {len(feedbacks)} participants")
        
        # ===== 6. END SESSION IN DATABASE =====
        try:
            end_session(room_id, ended_by=sender, end_reason='user_ended')
            logger.info(f"✅ Session ended in database for room {room_id}")
        except Exception as e:
            logger.error(f"❌ Failed to end session in database: {e}")
        
        # ===== 7. UPDATE ROOM STATUS =====
        try:
            update_room_status(room_id, 'completed')
            logger.info(f"✅ Room {room_id} marked as completed")
        except Exception as e:
            logger.error(f"❌ Failed to update room status: {e}")
        
        # ===== 8. STOP MONITORING THREADS =====
        if room_id in active_monitors:
            try:
                del active_monitors[room_id]
                logger.info(f"🛑 Removed active monitor for room {room_id}")
            except:
                pass

        # Wake the moderator loop one last time so it re-checks status and exits its
        # wait() immediately instead of lingering for the timeout, then drop the event.
        _ev = room_moderator_wake.pop(room_id, None)
        if _ev is not None:
            _ev.set()

        # Release the in-memory start guard so the room could host a fresh session later.
        _tasks_started.discard(room_id)
        
        if room_id in research_timers:
            try:
                del research_timers[room_id]
                logger.info(f"🛑 Removed research timer for room {room_id}")
            except:
                pass
        
        logger.info(f"✅ Session fully ended for room {room_id}")
        
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR ending session: {e}", exc_info=True)
        try:
            emit("error", {"message": "Failed to end session properly"})
        except:
            pass

# ============================================================
# Admin Room Creation Endpoint
# ============================================================
@app.route("/admin/rooms/create", methods=["POST"])
@require_admin_token
def admin_create_room():
    """Admin-only room creation endpoint"""
    try:
        data = request.json or {}
        
        mode = data.get('mode', 'active')
        story_id = data.get('story_id')
        max_participants = int(data.get('max_participants', 3))
        admin_note = data.get('admin_note', '')
        
        if mode not in ['active', 'passive']:
            return jsonify({"error": "Mode must be 'active' or 'passive'"}), 400
        
        if story_id:
            story_data = get_data(story_id)
        else:
            story_data = get_data()
            story_id = story_data.get('story_id', 'default-story')
        
        room = supabase_create_room(
            mode=mode,
            story_id=story_id,
            max_participants=max_participants,
            created_by='admin'
        )
        
        if admin_note:
            supabase.table('rooms').update({
                'admin_note': admin_note
            }).eq('id', room['id']).execute()
        
        active_link = f"{FRONTEND_URL}/join/{mode}"
        direct_link = f"{FRONTEND_URL}/chat/{room['id']}"
        
        log_admin_action('create_room_admin', 'room', room['id'], {
            'mode': mode,
            'story_id': story_id,
            'max_participants': max_participants,
            'admin_note': admin_note
        }, 'admin')
        
        logger.info(f"✅ Admin created room: {room['id']} (mode={mode})")
        
        return jsonify({
            "success": True,
            "room": room,
            "links": {
                "shareable": active_link,
                "direct": direct_link
            }
        })
    
    except Exception as e:
        logger.error(f"❌ Error creating room as admin: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# Admin End Session Endpoint
# ============================================================
@app.route("/admin/rooms/<room_id>/end", methods=["POST"])
@require_admin_token
def admin_end_session(room_id: str):
    """Admin endpoint to end a session"""
    try:
        data = request.json or {}
        admin_user = data.get('admin_user', 'admin')
        
        room = get_room(room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        
        # Trigger the socket event to end session with summaries
        socketio.emit("end_session", {
            "room_id": room_id,
            "sender": f"admin:{admin_user}"
        }, room=room_id)
        
        log_admin_action('end_session', 'room', room_id, {
            'previous_status': room.get('status')
        }, admin_user)
        
        logger.info(f"✅ Admin triggered session end for room {room_id}")
        
        return jsonify({
            "success": True,
            "message": "Session ending, summaries will be sent to participants",
            "room_id": room_id
        })
    
    except Exception as e:
        logger.error(f"❌ Error ending session: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# Helper: Log Admin Action
# ============================================================
def log_admin_action(action: str, entity_type: str = None, entity_id: str = None,
                     details: dict = None, admin_user: str = 'admin'):
    """Log an admin action"""
    try:
        supabase.table('admin_logs').insert({
            'action': action,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'details': details or {},
            'admin_user': admin_user,
            'ip_address': request.remote_addr if request else '127.0.0.1',
            'created_at': datetime.now().isoformat()
        }).execute()
        logger.info(f"📝 Admin action logged: {action} by {admin_user}")
    except Exception as e:
        logger.error(f"❌ Failed to log admin action: {e}")

# ============================================================
# TTS & STT Endpoints
# ============================================================
@app.route("/tts", methods=["POST"])
def tts():
    """Text-to-speech endpoint → audio/mpeg via the active TTS provider (TTS_PROVIDER env).

    Uses the blocking synthesize() path so the full audio is buffered before any bytes
    are sent. This guarantees a correct non-200 status on failure (streaming would have
    already committed to 200 before the exception is raised).  The tts-1 model is fast
    enough (~500 ms) that the frontend pre-warm makes the perceived latency negligible.
    """
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip() or "Hello"
    room_id = (payload.get("room_id") or "").strip()
    language = (payload.get("language") or "").strip()
    if not language and room_id:
        language = get_room_language(room_id) or ""
    if not language:
        language = detect_language(text)

    logger.info(f"[TTS] request lang={language!r} room={room_id[:8] or '-'} chars={len(text)}: {text[:100]!r}")
    clean, had_foreign, scripts = sanitize_to_supported(text)
    if had_foreign:
        logger.warning(f"[TTS] 🛡️ stripped foreign script before TTS: {[s['script'] for s in scripts]}")
        log_failure(room_id or None, "language_guard_tts",
                    scripts=[s["script"] for s in scripts])
        text = clean or text

    # Pakistani Roman-Urdu safety-net: swap any stray Hindi-Sanskrit words for everyday
    # Pakistani-Urdu ones before synthesis, so the SPOKEN line never carries Hindi
    # vocabulary even if the LLM slipped. Roman-Urdu/mixed only; English is untouched.
    if language in ("roman_urdu", "urdu", "mixed"):
        _pk = enforce_pakistani_roman_urdu(text)
        if _pk != text:
            logger.info(f"[TTS] applied Pakistani Roman-Urdu vocab fixes (lang={language!r})")
            text = _pk

    try:
        _t0 = time.time()
        # Cache-fronted: identical lines requested by the other participants (or the same
        # intro in another room) resolve to ONE synthesis instead of N concurrent ones.
        audio = synthesize_for_language_cached(text, language)
        _ms = int((time.time() - _t0) * 1000)
        # Guard: never return a 200 with a non-audio body — that plays nothing on the
        # client. If we somehow produced one, surface it as an error so the client logs it
        # and the user isn't left with a silent "Speaking…".
        if not audio or len(audio) < 256:
            logger.error(f"[TTS] ❌ produced implausible audio ({len(audio or b'')} bytes) lang={language!r}")
            log_failure(room_id or None, "tts", error=f"implausible audio {len(audio or b'')}B",
                        recovery="moderator text remains in chat")
            return jsonify({"error": "TTS produced no audio"}), 502
        logger.info(f"[TTS] ✅ generated lang={language!r} synth={_ms}ms bytes={len(audio)}")
        log_event(room_id or None, "tts", {"language": language, "chars": len(text)})
        return send_file(BytesIO(audio), mimetype="audio/mpeg")
    except VoiceProviderError as e:
        logger.warning(f"[TTS] ⚠️ unavailable: {e}")
        return jsonify({"error": "TTS unavailable: no voice provider configured"}), 503
    except Exception as e:
        logger.error(f"[TTS] ❌ error: {e}")
        log_failure(room_id or None, "tts", error=str(e)[:300], recovery="moderator text remains in chat")
        return jsonify({"error": f"TTS failed: {e}"}), 502

@app.route("/api/message/<message_id>/audio", methods=["GET"])
def get_message_audio(message_id):
    """Serve the original recording for a voice message (participant playback).

    The bucket stays PRIVATE: bytes are streamed from the server, never via a
    public URL. Text messages have no recording and return 404.
    """
    try:
        result = (
            supabase.table("voice_recordings")
            .select("storage_path, mime_type")
            .eq("message_id", message_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        storage_path = rows[0].get("storage_path") if rows else None
        if not storage_path:
            return jsonify({"error": "No audio for this message"}), 404

        mime = (rows[0].get("mime_type") or "audio/webm").split(";")[0]
        audio_bytes = download_voice_object(storage_path)
        return send_file(
            BytesIO(audio_bytes),
            mimetype=mime,
            as_attachment=False,
            download_name=f"{message_id}.webm",
        )
    except Exception as e:
        logger.error(f"❌ get_message_audio error for {message_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/stt", methods=["POST"])
def stt():
    """Speech-to-text: stream the uploaded webm/opus blob straight to OpenAI (no ffmpeg/pydub)."""
    _t_req = time.time()
    logger.info("🎤 STT request")

    if openai_client is None and groq_client is None:
        return jsonify({"error": "STT unavailable: Neither OpenAI nor Groq API keys configured"}), 503

    if "file" not in request.files:
        return jsonify({"error": "No audio file provided (expected form field 'file')"}), 400

    try:
        f = request.files["file"]
        data_bytes = f.read()
        content_type = f.mimetype or "audio/webm"

        audio_token = uuid.uuid4().hex

        def _stage_audio():
            try:
                upload_voice_staging(audio_token, data_bytes, content_type=content_type)
                logger.info(f"✅ Staged audio {audio_token} ({len(data_bytes)} bytes)")
            except Exception as up_err:
                logger.warning(f"⚠️ Audio staging failed for {audio_token}: {up_err}")

        staging_thread = threading.Thread(
            target=_stage_audio, name=f"stage-{audio_token[:8]}", daemon=True
        )
        staging_thread.start()

        buf = BytesIO(data_bytes)
        buf.name = "recording.webm"

        room_id = request.form.get("room_id") or request.form.get("roomId") or request.args.get("room_id")
        lang_hint = (request.form.get("language") or "").strip().lower()
        stt_lang = {"ur": "ur", "urdu": "ur", "roman_urdu": "ur", "en": "en", "english": "en"}.get(lang_hint)
        
        if not stt_lang and room_id:
            room_lang = get_room_primary_language(room_id)
            if room_lang in ("roman_urdu", "ur", "mixed"):
                stt_lang = "ur"
            elif room_lang == "en":
                stt_lang = "en"
        
        if not stt_lang:
            stt_lang = "ur"  # Explicitly force 'ur' for Urdu acoustic model

        logger.info(f"🎤 STT Language set to: {stt_lang!r} (room_id: {room_id})")

        if stt_lang == "ur":
            stt_prompt = (
                "Desert survival task in Roman Urdu: paani, tarp, qutub numa, naqsha, torch, "
                "shisha, jaket, multi-tool, lighter, namak, emergency triangle, guide book. "
                "Mera khayal hai ke paani sab se pehle 1 number par aana chahiye. "
                "Tarp ko 2 number par rank karein. Compass ko 3 number par rank karein. "
                "Mujhe lagta hai paani sab se zyada zaroori hai survival ke liye."
            )
        else:
            stt_prompt = (
                "Desert survival task in English: water bottles, tarp, compass, road map, "
                "flashlight, mirror, jackets, multi-tool, lighter, salt packets, "
                "emergency triangle, guide book. I think water should be rank number 1."
            )

        # Optional VAD & Denoise Preprocessing
        try:
            from audio_preprocessor import process_audio_for_stt
            cleaned_bytes, has_voice = process_audio_for_stt(data_bytes)
            if not has_voice:
                logger.info("🎤 VAD: Audio contains no audible speech / silence.")
        except Exception as vad_err:
            logger.debug(f"VAD preprocessing skipped: {vad_err}")

        _t_stt = time.time()
        res = None

        # Task 1: Primary STT using Groq Whisper (whisper-large-v3)
        if groq_client is not None:
            try:
                logger.info("🎤 STT: Attempting Groq Whisper (whisper-large-v3)...")
                stt_kwargs = {"model": "whisper-large-v3", "file": buf, "prompt": stt_prompt, "language": stt_lang}
                res = groq_client.audio.transcriptions.create(**stt_kwargs)
                logger.info("✅ Groq Whisper STT successful!")
            except Exception as groq_stt_err:
                logger.warning(f"⚠️ Groq Whisper STT failed: {groq_stt_err}. Retrying with OpenAI...")
                res = None

        # Fallback to OpenAI if Groq was unavailable or failed
        if res is None and openai_client is not None:
            try:
                logger.info("🎤 STT Fallback: Attempting OpenAI transcription...")
                # Rewind the buffer — Groq consumed it, so the read position is at the end
                buf.seek(0)
                stt_kwargs = {"model": "gpt-4o-mini-transcribe", "file": buf, "prompt": stt_prompt, "language": stt_lang}
                res = openai_client.audio.transcriptions.create(**stt_kwargs)
                logger.info("✅ OpenAI STT fallback successful!")
            except Exception as openai_stt_err:
                logger.error(f"❌ OpenAI STT fallback also failed: {openai_stt_err}")
                res = None

        if res is None:
            return jsonify({"error": "STT transcription failed on all available providers"}), 502

        _stt_ms = int((time.time() - _t_stt) * 1000)
        raw_text = (res.text or "").strip()
        logger.info(f"🎤 STT Raw Model Output: {raw_text!r}")

        # ONE structured LLM call returns {language, confidence, normalized_text}.
        _t_norm = time.time()
        result = classify_and_normalize(raw_text)
        normalized = result.get("normalized_text", raw_text) or raw_text
        _norm_ms = int((time.time() - _t_norm) * 1000)

        # Simple content check: Accept any transcript with 1+ characters (any script, any language)
        room_id = request.form.get("room_id") or request.form.get("roomId")
        user_name = request.form.get("user") or request.form.get("username") or "user"

        # The upload was running during transcription and is almost always done by
        # now; wait briefly so the token is reliably usable.
        staging_thread.join(timeout=1.5)

        if not raw_text or len(raw_text.strip()) < 1:
            retry_prompt = "Maaf kijiye, aap ki awaaz saaf nahi aayi. Kya aap dobara farma sakte hain?"
            logger.warning(f"⚠️ STT Empty Audio Output for {user_name} in room {room_id}")
            if room_id:
                try:
                    send_moderator_message(room_id, retry_prompt, "moderator")
                except Exception as mod_err:
                    logger.warning(f"Failed to send empty audio prompt: {mod_err}")
            return jsonify({
                "retry": True,
                "text": "",
                "raw_text": "",
                "language": result.get("language", "ur"),
                "confidence": 0.0,
                "audio_token": audio_token,
                "message": retry_prompt
            })

        _total_ms = int((time.time() - _t_req) * 1000)
        logger.info(
            f"✅ STT result ({result['language']}) [transcribe={_stt_ms}ms normalize={_norm_ms}ms total={_total_ms}ms]: {normalized[:50]}..."
        )
        log_event(room_id, "stt", {
            "audio_token": audio_token,
            "language": result["language"],
            "confidence": 0.95,
            "chars": len(normalized),
        })
        return jsonify({
            "retry": False,
            "text": normalized,
            "raw_text": raw_text,
            "language": result["language"],
            "confidence": 0.95,
            "low_confidence": False,
            "audio_token": audio_token,
        })

    except Exception as e:
        logger.error(f"❌ STT error: {e}")
        # 8.6: STT failed, but the raw audio was staged in the background (recoverable).
        log_failure(None, "stt", error=str(e)[:300],
                    recovery="raw audio staged; transcript unavailable")
        return jsonify({"error": f"Transcription failed: {e}"}), 502


# ============================================================
# Conversation Recording Export (admin-gated; private bucket stays private)
# ============================================================
import html as _html_mod


def _clean_speakable(raw: str) -> str:
    """Strip HTML/markdown so synthesized moderator audio reads cleanly (mirrors the client)."""
    if not raw:
        return ""
    t = re.sub(r"<[^>]*>", " ", raw)        # drop HTML (task-intro card is HTML)
    t = _html_mod.unescape(t)
    t = re.sub(r"[*_`#>|]", " ", t)          # markdown emphasis / formatting markers
    t = re.sub(r"\s+", " ", t).strip()
    return t


def ensure_audio_exists(room_id: str, message_id: str, text: str) -> Optional[dict]:
    """
    Ensure audio exists for a message, generate if missing.
    Uses the new TTS manager. Returns the DB record if successful.
    """
    try:
        # Check if recording exists in DB
        recording = supabase.table("voice_recordings") \
            .select("*") \
            .eq("message_id", message_id) \
            .execute()
        
        if recording.data:
            rec = recording.data[0]
            storage_path = rec.get("storage_path")
            if voice_recording_file_exists(storage_path):
                return rec
            else:
                logger.warning(f"⚠️ File missing from storage: {storage_path}")
        
        # Generate new audio
        logger.info(f"🔄 Generating missing audio for {message_id}")
        from supabase_client import persist_moderator_tts
        result = persist_moderator_tts(room_id, message_id, text)
        return result
        
    except Exception as e:
        logger.error(f"❌ ensure_audio_exists failed: {e}")
        return None


@app.route("/api/room/<room_id>/recording", methods=["GET"])
@require_admin_token
def download_room_recording(room_id: str):
    """Assemble a room's full spoken conversation into ONE ordered audio file.

    Chronological (by message time) concatenation of participant audio (V6) and
    moderator TTS clips. Moderator clips are synthesized + persisted lazily on first
    export (cached in voice_recordings). Admin-gated; clips are fetched server-side
    from the PRIVATE bucket — never exposed publicly. ?format=mp3 (default) | wav.
    """
    out_format = (request.args.get("format", "mp3") or "mp3").lower()
    if out_format not in ("mp3", "wav"):
        out_format = "mp3"

    room = get_room(room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404

    if not assembly_available():
        return jsonify({
            "error": "Audio assembly unavailable on this server "
                     "(install pydub + imageio-ffmpeg to enable recording export)."
        }), 503

    # Chronological message order (get_chat_history returns ascending created_at).
    messages = get_chat_history(room_id)
    recs_by_msg = {
        r.get("message_id"): r
        for r in get_voice_recordings_for_room(room_id)
        if r.get("message_id")
    }

    # Lazily synthesize + persist any missing moderator TTS clips (cached for next time).
    for m in messages:
        mid = m.get("id")
        if not mid or m.get("username") != "Moderator":
            continue

        text = _clean_speakable(m.get("message", ""))[:4000]
        if not text:
            continue

        row = ensure_audio_exists(room_id, str(mid), text)
        if row:
            recs_by_msg[mid] = row
        else:
            logger.warning(f"⚠️ Could not generate audio for {mid}")

    # Download each clip server-side, in conversation order.
    clips = []
    for m in messages:
        rec = recs_by_msg.get(m.get("id"))
        if not rec or not rec.get("storage_path"):
            continue
        try:
            data = download_voice_object(rec["storage_path"])
        except Exception as e:
            logger.warning(f"Could not download clip {rec.get('storage_path')}: {e}")
            continue
        if data:
            clips.append({"data": data, "mime": rec.get("mime_type"), "path": rec["storage_path"]})

    if not clips:
        return jsonify({"error": "No audio clips found for this room"}), 404

    try:
        out_bytes = concat_clips(clips, out_format)
    except AudioAssemblyError as e:
        return jsonify({"error": str(e)}), 503

    mime = "audio/mpeg" if out_format == "mp3" else "audio/wav"
    fname = f"room_{room_id}_recording.{out_format}"
    logger.info(f"🎧 Built conversation recording for room {room_id} ({len(clips)} clips, {out_format})")
    return send_file(BytesIO(out_bytes), mimetype=mime, as_attachment=True, download_name=fname)


# ============================================================
# Health Check Endpoint
# ============================================================
@app.route("/health")
def health_check():
    """Health check with a lightweight Supabase round-trip (skip with ?lite=1 for speed)."""
    lite = request.args.get("lite", "").lower() in ("1", "true", "yes")
    supabase_ok = False
    if not lite:
        try:
            supabase.table("rooms").select("id").limit(1).execute()
            supabase_ok = True
        except Exception as e:
            logger.warning(f"/health Supabase check failed: {e}")
    return jsonify({
        "status": "healthy",
        "llm_provider": LLM_PROVIDER,
        "socketio_async_mode": _socketio_async_mode,
        "openai_available": openai_client is not None,
        "groq_available": groq_client is not None,
        "supabase_connected": supabase_ok if not lite else None,
        "audio_support": openai_client is not None,
        "session_summaries": True,
        "feedback_delivery": "direct-with-broadcast-fallback",
        "timestamp": time.time(),
    })

# ============================================================
# Server Start
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("="*60)
    logger.info("🚀 Starting Flask-SocketIO server")
    logger.info(f"⚙️ Socket.IO async_mode: {_socketio_async_mode}")
    logger.info(f"📍 Host: 0.0.0.0:{port}")
    logger.info(f"🌐 Frontend: {FRONTEND_URL}")
    logger.info(f"🤖 LLM Provider: {LLM_PROVIDER}")
    if LLM_PROVIDER == "openai":
        logger.info(f"📊 OpenAI Model: {OPENAI_MODEL}")
    else:
        logger.info(f"📊 Groq Model: {GROQ_MODEL}")
    logger.info(f"📝 Session Summaries: ENABLED")
    logger.info(f"💬 Feedback Delivery: 3-Method Guaranteed")
    logger.info("="*60)
    
    try:
        socketio.run(
            app, 
            host="0.0.0.0", 
            port=port, 
            debug=False, 
            allow_unsafe_werkzeug=True
        )
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        import traceback
        traceback.print_exc()