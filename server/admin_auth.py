from __future__ import annotations

# ============================================================
# 🔐 admin_auth.py — username/password login for the admin panel
# ------------------------------------------------------------
# Replaces "paste the shared ADMIN_TOKEN into the browser" with a real login.
#
# How it works
#   1. POST /admin/login {username, password} → credentials checked against
#      ADMIN_USERNAME + ADMIN_PASSWORD_HASH (env; single admin).
#   2. On success the server mints a STATELESS, HMAC-signed, time-limited session
#      token and returns it. The client sends it back as X-Admin-Token on every
#      /admin/* request, exactly like before.
#   3. Every guard calls authorize_request(), which accepts EITHER a valid session
#      token OR the legacy raw ADMIN_TOKEN — so existing curl/export scripts and
#      research tooling keep working unchanged mid-study.
#
# Stateless by design: no session table, no server-side store. That matters here
# because Render free-tier restarts the process regularly and room state is already
# process-local — a server-side session store would log you out on every restart.
# The signing secret is derived deterministically (see _session_secret) so tokens
# survive restarts but are invalidated the moment the password changes.
#
# No new dependencies: PBKDF2-HMAC-SHA256 and HMAC are both stdlib.
# ============================================================

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("admin-auth")

# ---- password hashing -------------------------------------------------------
_HASH_SCHEME = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 390_000
_SALT_BYTES = 16

# ---- session tokens ---------------------------------------------------------
_DEFAULT_SESSION_TTL_HOURS = 12.0

# ---- login throttling -------------------------------------------------------
# A password is far easier to brute-force than a 32-byte random token, so the
# login route (and only the login route) is rate-limited per client IP.
_MAX_FAILED_ATTEMPTS = 5
_ATTEMPT_WINDOW_S = 15 * 60      # failures older than this are forgotten
_LOCKOUT_S = 15 * 60             # lockout duration once the limit is hit
_MAX_TRACKED_IPS = 2048          # bound the dict so it can't grow unbounded

_attempts: Dict[str, Dict[str, float]] = {}
_attempts_lock = threading.Lock()


# ============================================================
# Configuration helpers (read per-call so env changes take effect on redeploy)
# ============================================================
def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def admin_username() -> str:
    return _env("ADMIN_USERNAME", "admin")


def session_ttl_seconds() -> int:
    try:
        hours = float(_env("ADMIN_SESSION_TTL_HOURS") or _DEFAULT_SESSION_TTL_HOURS)
    except ValueError:
        hours = _DEFAULT_SESSION_TTL_HOURS
    return int(max(0.25, hours) * 3600)


def login_enabled() -> bool:
    """True when username/password login is usable (a credential is configured)."""
    return bool(_env("ADMIN_PASSWORD_HASH") or _env("ADMIN_PASSWORD"))


def legacy_token_enabled() -> bool:
    """True when the raw ADMIN_TOKEN header is still accepted (scripts/curl)."""
    return bool(_env("ADMIN_TOKEN"))


# ============================================================
# Password hashing
# ============================================================
def hash_password(password: str, iterations: int = _DEFAULT_ITERATIONS) -> str:
    """Hash a plaintext password into the storable `pbkdf2_sha256$...` format."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_HASH_SCHEME}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time check of `password` against a stored pbkdf2_sha256 hash."""
    try:
        scheme, iter_s, salt_hex, digest_hex = stored_hash.split("$", 3)
        if scheme != _HASH_SCHEME:
            logger.error("Unsupported ADMIN_PASSWORD_HASH scheme: %r", scheme)
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iter_s)
        )
        return hmac.compare_digest(actual, expected)
    except Exception as e:
        logger.error("Malformed ADMIN_PASSWORD_HASH (%s) — login cannot succeed", e)
        return False


def verify_credentials(username: str, password: str) -> bool:
    """Check a username/password pair. Fails closed when nothing is configured."""
    if not username or not password:
        return False

    # Compare the username in constant time too, so response timing doesn't reveal
    # whether the username was the part that was wrong.
    user_ok = hmac.compare_digest(username.strip(), admin_username())

    stored_hash = _env("ADMIN_PASSWORD_HASH")
    if stored_hash:
        pass_ok = verify_password(password, stored_hash)
    else:
        # Dev convenience: plaintext ADMIN_PASSWORD. Noisy on purpose.
        plaintext = _env("ADMIN_PASSWORD")
        if not plaintext:
            logger.error(
                "🔒 Admin login attempted but neither ADMIN_PASSWORD_HASH nor "
                "ADMIN_PASSWORD is set — refusing (fail closed)"
            )
            return False
        logger.warning(
            "⚠️ Admin login is using plaintext ADMIN_PASSWORD. Set ADMIN_PASSWORD_HASH "
            "instead: python admin_auth.py hash '<password>'"
        )
        pass_ok = hmac.compare_digest(password, plaintext)

    return user_ok and pass_ok


# ============================================================
# Stateless session tokens (HMAC-signed, time-limited)
# ============================================================
def _session_secret() -> bytes:
    """Key used to sign session tokens.

    Prefers an explicit ADMIN_SESSION_SECRET. Otherwise it is DERIVED from the
    password hash + ADMIN_TOKEN, which gives two useful properties for free:
      * deterministic → sessions survive a server restart (Render restarts often)
      * changing the password or token invalidates every issued session
    """
    explicit = _env("ADMIN_SESSION_SECRET")
    if explicit:
        return explicit.encode("utf-8")
    material = _env("ADMIN_PASSWORD_HASH") + "\x00" + _env("ADMIN_PASSWORD") + "\x00" + _env("ADMIN_TOKEN")
    return hashlib.sha256(("admin-session-v1" + material).encode("utf-8")).digest()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_session_token(username: str) -> Tuple[str, int]:
    """Mint a signed session token. Returns (token, expires_at_epoch_seconds)."""
    now = int(time.time())
    expires_at = now + session_ttl_seconds()
    payload = {"u": username, "iat": now, "exp": expires_at}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(_session_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64e(signature)}", expires_at


def verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Return the token payload if the signature is valid and it hasn't expired."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, signature_b64 = token.rsplit(".", 1)
        expected = hmac.new(_session_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(signature_b64), expected):
            return None
        payload = json.loads(_b64d(payload_b64))
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ============================================================
# Login throttling
# ============================================================
def _client_ip(headers: Any, remote_addr: Optional[str]) -> str:
    """Best-effort client IP. Render/Vercel put the real client in X-Forwarded-For."""
    try:
        forwarded = headers.get("X-Forwarded-For") or ""
    except Exception:
        forwarded = ""
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (remote_addr or "unknown")[:64]


def login_lockout_remaining(ip: str) -> int:
    """Seconds remaining before `ip` may attempt a login again (0 = allowed now)."""
    now = time.time()
    with _attempts_lock:
        entry = _attempts.get(ip)
        if not entry:
            return 0
        locked_until = entry.get("locked_until", 0.0)
        if locked_until > now:
            return int(locked_until - now) + 1
        # Lockout expired, or the failure window lapsed → forget this IP.
        if locked_until or (now - entry.get("first_failure", now)) > _ATTEMPT_WINDOW_S:
            _attempts.pop(ip, None)
        return 0


def record_login_failure(ip: str) -> int:
    """Count a failed attempt. Returns seconds of lockout now in effect (0 = none)."""
    now = time.time()
    with _attempts_lock:
        # Bound memory: drop the oldest tracked IPs if the table gets large.
        if len(_attempts) > _MAX_TRACKED_IPS:
            for stale_ip in sorted(
                _attempts, key=lambda k: _attempts[k].get("first_failure", 0.0)
            )[: len(_attempts) // 2]:
                _attempts.pop(stale_ip, None)

        entry = _attempts.get(ip)
        if not entry or (now - entry.get("first_failure", now)) > _ATTEMPT_WINDOW_S:
            entry = {"count": 0.0, "first_failure": now, "locked_until": 0.0}
            _attempts[ip] = entry

        entry["count"] += 1
        if entry["count"] >= _MAX_FAILED_ATTEMPTS:
            entry["locked_until"] = now + _LOCKOUT_S
            logger.warning(
                "🔒 Admin login locked out %s for %ds after %d failed attempts",
                ip, _LOCKOUT_S, int(entry["count"]),
            )
            return _LOCKOUT_S
    return 0


def clear_login_failures(ip: str) -> None:
    with _attempts_lock:
        _attempts.pop(ip, None)


# ============================================================
# The single authorization entry point used by every admin guard
# ============================================================
def authorize_request(headers: Any) -> Tuple[bool, Optional[str]]:
    """Authorize an /admin/* request from its headers.

    Accepts, in order:
      1. a valid signed session token (from /admin/login)   → ("<username>")
      2. the legacy raw ADMIN_TOKEN                          → ("admin_token")

    Returns (authorized, principal). Fails closed when nothing is configured.
    """
    try:
        provided = headers.get("X-Admin-Token") or ""
    except Exception:
        provided = ""
    if not provided:
        return False, None

    payload = verify_session_token(provided)
    if payload:
        return True, str(payload.get("u") or admin_username())

    expected = _env("ADMIN_TOKEN")
    if expected and hmac.compare_digest(provided, expected):
        return True, "admin_token"

    return False, None


def auth_status() -> Dict[str, Any]:
    """Non-sensitive summary of how admin auth is configured (for /admin/session)."""
    return {
        "login_enabled": login_enabled(),
        "legacy_token_enabled": legacy_token_enabled(),
        "username": admin_username(),
        "session_ttl_seconds": session_ttl_seconds(),
        "password_hashed": bool(_env("ADMIN_PASSWORD_HASH")),
    }


# ============================================================
# CLI: generate a password hash for ADMIN_PASSWORD_HASH
#   python admin_auth.py hash 'my-password'
# ============================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "hash":
        pw = sys.argv[2] if len(sys.argv) > 2 else ""
        if not pw:
            import getpass

            pw = getpass.getpass("New admin password: ")
            if pw != getpass.getpass("Confirm password: "):
                print("❌ Passwords did not match.")
                sys.exit(1)
        if len(pw) < 8:
            print("❌ Use at least 8 characters.")
            sys.exit(1)
        print("\nAdd this to server/.env (and to Render's environment):\n")
        print(f"ADMIN_PASSWORD_HASH={hash_password(pw)}\n")
    else:
        print(__doc__ or "")
        print("Usage: python admin_auth.py hash '<password>'")
        print("       python admin_auth.py hash          (prompts, no shell history)")
