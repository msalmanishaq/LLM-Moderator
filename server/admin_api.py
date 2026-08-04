"""
Admin API Endpoints - COMPLETE FIXED VERSION WITH OPENAI SUPPORT
===================
Backend API for admin panel - Fixed room creation with max_participants
"""

import os
import time
import logging
import csv
import json
import zipfile
from io import StringIO, BytesIO
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, make_response, send_file
from supabase_client import (
    supabase,
    get_room,
    get_participants,
    get_chat_history,
    get_participants_with_details,
    create_room,
    create_room_admin,  # IMPORT THE ADMIN VERSION WITH max_participants
    update_room_status,
    end_session,
    add_message,
    get_messages_for_export,
    get_all_rooms as get_all_rooms_from_db,
    get_system_stats as get_system_stats_from_db,
    get_room_stats as get_room_stats_from_db,
    log_admin_action,
    create_export_record,
    delete_room_voice_recordings,
    get_voice_recordings_for_room,
    AUDIO_BUCKET,
)
from research_metrics import message_input_mode, summarize_input_modes
import research_metrics_v2 as RM2
import event_log as EV

logger = logging.getLogger("ADMIN_API")

# Create blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# ============================================================
# Auth: every /admin/* blueprint route requires an X-Admin-Token that is either a
# signed session token from POST /admin/login (username + password) or the legacy
# raw ADMIN_TOKEN (kept working for curl/export scripts). Fails closed when neither
# credential is configured. App-level /admin routes use a matching decorator in
# app.py (require_admin_token). See admin_auth.py.
# ============================================================
import admin_auth

# Endpoints reachable without a token — the login route itself, or nobody could
# ever obtain one.
_AUTH_EXEMPT_ENDPOINTS = {"admin.admin_login", "admin.admin_auth_info"}


@admin_bp.before_request
def _require_admin_token():
    if request.method == "OPTIONS":  # allow CORS preflight without a token
        return None
    if request.endpoint in _AUTH_EXEMPT_ENDPOINTS:
        return None
    authorized, principal = admin_auth.authorize_request(request.headers)
    if not authorized:
        logger.warning("🔒 Rejected admin request to %s (bad/missing credentials)", request.path)
        return jsonify({"error": "Unauthorized"}), 401
    request.admin_principal = principal
    return None


# ============================================================
# Login / session
# ============================================================
@admin_bp.route('/login', methods=['POST'])
def admin_login():
    """Exchange username + password for a time-limited signed session token."""
    ip = admin_auth._client_ip(request.headers, request.remote_addr)

    locked_for = admin_auth.login_lockout_remaining(ip)
    if locked_for:
        logger.warning("🔒 Admin login refused for %s — locked out %ds more", ip, locked_for)
        return jsonify({
            "error": "Too many failed attempts. Try again later.",
            "retry_after_seconds": locked_for,
        }), 429

    if not admin_auth.login_enabled():
        logger.error("🔒 Admin login attempted but no password is configured on the server")
        return jsonify({
            "error": "Admin login is not configured on the server. "
                     "Set ADMIN_USERNAME and ADMIN_PASSWORD_HASH."
        }), 503

    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")

    if not admin_auth.verify_credentials(username, password):
        lockout = admin_auth.record_login_failure(ip)
        logger.warning("🔒 Failed admin login for %r from %s", username[:40], ip)
        body = {"error": "Invalid username or password."}
        if lockout:
            body["error"] = "Too many failed attempts. Try again later."
            body["retry_after_seconds"] = lockout
            return jsonify(body), 429
        return jsonify(body), 401

    admin_auth.clear_login_failures(ip)
    token, expires_at = admin_auth.issue_session_token(username)
    logger.info("✅ Admin login succeeded for %r from %s", username, ip)
    try:
        log_admin_action(
            action="admin_login", entity_type="session", entity_id=username,
            admin_user=username, ip_address=ip,
        )
    except Exception as e:
        logger.debug("admin_login audit entry skipped: %s", e)

    return jsonify({
        "token": token,
        "username": username,
        "expires_at": expires_at,
        "expires_in_seconds": expires_at - int(time.time()),
    })


@admin_bp.route('/session', methods=['GET'])
def admin_session():
    """Validate the caller's token (used by the dashboard to restore a session)."""
    return jsonify({
        "valid": True,
        "principal": getattr(request, "admin_principal", None),
        **admin_auth.auth_status(),
    })


@admin_bp.route('/auth-info', methods=['GET'])
def admin_auth_info():
    """Unauthenticated: tells the login screen how auth is configured (no secrets)."""
    return jsonify(admin_auth.auth_status())


@admin_bp.route('/logout', methods=['POST'])
def admin_logout():
    """Session tokens are stateless, so logout is a client-side discard.

    Acknowledged here so the dashboard has one place to call, and so the sign-out
    lands in the admin audit log.
    """
    principal = getattr(request, "admin_principal", None)
    try:
        log_admin_action(
            action="admin_logout", entity_type="session", entity_id=principal,
            admin_user=principal or "admin",
            ip_address=admin_auth._client_ip(request.headers, request.remote_addr),
        )
    except Exception as e:
        logger.debug("admin_logout audit entry skipped: %s", e)
    return jsonify({"ok": True})

# ============================================================
# Helper: Safe datetime parsing
# ============================================================

def safe_datetime_parse(dt_str):
    """Safely parse datetime string to avoid timezone issues"""
    if not dt_str:
        return None
    try:
        dt_str = dt_str.replace('Z', '+00:00')
        if '+' in dt_str:
            return datetime.fromisoformat(dt_str)
        else:
            return datetime.fromisoformat(dt_str + '+00:00')
    except:
        try:
            return datetime.strptime(dt_str.split('.')[0], '%Y-%m-%dT%H:%M:%S')
        except:
            return datetime.now(timezone.utc)

# ============================================================
# ✅ FIXED: Admin Room Creation - NOW WORKING WITH max_participants
# ============================================================

@admin_bp.route('/rooms', methods=['POST'])
def create_room_admin_endpoint():
    """Admin-only room creation endpoint - FIXED to use create_room_admin"""
    try:
        data = request.json or {}
        
        mode = data.get('mode', 'active')
        story_id = data.get('story_id')
        max_participants = int(data.get('max_participants', 3))
        admin_note = data.get('admin_note', '')
        admin_user = data.get('admin_user', 'admin')
        
        # Validate
        if mode not in ['active', 'passive']:
            return jsonify({"error": "Mode must be 'active' or 'passive'"}), 400
        
        if max_participants < 1 or max_participants > 10:
            return jsonify({"error": "Max participants must be between 1 and 10"}), 400
        
        # Import here to avoid circular imports
        from data_retriever import get_data
        
        # Get story
        if story_id:
            story_data = get_data(story_id)
            if not story_data:
                return jsonify({"error": f"Story {story_id} not found"}), 404
        else:
            story_data = get_data()
            story_id = story_data.get('story_id', 'default-story')
        
        # ✅ FIXED: Use create_room_admin which accepts max_participants
        room = create_room_admin(
            mode=mode,
            story_id=story_id,
            max_participants=max_participants,
            created_by=f'admin:{admin_user}',
            admin_note=admin_note
        )
        
        # Log the creation
        log_admin_action('create_room', 'room', room['id'], {
            'mode': mode,
            'story_id': story_id,
            'max_participants': max_participants,
            'admin_note': admin_note
        }, admin_user)
        
        logger.info(f"✅ Admin created room: {room['id']} (mode={mode}, max_participants={max_participants})")
        
        return jsonify({
            "success": True,
            "room": room,
            "shareable_link": f"/join/{mode}",
            "admin_link": f"/admin/rooms/{room['id']}"
        })
    
    except Exception as e:
        logger.error(f"❌ Error creating room as admin: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# FIXED: Enhanced Room Details with Usernames
# ============================================================

@admin_bp.route('/rooms/<room_id>', methods=['GET'])
def get_room_details(room_id: str):
    """Get detailed room information including participants and messages"""
    try:
        room = get_room(room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        
        # Get participants with proper usernames
        participants = get_participants_with_details(room_id)
        
        # Get messages
        messages = get_messages_for_export(room_id)
        
        # Get session info
        session_response = supabase.table('sessions').select('*').eq('room_id', room_id).execute()
        sessions = session_response.data if session_response.data else []
        
        # Get stats
        stats = get_room_stats_from_db(room_id)
        
        logger.info(f"📊 Admin: Viewed room {room_id} with {len(participants)} participants, {len(messages)} messages")
        
        return jsonify({
            "room": room,
            "participants": participants,
            "messages": messages,
            "sessions": sessions,
            "stats": stats
        })
    
    except Exception as e:
        logger.error(f"❌ Error getting room details: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# FIXED: Chat Export Endpoints
# ============================================================

@admin_bp.route('/rooms/<room_id>/export/chat', methods=['GET'])
def export_room_chat(room_id: str):
    """Export chat messages in various formats"""
    try:
        format_type = request.args.get('format', 'json').lower()
        
        # Get messages
        messages = get_messages_for_export(room_id)

        if not messages:
            return jsonify({"error": "No messages found for this room"}), 404

        # Thread input_mode (text/voice) onto each row so modalities can be compared downstream.
        for _m in messages:
            _m["input_mode"] = message_input_mode(_m)

        # Get room info for filename
        room = get_room(room_id)
        
        # Export based on format
        if format_type == 'json':
            return jsonify({
                "room_id": room_id,
                "room_mode": room.get('mode') if room else 'unknown',
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "message_count": len(messages),
                "messages": messages
            })
        
        elif format_type == 'csv':
            output = StringIO()
            if messages:
                fieldnames = ['id', 'username', 'message', 'message_type', 'created_at', 'word_count', 'input_mode']
                writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(messages)
            
            csv_data = output.getvalue()
            output.close()
            
            response = make_response(csv_data)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=chat_{room_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            
            create_export_record(room_id, 'chat', 'csv')
            
            return response
        
        elif format_type == 'tsv':
            output = StringIO()
            if messages:
                fieldnames = ['id', 'username', 'message', 'message_type', 'created_at', 'word_count', 'input_mode']
                writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter='\t', extrasaction='ignore')
                writer.writeheader()
                writer.writerows(messages)
            
            tsv_data = output.getvalue()
            output.close()
            
            response = make_response(tsv_data)
            response.headers['Content-Type'] = 'text/tab-separated-values'
            response.headers['Content-Disposition'] = f'attachment; filename=chat_{room_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.tsv'
            
            create_export_record(room_id, 'chat', 'tsv')
            
            return response
        
        else:
            return jsonify({"error": f"Unsupported format: {format_type}. Use json, csv, or tsv"}), 400
    
    except Exception as e:
        logger.error(f"❌ Error exporting chat: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# FIXED: Enhanced Room List
# ============================================================

@admin_bp.route('/rooms', methods=['GET'])
def get_all_rooms():
    """Get all rooms with filters"""
    try:
        # Get query parameters
        status = request.args.get('status')
        mode = request.args.get('mode')
        limit = int(request.args.get('limit', 50))
        search = request.args.get('search', '')
        
        # Use the function from supabase_client
        rooms = get_all_rooms_from_db(status, mode, limit)
        
        # Apply search filter if provided
        if search:
            rooms = [r for r in rooms if 
                    search.lower() in r.get('id', '').lower() or
                    search.lower() in r.get('story_id', '').lower() or
                    any(search.lower() in p.get('username', '').lower() or 
                        search.lower() in p.get('display_name', '').lower() 
                        for p in r.get('participant_list', []))]
        
        logger.info(f"📊 Admin: Retrieved {len(rooms)} rooms (status={status}, mode={mode})")
        return jsonify({
            "rooms": rooms,
            "count": len(rooms),
            "filters": {"status": status, "mode": mode, "search": search},
            "summary": {
                "total": len(rooms),
                "waiting": len([r for r in rooms if r.get('status') == 'waiting']),
                "active": len([r for r in rooms if r.get('status') == 'active']),
                "completed": len([r for r in rooms if r.get('status') == 'completed']),
                "active_mode": len([r for r in rooms if r.get('mode') == 'active']),
                "passive_mode": len([r for r in rooms if r.get('mode') == 'passive'])
            }
        })
    
    except Exception as e:
        logger.error(f"❌ Error getting rooms: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# FIXED: Enhanced Statistics
# ============================================================

@admin_bp.route('/stats', methods=['GET'])
def get_stats():
    """Get overall statistics"""
    try:
        stats = get_system_stats_from_db()
        logger.info(f"📊 Admin: Retrieved enhanced statistics")
        return jsonify(stats)
    
    except Exception as e:
        logger.error(f"❌ Error getting stats: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# FIXED: Room Control Endpoints
# ============================================================

@admin_bp.route('/rooms/<room_id>/end', methods=['POST'])
def end_room_session(room_id: str):
    """End a room session (admin control)"""
    try:
        data = request.json or {}
        admin_user = data.get('admin_user', 'admin')
        
        room = get_room(room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        
        # Import socketio to trigger session end with summaries
        from app import socketio as app_socketio
        
        # Trigger the socket event to end session with summaries
        app_socketio.emit("end_session", {
            "room_id": room_id,
            "sender": f"admin:{admin_user}"
        }, room=room_id)
        
        logger.info(f"✅ Admin triggered session end for room {room_id}")
        
        return jsonify({
            "success": True,
            "message": "Session ending, summaries will be sent to participants",
            "room_id": room_id
        })
    
    except Exception as e:
        logger.error(f"❌ Error ending room: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# FIXED: Delete Room Endpoint
# ============================================================

@admin_bp.route('/rooms/<room_id>', methods=['DELETE'])
def delete_room(room_id: str):
    """Delete a room and all associated data"""
    try:
        # Check if room exists
        room = get_room(room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        
        # Remove voice audio (storage objects + rows) BEFORE deleting messages, so the
        # rows are still present to resolve storage paths. DB cascade can't touch storage.
        try:
            removed = delete_room_voice_recordings(room_id)
            logger.info(f"🗑️ Admin: purged {removed} voice object(s) for room {room_id}")
        except Exception as e:
            logger.error(f"⚠️ Voice purge failed for room {room_id}: {e}")

        # Delete associated data in order
        supabase.table('messages').delete().eq('room_id', room_id).execute()
        supabase.table('participants').delete().eq('room_id', room_id).execute()
        supabase.table('sessions').delete().eq('room_id', room_id).execute()
        
        try:
            supabase.table('room_exports').delete().eq('room_id', room_id).execute()
        except:
            pass
        
        supabase.table('rooms').delete().eq('id', room_id).execute()
        
        log_admin_action('delete_room', 'room', room_id, {'room_mode': room.get('mode')})
        
        logger.info(f"🗑️ Admin: Deleted room {room_id}")
        return jsonify({"success": True, "message": "Room deleted successfully"})
    
    except Exception as e:
        logger.error(f"❌ Error deleting room: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# FIXED: Update Room Status
# ============================================================

@admin_bp.route('/rooms/<room_id>/status', methods=['PUT'])
def update_room_status_admin(room_id: str):
    """Update room status (admin control)"""
    try:
        data = request.json or {}
        status = data.get('status')
        admin_user = data.get('admin_user', 'admin')
        
        if status not in ['waiting', 'active', 'completed']:
            return jsonify({"error": "Invalid status. Use: waiting, active, completed"}), 400
        
        room = get_room(room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        
        update_room_status(room_id, status)
        
        if room.get('status') != status:
            add_message(
                room_id=room_id,
                username="System",
                message=f"Room status changed to '{status}' by admin.",
                message_type="system",
                metadata={"admin_action": True, "admin_user": admin_user}
            )
        
        log_admin_action('update_room_status', 'room', room_id, {
            'old_status': room.get('status'),
            'new_status': status
        }, admin_user)
        
        logger.info(f"✅ Admin updated room {room_id} status to {status}")
        
        return jsonify({
            "success": True,
            "message": f"Room status updated to {status}",
            "room_id": room_id,
            "old_status": room.get('status'),
            "new_status": status
        })
    
    except Exception as e:
        logger.error(f"❌ Error updating room status: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# Settings Management - UPDATED WITH OPENAI SUPPORT
# ============================================================

@admin_bp.route('/settings', methods=['GET'])
def get_all_settings():
    """Get all configuration settings grouped by category"""
    try:
        response = supabase.table('settings').select('*').order('category').execute()
        
        settings = response.data if response.data else []
        
        # Group by category
        grouped = {}
        for setting in settings:
            category = setting.get('category', 'general')
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(setting)
        
        logger.info(f"📊 Admin: Retrieved {len(settings)} settings")
        return jsonify({
            "settings": settings,
            "grouped": grouped,
            "count": len(settings)
        })
    
    except Exception as e:
        logger.error(f"❌ Error getting settings: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/settings/<key>', methods=['GET'])
def get_setting(key: str):
    """Get specific setting by key"""
    try:
        response = supabase.table('settings').select('*').eq('key', key).limit(1).execute()
        rows = response.data or []

        if not rows:
            return jsonify({"error": "Setting not found"}), 404

        return jsonify(rows[0])
    
    except Exception as e:
        logger.error(f"❌ Error getting setting {key}: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/settings/<key>', methods=['PUT'])
def update_setting(key: str):
    """Update a setting value"""
    try:
        # P5 — READ-ONLY RESEARCH MODE: reject config mutations that could drift frozen
        # behavior (e.g. silence thresholds affecting interventions/metrics) mid-study.
        import frozen_schema
        if frozen_schema.research_read_only():
            logger.warning(f"🔒 Settings change to '{key}' rejected — RESEARCH_READ_ONLY is ON")
            return jsonify({"error": "System is in READ-ONLY RESEARCH MODE; settings are frozen.",
                            "locked": True}), 423

        data = request.json
        new_value = data.get('value')

        if new_value is None:
            return jsonify({"error": "Value is required"}), 400
        
        # Check if setting exists (.limit(1) avoids a 406 on a not-yet-existing key)
        check = supabase.table('settings').select('*').eq('key', key).limit(1).execute()

        if check.data:
            # Update existing
            response = supabase.table('settings').update({
                'value': str(new_value),
                'updated_by': data.get('updated_by', 'admin'),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }).eq('key', key).execute()
        else:
            # Create new setting with default type
            response = supabase.table('settings').insert({
                'key': key,
                'value': str(new_value),
                'data_type': 'string',
                'category': 'llm',
                'description': f'Setting for {key}',
                'updated_by': data.get('updated_by', 'admin'),
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'created_at': datetime.now(timezone.utc).isoformat()
            }).execute()
        
        clear_settings_cache()  # keep cached config reads correct after a write

        log_admin_action('update_setting', 'setting', None, {
            'key': key,
            'new_value': new_value
        }, data.get('admin_user', 'unknown'))

        logger.info(f"✅ Admin: Updated setting {key} = {new_value}")
        return jsonify(response.data[0] if response.data else {"success": True})
    
    except Exception as e:
        logger.error(f"❌ Error updating setting {key}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================
# Admin Logs
# ============================================================

@admin_bp.route('/logs', methods=['GET'])
def get_admin_logs():
    """Get admin activity logs"""
    try:
        limit = int(request.args.get('limit', 100))
        
        response = (
            supabase.table('admin_logs')
            .select('*')
            .order('created_at', desc=True)
            .limit(limit)
            .execute()
        )
        
        logs = response.data if response.data else []
        
        return jsonify({
            "logs": logs,
            "count": len(logs)
        })
    
    except Exception as e:
        logger.error(f"❌ Error getting admin logs: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================
# Audio: short-lived signed URLs for private voice objects (never public URLs)
# ============================================================

@admin_bp.route('/audio/signed-url', methods=['GET'])
def get_audio_signed_url():
    """
    Mint a short-lived Supabase signed URL for a private audio object so admins can
    play voice recordings without exposing a public URL. The bucket stays private.
    Query: ?path=<object path>&expires_in=<seconds, 30..3600, default 300>
    """
    path = (request.args.get('path') or '').strip().lstrip('/')
    if not path:
        return jsonify({"error": "Missing 'path' query param"}), 400

    bucket = AUDIO_BUCKET
    try:
        expires_in = int(request.args.get('expires_in', 300))
    except (TypeError, ValueError):
        expires_in = 300
    expires_in = max(30, min(expires_in, 3600))

    try:
        signed = supabase.storage.from_(bucket).create_signed_url(path, expires_in)
        # supabase-py has used different key spellings across versions
        url = (
            (signed or {}).get("signedURL")
            or (signed or {}).get("signedUrl")
            or (signed or {}).get("signed_url")
        )
        if not url:
            return jsonify({"error": "Could not create signed URL"}), 502
        return jsonify({
            "signed_url": url,
            "bucket": bucket,
            "path": path,
            "expires_in": expires_in,
        })
    except Exception as e:
        logger.error(f"❌ Error creating signed URL for {bucket}/{path}: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# Helper: Get Setting Value - UPDATED WITH BETTER ERROR HANDLING
# ============================================================

# In-process cache of all settings rows, populated by prefetch_settings(). The
# config block reads ~16 keys at startup; without this each is a separate HTTP
# round-trip (and missing keys returned a noisy 406). The cache turns that into
# ONE query. It is cleared whenever a setting is written so reads stay correct.
_settings_cache = None  # type: ignore


def _convert_setting(setting: dict, default=None):
    """Type-convert a settings row's value per its data_type."""
    value_str = setting.get('value')
    data_type = setting.get('data_type', 'string')
    if value_str is None:
        return default
    try:
        if data_type == 'integer':
            return int(value_str)
        elif data_type == 'float':
            return float(value_str)
        elif data_type == 'boolean':
            return value_str.lower() in ('true', '1', 'yes', 'on')
        return value_str
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to convert setting {setting.get('key')} value '{value_str}': {e}")
        return default


def prefetch_settings():
    """Load ALL settings into the in-process cache in a single query."""
    global _settings_cache
    try:
        response = supabase.table('settings').select('*').execute()
        _settings_cache = {row['key']: row for row in (response.data or []) if row.get('key')}
        logger.info(f"⚙️ Prefetched {len(_settings_cache)} settings in one query")
    except Exception as e:
        logger.warning(f"Could not prefetch settings (will read per-key): {e}")
        _settings_cache = None
    return _settings_cache


def clear_settings_cache():
    """Invalidate the settings cache (call after any settings write)."""
    global _settings_cache
    _settings_cache = None


def get_setting_value(key: str, default=None):
    """Get a setting value from the DB (or cache) with type conversion."""
    # Serve from the prefetched cache when available — no network round-trip.
    if _settings_cache is not None:
        setting = _settings_cache.get(key)
        if not setting:
            logger.debug(f"Setting {key} not found (cache), using default: {default}")
            return default
        return _convert_setting(setting, default)

    try:
        # .limit(1) (not .maybe_single) so a missing key returns HTTP 200 + []
        # instead of a 406 that surfaces as "'NoneType' object has no attribute 'data'".
        response = supabase.table('settings').select('*').eq('key', key).limit(1).execute()
        rows = response.data or []
        if not rows:
            logger.debug(f"Setting {key} not found, using default: {default}")
            return default
        return _convert_setting(rows[0], default)
    except Exception as e:
        logger.warning(f"Failed to get setting {key}, using default: {e}")
        return default

# ============================================================
# RESEARCH EXPORT ENDPOINTS - SINGLE VERSION (NO DUPLICATES)
# ============================================================

@admin_bp.route('/research/export', methods=['GET'])
def export_research_data():
    """Export all research data for analysis (JSON or CSV)"""
    try:
        format_type = request.args.get('format', 'json').lower()
        condition = request.args.get('condition')  # 'active' or 'passive'
        
        # Get all completed rooms with their data
        query = supabase.table("rooms")\
            .select("""
                id,
                mode,
                condition,
                created_at,
                ended_at,
                final_ranking,
                research_metrics(*),
                moderator_interventions(*),
                participant_metrics(*),
                task_results(*)
            """)\
            .not_.is_("ended_at", "null")\
            .order("created_at", desc=True)
        
        if condition:
            query = query.eq("mode", condition)
        
        response = query.execute()
        rooms = response.data if response.data else []
        
        # Calculate summary statistics
        summary = {
            "total_sessions": len(rooms),
            "active_sessions": len([r for r in rooms if r.get('mode') == 'active']),
            "passive_sessions": len([r for r in rooms if r.get('mode') == 'passive']),
            "avg_gini": 0,
            "avg_dominance_gap": 0,
            "avg_accuracy": 0,
            "total_conflicts": 0,
            "total_interventions": 0
        }
        
        # Calculate averages
        gini_values = []
        dominance_values = []
        accuracy_values = []
        conflict_counts = []
        intervention_counts = []
        voice_shares = []

        for room in rooms:
            if room.get('research_metrics'):
                for metric in room['research_metrics']:
                    if metric.get('gini_coefficient'):
                        gini_values.append(metric['gini_coefficient'])
                    if metric.get('dominance_gap'):
                        dominance_values.append(metric['dominance_gap'])
                    if metric.get('ranking_accuracy'):
                        accuracy_values.append(metric['ranking_accuracy'])
                    if metric.get('conflict_count'):
                        conflict_counts.append(metric['conflict_count'])

            if room.get('moderator_interventions'):
                intervention_counts.append(len(room['moderator_interventions']))

            # Per-session text/voice breakdown (additive — modality comparison downstream)
            try:
                msgs = (
                    supabase.table('messages')
                    .select('username, metadata')
                    .eq('room_id', room['id'])
                    .execute()
                    .data
                ) or []
            except Exception:
                msgs = []
            mode_summary = summarize_input_modes(msgs)
            room['input_mode_summary'] = mode_summary
            if mode_summary['total_student_messages'] > 0:
                voice_shares.append(mode_summary['voice_share'])

        if gini_values:
            summary['avg_gini'] = sum(gini_values) / len(gini_values)
        if dominance_values:
            summary['avg_dominance_gap'] = sum(dominance_values) / len(dominance_values)
        if accuracy_values:
            summary['avg_accuracy'] = sum(accuracy_values) / len(accuracy_values)
        if conflict_counts:
            summary['avg_conflicts_per_session'] = sum(conflict_counts) / len(conflict_counts)
        if intervention_counts:
            summary['avg_interventions_per_session'] = sum(intervention_counts) / len(intervention_counts)
        if voice_shares:
            summary['avg_voice_share'] = sum(voice_shares) / len(voice_shares)
        
        # Return based on format
        if format_type == 'json':
            return jsonify({
                "success": True,
                "summary": summary,
                "rooms": rooms,
                "exported_at": datetime.now(timezone.utc).isoformat()
            })
        
        elif format_type == 'csv':
            # Create CSV with flattened data
            output = StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow([
                'room_id', 'condition', 'gini_coefficient', 'dominance_gap',
                'ranking_accuracy', 'total_messages', 'conflict_count',
                'intervention_count', 'time_to_consensus',
                'voice_message_count', 'text_message_count', 'voice_share'
            ])

            for room in rooms:
                metrics = room.get('research_metrics', [{}])[0] if room.get('research_metrics') else {}
                mode_summary = room.get('input_mode_summary', {})
                writer.writerow([
                    room['id'],
                    room.get('mode'),
                    metrics.get('gini_coefficient', ''),
                    metrics.get('dominance_gap', ''),
                    metrics.get('ranking_accuracy', ''),
                    metrics.get('total_messages', ''),
                    metrics.get('conflict_count', 0),
                    len(room.get('moderator_interventions', [])),
                    metrics.get('time_to_consensus', ''),
                    mode_summary.get('voice_message_count', ''),
                    mode_summary.get('text_message_count', ''),
                    mode_summary.get('voice_share', '')
                ])
            
            csv_data = output.getvalue()
            output.close()
            
            response = make_response(csv_data)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=research_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            return response
        
        else:
            return jsonify({"error": f"Unsupported format: {format_type}. Use json or csv"}), 400
    
    except Exception as e:
        logger.error(f"❌ Error exporting research data: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/research/metrics/<room_id>', methods=['GET'])
def get_room_research_metrics(room_id: str):
    """Get detailed research metrics for a specific room"""
    try:
        # Get room info (.limit(1) avoids a 406 when the room id doesn't exist)
        room_response = supabase.table("rooms").select("*").eq("id", room_id).limit(1).execute()
        room = (room_response.data or [{}])[0]
        
        # Get metrics
        metrics_response = supabase.table("research_metrics").select("*").eq("room_id", room_id).execute()
        metrics = metrics_response.data if metrics_response.data else []
        
        # Get interventions
        interventions_response = supabase.table("moderator_interventions").select("*").eq("room_id", room_id).order("timestamp").execute()
        interventions = interventions_response.data if interventions_response.data else []
        
        # Get participant metrics
        participant_response = supabase.table("participant_metrics").select("*").eq("room_id", room_id).execute()
        participants = participant_response.data if participant_response.data else []
        
        # Get task results
        task_response = supabase.table("task_results").select("*").eq("room_id", room_id).execute()
        task = task_response.data[0] if task_response.data else {}
        
        return jsonify({
            "room": room,
            "metrics": metrics,
            "interventions": interventions,
            "participants": participants,
            "task": task
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting room metrics: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/research/summary', methods=['GET'])
def get_research_summary():
    """Get summary statistics comparing active vs passive conditions"""
    try:
        # Get all completed rooms
        rooms_response = supabase.table("rooms")\
            .select("id, mode")\
            .not_.is_("ended_at", "null")\
            .execute()
        
        rooms = rooms_response.data if rooms_response.data else []
        
        # Get all metrics
        metrics_response = supabase.table("research_metrics").select("*").execute()
        all_metrics = metrics_response.data if metrics_response.data else []
        
        # Separate by condition
        active_metrics = []
        passive_metrics = []
        
        for metric in all_metrics:
            room_id = metric.get('room_id')
            room = next((r for r in rooms if r['id'] == room_id), {})
            condition = room.get('mode')
            
            if condition == 'active':
                active_metrics.append(metric)
            elif condition == 'passive':
                passive_metrics.append(metric)
        
        def avg_metrics(metrics_list, key):
            values = [m.get(key) for m in metrics_list if m.get(key) is not None]
            return sum(values) / len(values) if values else 0
        
        summary = {
            "total_sessions": len(rooms),
            "active_sessions": len(active_metrics),
            "passive_sessions": len(passive_metrics),
            "active": {
                "avg_gini": avg_metrics(active_metrics, 'gini_coefficient'),
                "avg_dominance_gap": avg_metrics(active_metrics, 'dominance_gap'),
                "avg_conflict_count": avg_metrics(active_metrics, 'conflict_count'),
                "avg_repair_rate": avg_metrics(active_metrics, 'repair_rate'),
                "avg_accuracy": avg_metrics(active_metrics, 'ranking_accuracy'),
                "avg_messages": avg_metrics(active_metrics, 'total_messages'),
                "avg_time_to_consensus": avg_metrics(active_metrics, 'time_to_consensus'),
                "total_interventions": sum(metric.get('intervention_count', 0) for metric in active_metrics)
            },
            "passive": {
                "avg_gini": avg_metrics(passive_metrics, 'gini_coefficient'),
                "avg_dominance_gap": avg_metrics(passive_metrics, 'dominance_gap'),
                "avg_conflict_count": avg_metrics(passive_metrics, 'conflict_count'),
                "avg_repair_rate": avg_metrics(passive_metrics, 'repair_rate'),
                "avg_accuracy": avg_metrics(passive_metrics, 'ranking_accuracy'),
                "avg_messages": avg_metrics(passive_metrics, 'total_messages'),
                "avg_time_to_consensus": avg_metrics(passive_metrics, 'time_to_consensus'),
                "total_interventions": sum(metric.get('intervention_count', 0) for metric in passive_metrics)
            }
        }
        
        return jsonify(summary)
        
    except Exception as e:
        logger.error(f"❌ Error getting research summary: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# Priority 6 — AUTHORITATIVE research metrics (research_metrics_v2)
# ============================================================
def _assemble_metric_inputs(room_id: str):
    """Authoritative metrics for a room via the SINGLE DB-only path (8.3).

    Delegates to event_log.compute_room_metrics so export, finalization, and
    reconstruction all use the exact same reproducible computation.
    """
    return EV.compute_room_metrics(room_id)


@admin_bp.route('/research/metrics/<room_id>/v2', methods=['GET'])
def get_room_metrics_v2(room_id):
    """Full authoritative metric set (participants + room summary + timelines)."""
    try:
        return jsonify(_assemble_metric_inputs(room_id))
    except Exception as e:
        logger.error(f"❌ metrics_v2 error for {room_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def _csv_response(rows, fieldnames, filename):
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return resp


@admin_bp.route('/research/metrics/<room_id>/export', methods=['GET'])
def export_room_metrics_v2(room_id):
    """Export metrics. format=json|csv, level=participant|summary (csv only)."""
    fmt = (request.args.get('format', 'json') or 'json').lower()
    level = (request.args.get('level', 'participant') or 'participant').lower()
    try:
        result = _assemble_metric_inputs(room_id)
        if fmt == 'json':
            return jsonify(result)

        if level == 'summary':
            row = dict(result["room_summary"])
            row["interventions_by_type"] = json.dumps(row.get("interventions_by_type", {}))
            return _csv_response([row], list(row.keys()), f"room_{room_id}_summary.csv")

        # default: one row per participant
        rows = result["participants"]
        fields = (rows[0].keys() if rows else
                  ["participant_id", "message_count", "turn_count", "turn_share",
                   "speaking_time_ms", "speaking_time_share", "avg_turn_duration_ms"])
        return _csv_response(rows, list(fields), f"room_{room_id}_participants.csv")
    except Exception as e:
        logger.error(f"❌ export metrics_v2 error for {room_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


_TIMELINE_NAMES = {
    "speaking_share_timeline", "consensus_timeline",
    "intervention_timeline", "participation_timeline",
}


@admin_bp.route('/research/metrics/<room_id>/timeline/<name>', methods=['GET'])
def get_metrics_timeline(room_id, name):
    """Clean JSON for one visualization timeline (no charts, just data)."""
    if name not in _TIMELINE_NAMES:
        return jsonify({"error": f"unknown timeline; expected one of {sorted(_TIMELINE_NAMES)}"}), 400
    try:
        result = _assemble_metric_inputs(room_id)
        return jsonify({"room_id": room_id, "timeline": name, "data": result["timelines"].get(name, [])})
    except Exception as e:
        logger.error(f"❌ timeline error for {room_id}/{name}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/research/session/<room_id>/reconstruct', methods=['GET'])
def reconstruct_session_endpoint(room_id):
    """Rebuild a whole session FROM THE DATABASE ONLY (8.3) — no runtime memory.

    Answers: what happened (events), who spoke how much (metrics), how the moderator
    intervened (interventions), how it evolved (timelines), and which condition.
    """
    try:
        return jsonify(EV.reconstruct_session(room_id))
    except Exception as e:
        logger.error(f"❌ reconstruct error for {room_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/research/session/<room_id>/finalize', methods=['POST'])
def finalize_session_endpoint(room_id):
    """Manually freeze a session's research record (snapshot + metrics + summary)."""
    try:
        return jsonify(EV.finalize_session(room_id))
    except Exception as e:
        logger.error(f"❌ finalize error for {room_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/research/mode', methods=['GET'])
def research_mode():
    """P5: report freeze + read-only status (drives the freeze banner in the UI)."""
    import frozen_schema
    return jsonify(frozen_schema.freeze_manifest())


@admin_bp.route('/research/preflight', methods=['GET'])
def research_preflight():
    """Schema preflight: which required tables/columns exist. ok=false => /join refuses sessions."""
    from supabase_client import check_required_schema
    try:
        return jsonify(check_required_schema())
    except Exception as e:
        logger.error(f"❌ preflight error: {e}", exc_info=True)
        return jsonify({"ok": False, "missing": ["preflight_error"], "error": str(e)}), 200


def _event_counts(events):
    by_type, fail_by_kind = {}, {}
    for e in events:
        et = e.get("event_type")
        by_type[et] = by_type.get(et, 0) + 1
        if et == "failure":
            kind = (e.get("payload_json") or {}).get("kind", "unknown")
            fail_by_kind[kind] = fail_by_kind.get(kind, 0) + 1
    return by_type, fail_by_kind


@admin_bp.route('/observability/overview', methods=['GET'])
def observability_overview():
    """P4: active sessions + STT/TTS failure rates + LLM/provider fallback rate."""
    try:
        rooms = supabase.table("rooms").select("id, mode, status, created_at")\
            .in_("status", ["active", "waiting"]).execute().data or []
        # Aggregate the recent event stream (cap to keep it light).
        events = supabase.table("event_log").select("event_type, payload_json")\
            .order("timestamp", desc=True).limit(2000).execute().data or []
        by_type, fail_by_kind = _event_counts(events)

        def _rate(fails, total):
            return round(fails / total, 4) if total else 0.0

        stt_total = by_type.get("stt", 0)
        tts_total = by_type.get("tts", 0)
        return jsonify({
            "active_sessions": [{"room_id": r["id"], "mode": r.get("mode"),
                                 "status": r.get("status"), "created_at": r.get("created_at")} for r in rooms],
            "active_session_count": len(rooms),
            "events_sampled": len(events),
            "event_counts": by_type,
            "stt_failure_rate": _rate(fail_by_kind.get("stt", 0), stt_total),
            "tts_failure_rate": _rate(fail_by_kind.get("tts", 0), tts_total),
            "llm_fallback_count": fail_by_kind.get("llm_fallback", 0) + fail_by_kind.get("tts_provider_fallback", 0),
            "failure_counts_by_kind": fail_by_kind,
        })
    except Exception as e:
        logger.error(f"❌ observability overview error: {e}", exc_info=True)
        return jsonify({"error": str(e), "active_sessions": [], "event_counts": {}}), 200


@admin_bp.route('/observability/events', methods=['GET'])
def observability_events():
    """P4: recent event_log stream (poll for a live view). ?room_id=&limit="""
    try:
        limit = min(int(request.args.get('limit', 100)), 1000)
        q = supabase.table("event_log").select("*").order("timestamp", desc=True).limit(limit)
        rid = request.args.get('room_id')
        if rid:
            q = q.eq("room_id", rid)
        return jsonify({"events": q.execute().data or []})
    except Exception as e:
        logger.error(f"❌ observability events error: {e}", exc_info=True)
        return jsonify({"error": str(e), "events": []}), 200


@admin_bp.route('/observability/session/<room_id>/health', methods=['GET'])
def observability_session_health(room_id):
    """P4: lightweight per-session health (counts + last finalization verdict)."""
    try:
        events = supabase.table("event_log").select("event_type, payload_json, timestamp")\
            .eq("room_id", room_id).order("timestamp", desc=True).limit(1000).execute().data or []
        by_type, fail_by_kind = _event_counts(events)
        finalization = None
        for e in events:  # newest first
            p = e.get("payload_json") or {}
            if e.get("event_type") == "session" and p.get("finalization"):
                finalization = p.get("finalization")
                break
        return jsonify({
            "room_id": room_id,
            "event_counts": by_type,
            "failure_counts_by_kind": fail_by_kind,
            "total_failures": sum(fail_by_kind.values()),
            "last_event_at": events[0]["timestamp"] if events else None,
            "finalization_status": finalization,
            "health": "ok" if sum(fail_by_kind.values()) == 0 else "degraded",
        })
    except Exception as e:
        logger.error(f"❌ session health error for {room_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 200


@admin_bp.route('/research/session/<room_id>/validate', methods=['GET'])
def validate_session_endpoint(room_id):
    """Full integrity report: consistency (C) + condition audit (D) + failures (E) + readiness (G)."""
    try:
        v = EV.validate_session(room_id)
        # Trim the heavy metrics blob from this view; it's available via /v2.
        v.pop("metrics", None)
        return jsonify(v)
    except Exception as e:
        logger.error(f"❌ validate error for {room_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/research/validate_experiment_ready/<room_id>', methods=['GET'])
def validate_experiment_ready(room_id):
    """Priority G: PASS/FAIL + missing components + integrity + reproducibility scores."""
    try:
        return jsonify(EV.validate_session(room_id)["readiness"])
    except Exception as e:
        logger.error(f"❌ readiness error for {room_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/research/experiment_readiness_final/<room_id>', methods=['GET'])
def experiment_readiness_final(room_id):
    """Final lock readiness: prereg lock + schema completeness + passive constraints +
    reproducibility + dataset integrity → READY / NOT READY."""
    import frozen_schema as FS
    import preregistration as PR
    import validation as V
    try:
        v = EV.validate_session(room_id)
        metrics = v.get("metrics", {})
        condition = v.get("experiment_condition")

        prereg = PR.verify()
        schema = V.check_schema_completeness(metrics, FS.LOCKED_METRIC_NAMES)
        passive = V.audit_passive_constraints(
            condition,
            EV.gather_room_inputs(room_id).get("interventions", []),
            set(FS.PASSIVE_ALLOWED_INTERVENTIONS),
        )

        missing = []
        if not prereg["matches"]:
            missing.append("preregistration_lock")
        if not schema["passed"]:
            missing.append("dataset_schema")
        if not passive["passed"]:
            missing.append("passive_constraint")
        if v["readiness"]["status"] != "PASS":
            missing.extend(v["readiness"]["missing_components"])

        ready = (
            not missing
            and v["reproducibility_score"] >= 0.999
            and v["consistency"]["passed"]
            and v["condition_audit"]["passed"]
        )
        return jsonify({
            "status": "READY" if ready else "NOT READY",
            "missing_components": sorted(set(missing)),
            "schema_completeness_score": schema["completeness_score"],
            "reproducibility_score": v["reproducibility_score"],
            "dataset_integrity_score": v["consistency"]["integrity_score"],
            "preregistration": prereg,
            "passive_constraint_audit": passive,
            "session_readiness": v["readiness"],
            "freeze": FS.freeze_manifest(),
        })
    except Exception as e:
        logger.error(f"❌ final readiness error for {room_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/research/preregistration', methods=['GET'])
def get_preregistration():
    """Serve the (immutable-during-study) pre-registration + its lock status."""
    import preregistration as PR
    return jsonify({"preregistration": PR.load_preregistration(), "lock": PR.verify()})


def _rows_to_csv(rows):
    """Serialize a list of dicts to CSV (union of keys; dict/list cells JSON-encoded)."""
    if not rows:
        return ""
    fields = []
    for r in rows:
        for k in r.keys():
            if k not in fields:
                fields.append(k)
    buf = StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
    return buf.getvalue()


@admin_bp.route('/export/paper_bundle/<room_id>', methods=['GET'])
def export_paper_bundle(room_id):
    """Priority F: a self-contained research artifact bundle (ZIP), reproducible offline.

    Contains: event_log.csv, metrics_v2.json, room_state_snapshot.json,
    intervention_log.csv, timeline.json, failure_report.json, session_metadata.json.
    """
    try:
        import frozen_schema
        room = get_room(room_id) or {}
        v = EV.validate_session(room_id)
        recon = EV.reconstruct_session(room_id)

        events = recon.get("events", [])
        interventions = recon.get("interventions", [])
        metrics = v.get("metrics", {})

        snapshot = None
        try:
            snaps = supabase.table("room_state_snapshots").select("*").eq("room_id", room_id).execute().data or []
            snapshot = snaps[-1] if snaps else None
        except Exception:
            snapshot = None

        metadata = {
            "room_id": room_id,
            "experiment_condition": v.get("experiment_condition"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "readiness": v.get("readiness"),
            "reproducibility_score": v.get("reproducibility_score"),
            "freeze_manifest": frozen_schema.freeze_manifest(),
            "room": {k: room.get(k) for k in ("id", "mode", "status", "created_at", "ended_at", "story_id")},
        }

        files = {
            "event_log.csv": _rows_to_csv(events),
            "metrics_v2.json": json.dumps(metrics, indent=2),
            "room_state_snapshot.json": json.dumps(snapshot or {}, indent=2),
            "intervention_log.csv": _rows_to_csv(interventions),
            "timeline.json": json.dumps(metrics.get("timelines", {}), indent=2),
            "failure_report.json": json.dumps(v.get("failure_report", {}), indent=2),
            "session_metadata.json": json.dumps(metadata, indent=2),
        }

        mem = BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        mem.seek(0)
        return send_file(mem, mimetype="application/zip", as_attachment=True,
                         download_name=f"paper_bundle_{room_id}.zip")
    except Exception as e:
        logger.error(f"❌ paper_bundle error for {room_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/research/metrics/export/summary', methods=['GET'])
def export_all_room_summaries():
    """One summary row per room across ALL rooms — for cross-condition analysis.
    format=json|csv. Computes on the fly; use sparingly on large datasets."""
    fmt = (request.args.get('format', 'csv') or 'csv').lower()
    try:
        rooms = supabase.table("rooms").select("id").order("created_at", desc=True).execute().data or []
        summaries = []
        for r in rooms:
            rid = r.get("id")
            if not rid:
                continue
            try:
                s = dict(_assemble_metric_inputs(rid)["room_summary"])
                s["interventions_by_type"] = json.dumps(s.get("interventions_by_type", {}))
                summaries.append(s)
            except Exception as inner:
                logger.debug(f"summary skipped for {rid}: {inner}")
        if fmt == 'json':
            return jsonify({"count": len(summaries), "rooms": summaries})
        fields = list(summaries[0].keys()) if summaries else ["room_id", "condition"]
        return _csv_response(summaries, fields, "all_rooms_summary.csv")
    except Exception as e:
        logger.error(f"❌ export all summaries error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500