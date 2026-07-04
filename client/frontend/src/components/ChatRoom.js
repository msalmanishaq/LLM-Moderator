// ============================================================
// ChatRoom.js - RESEARCH VERSION (Desert Survival Task)
// ============================================================
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useLocation, useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import rehypeSanitize from "rehype-sanitize";
import { socket, API_BASE } from "../socket"; // ✅ FIXED: Import API_BASE from socket.js
import MessageAudio from "./MessageAudio";
import audioManager from "../utils/AudioManager";
import {
  MdExitToApp,
  MdContentCopy,
  MdCheck,
  MdPerson,
  MdChat,
  MdCheckCircle,
  MdWarning,
  MdVolumeUp,
  MdVolumeOff,
  MdMic,
} from "react-icons/md";

// ============================================================
// 🎨 USER COLOR SYSTEM
// ============================================================
const USER_COLORS = [
  { bg: "bg-blue-50/80", border: "border-blue-150", text: "text-blue-700", accent: "bg-blue-500" },
  { bg: "bg-emerald-50/80", border: "border-emerald-150", text: "text-emerald-700", accent: "bg-emerald-500" },
  { bg: "bg-purple-50/80", border: "border-purple-150", text: "text-purple-700", accent: "bg-purple-500" },
  { bg: "bg-rose-50/80", border: "border-rose-150", text: "text-rose-700", accent: "bg-rose-500" },
  { bg: "bg-sky-50/80", border: "border-sky-150", text: "text-sky-700", accent: "bg-sky-500" },
  { bg: "bg-amber-50/80", border: "border-amber-150", text: "text-amber-700", accent: "bg-amber-500" },
];

const getUserColor = (userName, currentUserName) => {
  if (userName === currentUserName) {
    return USER_COLORS[0];
  }
  let hash = 0;
  for (let i = 0; i < userName.length; i++) {
    hash = userName.charCodeAt(i) + ((hash << 5) - hash);
  }
  const index = Math.abs(hash) % USER_COLORS.length;
  return USER_COLORS[index];
};

// ============================================================
// 🏜️ DESERT SURVIVAL ITEMS (for ranking)
// ============================================================
// Fallback only — server sends the pinned list via /api/desert-items?room_id=
const DESERT_ITEMS = [
  "A flashlight (4 batteries included)",
  "A map of the region",
  "A compass",
  "A large plastic sheet (6x8 feet)",
  "A box of matches",
  "A winter coat",
  "A bottle of salt tablets (1000 tablets)",
  "A small hunting knife",
  "2 quarts of water per person (6 quarts total)",
  "A cosmetic mirror",
  "A parachute (red & white, 30ft diameter)",
  "A book - 'Edible Animals of the Desert'",
];

// ✅ REMOVED: const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:5000";
// ✅ Now using API_BASE from socket.js

// ============================================================
// 🔤 Roman Urdu transliteration (display + storage stay Latin-only)
// ------------------------------------------------------------
// STT may return native Urdu script; the product is English / Roman Urdu only.
// We transliterate any Arabic-script text to Latin so chat never shows Urdu
// script. Common whole words get clean overrides; everything else falls back to
// a character map (imperfect — short vowels aren't written in Urdu — but always
// readable Latin, never leftover script). English/Latin text is returned as-is.
// ============================================================
// Arabic + Arabic Supplement + Presentation Forms A/B (covers Urdu script).
const URDU_SCRIPT_RE = /[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]/;

const URDU_WORD_MAP = {
  "اب": "ab", "کیا": "kya", "کرنا": "karna", "ہے": "hai", "ہیں": "hain",
  "نہیں": "nahi", "آپ": "aap", "کا": "ka", "کے": "ke", "کی": "ki",
  "خیال": "khayal", "ہم": "hum", "میں": "mein", "کرو": "karo", "کریں": "karein",
  "کرتے": "karte", "ٹھیک": "theek", "اچھا": "acha", "ہاں": "haan", "کیوں": "kyun",
  "کہاں": "kahan", "کب": "kab", "کیسے": "kaise", "بہت": "bohot", "تھوڑا": "thora",
  "پانی": "pani", "چاہیے": "chahiye", "مطلب": "matlab", "سمجھ": "samajh",
  "دیکھو": "dekho", "سنو": "suno", "چلو": "chalo", "پھر": "phir", "لیکن": "lekin",
  "مگر": "magar", "اور": "aur", "یہ": "yeh", "وہ": "woh", "کون": "kaun",
  "سب": "sab", "کچھ": "kuch", "بھی": "bhi", "تو": "to", "مجھے": "mujhe",
  "تم": "tum", "کرنے": "karne", "والا": "wala", "سہی": "sahi", "غلط": "ghalat",
  "اچھی": "achi", "ضروری": "zaroori", "پہلے": "pehle", "بعد": "baad",
};

const URDU_CHAR_MAP = {
  "آ": "aa", "ا": "a", "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ث": "s",
  "ج": "j", "چ": "ch", "ح": "h", "خ": "kh", "د": "d", "ڈ": "d", "ذ": "z",
  "ر": "r", "ڑ": "r", "ز": "z", "ژ": "zh", "س": "s", "ش": "sh", "ص": "s",
  "ض": "z", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "q",
  "ک": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n", "ں": "n", "و": "o",
  "ہ": "h", "ھ": "h", "ۀ": "h", "ۂ": "h", "ء": "", "ی": "y", "ئ": "y",
  "ے": "e", "ؤ": "o",
  // diacritics
  "َ": "a", "ِ": "i", "ُ": "u", "ّ": "", "ْ": "", "ٰ": "a",
  // punctuation + digits
  "۔": ".", "،": ",", "؟": "?", "؛": ";", "۰": "0", "۱": "1", "۲": "2",
  "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
};

const transliterateUrduWord = (word) => {
  // Split a trailing run of punctuation (Urdu or ASCII) so word-map lookups hit.
  const m = word.match(/^(.*?)([،؛؟۔!?.,:;]*)$/);
  const core = m ? m[1] : word;
  const punct = m ? m[2] : "";
  const punctRoman = [...punct].map((c) => URDU_CHAR_MAP[c] ?? c).join("");
  if (URDU_WORD_MAP[core]) return URDU_WORD_MAP[core] + punctRoman;
  let out = "";
  for (const ch of core) {
    if (ch in URDU_CHAR_MAP) out += URDU_CHAR_MAP[ch];
    else if (URDU_SCRIPT_RE.test(ch)) out += ""; // drop unmapped Urdu marks
    else out += ch; // keep Latin/English untouched
  }
  return out + punctRoman;
};

const romanizeUrdu = (text) => {
  if (!text || !URDU_SCRIPT_RE.test(text)) return text; // English / already-Latin
  return text
    .split(/(\s+)/)
    .map((tok) => (/^\s+$/.test(tok) ? tok : transliterateUrduWord(tok)))
    .join("");
};

// Parse a message's metadata whether it arrives as an object (live socket) or a
// JSON string (DB history). Returns {} when absent/unparseable.
const getMsgMeta = (msg) => {
  const meta = msg && msg.metadata;
  if (meta && typeof meta === "object") return meta;
  if (typeof meta === "string") {
    try { return JSON.parse(meta); } catch (_) { return {}; }
  }
  return {};
};

// A message is "voice" if flagged top-level (live broadcast) or in metadata (history).
const isVoiceMessage = (msg) =>
  msg?.input_mode === "voice" || getMsgMeta(msg).input_mode === "voice";

// ============================================================
// 🔊 Convert a moderator message to clean speakable text
// (strips the HTML task card and markdown markers so TTS doesn't read tags/asterisks)
// ============================================================
const toSpeechText = (raw) => {
  if (typeof raw !== "string") return "";
  let t = raw;
  t = t.replace(/<[^>]*>/g, " "); // strip HTML tags (task intro is HTML)
  t = t
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
  t = t.replace(/[*_`#>|]/g, " "); // drop markdown emphasis / formatting markers
  t = t.replace(/\s+/g, " ").trim(); // collapse whitespace
  return t;
};

// Canonical per-message key — MUST match the `sid` the socket handler uses to enqueue
// TTS, so voice-note playback status (queued/playing/played) lines up with the queue.
const msgKey = (msg) =>
  msg && msg.id != null
    ? String(msg.id)
    : `${msg?.sender}|${msg?.message}|${msg?.timestamp || ""}`;

// Classify a Moderator message for the voice-first UI:
//   'task'   → the HTML task-intro card (items + instructions); stays a visual card.
//   'notice' → short system/time announcements ("5 minutes remaining"); stays a card.
//   'voice'  → a conversational moderator turn; rendered as a voice note.
// Structural signals (content_format/message_type) are authoritative when present
// (always on history, and on the live task-card emit). Live announcements carry no
// type, so a conservative glyph+keyword heuristic catches them without misclassifying
// ordinary conversation.
const MODERATOR_NOTICE_GLYPHS = ["⏰", "⚠️", "⚠", "✅", "🏁", "🛑"];
const MODERATOR_NOTICE_RE = /(remaining|minute|min left|recorded|finaliz|ranking|inferring)/i;
const classifyModerator = (msg) => {
  const m = typeof msg?.message === "string" ? msg.message : "";
  if (
    msg?.content_format === "html" ||
    msg?.message_type === "task" ||
    m.includes('class="task-intro"')
  ) {
    return "task";
  }
  if (msg?.message_type === "system") return "notice";
  const t = m.trimStart();
  if (MODERATOR_NOTICE_GLYPHS.some((g) => t.startsWith(g)) && MODERATOR_NOTICE_RE.test(t)) {
    return "notice";
  }
  return "voice";
};

// Deterministic pseudo-waveform bar heights (0.3..1) seeded from the message text, so a
// note's waveform is stable across re-renders but varies between messages.
const waveformBars = (seed, count = 32) => {
  const s = seed || "moderator";
  const bars = new Array(count);
  for (let i = 0; i < count; i++) {
    const c = s.charCodeAt(i % s.length) || 60;
    const v = ((c * (i + 7) * 31) % 100) / 100; // 0..1
    bars[i] = 0.3 + v * 0.7;
  }
  return bars;
};

const formatClock = (secs) => {
  if (!secs || !isFinite(secs) || secs < 0) return "0:00";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
};

const MARKDOWN_COMPONENTS = {
  p: ({ children, ...rest }) => (
    <p className="mb-2 last:mb-0 text-sm leading-relaxed" {...rest}>
      {children}
    </p>
  ),
  strong: ({ children, ...rest }) => (
    <strong className="font-semibold" {...rest}>
      {children}
    </strong>
  ),
  em: ({ children, ...rest }) => (
    <em className="italic" {...rest}>
      {children}
    </em>
  ),
  ul: ({ children, ...rest }) => (
    <ul className="list-disc pl-5 space-y-1 mb-2 text-sm" {...rest}>
      {children}
    </ul>
  ),
  ol: ({ children, ...rest }) => (
    <ol className="list-decimal pl-5 space-y-1 mb-2 text-sm" {...rest}>
      {children}
    </ol>
  ),
  li: ({ children, ...rest }) => (
    <li className="leading-relaxed" {...rest}>
      {children}
    </li>
  ),
  h1: ({ children, ...rest }) => (
    <h1 className="text-lg font-bold mb-2" {...rest}>
      {children}
    </h1>
  ),
  h2: ({ children, ...rest }) => (
    <h2 className="text-base font-bold mb-2" {...rest}>
      {children}
    </h2>
  ),
  h3: ({ children, ...rest }) => (
    <h3 className="text-sm font-bold mb-1" {...rest}>
      {children}
    </h3>
  ),
  code: ({ children, ...rest }) => (
    <code className="bg-black/10 rounded px-1 text-xs font-mono" {...rest}>
      {children}
    </code>
  ),
};

function ChatMessageBody({ msg, isCurrentUser, onPlayVoice, onSpeak }) {
  // 🎤 Voice message: show a mic badge, the Roman Urdu transcript, and a ▶ button
  // to hear the original recording. The transcript is romanized at send time, but
  // we re-romanize defensively so no Urdu script ever leaks into the UI.
  if (isVoiceMessage(msg)) {
    const meta = getMsgMeta(msg);
    const transcript = romanizeUrdu(meta.roman_transcript || msg.message || "");
    const hasAudio = msg.id != null && !String(msg.id).includes("_");
    const accent = isCurrentUser ? "text-indigo-100" : "text-purple-700";
    const audioUrl = `${API_BASE}/api/message/${msg.id}/audio`;
    return (
      <div className="flex flex-col gap-2 text-left">
        <div className="min-w-0">
          <span
            className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide mb-0.5 ${accent}`}
          >
            🎤 Voice
          </span>
          <p className="whitespace-pre-wrap break-words text-sm italic">{transcript}</p>
        </div>
        {hasAudio && (
          <MessageAudio
            audioUrl={audioUrl}
            messageId={String(msg.id)}
          />
        )}
      </div>
    );
  }

  const isHtml =
    msg.content_format === "html" ||
    msg.message_type === "task" ||
    (typeof msg.message === "string" && msg.message.includes('class="task-intro"'));

  const isModerator = msg.sender === "Moderator";
  const isModeratorOrSystem = isModerator || msg.sender === "System";

  // Build the message body once, then (for Moderator) attach a ▶ Play button so it can
  // be voiced on demand — same affordance as a user voice message, and immune to the
  // browser's auto-play block since a click is a user gesture.
  let body;
  if (isHtml && typeof msg.message === "string") {
    body = (
      <div
        className="task-message-html max-w-none text-left [&_a]:text-indigo-600"
        dangerouslySetInnerHTML={{ __html: msg.message }}
      />
    );
  } else if (isModeratorOrSystem && typeof msg.message === "string" && /[*_`#[\]|]/.test(msg.message)) {
    body = (
      <div className={`max-w-none text-left ${isCurrentUser ? "text-white" : ""}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkBreaks]}
          rehypePlugins={[rehypeSanitize]}
          components={MARKDOWN_COMPONENTS}
        >
          {msg.message}
        </ReactMarkdown>
      </div>
    );
  } else {
    body = <p className="whitespace-pre-wrap break-words text-sm">{msg.message}</p>;
  }

  if (isModerator && onSpeak) {
    return (
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={() => onSpeak(String(msg.id ?? msg.message), msg.message)}
          title="Play the moderator's voice"
          className="flex-shrink-0 mt-0.5 w-7 h-7 rounded-full flex items-center justify-center bg-amber-100 hover:bg-amber-200 text-amber-700 transition-colors"
        >
          ▶
        </button>
        <div className="min-w-0 flex-1">{body}</div>
      </div>
    );
  }
  return body;
}

// ============================================================
// 🎙️ MODERATOR VOICE NOTE (Telegram-style; voice-first presentation)
// ------------------------------------------------------------
// Renders a conversational moderator turn as a voice note instead of a text bubble:
// avatar (in the parent row), play/pause, an animated waveform that fills with playback
// progress, a live status line (Speaking… / Queued / Played / Tap to play), duration,
// and a collapsible "View transcript" for debugging + accessibility. The full transcript
// is ALWAYS in the DOM (sr-only) so screen readers and research/analytics never lose it.
// ============================================================
function ModeratorVoiceNote({
  msg,
  status,        // 'playing' | 'queued' | 'played' | 'idle'
  paused,        // true if the currently-playing clip is paused
  progress,      // 0..1 (only meaningful while playing)
  elapsed,       // seconds elapsed (while playing)
  duration,      // seconds total (known after first play)
  muted,
  timestamp,
  transcript,
  expanded,
  onToggleTranscript,
  onPlayPause,
  onSkip,
}) {
  const bars = useMemo(() => waveformBars(msgKey(msg)), [msg]);
  const isPlaying = status === "playing";
  const isQueued = status === "queued";
  const isPlayed = status === "played";
  const isActivePlaying = isPlaying && !paused;

  // Per-bar fill: while playing, bars up to `progress` are lit; played → all lit;
  // queued/idle → none lit (queued gently pulses to signal "waiting").
  const litFraction = isPlaying ? progress : isPlayed ? 1 : 0;

  const statusMeta = isPlaying
    ? paused
      ? { dot: "bg-amber-400", text: "text-amber-700", label: "Paused" }
      : { dot: "bg-amber-500 animate-pulse", text: "text-amber-700", label: "Speaking…" }
    : isQueued
    ? { dot: "bg-indigo-400 animate-pulse", text: "text-indigo-600", label: "Queued" }
    : isPlayed
    ? { dot: "bg-emerald-500", text: "text-emerald-600", label: "Played" }
    : { dot: "bg-slate-300", text: "text-slate-500", label: muted ? "Tap to play (muted)" : "Tap to play" };

  const timeLabel = isPlaying
    ? `${formatClock(elapsed)}${duration ? ` / ${formatClock(duration)}` : ""}`
    : duration
    ? formatClock(duration)
    : "voice";

  return (
    <div className="min-w-0 w-full max-w-md">
      <div className="flex items-center gap-2 mb-1.5 px-1">
        <span className="font-bold text-xs text-amber-705">Moderator</span>
        <span className="inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider text-amber-600 bg-amber-50 border border-amber-200 rounded-full px-1.5 py-0.5">
          🎙️ Voice
        </span>
        <span className="text-[10px] text-slate-400 font-medium">{timestamp}</span>
      </div>

      <div
        className={`rounded-2xl rounded-tl-none border px-3 py-2.5 shadow-sm transition-colors ${
          isPlaying
            ? "bg-amber-50 border-amber-300"
            : "bg-amber-50/60 border-amber-200/80"
        }`}
      >
        <div className="flex items-center gap-3">
          {/* Play / Pause */}
          <button
            type="button"
            onClick={onPlayPause}
            aria-label={isActivePlaying ? "Pause moderator voice" : "Play moderator voice"}
            className="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center bg-amber-500 hover:bg-amber-600 text-white shadow-sm transition-colors text-base leading-none"
          >
            {isActivePlaying ? "⏸" : "▶"}
          </button>

          {/* Waveform */}
          <div className="flex-1 min-w-0 flex items-center gap-[2px] h-8" aria-hidden="true">
            {bars.map((h, i) => {
              const lit = (i + 1) / bars.length <= litFraction;
              return (
                <span
                  key={i}
                  className={`flex-1 rounded-full transition-colors duration-150 ${
                    lit ? "bg-amber-500" : isQueued ? "bg-amber-200 animate-pulse" : "bg-amber-200"
                  }`}
                  style={{ height: `${Math.round(h * 100)}%` }}
                />
              );
            })}
          </div>

          {/* Duration / elapsed */}
          <span className="flex-shrink-0 text-[10px] font-mono font-semibold text-amber-700 tabular-nums">
            {timeLabel}
          </span>
        </div>

        {/* Status line + Skip */}
        <div className="flex items-center justify-between mt-2 px-0.5">
          <span className={`inline-flex items-center gap-1.5 text-[10px] font-bold ${statusMeta.text}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${statusMeta.dot}`} />
            {statusMeta.label}
          </span>
          <div className="flex items-center gap-2">
            {isPlaying && onSkip && (
              <button
                type="button"
                onClick={onSkip}
                title="Skip to the next moderator message"
                className="inline-flex items-center gap-1 text-[10px] font-bold text-amber-700 hover:text-amber-900 transition-colors"
              >
                ⏭ Skip
              </button>
            )}
            <button
              type="button"
              onClick={onToggleTranscript}
              aria-expanded={expanded}
              className="text-[10px] font-semibold text-slate-400 hover:text-slate-600 transition-colors"
            >
              {expanded ? "Hide transcript" : "View transcript"}
            </button>
          </div>
        </div>

        {expanded && (
          <p className="mt-2 pt-2 border-t border-amber-200/70 text-[11px] leading-relaxed text-slate-600 whitespace-pre-wrap break-words">
            {transcript}
          </p>
        )}
      </div>

      {/* Always-present transcript for screen readers / accessibility (visually hidden). */}
      <p className="sr-only">Moderator voice message: {transcript}</p>
    </div>
  );
}

// ============================================================
// 🎯 MAIN CHATROOM COMPONENT
// ============================================================
export default function ChatRoom() {
  const { roomId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();

  const userName = useMemo(
    () => new URLSearchParams(location.search).get("userName") || "Anonymous",
    [location.search]
  );
  // Join-time language choice (en | roman_urdu) carried from the join screen.
  const joinLanguage = useMemo(
    () => new URLSearchParams(location.search).get("language") || "",
    [location.search]
  );

  const [messages, setMessages] = useState([]);
  const [ready, setReady] = useState(false);
  const [copied, setCopied] = useState(false);
  const [isLoadingFeedback, setIsLoadingFeedback] = useState(false);
  const [showParticipants, setShowParticipants] = useState(false);
  const [participants, setParticipants] = useState([]);
  const [connectionStatus, setConnectionStatus] = useState("connecting");
  
  // ============================================================
  // 📊 RESEARCH STUDY STATE
  // ============================================================
  const [rankingSubmitted, setRankingSubmitted] = useState(false);
  const [languageWarning, setLanguageWarning] = useState(null);
  const languageWarningTimerRef = useRef(null);
  const processedIdsRef = useRef(new Set());
  const [showItemsPanel, setShowItemsPanel] = useState(() => window.innerWidth > 768);
  const [desertItems, setDesertItems] = useState(() => [...DESERT_ITEMS]);

  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (!roomId) return undefined;
    let cancelled = false;
    const q = encodeURIComponent(roomId);
    fetch(`${API_BASE}/api/desert-items?room_id=${q}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(res.statusText))))
      .then((data) => {
        if (!cancelled && Array.isArray(data.items) && data.items.length > 0) {
          setDesertItems(data.items);
          try {
            sessionStorage.setItem(`room_${roomId}_items`, JSON.stringify(data.items));
          } catch (_) {
            /* ignore quota / private mode */
          }
        }
      })
      .catch(() => {
        if (cancelled) return;
        try {
          const cached = sessionStorage.getItem(`room_${roomId}_items`);
          if (cached) {
            const parsed = JSON.parse(cached);
            if (Array.isArray(parsed) && parsed.length > 0) {
              setDesertItems(parsed);
              return;
            }
          }
        } catch (_) {
          /* ignore */
        }
        setDesertItems([...DESERT_ITEMS]);
      });
    return () => {
      cancelled = true;
    };
  }, [roomId]);

  // Handle responsive panel visibility on screen resize
  useEffect(() => {
    const handleResize = () => {
      const isMobile = window.innerWidth <= 768;
      if (isMobile) {
        setShowItemsPanel(false);
        setShowParticipants(false);
      } else {
        setShowItemsPanel(true);
      }
    };
    window.addEventListener("resize", handleResize);
    // Note: we don't call handleResize() immediately here to avoid overwriting user
    // toggle interactions on mount, since the initial state function already handles it.
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const dismissLanguageWarning = useCallback(() => {
    if (languageWarningTimerRef.current) {
      window.clearTimeout(languageWarningTimerRef.current);
      languageWarningTimerRef.current = null;
    }
    setLanguageWarning(null);
  }, []);

  const showLanguageWarningBanner = useCallback((text) => {
    if (languageWarningTimerRef.current) {
      window.clearTimeout(languageWarningTimerRef.current);
    }
    setLanguageWarning(text);
    languageWarningTimerRef.current = window.setTimeout(() => {
      setLanguageWarning(null);
      languageWarningTimerRef.current = null;
    }, 8000);
  }, []);

  // ============================================================
  // 🔊 LOCAL SEND SOUND
  // ============================================================
  const [sendSound] = useState(() => {
    const audio = new Audio();
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    audio.play = () => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = 523.25;
      osc.connect(gain);
      gain.connect(ctx.destination);
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.1);
      osc.start();
      osc.stop(ctx.currentTime + 0.1);
      return ctx.resume();
    };
    return audio;
  });

  // ============================================================
  // 🔊 MODERATOR VOICE PLAYBACK (auto-play; queue never overlaps)
  // ============================================================
  // Default ON: PTT is the primary interaction, so the moderator is read aloud
  // automatically. The user's first PTT press is the gesture that unlocks audio.
  const [voiceOn, setVoiceOn] = useState(true);
  const [isSpeaking, setIsSpeaking] = useState(false); // drives the "Speaking" status
  const [playingKey, setPlayingKey] = useState(null);  // key of the message currently playing
  // Voice-note presentation state (drives the per-note waveform/status UI):
  const [playback, setPlayback] = useState({ progress: 0, elapsed: 0, duration: 0 }); // current clip
  const [voicePaused, setVoicePaused] = useState(false);  // currently-playing clip is paused
  const [noteStatuses, setNoteStatuses] = useState({});   // msgKey → 'queued'|'playing'|'played'
  const [noteDurations, setNoteDurations] = useState({}); // msgKey → seconds (captured on first play)
  const [expandedTranscripts, setExpandedTranscripts] = useState({}); // msgKey → bool
  const voiceOnRef = useRef(true);           // mirror for the long-lived socket handler
  const audioQueueRef = useRef([]);          // pending FIFO of { key, text }
  const audioPlayingRef = useRef(false);     // a clip is currently playing
  const spokenIdsRef = useRef(new Set());    // message ids already queued (no repeats)
  const ttsCacheRef = useRef(new Map());     // spoken text → blob object URL (skip refetch on replay)
  const ttsPrewarmRef = useRef(new Map());   // spoken text → { promise, controller } for in-flight pre-warm
  const playbackEpochRef = useRef(0);        // bumped on stop/skip to cancel in-flight plays
  const playNextRef = useRef(null);          // latest playNextInQueue, for unlock-time resume

  // ONE reusable <audio> element. Reusing a single element (not new Audio() each time)
  // lets us "unlock" it once on a user gesture so playback works AFTER the async /tts
  // fetch — browsers block play() that isn't tied to a gesture, which is why nothing was
  // audible before. A tiny silent clip played during the first tap blesses the element.
  const audioElRef = useRef(null);
  const audioUnlockedRef = useRef(false);

  const getAudioEl = useCallback(() => {
    if (!audioElRef.current) audioElRef.current = new Audio();
    return audioElRef.current;
  }, []);

  // Set (or clear, with status=null) a voice note's playback status. Stable identity so it
  // can sit in the dependency lists of the queue callbacks without churning them.
  const markNote = useCallback((key, status) => {
    if (!key) return;
    setNoteStatuses((prev) => {
      if (status == null) {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      }
      if (prev[key] === status) return prev;
      return { ...prev, [key]: status };
    });
  }, []);

  // Call from ANY user gesture (mic press, Play/Voice buttons) to enable audio output.
  const unlockAudio = useCallback(() => {
    if (audioUnlockedRef.current) return;
    const el = getAudioEl();
    const finish = () => {
      audioUnlockedRef.current = true;
      console.log("[AUDIO] ✅ audio UNLOCKED — draining any held queue");
      if (playNextRef.current) playNextRef.current();
    };
    try {
      el.src =
        "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";
      const p = el.play();
      if (p && p.then) {
        p.then(() => { try { el.pause(); el.currentTime = 0; } catch (_) {} finish(); })
         .catch(() => { /* autoplay blocked — retry on next gesture */ });
      } else {
        finish();
      }
    } catch (_) { /* ignore */ }
  }, [getAudioEl]);

  // Robust unlock safety-net: the FIRST user interaction anywhere on the page unlocks
  // audio — not just the mic/Play/Voice buttons. This guarantees the queue can never stay
  // deadlocked with audioUnlockedRef=false just because the user happened to click/scroll
  // somewhere else first. unlockAudio() drains any held queue on success and is a no-op
  // once unlocked, so these listeners are pure belt-and-suspenders.
  useEffect(() => {
    if (audioUnlockedRef.current) return undefined;
    const onFirstGesture = () => {
      console.log("[AUDIO] first user gesture → unlocking audio");
      unlockAudio();
    };
    const opts = { passive: true };
    window.addEventListener("pointerdown", onFirstGesture, opts);
    window.addEventListener("keydown", onFirstGesture, opts);
    window.addEventListener("touchstart", onFirstGesture, opts);
    return () => {
      window.removeEventListener("pointerdown", onFirstGesture);
      window.removeEventListener("keydown", onFirstGesture);
      window.removeEventListener("touchstart", onFirstGesture);
    };
  }, [unlockAudio]);

  useEffect(() => {
    voiceOnRef.current = voiceOn;
  }, [voiceOn]);

  // ⏹ Stop ALL audio instantly: pause, reset, clear the queue and all in-flight pre-warm
  // fetches, reset button state. Does NOT clear the TTS blob cache — clips stay reusable.
  const stopAndClearVoice = useCallback(() => {
    playbackEpochRef.current += 1;
    audioQueueRef.current = [];
    // Cancel every in-flight pre-warm request — they're for messages we just discarded.
    for (const { controller } of ttsPrewarmRef.current.values()) {
      try { controller.abort(); } catch (_) { /* ignore */ }
    }
    ttsPrewarmRef.current.clear();
    const el = audioElRef.current;
    if (el) {
      try { el.pause(); el.currentTime = 0; el.onended = null; el.onerror = null; el.ontimeupdate = null; } catch (_) { /* ignore */ }
    }
    audioPlayingRef.current = false;
    setIsSpeaking(false);
    setPlayingKey(null);
    setPlayback({ progress: 0, elapsed: 0, duration: 0 });
    setVoicePaused(false);
    // Drop 'queued'/'playing' badges (those clips are gone) but keep 'played' history so
    // notes that already spoke stay marked. Surviving notes render as tap-to-play.
    setNoteStatuses((prev) => {
      const next = {};
      for (const k in prev) if (prev[k] === "played") next[k] = "played";
      return next;
    });
  }, []);

  // Pre-warm TTS for the SINGLE next clip while the current one plays. Stores the
  // fetch promise in ttsPrewarmRef so playNextInQueue can await it instead of starting
  // a fresh request — hiding TTS latency for every clip after the first.
  //
  // Hard cap of ONE in-flight pre-warm at a time: warming every queued message on
  // arrival (the previous behavior) overlaid many concurrent /tts requests on the
  // backend, starving the independent /stt request on the concurrency-limited dev
  // server and freezing transcription after the first turn. Pipelining one-ahead keeps
  // backend load at ≤1 TTS request — the original, working profile.
  const prewarmTTS = useCallback((cleanText) => {
    if (!cleanText) return;
    if (ttsCacheRef.current.has(cleanText)) return;       // already cached
    if (ttsPrewarmRef.current.has(cleanText)) return;     // already warming
    if (ttsPrewarmRef.current.size >= 1) return;          // cap: one pre-warm at a time
    const controller = new AbortController();
    // Hard cap: if the server hangs, the promise resolves to null and playNextInQueue
    // falls through to a fresh fetch rather than blocking forever. Roman Urdu (slow Uplift
    // + transliteration) needs a generous window so the PRE-WARM actually completes and
    // hides the latency; the old 10s cap aborted it every time, forcing a cold main fetch.
    const prewarmTimeoutMs = joinLanguage === "roman_urdu" ? 75000 : 10000;
    const timeoutId = setTimeout(() => controller.abort(), prewarmTimeoutMs);
    console.log(`[TTS] prewarm START chars=${cleanText.length}`);
    const promise = fetch(`${API_BASE}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: cleanText, room_id: roomId }),
      signal: controller.signal,
    })
      .then(async (res) => {
        clearTimeout(timeoutId);
        console.log(`[TTS] prewarm DONE status=${res.status} ok=${res.ok}`);
        if (!res.ok) return null;
        const blob = await res.blob();
        // A blob smaller than 100 bytes is a server-side error body, not audio.
        // Storing it would permanently cache a bad URL for this text.
        console.log(`[TTS] prewarm blob size=${blob ? blob.size : 0}`);
        if (!blob || blob.size < 100) return null;
        const url = URL.createObjectURL(blob);
        ttsCacheRef.current.set(cleanText, url);  // populate main cache
        return url;
      })
      .catch((err) => { clearTimeout(timeoutId); console.warn(`[TTS] prewarm aborted/failed: ${err?.message || err}`); return null; });  // abort/network → null, fall back to fresh fetch
    ttsPrewarmRef.current.set(cleanText, { promise, controller });
  }, [roomId, joinLanguage]);

  // Play the next queued clip on the single element; chains via onended (no overlap).
  // Hardened against: (1) autoplay lock — if audio isn't unlocked yet we leave the queue
  // intact and bail; unlockAudio() resumes us, so the intro that arrives when 3 join is
  // never lost. (2) stop/skip during the async /tts fetch — an epoch token makes the stale
  // attempt abort without touching shared state. (3) playback/network errors — we advance
  // to the next clip instead of deadlocking. (4) pre-warmed TTS — if a fetch is in-flight
  // from prewarmTTS, we await it instead of starting a duplicate request.
  const playNextInQueue = useCallback(async () => {
    if (audioPlayingRef.current) return;
    if (audioQueueRef.current.length === 0) {
      setIsSpeaking(false);
      setPlayingKey(null);
      return;
    }
    if (!audioUnlockedRef.current) {
      // Browser autoplay policy: audio can't start until a user gesture unlocks it.
      // The queue is preserved; unlockAudio() (first mic/Play tap) resumes it.
      console.log(`[AUDIO] ⏸ queue HELD — audio not unlocked yet (waiting for a user gesture). queueLen=${audioQueueRef.current.length}`);
      setIsSpeaking(false);
      return;
    }
    const item = audioQueueRef.current.shift();
    console.log(`[QUEUE] ▶ dequeued key=${item.key} remaining=${audioQueueRef.current.length}`);
    audioPlayingRef.current = true;
    setIsSpeaking(true);
    setPlayingKey(item.key);
    markNote(item.key, "playing");
    setPlayback({ progress: 0, elapsed: 0, duration: 0 });
    setVoicePaused(false);
    const epoch = playbackEpochRef.current;
    const t0 = performance.now();

    // One-shot advance: called by onended, onerror, AND the catch block.
    // Hoisted here so both the DOM event path and the exception path share the
    // same fired flag — prevents double-calls that corrupt queue state or clear
    // handlers registered by the next in-flight playNextInQueue call.
    let advanceFired = false;
    let elForAdvance = null;
    const advance = (reason) => {
      if (advanceFired) return;
      advanceFired = true;
      console.log(`[QUEUE] advance(${reason}) key=${item.key} → draining; queueLen=${audioQueueRef.current.length}`);
      if (elForAdvance) { elForAdvance.onended = null; elForAdvance.onerror = null; elForAdvance.ontimeupdate = null; }
      audioPlayingRef.current = false;
      setPlayingKey(null);
      setPlayback({ progress: 0, elapsed: 0, duration: 0 });
      if (reason === "error") {
        // Evict the cached URL so the next attempt fetches fresh audio instead of
        // replaying a corrupt blob. Clear the badge so the note shows as tap-to-play.
        markNote(item.key, null);
        const cachedUrl = ttsCacheRef.current.get(item.text);
        if (cachedUrl && cachedUrl.startsWith("blob:")) {
          ttsCacheRef.current.delete(item.text);
          try { URL.revokeObjectURL(cachedUrl); } catch (_) { /* ignore */ }
        }
      } else {
        markNote(item.key, "played");
        const dur = elForAdvance && isFinite(elForAdvance.duration) ? elForAdvance.duration : 0;
        if (dur) setNoteDurations((prev) => (prev[item.key] === dur ? prev : { ...prev, [item.key]: dur }));
      }
      playNextInQueue();
    };

    try {
      let url = ttsCacheRef.current.get(item.text);
      if (url) {
        console.log(`[TTS] cache HIT (client blob) key=${item.key}`);
      }
      if (!url) {
        // Reuse an in-flight pre-warm promise if one exists (started while prev clip played)
        const prewarm = ttsPrewarmRef.current.get(item.text);
        if (prewarm) {
          console.log(`[TTS] awaiting in-flight prewarm key=${item.key}`);
          url = await prewarm.promise;
          ttsPrewarmRef.current.delete(item.text);
          console.log(`[TTS] prewarm resolved key=${item.key} url=${url ? "ok" : "null"}`);
        }
      }
      if (!url) {
        console.log(`[TTS] fetch START key=${item.key} chars=${item.text.length}`);
        // Hard timeout so a slow/hung backend can NEVER strand playback. The prewarm
        // (10s) and STT (40s) already do this; the main fetch previously had none, so a
        // slow cold synthesis (e.g. Roman Urdu via Uplift) left the clip silent forever.
        // On timeout we throw → advance("error"), and the note stays tap-to-play.
        const ttsController = new AbortController();
        // Roman Urdu (Uplift + Urdu-script transliteration) can take tens of seconds for a
        // long line — too slow for the 25s English cap, which was aborting mid-synthesis
        // ("signal is aborted without reason"). Give the Urdu path a generous window; keep
        // English (OpenAI, ~1s) fast-fail. This is the safety net; the pre-warm usually wins.
        const ttsFetchTimeoutMs = joinLanguage === "roman_urdu" ? 75000 : 25000;
        const ttsTimeout = setTimeout(() => ttsController.abort(), ttsFetchTimeoutMs);
        let res;
        try {
          res = await fetch(`${API_BASE}/tts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: item.text, room_id: roomId }),
            signal: ttsController.signal,
          });
        } finally {
          clearTimeout(ttsTimeout);
        }
        console.log(`[TTS] fetch DONE key=${item.key} status=${res.status} ok=${res.ok}`);
        if (!res.ok) throw new Error(`TTS ${res.status}`);
        const blob = await res.blob();
        console.log(`[TTS] blob key=${item.key} size=${blob ? blob.size : 0} type=${blob ? blob.type : "-"}`);
        if (!blob || blob.size < 100) throw new Error("TTS returned empty audio");
        url = URL.createObjectURL(blob);
        console.log(`[AUDIO] objectURL created key=${item.key}`);
        ttsCacheRef.current.set(item.text, url);
      }
      if (epoch !== playbackEpochRef.current) {
        console.log(`[QUEUE] stale epoch — abandoning key=${item.key} (stop/skip happened)`);
        return;
      }
      console.log(`[TTS] ready key=${item.key} in ${Math.round(performance.now() - t0)}ms`);
      const el = getAudioEl();
      elForAdvance = el;
      el.src = url;
      el.onended = () => { console.log(`[AUDIO] onended key=${item.key}`); advance("ended"); };
      el.onerror = () => { console.warn(`[AUDIO] onerror key=${item.key} code=${el.error ? el.error.code : "?"}`); advance("error"); };
      // Drive the voice-note waveform fill + elapsed/duration readout (~4 Hz).
      el.ontimeupdate = () => {
        const d = isFinite(el.duration) ? el.duration : 0;
        const ct = el.currentTime || 0;
        setPlayback({ progress: d ? Math.min(1, ct / d) : 0, elapsed: ct, duration: d });
      };
      console.log(`[AUDIO] play() called key=${item.key} unlocked=${audioUnlockedRef.current}`);
      try { audioManager.stop(); } catch (_) {}
      await el.play();
      console.log(`[AUDIO] play() resolved — audio started key=${item.key}`);
      // Pipeline: now that this clip is playing, warm the NEXT queued clip (one only,
      // enforced by prewarmTTS's cap) so its audio is ready the moment this one ends.
      const next = audioQueueRef.current[0];
      if (next) prewarmTTS(next.text);
    } catch (e) {
      if (epoch !== playbackEpochRef.current) return;
      console.warn(`[AUDIO] play/fetch REJECTED key=${item.key}:`, e?.message || e);
      advance("error");
    }
  }, [roomId, getAudioEl, prewarmTTS, markNote, joinLanguage]);

  // Keep a ref to the latest playNextInQueue so unlockAudio (defined above) can resume the
  // queue after the first gesture without a forward reference.
  useEffect(() => {
    playNextRef.current = playNextInQueue;
  }, [playNextInQueue]);

  // ⏭ Skip the current clip and immediately play the next queued one (queue preserved).
  const skipCurrent = useCallback(() => {
    playbackEpochRef.current += 1;
    const el = audioElRef.current;
    if (el) {
      try { el.pause(); el.currentTime = 0; el.onended = null; el.onerror = null; el.ontimeupdate = null; } catch (_) { /* ignore */ }
    }
    // The manually-paused clip won't fire onended, so mark it played here.
    setPlayingKey((cur) => { if (cur) markNote(cur, "played"); return null; });
    audioPlayingRef.current = false;
    setPlayback({ progress: 0, elapsed: 0, duration: 0 });
    setVoicePaused(false);
    playNextInQueue();
  }, [playNextInQueue, markNote]);

  const enqueueModeratorSpeech = useCallback((key, rawText) => {
    const clean = toSpeechText(rawText);
    if (!clean) {
      console.log(`[QUEUE] skip key=${key} — empty after toSpeechText`);
      return;
    }
    if (audioQueueRef.current.some(item => item.text === clean)) {
      console.log(`[QUEUE] skip key=${key} — identical text already queued`);
      return;
    }
    audioQueueRef.current.push({ key, text: clean });
    console.log(`[QUEUE] enqueued key=${key} len=${audioQueueRef.current.length} chars=${clean.length}`);
    markNote(key, "queued");
    // Kick off TTS synthesis the INSTANT this message enters the queue — before the
    // playback state bookkeeping and the message-list re-render — so the audio request is
    // already in flight at the earliest possible moment. This matters most for the common
    // case: a single moderator reply arriving while the system is idle (every turn of a
    // normal back-and-forth). playNextInQueue then awaits this in-flight fetch instead of
    // starting its own, so there is no duplicate request and no extra wait.
    //   • Idle  → this is the message about to play; synthesis starts now.
    //   • Busy  → this is the next-to-play clip; it warms while the current one finishes.
    // The one-at-a-time cap inside prewarmTTS still bounds backend load to ≤1 concurrent
    // /tts request, preserving the fix that keeps /stt (transcription) from being starved.
    prewarmTTS(clean);
    playNextInQueue();
  }, [playNextInQueue, prewarmTTS, markNote]);

  // ▶ Play a specific moderator message NOW (clears the queue, stops current). The click
  // is a user gesture, so it also unlocks audio for subsequent auto-play.
  const playModeratorMessage = useCallback((key, rawText) => {
    unlockAudio();
    playbackEpochRef.current += 1;           // cancel any in-flight fetch for old epoch
    const el = audioElRef.current;
    if (el) {
      try { el.pause(); el.currentTime = 0; el.onended = null; el.onerror = null; el.ontimeupdate = null; } catch (_) { /* ignore */ }
    }
    audioQueueRef.current = [];
    audioPlayingRef.current = false;
    setPlayback({ progress: 0, elapsed: 0, duration: 0 });
    // Replaying clears the previous queue, so drop other transient badges (keep 'played').
    setNoteStatuses((prev) => {
      const next = {};
      for (const k in prev) if (prev[k] === "played") next[k] = "played";
      return next;
    });
    enqueueModeratorSpeech(key, rawText);
  }, [unlockAudio, enqueueModeratorSpeech]);

  // Expand/collapse a voice note's transcript (debug + accessibility disclosure).
  const toggleTranscript = useCallback((key) => {
    setExpandedTranscripts((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // Pause/resume the clip that is currently playing (the shared audio element). Safe: it
  // doesn't touch src/epoch/queue, so onended still advances once the clip finishes.
  const togglePlayPauseCurrent = useCallback(() => {
    const el = audioElRef.current;
    if (!el) return;
    if (el.paused) {
      try { audioManager.stop(); } catch (_) {}
      el.play().then(() => setVoicePaused(false)).catch(() => {});
    } else {
      el.pause();
      setVoicePaused(true);
    }
  }, []);

  // Voice-note tap handler: resume/pause the active note, or play a different one now.
  const handleVoiceNoteTap = useCallback((key, rawText) => {
    if (playingKey === key) {
      togglePlayPauseCurrent();
    } else {
      playModeratorMessage(key, rawText);
    }
  }, [playingKey, togglePlayPauseCurrent, playModeratorMessage]);

  // ▶ Play the ORIGINAL recording for a voice message (participant playback).
  const playbackAudioRef = useRef(null);
  const playVoiceMessage = useCallback((messageId) => {
    unlockAudio();
    if (!messageId) return;
    if (playbackAudioRef.current) {
      try { playbackAudioRef.current.pause(); } catch (_) { /* ignore */ }
      playbackAudioRef.current = null;
    }
    try {
      const audio = new Audio(`${API_BASE}/api/message/${messageId}/audio`);
      playbackAudioRef.current = audio;
      audio.play().catch((e) => console.warn("🔇 Voice playback failed:", e?.message || e));
    } catch (e) {
      console.warn("🔇 Voice playback error:", e?.message || e);
    }
  }, [unlockAudio]);

  // Stop audio + free blob URLs on unmount
  useEffect(() => stopAndClearVoice, [stopAndClearVoice]);

  // Pause/stop moderator audio when a user voice message is played
  useEffect(() => {
    const handleOtherAudioPlay = () => {
      stopAndClearVoice();
    };
    audioManager.registerOnPlayCallback(handleOtherAudioPlay);
    return () => {
      audioManager.unregisterOnPlayCallback(handleOtherAudioPlay);
    };
  }, [stopAndClearVoice]);

  // Revoke every cached TTS blob URL on unmount (the cache, not playback, owns them now).
  useEffect(() => {
    const cache = ttsCacheRef.current;
    return () => {
      for (const url of cache.values()) {
        try { URL.revokeObjectURL(url); } catch (_) { /* ignore */ }
      }
      cache.clear();
    };
  }, []);

  // ============================================================
  // 💬 SEND A TURN (shared by the voice path; broadcast + attribution unchanged)
  // ============================================================
  // Emits to the SAME send_message pipeline as before. The spoken turn shows up
  // as an attributed, read-only transcript entry like any other message.
  // `voice` (optional): { audioToken, durationMs, transcript } — when present the turn
  // is tagged as voice so the server links its staged audio to this message at send time.
  const sendMessageText = useCallback((rawText, voice) => {
    const trimmed = (rawText || "").trim();
    if (!trimmed || !ready) return;

    sendSound.play().catch(() => {});

    const tempId = `temp:${userName}:${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      {
        id: tempId,
        _optimistic: true,
        sender: userName,
        message: trimmed,
        timestamp: new Date().toISOString(),
      },
    ]);

    const payload = { room_id: roomId, message: trimmed, sender: userName };
    if (voice) {
      payload.metadata = {
        input_mode: "voice",
        stt_model: "gpt-4o-mini-transcribe",
        mime_type: "audio/webm",
        ...(voice.audioToken ? { audio_token: voice.audioToken } : {}),
        ...(Number.isFinite(voice.durationMs) ? { duration_ms: Math.round(voice.durationMs) } : {}),
        ...(voice.transcript ? { transcript_text: voice.transcript } : {}),
        ...(voice.language ? { language: voice.language } : {}),
        ...(Number.isFinite(voice.confidence) ? { confidence: voice.confidence } : {}),
        roman_transcript: voice.romanTranscript || trimmed,
      };
    }
    socket.emit("send_message", payload);
  }, [roomId, userName, ready, sendSound]);

  // ============================================================
  // 🎤 PUSH-TO-TALK (press & hold → record webm → release → auto-send via /stt)
  // ============================================================
  const [isRecording, setIsRecording] = useState(false); // "Listening"
  const [sttBusy, setSttBusy] = useState(false);          // "Thinking"
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const audioChunksRef = useRef([]);
  const pttHeldRef = useRef(false); // true while the button is held (survives mic warmup)
  const recordStartRef = useRef(0); // ms timestamp when recording began (for duration_ms)

  const stopMediaStream = useCallback(() => {
    if (mediaStreamRef.current) {
      try { mediaStreamRef.current.getTracks().forEach((t) => t.stop()); } catch (_) { /* ignore */ }
      mediaStreamRef.current = null;
    }
  }, []);

  // POST the recorded blob to /stt and immediately send the transcript (no edit step).
  // The server returns an audio_token for the staged recording; we pass it (plus the
  // measured duration and raw transcript) so the send links the audio to this message.
  const transcribeAndSend = useCallback(async (blob, durationMs) => {
    setSttBusy(true);
    // Hard client-side timeout so a hung /stt request can NEVER strand the UI in
    // "Transcribing your turn…". 40s comfortably covers a slow-but-real transcription
    // (server bounds its own OpenAI call), while guaranteeing the finally always runs so
    // the mic frees up. On abort we surface a retry prompt instead of a silent freeze.
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 40000);
    try {
      const form = new FormData();
      form.append("file", blob, "recording.webm");
      if (roomId) form.append("room_id", roomId);
      // Language hint (en | ur) from room choice -> constrains Whisper to avoid auto-translating to English
      const sttLang = (joinLanguage === "roman_urdu" || joinLanguage === "ur") ? "ur" : joinLanguage === "en" ? "en" : "ur";
      form.append("language", sttLang);
      const res = await fetch(`${API_BASE}/stt`, { method: "POST", body: form, signal: controller.signal });
      if (!res.ok) throw new Error(`STT ${res.status}`);
      const data = await res.json();
      // `text` is the server-normalized Roman Urdu (or English); `raw_text` is the
      // faithful, unmodified STT output we preserve for research fidelity.
      const text = (data && data.text ? String(data.text) : "").trim();
      const rawText = (data && data.raw_text ? String(data.raw_text) : text).trim();
      if (text) {
        // Defensive: server already normalizes to Latin, but re-romanize in case the
        // LLM pass was skipped/failed so no Urdu script ever reaches the chat.
        const romanTranscript = romanizeUrdu(text);
        sendMessageText(romanTranscript, {
          audioToken: data && data.audio_token ? String(data.audio_token) : undefined,
          durationMs,
          transcript: rawText,
          romanTranscript,
          language: data && data.language ? String(data.language) : undefined,
          confidence: data && typeof data.confidence === "number" ? data.confidence : undefined,
        });
      } else {
        showLanguageWarningBanner("Couldn't catch that — hold the mic and try again.");
      }
    } catch (err) {
      if (err?.name === "AbortError") {
        console.warn("STT timed out after 40s");
        showLanguageWarningBanner("Transcription is taking too long — please hold the mic and try again.");
      } else {
        console.warn("STT failed:", err?.message || err);
        showLanguageWarningBanner("Transcription failed — please hold the mic and try again.");
      }
    } finally {
      clearTimeout(timeoutId);
      setSttBusy(false);
    }
  }, [sendMessageText, showLanguageWarningBanner, joinLanguage]);

  const startRecording = useCallback(async () => {
    if (isRecording || sttBusy) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      showLanguageWarningBanner("Voice input isn't supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      mediaStreamRef.current = stream;
      // Pick an explicit, supported codec so MediaRecorder never falls back to a
      // type the server can't decode. Prefer Opus, then plain webm.
      const preferredTypes = ["audio/webm;codecs=opus", "audio/webm"];
      const chosenType =
        typeof MediaRecorder.isTypeSupported === "function"
          ? preferredTypes.find((t) => MediaRecorder.isTypeSupported(t))
          : undefined;
      // 32 kbps Opus is plenty for speech and keeps the upload small → faster STT.
      const opts = chosenType
        ? { mimeType: chosenType, audioBitsPerSecond: 32000 }
        : { audioBitsPerSecond: 32000 };
      const recorder = new MediaRecorder(stream, opts);
      audioChunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        stopMediaStream();
        const blobType = recorder.mimeType || chosenType || "audio/webm";
        const blob = new Blob(audioChunksRef.current, { type: blobType });
        audioChunksRef.current = [];
        const durationMs = recordStartRef.current ? Date.now() - recordStartRef.current : null;
        recordStartRef.current = 0;
        setIsRecording(false);
        // A header-only / empty capture (first-press warmup, instant taps) is a
        // few hundred bytes and reaches /stt as a "corrupt" file. Real Opus
        // speech comfortably exceeds this floor — reject anything smaller.
        if (blob.size < 200) {
          showLanguageWarningBanner("Recording too short — hold the mic and speak.");
          return;
        }
        transcribeAndSend(blob, durationMs);
      };
      mediaRecorderRef.current = recorder;
      // No timeslice: deliver ONE complete, properly-finalized WebM on stop().
      // A timeslice can cut mid-cluster on a short release, yielding a structurally
      // incomplete file that OpenAI rejects as "corrupted or unsupported".
      recorder.start();
      recordStartRef.current = Date.now();
      setIsRecording(true);
      // If the user already released during mic warmup, stop right away.
      if (!pttHeldRef.current) {
        try { recorder.stop(); } catch (_) { /* ignore */ }
        mediaRecorderRef.current = null;
      }
    } catch (err) {
      console.warn("Microphone access denied:", err?.name || err);
      setIsRecording(false);
      stopMediaStream();
      showLanguageWarningBanner("Microphone access was blocked. Allow it in your browser.");
    }
  }, [isRecording, sttBusy, showLanguageWarningBanner, stopMediaStream, transcribeAndSend]);

  const stopRecording = useCallback(() => {
    const rec = mediaRecorderRef.current;
    if (rec && rec.state !== "inactive") {
      try { rec.stop(); } catch (_) { /* ignore */ }
    }
    mediaRecorderRef.current = null;
  }, []);

  // Press-and-hold via pointer events (works for mouse + touch). Pointer capture
  // keeps the release (up) firing on the button even if the finger drifts off it.
  const handlePttDown = useCallback((e) => {
    e.preventDefault();
    if (!ready || sttBusy) return;
    unlockAudio(); // first mic press unlocks audio output for moderator playback
    pttHeldRef.current = true;
    try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch (_) { /* ignore */ }
    startRecording();
  }, [ready, sttBusy, startRecording, unlockAudio]);

  const handlePttUp = useCallback((e) => {
    e.preventDefault();
    if (!pttHeldRef.current) return;
    pttHeldRef.current = false;
    try { e.currentTarget.releasePointerCapture?.(e.pointerId); } catch (_) { /* ignore */ }
    stopRecording();
  }, [stopRecording]);

  // Release mic if the user navigates away mid-recording
  useEffect(() => {
    return () => {
      const rec = mediaRecorderRef.current;
      if (rec && rec.state !== "inactive") {
        try { rec.stop(); } catch (_) { /* ignore */ }
      }
      stopMediaStream();
    };
  }, [stopMediaStream]);

  // ============================================================
  // ⚡ SOCKET CONNECTION & MESSAGES
  // ============================================================
  useEffect(() => {
    if (!roomId || !userName) return;

    setConnectionStatus("connecting");

    // ── named handlers so teardown only removes THIS effect's listeners,
    //    not the global ones registered in socket.js (heartbeat, upgrade log).
    const onConnect = () => {
      setConnectionStatus("connected");
      socket.emit("join_room", { room_id: roomId, user_name: userName, language: joinLanguage });
    };
    const onDisconnect = () => setConnectionStatus("disconnected");
    const onConnectError = () => setConnectionStatus("error");

    const onJoinedRoom = () => {
      setReady(true);
      setConnectionStatus("connected");
      setParticipants(prev => prev.includes(userName) ? prev : [...prev, userName]);
      // Best-effort: try to unlock audio now. If the user's "Join" click left a sticky
      // activation on this SPA document, the silent-clip play() resolves and the intro can
      // autoplay without waiting for a separate gesture. If there's no activation, this is
      // a harmless no-op (play() rejects, audioUnlockedRef stays false) and the first
      // mic/Play tap still unlocks. Never blocks and never changes queue logic.
      console.log("[AUDIO] joined_room → attempting audio unlock");
      unlockAudio();
    };

    const onChatHistory = (data) => {
      const list = data.chat_history || [];
      processedIdsRef.current = new Set();
      for (const m of list) {
        const mid = m.id != null ? String(m.id) : `${m.sender}|${m.message}|${m.timestamp}`;
        processedIdsRef.current.add(mid);
      }
      setMessages(list);
      setParticipants(data.participants || [userName]);
    };

    const onReceiveMessage = (data) => {
      // Auto-speak every live Moderator turn when voice is on. toSpeechText strips
      // HTML/markdown so the task-intro card is read as clean plain text. The sid here
      // is the canonical msgKey so the voice-note status UI lines up with the queue.
      if (data && data.sender === "Moderator") {
        const sid = msgKey(data);
        console.log(`[VOICE] moderator msg received sid=${sid} voiceOn=${voiceOnRef.current} alreadySpoken=${spokenIdsRef.current.has(sid)} audioUnlocked=${audioUnlockedRef.current}`);
        if (voiceOnRef.current && !spokenIdsRef.current.has(sid)) {
          spokenIdsRef.current.add(sid);
          // The server may send a separate `speak_text` (e.g. the Roman-Urdu task intro)
          // when what should be SPOKEN differs from the displayed message (the English task
          // card). Fall back to the message text for every normal moderator turn.
          enqueueModeratorSpeech(sid, data.speak_text || data.message);
        } else {
          console.log(`[VOICE] NOT speaking sid=${sid} (muted or duplicate)`);
        }
      }

      setMessages((prev) => {
        const mid =
          data.id != null
            ? String(data.id)
            : `${data.sender}|${data.message}|${data.timestamp || ""}`;

        // Replace an optimistic bubble with the confirmed server message
        const optIdx = prev.findIndex(
          (msg) =>
            msg._optimistic &&
            msg.sender === data.sender &&
            msg.message === data.message
        );
        if (optIdx >= 0) {
          if (processedIdsRef.current.has(mid)) return prev;
          processedIdsRef.current.add(mid);
          const next = [...prev];
          next[optIdx] = { ...data, timestamp: data.timestamp || next[optIdx].timestamp };
          return next;
        }

        if (processedIdsRef.current.has(mid)) {
          // A flagged update may arrive for a message we already have — patch it in-place
          if (data.flagged) {
            const idx = prev.findIndex(
              (msg) =>
                String(msg.id) === mid ||
                (msg.sender === data.sender && msg.message === data.message)
            );
            if (idx >= 0) {
              const next = [...prev];
              next[idx] = { ...next[idx], ...data };
              return next;
            }
          }
          console.log("⚠️ Duplicate message ignored:", mid);
          return prev;
        }

        processedIdsRef.current.add(mid);
        // Bound the seen-set size to avoid unbounded memory growth over a long session
        if (processedIdsRef.current.size > 800) {
          processedIdsRef.current = new Set(
            Array.from(processedIdsRef.current).slice(-400)
          );
        }

        return [...prev, { ...data, timestamp: data.timestamp || new Date().toISOString() }];
      });
    };

    const onLanguageWarning = (data) => {
      if (data?.type === "language_warning" && data.message) {
        showLanguageWarningBanner(data.message);
      }
    };

    const onParticipantsUpdate = (data) => setParticipants(data.participants || []);

    const onRankingSubmitted = (data) => {
      if (data.success) {
        setRankingSubmitted(true);
        const successId = `local-ranking-ok-${Date.now()}`;
        processedIdsRef.current.add(successId);
        setMessages((prev) => [
          ...prev,
          {
            id: successId,
            sender: "System",
            message: "✅ Final ranking recorded (from your discussion or end of session).",
            timestamp: new Date().toISOString(),
          },
        ]);
      } else {
        alert("❌ Failed to submit ranking: " + data.message);
      }
    };

    const onSessionEnded = (data) => {
      console.log("📨 Session ended with data:", data);
      const intended = data?.username;
      if (intended && intended !== userName) return;
      navigate("/feedback", {
        state: {
          feedback: data?.feedback || "Session ended. Thank you for participating!",
          room_id: data?.room_id,
          studentName: userName,
          targetUsername: intended || userName,
        },
      });
      setIsLoadingFeedback(false);
    };

    socket.on("connect",            onConnect);
    socket.on("disconnect",         onDisconnect);
    socket.on("connect_error",      onConnectError);
    socket.on("joined_room",        onJoinedRoom);
    socket.on("chat_history",       onChatHistory);
    socket.on("receive_message",    onReceiveMessage);
    socket.on("language_warning",   onLanguageWarning);
    socket.on("warning_message",    onLanguageWarning);
    socket.on("participants_update",onParticipantsUpdate);
    socket.on("ranking_submitted",  onRankingSubmitted);
    socket.on("session_ended",      onSessionEnded);

    // Join immediately if already connected; otherwise wait for the connect event.
    if (socket.connected) {
      socket.emit("join_room", { room_id: roomId, user_name: userName, language: joinLanguage });
    } else {
      socket.connect();
    }

    return () => {
      if (languageWarningTimerRef.current) {
        window.clearTimeout(languageWarningTimerRef.current);
        languageWarningTimerRef.current = null;
      }
      // Remove only THIS effect's handlers — the global ones in socket.js are preserved.
      socket.off("connect",            onConnect);
      socket.off("disconnect",         onDisconnect);
      socket.off("connect_error",      onConnectError);
      socket.off("joined_room",        onJoinedRoom);
      socket.off("chat_history",       onChatHistory);
      socket.off("receive_message",    onReceiveMessage);
      socket.off("language_warning",   onLanguageWarning);
      socket.off("warning_message",    onLanguageWarning);
      socket.off("participants_update",onParticipantsUpdate);
      socket.off("ranking_submitted",  onRankingSubmitted);
      socket.off("session_ended",      onSessionEnded);
    };
  }, [roomId, userName, navigate, showLanguageWarningBanner, enqueueModeratorSpeech, unlockAudio]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ============================================================
  // 🏁 END SESSION
  // ============================================================
  const endSession = () => {
    if (window.confirm("Are you sure you want to end this session? All participants will receive feedback.")) {
      setIsLoadingFeedback(true);
      socket.emit("end_session", { room_id: roomId, sender: userName });
    }
  };

  // ============================================================
  // 📊 RANKING MODAL COMPONENT
  // ============================================================
  // Calculate online count
  const onlineCount = Math.max(participants.length, 1);

  // Minimal PTT status: Idle / Listening / Thinking / Speaking
  const sessionStatus = isRecording
    ? "Listening"
    : sttBusy
    ? "Thinking"
    : isSpeaking
    ? "Speaking"
    : "Idle";

  return (
    <div className="flex flex-col h-screen bg-slate-50 font-body overflow-hidden select-none">
      {/* ⚠️ SYSTEM WARNING BANNERS */}
      {languageWarning && (
        <div
          className="fixed top-6 left-1/2 -translate-x-1/2 z-[60] max-w-lg w-[calc(100%-2rem)] rounded-2xl border-l-4 border-amber-500 border border-amber-200 bg-amber-50/95 backdrop-blur-md px-4 py-3.5 shadow-xl animate-float"
          role="alert"
        >
          <div className="flex items-start gap-3">
            <MdWarning className="text-amber-600 flex-shrink-0 mt-0.5" size={20} />
            <div className="flex-1">
              <h4 className="font-bold text-xs text-amber-950 uppercase tracking-wider mb-0.5">Moderator Notice</h4>
              <p className="text-xs text-amber-900 leading-relaxed font-medium">{languageWarning}</p>
            </div>
            <button
              type="button"
              onClick={dismissLanguageWarning}
              className="flex-shrink-0 text-amber-500 hover:text-amber-850 text-base font-bold px-1"
              aria-label="Dismiss warning"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* 🎪 TOPBAR NAVIGATION */}
      <div className="bg-white/90 backdrop-blur-md border-b border-slate-200/80 z-30 transition-all duration-300">
        <div className="px-4 py-3 md:px-6 flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-violet-650 flex items-center justify-center text-white shadow-md shadow-indigo-100">
              <MdChat className="text-lg" />
            </div>
            <div>
              <h1 className="font-bold text-sm md:text-base text-slate-800 tracking-tight leading-tight">
                Desert Survival Discussion
              </h1>
              <div className="flex flex-wrap items-center gap-2 text-[11px] mt-0.5">
                <span className="font-semibold text-slate-450 uppercase tracking-wider">Room:</span>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(roomId);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  }}
                  className="font-mono bg-slate-100 hover:bg-slate-200 text-slate-700 px-1.5 py-0.5 rounded border border-slate-200 transition-colors flex items-center gap-1 cursor-pointer"
                  title="Click to copy Room ID"
                >
                  <span>{roomId.length > 10 ? `${roomId.substring(0, 6)}...${roomId.substring(roomId.length - 4)}` : roomId}</span>
                  {copied ? <MdCheck size={11} className="text-emerald-600" /> : <MdContentCopy size={10} />}
                </button>
                
                <span className="text-slate-300">|</span>

                <div className="flex items-center gap-1 bg-slate-50 px-2 py-0.5 rounded-full border border-slate-150">
                  <span className="pulse-green">
                    <span className="pulse-green-ping"></span>
                    <span className="pulse-green-dot"></span>
                  </span>
                  <span className="text-slate-600 font-semibold">{onlineCount}/3 online</span>
                </div>

                {rankingSubmitted && (
                  <span className="badge badge-success text-[10px]">Ranking Recorded</span>
                )}

                {connectionStatus === "disconnected" && (
                  <span className="badge badge-danger text-[10px]">Offline</span>
                )}
              </div>
            </div>
          </div>
          
          <div className="flex items-center gap-2 overflow-x-auto whitespace-nowrap max-w-full pb-1 md:pb-0 scrollbar-none">
            <button
              onClick={() => setShowItemsPanel(!showItemsPanel)}
              className={`px-3 py-1.5 rounded-xl font-bold text-xs border transition-all flex items-center gap-1.5 ${
                showItemsPanel 
                  ? 'bg-indigo-50 text-indigo-700 border-indigo-200' 
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}
            >
              <span>Items Panel</span>
            </button>

            {/* 🔊 Global Moderator Voice toggle — segmented Voice / Muted (voice-first). */}
            <div
              className="flex items-center rounded-xl border border-slate-200 bg-white overflow-hidden text-xs font-bold"
              role="group"
              aria-label="Moderator voice"
            >
              <button
                onClick={() => {
                  unlockAudio();          // gesture: enable audio output
                  setVoiceOn(true);
                }}
                aria-pressed={voiceOn}
                title="Moderator speaks automatically"
                className={`px-3 py-1.5 flex items-center gap-1.5 transition-all ${
                  voiceOn ? 'bg-amber-500 text-white' : 'text-slate-500 hover:bg-slate-50'
                }`}
              >
                <MdVolumeUp size={15} />
                <span>Voice</span>
              </button>
              <button
                onClick={() => {
                  setVoiceOn(false);
                  stopAndClearVoice();    // muting stops playback + clears the queue
                }}
                aria-pressed={!voiceOn}
                title="Mute the moderator (notes stay tappable)"
                className={`px-3 py-1.5 flex items-center gap-1.5 transition-all border-l border-slate-200 ${
                  !voiceOn ? 'bg-slate-700 text-white' : 'text-slate-500 hover:bg-slate-50'
                }`}
              >
                <MdVolumeOff size={15} />
                <span>Muted</span>
              </button>
            </div>

            {/* ⏭ Skip — stays available while the moderator is speaking. */}
            {isSpeaking && (
              <button
                onClick={skipCurrent}
                className="px-3 py-1.5 rounded-xl font-bold text-xs border bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100 transition-all flex items-center gap-1.5"
                title="Skip current clip and play next queued message"
              >
                <span>⏭ Skip</span>
              </button>
            )}

            <button
              onClick={() => setShowParticipants(!showParticipants)}
              className={`p-2 rounded-xl border transition-all ${
                showParticipants
                  ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
                  : 'bg-white text-slate-650 border-slate-200 hover:bg-slate-50'
              }`}
              title="Participants drawer"
            >
              <MdPerson size={18} />
            </button>

            <button
              onClick={endSession}
              disabled={isLoadingFeedback}
              className="px-3.5 py-2 bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-600 hover:text-rose-700 rounded-xl font-bold text-xs flex items-center gap-1.5 transition-all duration-200 disabled:opacity-50"
            >
              <MdExitToApp size={14} />
              <span>Leave Room</span>
            </button>
          </div>
        </div>
      </div>

      {/* 📱 WORKSPACE WRAPPER */}
      <div className="flex flex-1 overflow-hidden relative">
        
        {/* Drawer backdrop for mobile screens */}
        {(showItemsPanel || showParticipants) && (
          <div 
            className="fixed inset-0 bg-slate-900/30 backdrop-blur-sm z-40 md:hidden"
            onClick={() => {
              setShowItemsPanel(false);
              setShowParticipants(false);
            }}
          />
        )}
        
        {/* 🏜️ LEFT DRAWER: Desert items references */}
        <aside
          style={{ backgroundColor: '#ffffff' }}
          className={`fixed md:static left-0 top-0 md:top-16 bottom-0 w-80 max-w-[85vw] bg-white border-r border-slate-200 shadow-xl md:shadow-none z-50 flex flex-col transition-all duration-300 ${
            showItemsPanel ? "translate-x-0 opacity-100" : "-translate-x-full md:-ml-80 opacity-0"
          }`}
        >
          <div className="p-4 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between">
            <div>
              <h3 className="font-bold text-slate-800 text-sm">Desert Survival Reference</h3>
              <p className="text-[10px] text-slate-400 font-semibold tracking-wider uppercase mt-0.5">Rank Importance (1 to 12)</p>
            </div>
            <button
              type="button"
              onClick={() => setShowItemsPanel(false)}
              className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 p-1.5 rounded-lg text-lg leading-none"
              aria-label="Hide items panel"
            >
              ×
            </button>
          </div>
          
          <div className="flex-1 overflow-y-auto p-4 space-y-2.5">
            {desertItems.map((item, idx) => (
              <div 
                key={`${idx}-${item}`} 
                className="p-3 bg-slate-50 border border-slate-200/60 rounded-xl text-xs text-slate-800 font-medium hover:border-indigo-150 hover:bg-white transition-all duration-200 shadow-[0_2px_8px_rgba(0,0,0,0.01)] flex items-start gap-2.5 group"
              >
                <span className="w-5 h-5 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center font-bold text-indigo-600 text-[10px] flex-shrink-0 group-hover:bg-indigo-600 group-hover:text-white transition-colors duration-250">
                  {idx + 1}
                </span>
                <span className="leading-relaxed">{item}</span>
              </div>
            ))}
          </div>

          <div className="p-4 border-t border-slate-100 bg-amber-50/30">
            <h4 className="text-[11px] font-bold text-amber-800 mb-1">💬 Consensus Agreement:</h4>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              Agree out loud on your full order, from <span className="font-mono bg-amber-50/80 px-1 border border-amber-100 text-amber-900 rounded font-bold">1 (most important)</span> through <span className="font-mono bg-amber-50/80 px-1 border border-amber-100 text-amber-900 rounded font-bold">12 (least)</span>. The moderator listens to your discussion and records the group's final ranking.
            </p>
          </div>
        </aside>

        {/* 💬 MAIN CHAT SCREEN */}
        <div className="flex-1 flex flex-col overflow-hidden min-w-0 bg-white">
          
          {/* Scrollable messages log */}
          <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 select-text">
            {messages.length === 0 ? (
              <div className="h-full flex items-center justify-center p-4">
                <div className="text-center max-w-md animate-slide-up">
                  <div className="w-16 h-16 rounded-2xl bg-indigo-50 border border-indigo-100 flex items-center justify-center mx-auto mb-5 text-indigo-500">
                    <MdChat className="text-3xl" />
                  </div>
                  <h2 className="text-2xl font-bold text-slate-800 tracking-tight mb-2.5">
                    Desert Survival Workspace
                  </h2>
                  <p className="text-xs text-slate-500 leading-relaxed mb-6 font-medium">
                    Talk with your teammates to rank the 12 items. Work collaboratively to reach consensus under AI moderation.
                  </p>

                  <div className="p-4 bg-slate-50 border border-slate-200/80 rounded-2xl text-[11px] text-slate-650 leading-relaxed font-semibold max-w-sm mx-auto">
                    ⚠️ You have <strong className="text-indigo-650">15 minutes</strong> to finish. Talk through your ranking — the moderator follows the discussion and records your group's final order.
                  </div>
                </div>
              </div>
            ) : (
              messages.map((msg, index) => {
                const isModerator = msg.sender === "Moderator";
                const isSystem = msg.sender === "System";
                // Voice-first: a conversational moderator turn renders as a VOICE NOTE; the
                // task-intro card and short system/time notices keep their text card
                // (classifyModerator decides). TTS is still triggered in the socket handler.
                const isModeratorVoiceNote = isModerator && classifyModerator(msg) === "voice";
                const isFlagged = Boolean(msg.flagged);
                const isCurrentUser = msg.sender === userName;
                const userColor = !isModerator && !isSystem ? getUserColor(msg.sender, userName) : null;
                const timestamp = msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit'
                }) : '';

                return (
                  <div
                    key={msg.id || `${msg.sender}-${index}-${String(msg.message).slice(0, 24)}`}
                    className={`flex items-start gap-3.5 ${isCurrentUser ? 'flex-row-reverse animate-slide-up' : 'animate-slide-up'}`}
                  >
                    {/* Avatars */}
                    <div className="flex-shrink-0">
                      {isModerator ? (
                        <div className={`w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-400 to-orange-500 flex items-center justify-center text-white shadow-md shadow-orange-100 ${
                          isModeratorVoiceNote && playingKey === msgKey(msg) && !voicePaused ? 'animate-pulse-glow ring-2 ring-amber-300' : ''
                        }`}>
                          <span className="text-lg">🤖</span>
                        </div>
                      ) : isSystem ? (
                        <div className="w-10 h-10 rounded-xl bg-slate-100 border border-slate-250 flex items-center justify-center text-slate-600">
                          <MdCheckCircle size={18} />
                        </div>
                      ) : (
                        <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-white font-extrabold shadow-sm ${userColor?.accent || 'bg-slate-500'}`}>
                          {msg.sender.charAt(0).toUpperCase()}
                        </div>
                      )}
                    </div>

                    {isModeratorVoiceNote ? (
                      /* 🎙️ Voice-first moderator turn — rendered as a voice note */
                      <ModeratorVoiceNote
                        msg={msg}
                        status={noteStatuses[msgKey(msg)] || "idle"}
                        paused={playingKey === msgKey(msg) && voicePaused}
                        progress={playingKey === msgKey(msg) ? playback.progress : 0}
                        elapsed={playingKey === msgKey(msg) ? playback.elapsed : 0}
                        duration={
                          playingKey === msgKey(msg)
                            ? playback.duration || noteDurations[msgKey(msg)] || 0
                            : noteDurations[msgKey(msg)] || 0
                        }
                        muted={!voiceOn}
                        timestamp={timestamp}
                        transcript={toSpeechText(msg.message)}
                        expanded={!!expandedTranscripts[msgKey(msg)]}
                        onToggleTranscript={() => toggleTranscript(msgKey(msg))}
                        onPlayPause={() => handleVoiceNoteTap(msgKey(msg), msg.message)}
                        onSkip={skipCurrent}
                      />
                    ) : (
                    /* Message detail container */
                    <div className={`max-w-[75%] md:max-w-[65%] ${isCurrentUser ? 'text-right' : 'text-left'}`}>
                      <div className="flex items-center gap-2 mb-1.5 px-1">
                        <span className={`font-bold text-xs ${
                          isModerator ? 'text-amber-705' :
                          isSystem ? 'text-slate-500' :
                          userColor?.text || 'text-slate-700'
                        }`}>
                          {isCurrentUser ? 'You' : msg.sender}
                        </span>

                        <span className="text-[10px] text-slate-400 font-medium">{timestamp}</span>

                        {isFlagged && !isModerator && !isSystem && (
                          <span className="badge badge-warning text-[9px] py-0 px-1.5 flex items-center gap-0.5">
                            <MdWarning size={10} />
                            Flagged
                          </span>
                        )}
                      </div>

                      {/* Message Body Card */}
                      <div
                        className={`rounded-2xl px-4 py-3 text-xs leading-relaxed shadow-sm border ${
                          isModerator
                            ? 'bg-amber-50/70 border-amber-200/80 text-amber-950 rounded-tl-none font-medium'
                            : isSystem
                            ? 'bg-slate-50 border-slate-200 text-slate-550 rounded-2xl text-center italic font-medium'
                            : isCurrentUser
                            ? 'bg-gradient-to-tr from-indigo-500 via-indigo-600 to-violet-650 border-indigo-650 text-white rounded-tr-none font-medium shadow-md shadow-indigo-50'
                            : `${userColor?.bg || 'bg-slate-50'} border ${userColor?.border || 'border-slate-150'} text-slate-800 rounded-tl-none font-medium`
                        } ${isFlagged && !isModerator && !isSystem ? 'ring-2 ring-amber-400 border-amber-300 bg-amber-50/40' : ''}`}
                      >
                        {isFlagged && !isModerator && !isSystem && (
                          <div
                            className={`text-[10px] font-bold mb-1.5 flex items-center gap-1.5 ${
                              isCurrentUser ? "text-amber-100" : "text-amber-900"
                            }`}
                          >
                            <MdWarning size={12} />
                            <span>This post is undergoing automated AI safety review</span>
                          </div>
                        )}
                        <ChatMessageBody msg={msg} isCurrentUser={isCurrentUser} onPlayVoice={playVoiceMessage} onSpeak={playModeratorMessage} />
                      </div>
                    </div>
                    )}
                  </div>
                );
              })
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* 🎙️ PUSH-TO-TALK CONTROL (primary input; transcript above stays read-only) */}
          <div className="border-t border-slate-200 bg-slate-50/80 backdrop-blur-md p-4">
            <div className="max-w-4xl mx-auto flex flex-col items-center gap-3">

              {/* Status indicator: Idle / Listening / Thinking / Speaking */}
              <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider">
                <span
                  className={`w-2.5 h-2.5 rounded-full ${
                    isRecording
                      ? 'bg-rose-500 animate-pulse'
                      : sttBusy
                      ? 'bg-amber-500 animate-pulse'
                      : isSpeaking
                      ? 'bg-indigo-500 animate-pulse'
                      : 'bg-slate-300'
                  }`}
                />
                <span
                  className={
                    isRecording
                      ? 'text-rose-600'
                      : sttBusy
                      ? 'text-amber-600'
                      : isSpeaking
                      ? 'text-indigo-600'
                      : 'text-slate-400'
                  }
                >
                  {sessionStatus}
                </span>
                
                {/* 📊 Animated Audio Waveform Visualizer */}
                {isRecording && (
                  <div className="flex items-end gap-0.5 h-4 ml-3">
                    <span className="w-0.5 bg-rose-500 rounded-full animate-wave-1"></span>
                    <span className="w-0.5 bg-rose-500 rounded-full animate-wave-2"></span>
                    <span className="w-0.5 bg-rose-500 rounded-full animate-wave-3"></span>
                    <span className="w-0.5 bg-rose-500 rounded-full animate-wave-4"></span>
                    <span className="w-0.5 bg-rose-500 rounded-full animate-wave-5"></span>
                  </div>
                )}
                {isSpeaking && (
                  <div className="flex items-end gap-0.5 h-4 ml-3">
                    <span className="w-0.5 bg-indigo-500 rounded-full animate-wave-2"></span>
                    <span className="w-0.5 bg-indigo-500 rounded-full animate-wave-3"></span>
                    <span className="w-0.5 bg-indigo-500 rounded-full animate-wave-4"></span>
                  </div>
                )}
              </div>

              {/* Big press-and-hold mic button */}
              <button
                type="button"
                onPointerDown={handlePttDown}
                onPointerUp={handlePttUp}
                onPointerCancel={handlePttUp}
                onContextMenu={(e) => e.preventDefault()}
                disabled={!ready || sttBusy}
                style={{ touchAction: "none" }}
                className={`relative w-20 h-20 rounded-full flex items-center justify-center text-white shadow-lg transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed select-none ${
                  isRecording
                    ? 'bg-rose-500 scale-105 shadow-rose-200'
                    : 'bg-gradient-to-tr from-indigo-500 to-violet-600 hover:from-indigo-600 hover:to-violet-700 shadow-indigo-200'
                }`}
                aria-pressed={isRecording}
                aria-label="Press and hold to talk"
                title={ready ? "Press and hold to talk" : "Connecting…"}
              >
                {isRecording && (
                  <span className="absolute inset-0 rounded-full bg-rose-400/40 animate-ping" />
                )}
                {sttBusy ? (
                  <span className="block w-7 h-7 border-[3px] border-white/70 border-t-transparent rounded-full animate-spin" />
                ) : (
                  <MdMic size={32} />
                )}
              </button>

              <p className="text-[11px] font-semibold text-slate-500">
                {!ready
                  ? "Connecting to room workspace…"
                  : isRecording
                  ? "Listening… release to send"
                  : sttBusy
                  ? "Transcribing your turn…"
                  : isSpeaking
                  ? "Moderator is speaking…"
                  : "Press and hold to talk"}
              </p>

              {/* Footer: role + end session (actions unchanged) */}
              <div className="w-full mt-1 px-1.5 flex justify-between items-center text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                <span>
                  {ready ? (
                    <>Role: <span className="text-indigo-600 font-extrabold">{userName}</span></>
                  ) : (
                    <span className="text-amber-500">Connecting network...</span>
                  )}
                </span>

                <button
                  onClick={endSession}
                  disabled={isLoadingFeedback}
                  className="text-rose-500 hover:text-rose-700 flex items-center gap-1 font-bold cursor-pointer"
                >
                  {isLoadingFeedback ? (
                    <>
                      <div className="w-2.5 h-2.5 border-2 border-rose-500 border-t-transparent rounded-full animate-spin"></div>
                      <span>Analyzing feedback...</span>
                    </>
                  ) : (
                    <>
                      <MdExitToApp size={12} />
                      <span>End & Evaluate</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* 👥 RIGHT DRAWER: Room Participants */}
        {showParticipants && (
          <aside
            style={{ backgroundColor: '#ffffff' }}
            className="fixed md:static right-0 top-0 md:top-16 bottom-0 w-80 max-w-[85vw] bg-white border-l border-slate-200 shadow-xl md:shadow-none z-50 flex flex-col animate-fade-in"
          >
            <div className="p-4 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between">
              <div>
                <h3 className="font-bold text-slate-800 text-sm">Active Session Users</h3>
                <p className="text-[10px] text-slate-400 font-semibold tracking-wider uppercase mt-0.5">Participants ({onlineCount}/3)</p>
              </div>
              <button
                type="button"
                onClick={() => setShowParticipants(false)}
                className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 p-1.5 rounded-lg text-base font-bold"
              >
                ×
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {/* Current user badge */}
              <div className="flex items-center gap-3 p-3 rounded-2xl bg-indigo-50/50 border border-indigo-100/60 shadow-[0_2px_8px_rgba(99,102,241,0.02)]">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-indigo-500 to-indigo-600 flex items-center justify-center text-white font-extrabold text-xs shadow-sm">
                  {userName.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-bold text-xs text-slate-800 truncate flex items-center gap-1.5">
                    <span>{userName}</span>
                    <span className="badge badge-indigo text-[8px] py-0 px-1 font-bold">You</span>
                  </div>
                  <div className="text-[10px] text-slate-400 font-semibold flex items-center gap-1 mt-0.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                    Active
                  </div>
                </div>
              </div>

              {/* Teammates list */}
              {participants
                .filter(p => p !== userName)
                .map((participant, index) => {
                  const color = getUserColor(participant, userName);
                  return (
                    <div 
                      key={index} 
                      className="flex items-center gap-3 p-3 rounded-2xl border border-slate-150 hover:bg-slate-50/40 transition-all duration-200"
                    >
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-white font-extrabold text-xs ${color.accent}`}>
                        {participant.charAt(0).toUpperCase()}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-bold text-xs text-slate-850 truncate">{participant}</div>
                        <div className="text-[10px] text-slate-400 font-semibold flex items-center gap-1 mt-0.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                          Online
                        </div>
                      </div>
                    </div>
                  );
                })}
              
              {/* Waiting status notifications */}
              {participants.length < 3 && (
                <div className="text-center py-6 px-4 bg-slate-50 border border-dashed border-slate-200 rounded-2xl text-[10px] text-slate-450 font-bold tracking-wide uppercase space-y-2">
                  <div className="w-5 h-5 border-2 border-slate-400 border-t-transparent rounded-full animate-spin mx-auto"></div>
                  <p>Awaiting {3 - participants.length} more student(s)</p>
                </div>
              )}
            </div>
            
            <div className="p-4 border-t border-slate-100 bg-slate-50/40 space-y-3">
              <div className="text-[10px] text-slate-400 font-bold tracking-wide uppercase">Workspace Metadata</div>
              <div className="text-[11px] text-slate-600 font-semibold space-y-2">
                <div className="flex justify-between">
                  <span>Room ID:</span>
                  <span className="font-mono text-slate-800">{roomId.substring(0, 8)}...</span>
                </div>
                <div className="flex justify-between">
                  <span>Total Messages:</span>
                  <span className="text-slate-800">{messages.length}</span>
                </div>
                <div className="flex justify-between">
                  <span>Subject Focus:</span>
                  <span className="text-indigo-600 uppercase text-[9px] bg-indigo-50 border border-indigo-100/60 rounded px-1 py-0.5">Desert survival</span>
                </div>
              </div>
            </div>
          </aside>
        )}
      </div>

    </div>
  );
}