-- =====================================================================
-- LLM Moderator — consolidated database schema
-- =====================================================================
-- One file that recreates the whole `public` schema on a fresh Supabase
-- project. Run it in the Supabase SQL editor.
--
-- PROVENANCE
--   Tables, columns, types, NOT NULL and DEFAULTs below were introspected
--   from the LIVE database (via the PostgREST OpenAPI document), not
--   replayed from supabase/migrations/. The live schema has drifted from
--   those migrations — see "DRIFT" below. This file is the accurate one.
--
-- WHAT COULD NOT BE INTROSPECTED (reconstructed from the migrations, or
-- omitted — verify against production before relying on them):
--   * Indexes            — taken from supabase/migrations/*.sql, filtered
--                          to columns that still exist.
--   * ON DELETE actions  — assumed CASCADE (what the migrations declare).
--   * CHECK constraints  — omitted; the live set is not recoverable this way.
--   * UNIQUE constraints — only settings.key (declared in 002) and
--                          user_stats.username (inferred) are included.
--   * Identity columns   — the five INTEGER primary keys report no default,
--                          so they are written as IDENTITY.
--
-- DRIFT vs supabase/migrations/ (migrations 001/002 no longer describe
-- production; the app follows the live shape below):
--   * messages           — live: username / message / color / deleted /
--                          word_count / edited_at.  001 declared
--                          participant_id / sender_name / message_text.
--   * rooms              — live: participant_count, ended_at, condition,
--                          settings, final_ranking, primary_language, …
--                          001 declared current_participants, completed_at,
--                          story_progress, started_at.
--   * participants       — live has no is_moderator; adds anonymous_id,
--                          language_preference, user_agent, ip_address.
--   * sessions           — live has 23 columns vs the 10 in 001.
--   * research_data      — declared in 001, does NOT exist in production.
--   * analysis_messages, user_stats, room_exports, task_results
--                        — exist in production, declared in no migration.
--   * The 001 triggers on rooms/messages reference columns that no longer
--     exist and are therefore NOT live; only the settings trigger survives.
-- =====================================================================


-- =====================================================================
-- Extensions
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS "pgcrypto"  WITH SCHEMA extensions;


-- =====================================================================
-- Core session tables
-- =====================================================================

-- Chat rooms. One row per discussion session.
CREATE TABLE IF NOT EXISTS public.rooms (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mode                 VARCHAR(50) NOT NULL,
    status               VARCHAR(50) DEFAULT 'waiting',
    story_title          VARCHAR(255),
    story_id             VARCHAR(255),
    current_chunk_index  INTEGER DEFAULT 0,
    max_participants     INTEGER DEFAULT 3,
    participant_count    INTEGER DEFAULT 0,
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_at           TIMESTAMPTZ DEFAULT now(),
    admin_note           TEXT,
    created_by           TEXT DEFAULT 'user',
    story_finished       BOOLEAN DEFAULT false,
    ended_at             TIMESTAMPTZ,
    settings             JSONB,
    condition            TEXT,
    final_ranking        JSONB,
    ranking_submitted_at TIMESTAMPTZ,
    primary_language     TEXT DEFAULT 'en'
);

COMMENT ON TABLE  public.rooms          IS 'Discussion rooms; one row per session.';
COMMENT ON COLUMN public.rooms.mode      IS 'Moderation mode: active | passive.';
COMMENT ON COLUMN public.rooms.condition IS 'Experiment condition: no_moderator | passive_moderator | active_moderator.';
COMMENT ON COLUMN public.rooms.status    IS 'Room state: waiting | active | completed.';

-- Anonymous participants.
CREATE TABLE IF NOT EXISTS public.participants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id             UUID REFERENCES public.rooms(id) ON DELETE CASCADE,
    username            VARCHAR(100) NOT NULL,
    user_color          VARCHAR(50),
    socket_id           VARCHAR(255),
    joined_at           TIMESTAMPTZ DEFAULT now(),
    display_name        TEXT,
    user_agent          TEXT,
    ip_address          INET,
    updated_at          TIMESTAMPTZ DEFAULT now(),
    anonymous_id        TEXT,
    language_preference TEXT,
    last_active_at      TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE  public.participants           IS 'Anonymous participants in a room.';
COMMENT ON COLUMN public.participants.socket_id IS 'Current Socket.IO connection id for real-time events.';

-- Every chat message. The research corpus.
CREATE TABLE IF NOT EXISTS public.messages (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id      UUID REFERENCES public.rooms(id) ON DELETE CASCADE,
    username     VARCHAR(100),
    message      TEXT,
    message_type VARCHAR(50),
    color        VARCHAR(50),
    created_at   TIMESTAMPTZ DEFAULT now(),
    metadata     JSONB,
    edited_at    TIMESTAMPTZ,
    deleted      BOOLEAN DEFAULT false,
    word_count   INTEGER DEFAULT 0
);

COMMENT ON TABLE  public.messages              IS 'All chat messages, stored for research analysis.';
COMMENT ON COLUMN public.messages.message_type IS 'chat | chat_flagged | system | story | moderator | task.';
COMMENT ON COLUMN public.messages.message      IS 'Final displayed text. Raw STT output lives in voice_recordings.transcript_text.';

-- Session lifecycle + rollup counters for a room.
CREATE TABLE IF NOT EXISTS public.sessions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id                 UUID REFERENCES public.rooms(id) ON DELETE CASCADE,
    story_id                VARCHAR(255) NOT NULL,
    mode                    VARCHAR(50) DEFAULT 'active',
    participant_count       INTEGER DEFAULT 1,
    started_at              TIMESTAMPTZ DEFAULT now(),
    ended_at                TIMESTAMPTZ,
    current_step            INTEGER DEFAULT 1,
    is_active               BOOLEAN DEFAULT true,
    story_data              JSONB,
    intervention_count      INTEGER DEFAULT 0,
    total_chunks            INTEGER DEFAULT 0,
    last_intervention       TIMESTAMPTZ,
    last_activity           TIMESTAMPTZ DEFAULT now(),
    settings                JSONB,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now(),
    ended_by                TEXT,
    end_reason              TEXT,
    metadata                JSONB,
    message_count           INTEGER DEFAULT 0,
    duration_seconds        INTEGER DEFAULT 0,
    moderator_message_count INTEGER DEFAULT 0
);

COMMENT ON TABLE public.sessions IS 'Complete conversation sessions with rollup counters.';


-- =====================================================================
-- Voice
-- =====================================================================
-- Audio for push-to-talk messages. Bytes live in the PRIVATE storage
-- bucket `voice-recordings` at {room_id}/{message_id}.webm and are served
-- only through short-lived signed URLs. Text messages create no rows here.
CREATE TABLE IF NOT EXISTS public.voice_recordings (
    id               UUID PRIMARY KEY DEFAULT extensions.uuid_generate_v4(),
    message_id       UUID NOT NULL REFERENCES public.messages(id) ON DELETE CASCADE,
    room_id          UUID NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
    storage_path     TEXT NOT NULL,
    duration_ms      INTEGER,
    mime_type        VARCHAR(100) DEFAULT 'audio/webm',
    stt_model        VARCHAR(80),
    transcript_text  TEXT,
    edited_after_stt BOOLEAN DEFAULT false,
    created_at       TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE  public.voice_recordings                  IS 'Audio for voice messages; private bucket, signed-URL playback.';
COMMENT ON COLUMN public.voice_recordings.transcript_text  IS 'RAW STT output; messages.message holds the final (possibly edited) text.';
COMMENT ON COLUMN public.voice_recordings.edited_after_stt IS 'true when the sent text differs from the raw transcript.';


-- =====================================================================
-- Admin panel
-- =====================================================================

-- Runtime configuration, editable from /admin (overrides env defaults).
CREATE TABLE IF NOT EXISTS public.settings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key         VARCHAR(100) NOT NULL UNIQUE,
    value       TEXT,
    data_type   VARCHAR(50) DEFAULT 'string',
    description TEXT,
    category    VARCHAR(50) DEFAULT 'general',
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE  public.settings           IS 'Configuration settings controlled from the admin panel.';
COMMENT ON COLUMN public.settings.data_type IS 'Type for conversion: string | integer | boolean | float.';

-- Audit trail of admin actions.
CREATE TABLE IF NOT EXISTS public.admin_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    details     JSONB,
    admin_user  TEXT NOT NULL DEFAULT 'admin',
    ip_address  INET,
    created_at  TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE public.admin_logs IS 'Audit log of all admin panel actions.';

-- Record of each data export triggered from the admin panel.
-- NOTE: room_id is TEXT here and carries no foreign key, unlike everywhere else.
CREATE TABLE IF NOT EXISTS public.room_exports (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id     TEXT NOT NULL,
    export_type TEXT NOT NULL,
    format      TEXT NOT NULL,
    file_path   TEXT,
    file_size   BIGINT,
    exported_by TEXT DEFAULT 'admin',
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Lifetime per-username counters.
CREATE TABLE IF NOT EXISTS public.user_stats (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username       TEXT NOT NULL UNIQUE,
    total_messages INTEGER DEFAULT 0,
    total_rooms    INTEGER DEFAULT 0,
    total_sessions INTEGER DEFAULT 0,
    first_seen     TIMESTAMPTZ DEFAULT now(),
    last_seen      TIMESTAMPTZ DEFAULT now(),
    metadata       JSONB
);


-- =====================================================================
-- Research instrumentation (v1)
-- =====================================================================

-- One wide row per room: participation equality, conflict/repair, task accuracy.
CREATE TABLE IF NOT EXISTS public.research_metrics (
    id                     INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    room_id                UUID NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
    gini_coefficient       DOUBLE PRECISION,
    entropy                DOUBLE PRECISION,
    max_share              DOUBLE PRECISION,
    min_share              DOUBLE PRECISION,
    dominance_gap          DOUBLE PRECISION,
    conflict_count         INTEGER,
    repair_count           INTEGER,
    repair_rate            DOUBLE PRECISION,
    total_turns            INTEGER,
    turn_switches          INTEGER,
    avg_response_time      DOUBLE PRECISION,
    total_messages         INTEGER,
    ranking_accuracy       DOUBLE PRECISION,
    created_at             TIMESTAMPTZ DEFAULT now(),
    total_words            INTEGER DEFAULT 0,
    voice_share            DOUBLE PRECISION,
    voice_message_count    INTEGER DEFAULT 0,
    text_message_count     INTEGER DEFAULT 0,
    condition              TEXT,
    language_share_urdu    DOUBLE PRECISION DEFAULT 0,
    language_share_english DOUBLE PRECISION DEFAULT 0,
    participation_entropy  DOUBLE PRECISION
);

COMMENT ON COLUMN public.research_metrics.participation_entropy IS 'RQ1: normalized Shannon entropy of speaking shares (0-1).';
COMMENT ON COLUMN public.research_metrics.conflict_count        IS 'RQ2: keyword-based conflict turns.';
COMMENT ON COLUMN public.research_metrics.repair_count          IS 'RQ2: repair messages paired with recent conflicts.';

-- One row per participant per room.
CREATE TABLE IF NOT EXISTS public.participant_metrics (
    id             INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    room_id        UUID NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
    username       TEXT NOT NULL,
    message_count  INTEGER,
    word_count     INTEGER,
    share_of_talk  DOUBLE PRECISION,
    times_invited  INTEGER,
    times_dominant INTEGER,
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- Every moderator intervention, with the participant response it drew.
CREATE TABLE IF NOT EXISTS public.moderator_interventions (
    id                INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    room_id           UUID NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
    intervention_type TEXT NOT NULL,
    target_user       TEXT,
    "timestamp"       TIMESTAMPTZ DEFAULT now(),
    response_received BOOLEAN DEFAULT false,
    response_time     INTEGER,
    response_user     TEXT
);

COMMENT ON COLUMN public.moderator_interventions.intervention_type IS 'Taxonomy locked in server/frozen_schema.py (ACTIVE_/PASSIVE_ intervention sets).';

-- Row-level conflict -> repair pairs (RQ2).
CREATE TABLE IF NOT EXISTS public.conflict_episodes (
    id                  INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    room_id             UUID NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
    conflict_message_id UUID REFERENCES public.messages(id) ON DELETE CASCADE,
    conflict_user       TEXT NOT NULL,
    conflict_text       TEXT,
    severity_score      INTEGER DEFAULT 1,
    repair_message_id   UUID REFERENCES public.messages(id) ON DELETE CASCADE,
    repair_user         TEXT,
    time_to_repair      INTEGER,
    resolved            BOOLEAN DEFAULT false,
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- Final submitted ranking + task accuracy for a room.
CREATE TABLE IF NOT EXISTS public.task_results (
    id                  INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    room_id             UUID NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
    final_ranking       JSONB,
    accuracy_percentage DOUBLE PRECISION,
    time_to_consensus   INTEGER,
    submitted_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT now()
);


-- =====================================================================
-- Research instrumentation (v2 — authoritative)
-- =====================================================================

-- Long/tidy format: one row per metric value. Ideal for R/pandas.
CREATE TABLE IF NOT EXISTS public.research_metrics_v2 (
    id             UUID PRIMARY KEY DEFAULT extensions.uuid_generate_v4(),
    room_id        UUID NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
    participant_id VARCHAR(100),
    metric_name    VARCHAR(80) NOT NULL,
    metric_value   DOUBLE PRECISION,
    "timestamp"    TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE  public.research_metrics_v2                IS 'Authoritative tidy research metrics; see server/research_metrics_v2.py.';
COMMENT ON COLUMN public.research_metrics_v2.participant_id IS 'NULL for room-level metrics.';
COMMENT ON COLUMN public.research_metrics_v2.metric_name    IS 'Locked vocabulary — see LOCKED_METRIC_NAMES in server/frozen_schema.py.';

-- Wide format: one row per room, for cross-condition statistical comparison.
CREATE TABLE IF NOT EXISTS public.room_metrics_summary (
    id                   UUID PRIMARY KEY DEFAULT extensions.uuid_generate_v4(),
    room_id              UUID NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
    session_id           UUID,
    condition            VARCHAR(20),
    gini                 DOUBLE PRECISION,
    entropy              DOUBLE PRECISION,
    dominance_gap        DOUBLE PRECISION,
    turn_count           INTEGER,
    avg_turn_duration    DOUBLE PRECISION,
    avg_silence_duration DOUBLE PRECISION,
    consensus_score      DOUBLE PRECISION,
    intervention_count   INTEGER,
    created_at           TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE  public.room_metrics_summary                   IS 'One wide row per room for cross-condition statistical analysis.';
COMMENT ON COLUMN public.room_metrics_summary.condition         IS 'no_moderator | passive | active.';
COMMENT ON COLUMN public.room_metrics_summary.avg_turn_duration IS 'Milliseconds; NULL when no audio durations are available.';
COMMENT ON COLUMN public.room_metrics_summary.consensus_score   IS 'Lexical consensus PROXY, not the validated consensus measure.';


-- =====================================================================
-- Research integrity: ground truth + frozen snapshots
-- =====================================================================

-- Append-only ground truth. Every subsystem writes here.
CREATE TABLE IF NOT EXISTS public.event_log (
    event_id             UUID PRIMARY KEY DEFAULT extensions.uuid_generate_v4(),
    room_id              UUID REFERENCES public.rooms(id) ON DELETE CASCADE,
    session_id           UUID,
    experiment_condition VARCHAR(20),
    event_type           VARCHAR(40) NOT NULL,
    payload_json         JSONB,
    "timestamp"          TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE  public.event_log                      IS 'Append-only ground-truth event stream; the authoritative research dataset.';
COMMENT ON COLUMN public.event_log.event_type           IS 'message | stt | tts | intervention | state_update | session | failure.';
COMMENT ON COLUMN public.event_log.experiment_condition IS 'no_moderator | passive_moderator | active_moderator.';

-- Frozen room_state + final metrics at session end.
CREATE TABLE IF NOT EXISTS public.room_state_snapshots (
    id                   UUID PRIMARY KEY DEFAULT extensions.uuid_generate_v4(),
    room_id              UUID NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
    session_id           UUID,
    experiment_condition VARCHAR(20),
    full_room_state_json JSONB,
    final_metrics_json   JSONB,
    snapshot_kind        VARCHAR(20) DEFAULT 'final',
    "timestamp"          TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE  public.room_state_snapshots               IS 'Frozen room_state + final metrics per session, stamped with experiment_condition.';
COMMENT ON COLUMN public.room_state_snapshots.snapshot_kind IS 'final | periodic.';


-- =====================================================================
-- Views
-- =====================================================================
-- Read-only analysis convenience view: messages joined to their room's
-- experiment condition. Exists in production but in no migration; the
-- definition below is RECONSTRUCTED from its live column list and may
-- differ from the original in filtering (e.g. deleted-message handling).
CREATE OR REPLACE VIEW public.analysis_messages AS
SELECT m.id,
       m.room_id,
       m.username,
       m.message,
       m.word_count,
       m.created_at,
       r.condition
FROM public.messages m
JOIN public.rooms r ON r.id = m.room_id;


-- =====================================================================
-- Indexes
-- =====================================================================
CREATE INDEX IF NOT EXISTS idx_rooms_status_mode          ON public.rooms(status, mode);
CREATE INDEX IF NOT EXISTS idx_rooms_created_at           ON public.rooms(created_at);

CREATE INDEX IF NOT EXISTS idx_participants_room_id       ON public.participants(room_id);
CREATE INDEX IF NOT EXISTS idx_participants_socket_id     ON public.participants(socket_id);

CREATE INDEX IF NOT EXISTS idx_messages_room_id_created_at ON public.messages(room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_created_at         ON public.messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_metadata           ON public.messages USING GIN (metadata);

CREATE INDEX IF NOT EXISTS idx_sessions_mode_started_at   ON public.sessions(mode, started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_metadata          ON public.sessions USING GIN (metadata);

CREATE INDEX IF NOT EXISTS idx_settings_key               ON public.settings(key);
CREATE INDEX IF NOT EXISTS idx_settings_category          ON public.settings(category);

CREATE INDEX IF NOT EXISTS idx_admin_logs_created_at      ON public.admin_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_logs_admin_user      ON public.admin_logs(admin_user);
CREATE INDEX IF NOT EXISTS idx_admin_logs_action          ON public.admin_logs(action);

CREATE INDEX IF NOT EXISTS idx_voice_recordings_room_id    ON public.voice_recordings(room_id);
CREATE INDEX IF NOT EXISTS idx_voice_recordings_message_id ON public.voice_recordings(message_id);
-- One audio object per message.
CREATE UNIQUE INDEX IF NOT EXISTS uq_voice_recordings_message_id ON public.voice_recordings(message_id);

CREATE INDEX IF NOT EXISTS idx_research_metrics_room_id        ON public.research_metrics(room_id);
CREATE INDEX IF NOT EXISTS idx_participant_metrics_room_id     ON public.participant_metrics(room_id);
CREATE INDEX IF NOT EXISTS idx_moderator_interventions_room_id ON public.moderator_interventions(room_id);
CREATE INDEX IF NOT EXISTS idx_moderator_interventions_type    ON public.moderator_interventions(intervention_type);
CREATE INDEX IF NOT EXISTS idx_conflict_episodes_room_id       ON public.conflict_episodes(room_id);
CREATE INDEX IF NOT EXISTS idx_task_results_room_id            ON public.task_results(room_id);

CREATE INDEX IF NOT EXISTS idx_rmv2_room_id    ON public.research_metrics_v2(room_id);
CREATE INDEX IF NOT EXISTS idx_rmv2_metric     ON public.research_metrics_v2(metric_name);
CREATE INDEX IF NOT EXISTS idx_rms_room_id     ON public.room_metrics_summary(room_id);
CREATE INDEX IF NOT EXISTS idx_rms_condition   ON public.room_metrics_summary(condition);

CREATE INDEX IF NOT EXISTS idx_event_log_room_ts ON public.event_log(room_id, "timestamp");
CREATE INDEX IF NOT EXISTS idx_event_log_type    ON public.event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_rss_room_id       ON public.room_state_snapshots(room_id);

CREATE INDEX IF NOT EXISTS idx_room_exports_room_id ON public.room_exports(room_id);
CREATE INDEX IF NOT EXISTS idx_user_stats_username  ON public.user_stats(username);


-- =====================================================================
-- Functions & triggers
-- =====================================================================
-- Keep settings.updated_at current. (The 001 triggers on rooms/messages are
-- deliberately not recreated — they referenced columns that no longer exist.)
CREATE OR REPLACE FUNCTION public.update_settings_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_settings_timestamp ON public.settings;
CREATE TRIGGER trigger_update_settings_timestamp
BEFORE UPDATE ON public.settings
FOR EACH ROW
EXECUTE FUNCTION public.update_settings_timestamp();


-- =====================================================================
-- Storage
-- =====================================================================
-- Private bucket for voice messages. public = false keeps it private; the
-- server uses the service role key (bypasses RLS) and mints only short-lived
-- signed URLs for playback. Matches AUDIO_BUCKET in server/.env.
INSERT INTO storage.buckets (id, name, public)
VALUES ('voice-recordings', 'voice-recordings', false)
ON CONFLICT (id) DO NOTHING;


-- =====================================================================
-- Row Level Security
-- =====================================================================
-- Disabled throughout: there is no end-user auth. The Flask server is the
-- only client and connects with the service role key. Do NOT expose the
-- anon key to a browser against this schema.
ALTER TABLE public.rooms                   DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.participants            DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages                DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions                DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.voice_recordings        DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.settings                DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_logs              DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_exports            DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_stats              DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_metrics        DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.participant_metrics     DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.moderator_interventions DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.conflict_episodes       DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.task_results            DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_metrics_v2     DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_metrics_summary    DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_state_snapshots    DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_log               DISABLE ROW LEVEL SECURITY;


-- =====================================================================
-- Seed: default admin-panel settings
-- =====================================================================
-- Safe to re-run. Existing values are never overwritten.
INSERT INTO public.settings (key, value, data_type, category, description) VALUES
    ('WELCOME_MESSAGE',                     'Welcome everyone! I''m the Moderator.',     'string',  'moderator', 'Initial welcome message sent to all participants'),
    ('ACTIVE_ENDING_MESSAGE',               '✨ We have reached the end of the story.',  'string',  'moderator', 'Message sent when the story ends in active mode'),
    ('PASSIVE_ENDING_MESSAGE',              '✨ We have reached the end of the story.',  'string',  'moderator', 'Message sent when the story ends in passive mode'),
    ('ACTIVE_STORY_STEP',                   '1',                                         'integer', 'story',     'Sentences per chunk in active mode'),
    ('PASSIVE_STORY_STEP',                  '1',                                         'integer', 'story',     'Sentences per chunk in passive mode'),
    ('PASSIVE_SILENCE_SECONDS',             '10',                                        'integer', 'timing',    'Seconds of silence before intervention in passive mode'),
    ('ACTIVE_SILENCE_SECONDS',              '20',                                        'integer', 'timing',    'Seconds of silence before intervention in active mode'),
    ('STORY_CHUNK_INTERVAL',                '10',                                        'integer', 'timing',    'Seconds between story chunks in passive mode'),
    ('ACTIVE_INTERVENTION_WINDOW_SECONDS',  '20',                                        'integer', 'timing',    'Intervention window for active mode'),
    ('PASSIVE_INTERVENTION_WINDOW_SECONDS', '10',                                        'integer', 'timing',    'Intervention window for passive mode'),
    ('MAX_PARTICIPANTS_PER_ROOM',           '3',                                         'integer', 'room',      'Maximum participants allowed per room'),
    ('ROOM_IDLE_TIMEOUT_MINUTES',           '60',                                        'integer', 'room',      'Minutes before idle rooms are cleaned up'),
    ('CHAT_HISTORY_LIMIT',                  '50',                                        'integer', 'chat',      'Messages of history sent to the LLM'),
    ('ENABLE_TTS',                          'true',                                      'boolean', 'features',  'Enable text-to-speech'),
    ('ENABLE_STT',                          'true',                                      'boolean', 'features',  'Enable speech-to-text'),
    ('ENABLE_AUTO_START_SINGLE_USER',       'true',                                      'boolean', 'features',  'Allow the story to start with a single participant'),
    ('OPENAI_CHAT_MODEL',                   'gpt-4o-mini',                               'string',  'ai',        'OpenAI model used when Groq is unavailable'),
    ('OPENAI_TEMPERATURE',                  '0.3',                                       'float',   'ai',        'Temperature for AI responses (0.0-1.0)'),
    ('OPENAI_MAX_TOKENS',                   '1500',                                      'integer', 'ai',        'Maximum tokens for AI responses')
ON CONFLICT (key) DO NOTHING;
