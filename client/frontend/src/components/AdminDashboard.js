// =========================
// Admin Dashboard - COMPLETELY FIXED VERSION
// =========================
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom'; // ✅ ADD THIS IMPORT
import { 
  MdSettings, 
  MdPeople, 
  MdLink, 
  MdDelete, 
  MdRefresh, 
  MdVisibility, 
  MdContentCopy,
  MdDashboard,
  MdHistory,
  MdSecurity,
  MdCheckCircle,
  MdEdit,
  MdCancel,
  MdSave,
  MdAdd,
  MdDownload,
  MdFileDownload,
  MdVolumeUp,
  MdExitToApp,
  MdStop,
  MdChat,
  MdGroup,
  MdPsychology,
  MdAutoMode,
  MdMenu,
  MdClose
} from 'react-icons/md';

const API_URL = process.env.REACT_APP_API_URL || 'https://llm-moderator-main.onrender.com';
const FRONTEND_URL = window.location.origin;

// Admin session. The panel is gated by a username/password login (POST /admin/login),
// which returns a signed, time-limited token. That token is sent as X-Admin-Token on
// every /admin/* request. NOTE: never reintroduce REACT_APP_ADMIN_TOKEN here — CRA
// inlines REACT_APP_* into the public bundle, which would hand the admin credential
// to anyone who opens the site.
const ADMIN_FETCH_TIMEOUT_MS = 20000;
const SESSION_KEY = 'adminSession';

const loadStoredSession = () => {
  try {
    const stored = JSON.parse(localStorage.getItem(SESSION_KEY) || 'null');
    if (!stored?.token || !stored?.expiresAt) return null;
    if (stored.expiresAt * 1000 <= Date.now()) {
      localStorage.removeItem(SESSION_KEY);
      return null;
    }
    return stored;
  } catch (_) {
    return null;
  }
};

const storeSession = (session) => {
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else localStorage.removeItem(SESSION_KEY);
  } catch (_) { /* private browsing / quota — session just won't persist */ }
};

const adminFetch = (url, token, options = {}, timeoutMs = ADMIN_FETCH_TIMEOUT_MS) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, {
    ...options,
    signal: controller.signal,
    headers: { ...(options.headers || {}), 'X-Admin-Token': token },
  }).finally(() => clearTimeout(timer));
};

// =========================
// Login screen — shown until a valid session exists
// =========================
function AdminLogin({ onSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), ADMIN_FETCH_TIMEOUT_MS);
      const res = await fetch(`${API_URL}/admin/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
        signal: controller.signal,
      }).finally(() => clearTimeout(timer));

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        if (res.status === 429 && data.retry_after_seconds) {
          const mins = Math.ceil(data.retry_after_seconds / 60);
          setError(`${data.error} Locked for about ${mins} minute${mins === 1 ? '' : 's'}.`);
        } else {
          setError(data.error || `Login failed (HTTP ${res.status}).`);
        }
        setPassword('');
        return;
      }

      onSuccess({
        token: data.token,
        username: data.username,
        expiresAt: data.expires_at,
      });
    } catch (err) {
      setError(
        err.name === 'AbortError'
          ? `The server did not respond within ${ADMIN_FETCH_TIMEOUT_MS / 1000}s. It may be asleep (Render free tier) — wait a moment and try again.`
          : `Could not reach the server at ${API_URL}: ${err.message}`
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 font-body flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-indigo-500 to-violet-650 flex items-center justify-center shadow-lg shadow-indigo-100">
            <MdSecurity className="text-2xl text-white" />
          </div>
          <h1 className="text-xl font-bold text-slate-800 tracking-tight mt-4">Moderator Control Panel</h1>
          <p className="text-xs text-slate-400 font-semibold tracking-wide uppercase mt-1">Administrator sign in</p>
        </div>

        <form
          onSubmit={submit}
          className="bg-white border border-slate-200 rounded-2xl shadow-sm p-6 space-y-4"
        >
          <div>
            <label htmlFor="admin-username" className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              Username
            </label>
            <input
              id="admin-username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
              disabled={busy}
              className="w-full px-3.5 py-2.5 text-sm border border-slate-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-50"
            />
          </div>

          <div>
            <label htmlFor="admin-password" className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">
              Password
            </label>
            <input
              id="admin-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              disabled={busy}
              className="w-full px-3.5 py-2.5 text-sm border border-slate-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-50"
            />
          </div>

          {error && (
            <div className="bg-rose-50 border border-rose-200 rounded-lg px-3.5 py-2.5 text-xs text-rose-700 leading-relaxed">
              ⚠️ {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy || !username.trim() || !password}
            className="btn-primary w-full py-2.5 text-sm font-bold disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="text-[11px] text-slate-400 text-center mt-5 leading-relaxed">
          Credentials are set on the server via <span className="font-mono">ADMIN_USERNAME</span> and{' '}
          <span className="font-mono">ADMIN_PASSWORD_HASH</span>.
        </p>
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const navigate = useNavigate(); // ✅ ADD THIS LINE
  const [activeTab, setActiveTab] = useState('dashboard');
  const [session, setSession] = useState(loadStoredSession);
  // Every existing call site reads `adminToken`; it now comes from the login session.
  const adminToken = session?.token || '';
  const [rooms, setRooms] = useState([]);
  const [stats, setStats] = useState(null);
  const [settings, setSettings] = useState([]);
  const [selectedRoom, setSelectedRoom] = useState(null);
  const [loading, setLoading] = useState(false);
  const [exportingRecordingId, setExportingRecordingId] = useState(null);
  const [connectionStatus, setConnectionStatus] = useState('idle'); // idle | loading | ok | error
  const [authError, setAuthError] = useState(null); // visible reason loads fail (e.g. 401)
  const [loginNotice, setLoginNotice] = useState(null); // shown on the login screen after sign-out/expiry
  const [adminLogs, setAdminLogs] = useState([]);
  const [showCreateRoomModal, setShowCreateRoomModal] = useState(false);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [newRoomData, setNewRoomData] = useState({
    mode: 'active',
    max_participants: 3,
    story_id: '',
    admin_note: ''
  });

  // Load data once a session exists (on mount if one was restored, or right after login).
  useEffect(() => {
    if (!adminToken) return;
    loadDashboardData(adminToken);
    loadSettings(adminToken);
    loadAdminLogs(adminToken);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminToken]);

  // Expire the session in-place so a long-idle tab returns to the login screen
  // instead of firing doomed 401s.
  useEffect(() => {
    if (!session?.expiresAt) return;
    const msLeft = session.expiresAt * 1000 - Date.now();
    if (msLeft <= 0) {
      signOut('Your session expired. Please sign in again.');
      return;
    }
    const timer = setTimeout(
      () => signOut('Your session expired. Please sign in again.'),
      msLeft
    );
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    // Event listeners for Quick Actions
    const handleTabChange = (e) => {
      setActiveTab(e.detail.tab);
    };

    const handleOpenCreateRoom = () => {
      setShowCreateRoomModal(true);
    };

    window.addEventListener('admin:changeTab', handleTabChange);
    window.addEventListener('admin:openCreateRoom', handleOpenCreateRoom);

    return () => {
      window.removeEventListener('admin:changeTab', handleTabChange);
      window.removeEventListener('admin:openCreateRoom', handleOpenCreateRoom);
    };
  }, []);

  const signIn = (newSession) => {
    storeSession(newSession);
    setSession(newSession);
    setAuthError(null);
    setLoginNotice(null);
  };

  const signOut = (notice = null) => {
    const token = session?.token;
    // Best-effort audit entry; the token is stateless so logout is a local discard.
    if (token) {
      adminFetch(`${API_URL}/admin/logout`, token, { method: 'POST' }).catch(() => {});
    }
    storeSession(null);
    setSession(null);
    setRooms([]);
    setStats(null);
    setSettings([]);
    setAdminLogs([]);
    setSelectedRoom(null);
    setActiveTab('dashboard');
    setConnectionStatus('idle');
    setAuthError(null);
    setLoginNotice(notice);
  };

  // A 401 mid-session means the token was revoked (password/secret changed) or expired.
  const handleUnauthorized = () => {
    signOut('Your session is no longer valid. Please sign in again.');
  };

  const formatFetchError = (err) => {
    if (err?.name === 'AbortError') {
      return (
        `Request timed out after ${ADMIN_FETCH_TIMEOUT_MS / 1000}s. ` +
        `The backend at ${API_URL} may be asleep (Render free tier), down, or stuck on a database call. ` +
        `Try running the server locally (python app.py) or wait for Render to wake up, then click Retry.`
      );
    }
    return `Could not reach the server: ${err.message}. Is the backend running on ${API_URL}?`;
  };

  const loadDashboardData = async (token = adminToken) => {
    try {
      setLoading(true);
      setConnectionStatus('loading');
      const [roomsRes, statsRes] = await Promise.all([
        adminFetch(`${API_URL}/admin/rooms`, token),
        adminFetch(`${API_URL}/admin/stats`, token),
      ]);

      // Surface auth/HTTP failures instead of silently treating a 401 body as data.
      if (roomsRes.status === 401 || statsRes.status === 401) {
        setConnectionStatus('error');
        handleUnauthorized();
        return;
      }
      if (!roomsRes.ok || !statsRes.ok) {
        setAuthError(`Server error loading dashboard (rooms ${roomsRes.status}, stats ${statsRes.status}).`);
        setConnectionStatus('error');
        return;
      }

      const roomsData = await roomsRes.json();
      const statsData = await statsRes.json();

      setRooms(roomsData.rooms || []);
      setStats(statsData);
      setAuthError(null);
      setConnectionStatus('ok');
    } catch (err) {
      console.error('Failed to load data:', err);
      setAuthError(formatFetchError(err));
      setConnectionStatus('error');
    } finally {
      setLoading(false); // ALWAYS reset — never leave the panel stuck "Refreshing..."
    }
  };

  const loadSettings = async (token = adminToken) => {
    try {
      const res = await adminFetch(`${API_URL}/admin/settings`, token);
      if (res.status === 401) { handleUnauthorized(); return; }
      const data = await res.json();
      setSettings(data.settings || []);
    } catch (err) {
      console.error('Failed to load settings:', err);
    }
  };

  const loadAdminLogs = async (token = adminToken) => {
    try {
      const res = await adminFetch(`${API_URL}/admin/logs`, token);
      if (res.status === 401) { handleUnauthorized(); return; }
      const data = await res.json();
      setAdminLogs(data.logs || []);
    } catch (err) {
      console.error('Failed to load admin logs:', err);
    }
  };

  const reloadAll = (token = adminToken) => {
    loadDashboardData(token);
    loadSettings(token);
    loadAdminLogs(token);
  };

  const fetchAdmin = (url, options) => adminFetch(url, adminToken, options);

  const updateSetting = async (key, value) => {
    try {
      setLoading(true);
      await fetchAdmin(`${API_URL}/admin/settings/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value, updated_by: 'admin' })
      });
      await loadSettings();
      alert(`✅ Setting "${key}" updated successfully.`);
    } catch (err) {
      console.error('Failed to update setting:', err);
      alert(`❌ Failed to update setting: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const deleteRoom = async (roomId) => {
    if (!window.confirm('Are you sure you want to delete this room? This cannot be undone.')) {
      return;
    }

    try {
      const res = await fetchAdmin(`${API_URL}/admin/rooms/${roomId}`, {
        method: 'DELETE'
      });

      if (!res.ok) {
        throw new Error('Failed to delete room');
      }

      alert('✅ Room deleted successfully');
      await loadDashboardData();
      if (selectedRoom?.room?.id === roomId) {
        setSelectedRoom(null);
        setActiveTab('rooms');
      }
    } catch (err) {
      console.error('Failed to delete room:', err);
      alert(`❌ Failed to delete room: ${err.message}`);
    }
  };

  const viewRoomDetails = async (roomId) => {
    try {
      setLoading(true);
      const res = await fetchAdmin(`${API_URL}/admin/rooms/${roomId}`);
      const data = await res.json();
      setSelectedRoom(data);
      setActiveTab('room-detail');
    } catch (err) {
      console.error('Failed to load room details:', err);
      alert(`Failed to load room details: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const createAdminRoom = async () => {
    try {
      setLoading(true);
      const res = await fetchAdmin(`${API_URL}/admin/rooms`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...newRoomData,
          admin_user: 'admin'
        })
      });

      const data = await res.json();
      
      if (!res.ok) {
        throw new Error(data.error || 'Failed to create room');
      }

      alert(`✅ Room created successfully!\nRoom ID: ${data.room.id}\nShareable Link: ${FRONTEND_URL}${data.shareable_link}`);
      setShowCreateRoomModal(false);
      setNewRoomData({
        mode: 'active',
        max_participants: 3,
        story_id: '',
        admin_note: ''
      });
      await loadDashboardData();
      await loadAdminLogs();
    } catch (err) {
      console.error('Failed to create room:', err);
      alert(`❌ Failed to create room: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const exportRoomChat = async (roomId, format) => {
    try {
      const res = await fetchAdmin(`${API_URL}/admin/rooms/${roomId}/export/messages?format=${format}`);
      
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.error || 'Export failed');
      }

      if (format === 'json') {
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `chat_${roomId}_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      } else {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = res.headers.get('Content-Disposition')?.split('filename=')[1] || `chat_${roomId}.${format}`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      }

      alert(`✅ Chat exported successfully as ${format.toUpperCase()}`);
    } catch (err) {
      console.error('Export failed:', err);
      alert(`❌ Export failed: ${err.message}`);
    }
  };

  // Download the room's full spoken conversation as ONE ordered audio file.
  // Admin-gated server endpoint; the private audio bucket is never exposed.
  const downloadRoomRecording = async (roomId) => {
    if (exportingRecordingId === roomId) {
      console.log('⏳ Already downloading this recording');
      return;
    }
    
    try {
      setExportingRecordingId(roomId);
      console.log(`📥 Starting download for room ${roomId}`);
      
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 300000); // 5 minutes — large rooms need lazy TTS generation + clip downloads + ffmpeg assembly
      
      const response = await fetch(`${API_URL}/api/room/${roomId}/recording?format=mp3`, {
        headers: {
          'X-Admin-Token': adminToken
        },
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      if (!response.ok) {
        let errorText = 'Recording export failed';
        try {
          const jsonErr = await response.json();
          errorText = jsonErr.error || errorText;
        } catch (_) {
          try {
            errorText = await response.text();
          } catch (__) {}
        }
        throw new Error(errorText);
      }
      
      const blob = await response.blob();
      console.log(`✅ Download complete: ${blob.size} bytes`);
      
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `room_${roomId}_recording.mp3`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      alert('✅ Conversation recording downloaded');
      
    } catch (err) {
      if (err.name === 'AbortError') {
        console.warn('⏹️ Download was cancelled (timeout or user action)');
        alert('❌ Recording download timed out (exceeded 5 minutes). This room may have too many messages.');
      } else {
        console.error('❌ Recording download failed:', err);
        alert(`❌ Recording download failed: ${err.message}`);
      }
    } finally {
      setExportingRecordingId(null);
    }
  };

  // Export authoritative research metrics (Priority 6). level=participant|summary.
  const downloadRoomMetrics = async (roomId, level = 'participant') => {
    try {
      const res = await fetchAdmin(`${API_URL}/admin/research/metrics/${roomId}/export?format=csv&level=${level}`);
      if (!res.ok) {
        let msg = 'Metrics export failed';
        try { msg = (await res.json()).error || msg; } catch (_) { /* non-JSON */ }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `room_${roomId}_${level}_metrics.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      alert(`✅ Metrics (${level}) exported`);
    } catch (err) {
      console.error('Metrics export failed:', err);
      alert(`❌ Metrics export failed: ${err.message}`);
    }
  };

  const endRoomSession = async (roomId, endType = 'session') => {
    if (!window.confirm(`Are you sure you want to end the ${endType}?`)) {
      return;
    }

    try {
      const res = await fetchAdmin(`${API_URL}/admin/rooms/${roomId}/end`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: endType,
          admin_user: 'admin'
        })
      });

      const data = await res.json();
      
      if (!res.ok) {
        throw new Error(data.error || 'Failed to end session');
      }

      alert(`✅ ${endType === 'story' ? 'Story' : 'Session'} ended successfully`);
      await loadDashboardData();
      if (selectedRoom?.room?.id === roomId) {
        viewRoomDetails(roomId);
      }
    } catch (err) {
      console.error('Failed to end session:', err);
      alert(`❌ Failed to end session: ${err.message}`);
    }
  };

  const updateRoomStatus = async (roomId, status) => {
    try {
      const res = await fetchAdmin(`${API_URL}/admin/rooms/${roomId}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status,
          admin_user: 'admin'
        })
      });

      const data = await res.json();
      
      if (!res.ok) {
        throw new Error(data.error || 'Failed to update status');
      }

      alert(`✅ Room status updated to ${status}`);
      await loadDashboardData();
      if (selectedRoom?.room?.id === roomId) {
        viewRoomDetails(roomId);
      }
    } catch (err) {
      console.error('Failed to update status:', err);
      alert(`❌ Failed to update status: ${err.message}`);
    }
  };

  // Gate: no valid session → the panel is never rendered and no admin request fires.
  if (!session) {
    return (
      <>
        {loginNotice && (
          <div className="fixed top-0 inset-x-0 z-50 bg-amber-50 border-b border-amber-200 px-6 py-3 text-sm text-amber-800 text-center">
            {loginNotice}
          </div>
        )}
        <AdminLogin onSuccess={signIn} />
      </>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 font-body">
      {/* Modern Header */}
      <header className="bg-white/80 backdrop-blur-md border-b border-slate-200 shadow-sm sticky top-0 z-50">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3.5">
              {/* Hamburger Toggle Button for Mobile Navigation */}
              <button 
                onClick={() => setIsMenuOpen(!isMenuOpen)}
                className="block md:hidden p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 focus:outline-none transition-colors"
                aria-label="Toggle Navigation Menu"
              >
                {isMenuOpen ? <MdClose className="text-2xl" /> : <MdMenu className="text-2xl" />}
              </button>

              <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-violet-650 flex items-center justify-center shadow-md shadow-indigo-100">
                <MdSecurity className="text-xl text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-800 tracking-tight leading-tight">Moderator Control Panel</h1>
                <p className="text-xs text-slate-400 font-semibold tracking-wide uppercase mt-0.5">LLM Moderator System Admin</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="hidden md:flex items-center gap-5">
                <div className="text-right">
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Backend</p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    {connectionStatus === 'loading' && (
                      <>
                        <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                        <span className="text-xs text-amber-700 font-bold">Connecting…</span>
                      </>
                    )}
                    {connectionStatus === 'ok' && (
                      <>
                        <span className="pulse-green">
                          <span className="pulse-green-ping"></span>
                          <span className="pulse-green-dot"></span>
                        </span>
                        <span className="text-xs text-emerald-650 font-bold">Connected</span>
                      </>
                    )}
                    {(connectionStatus === 'error' || connectionStatus === 'idle') && (
                      <>
                        <span className="inline-block w-2 h-2 rounded-full bg-rose-500" />
                        <span className="text-xs text-rose-600 font-bold">
                          {connectionStatus === 'idle' ? 'Not loaded' : 'Unreachable'}
                        </span>
                      </>
                    )}
                  </div>
                  <p className="text-[10px] text-slate-400 mt-0.5 truncate max-w-[180px]" title={API_URL}>
                    {API_URL.replace(/^https?:\/\//, '')}
                  </p>
                </div>
                <button
                  onClick={() => reloadAll()}
                  disabled={loading}
                  className="btn-primary py-2.5 px-4 flex items-center gap-2 shadow-sm text-xs font-bold"
                >
                  <MdRefresh className={`text-base ${loading ? 'animate-spin' : ''}`} />
                  <span>{loading ? 'Refreshing...' : 'Refresh Engine'}</span>
                </button>
                <div className="flex items-center gap-2.5 pl-4 border-l border-slate-200">
                  <div className="text-right">
                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Signed in</p>
                    <p className="text-xs font-bold text-slate-700 truncate max-w-[120px]" title={session?.username}>
                      {session?.username}
                    </p>
                  </div>
                  <button
                    onClick={() => signOut()}
                    title="Sign out of the admin panel"
                    className="p-2 rounded-lg text-slate-500 hover:bg-rose-50 hover:text-rose-600 transition-colors"
                    aria-label="Sign out"
                  >
                    <MdExitToApp className="text-lg" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      {authError && (
        <div className="bg-rose-50 border-b border-rose-200 px-6 py-3 text-sm text-rose-700 flex items-center justify-between">
          <span>⚠️ {authError}</span>
          <button
            onClick={() => { setAuthError(null); reloadAll(); }}
            className="ml-4 px-3 py-1 bg-rose-600 text-white rounded-lg text-xs font-bold hover:bg-rose-700"
          >
            Retry
          </button>
        </div>
      )}

      {/* Mobile Drawer Overlay Backdrop */}
      {isMenuOpen && (
        <div 
          className="fixed inset-0 bg-slate-900/30 backdrop-blur-sm z-40 md:hidden"
          onClick={() => setIsMenuOpen(false)}
        />
      )}

      <div className="flex relative">
        {/* Modern Sidebar */}
        <aside className={`w-64 bg-white border-r border-gray-200 min-h-[calc(100vh-5rem)] transition-all duration-300 z-45
          fixed md:static left-0 top-20 bottom-0 md:translate-x-0
          ${isMenuOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full md:translate-x-0'}
        `}>
          <nav className="p-4 space-y-1">
            <NavItem 
              active={activeTab === 'dashboard'} 
              onClick={() => { setActiveTab('dashboard'); setIsMenuOpen(false); }}
              icon={<MdDashboard />}
              label="Dashboard"
              badge=""
            />
            <NavItem 
              active={activeTab === 'rooms'} 
              onClick={() => { setActiveTab('rooms'); setIsMenuOpen(false); }}
              icon={<MdPeople />}
              label="Rooms"
              badge={rooms.length}
            />
            <NavItem 
              active={activeTab === 'links'} 
              onClick={() => {
                setActiveTab('links');
                setIsMenuOpen(false);
                navigate('/shareable-links'); // ✅ NOW WORKS with useNavigate
              }} 
              icon={<MdLink />}
              label="Shareable Links"
              badge=""
            />
            <NavItem 
              active={activeTab === 'settings'} 
              onClick={() => { setActiveTab('settings'); setIsMenuOpen(false); }}
              icon={<MdSettings />}
              label="Settings"
              badge=""
            />
            <NavItem 
              active={activeTab === 'logs'} 
              onClick={() => { setActiveTab('logs'); setIsMenuOpen(false); }}
              icon={<MdHistory />}
              label="Admin Logs"
              badge={adminLogs.length}
            />
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1 p-6">
          {activeTab === 'dashboard' && <DashboardView stats={stats} rooms={rooms} />}
          {activeTab === 'rooms' && (
            <RoomsView 
              rooms={rooms} 
              onViewDetails={viewRoomDetails}
              onDeleteRoom={deleteRoom}
              onRefresh={loadDashboardData}
              onCreateRoom={() => setShowCreateRoomModal(true)}
              onExportChat={exportRoomChat}
              onEndSession={endRoomSession}
              onUpdateStatus={updateRoomStatus}
              loading={loading}
            />
          )}
          {activeTab === 'links' && <LinksView />}
          {activeTab === 'settings' && (
            <SettingsView 
              settings={settings}
              onUpdate={updateSetting}
              loading={loading}
            />
          )}
          {activeTab === 'room-detail' && selectedRoom && (
            <RoomDetailView
              room={selectedRoom}
              onBack={() => setActiveTab('rooms')}
              onDelete={() => deleteRoom(selectedRoom.room?.id)}
              onExportChat={exportRoomChat}
              onDownloadRecording={downloadRoomRecording}
              onExportMetrics={downloadRoomMetrics}
              onEndSession={endRoomSession}
              onUpdateStatus={updateRoomStatus}
              exportingRecordingId={exportingRecordingId}
            />
          )}
          {activeTab === 'logs' && (
            <AdminLogsView logs={adminLogs} />
          )}
        </main>
      </div>

      {/* Create Room Modal */}
      {showCreateRoomModal && (
        <CreateRoomModal
          newRoomData={newRoomData}
          setNewRoomData={setNewRoomData}
          onCreate={createAdminRoom}
          onCancel={() => setShowCreateRoomModal(false)}
          loading={loading}
        />
      )}
    </div>
  );
}

// Modern Nav Item Component
function NavItem({ active, onClick, icon, label, badge }) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center justify-between px-3.5 py-3 rounded-2xl border transition-all duration-200 select-none ${
        active 
          ? 'bg-gradient-to-tr from-indigo-50/70 to-purple-50/70 text-indigo-750 border-indigo-100 font-bold shadow-[0_2px_8px_rgba(99,102,241,0.02)]'
          : 'text-slate-500 border-transparent hover:bg-slate-50 hover:text-slate-800 font-semibold'
      }`}
    >
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-xl transition-colors ${active ? 'bg-indigo-100/60' : 'bg-slate-100'}`}>
          {React.cloneElement(icon, { className: `text-lg ${active ? 'text-indigo-600' : 'text-slate-500'}` })}
        </div>
        <span className="text-xs tracking-tight">{label}</span>
      </div>
      {badge !== '' && badge > 0 && (
        <span className={`px-2 py-0.5 text-[10px] font-bold rounded-full ${
          active ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-600'
        }`}>
          {badge}
        </span>
      )}
    </button>
  );
}

// Modern Dashboard View
function DashboardView({ stats, rooms }) {
  const activeRooms = rooms.filter(r => r.status === 'active').length;
  const completedRooms = rooms.filter(r => r.status === 'completed').length;
  const totalParticipants = rooms.reduce((sum, room) => sum + (room.actual_participant_count || 0), 0);
  const uniqueUsers = new Set();
  rooms.forEach(room => {
    (room.participant_names || []).forEach(name => uniqueUsers.add(name));
  });

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Active Rooms"
          value={activeRooms}
          icon={<MdPeople className="text-2xl" />}
          color="green"
          change={`${((activeRooms / rooms.length) * 100 || 0).toFixed(1)}%`}
        />
        <StatCard
          title="Total Participants"
          value={totalParticipants}
          icon={<MdGroup className="text-2xl" />}
          color="blue"
          change={`${uniqueUsers.size} unique`}
        />
        <StatCard
          title="Total Messages"
          value={stats?.messages?.total || 0}
          icon={<MdChat className="text-2xl" />}
          color="purple"
          change={`${stats?.messages?.messages_today || 0} today`}
        />
        <StatCard
          title="Completed Sessions"
          value={completedRooms}
          icon={<MdCheckCircle className="text-2xl" />}
          color="orange"
          change={`${((completedRooms / rooms.length) * 100 || 0).toFixed(1)}%`}
        />
      </div>

      {/* Quick Actions */}
      <div className="card p-6">
        <h3 className="text-lg font-bold text-gray-800 mb-4">Quick Actions</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <button 
            onClick={() => {
              window.dispatchEvent(new CustomEvent('admin:changeTab', { detail: { tab: 'links' } }));
            }}
            className="p-4 bg-indigo-50 hover:bg-indigo-100 rounded-xl transition-colors text-center group"
          >
            <MdLink className="text-2xl text-indigo-600 mx-auto mb-2 group-hover:scale-110 transition-transform" />
            <span className="font-medium text-gray-700">Share Links</span>
          </button>
          
          <button 
            onClick={() => {
              window.dispatchEvent(new CustomEvent('admin:openCreateRoom'));
            }}
            className="p-4 bg-green-50 hover:bg-green-100 rounded-xl transition-colors text-center group"
          >
            <MdAdd className="text-2xl text-green-600 mx-auto mb-2 group-hover:scale-110 transition-transform" />
            <span className="font-medium text-gray-700">New Room</span>
          </button>
          
          <button 
            onClick={() => {
              const exportAllData = async () => {
                try {
                  // Export the rooms already loaded into this view — no extra fetch (and no
                  // token needed here, which is why fetchAdmin isn't in scope inside DashboardView).
                  const data = { rooms, count: rooms.length, exported_at: new Date().toISOString() };
                  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                  const url = window.URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `all_rooms_export_${new Date().toISOString().split('T')[0]}.json`;
                  document.body.appendChild(a);
                  a.click();
                  window.URL.revokeObjectURL(url);
                  document.body.removeChild(a);
                  alert('✅ All rooms data exported successfully');
                } catch (err) {
                  console.error('Export failed:', err);
                  alert('❌ Export failed: ' + err.message);
                }
              };
              exportAllData();
            }}
            className="p-4 bg-purple-50 hover:bg-purple-100 rounded-xl transition-colors text-center group"
          >
            <MdDownload className="text-2xl text-purple-600 mx-auto mb-2 group-hover:scale-110 transition-transform" />
            <span className="font-medium text-gray-700">Export Data</span>
          </button>
          
          <button 
            onClick={() => {
              window.dispatchEvent(new CustomEvent('admin:changeTab', { detail: { tab: 'settings' } }));
            }}
            className="p-4 bg-orange-50 hover:bg-orange-100 rounded-xl transition-colors text-center group"
          >
            <MdSettings className="text-2xl text-orange-600 mx-auto mb-2 group-hover:scale-110 transition-transform" />
            <span className="font-medium text-gray-700">Settings</span>
          </button>
        </div>
      </div>

      {/* Recent Rooms */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-bold text-gray-800">Recent Rooms</h3>
          <span className="text-sm text-gray-500">{rooms.length} total rooms</span>
        </div>
        <div className="space-y-4">
          {rooms.slice(0, 5).map((room) => (
            <div key={room.id} className="flex items-center justify-between p-4 bg-gray-50 rounded-xl hover:bg-gray-100 transition-colors">
              <div className="flex items-center gap-3">
                <div className={`w-3 h-3 rounded-full ${
                  room.status === 'active' ? 'bg-green-500' :
                  room.status === 'waiting' ? 'bg-yellow-500' : 'bg-gray-500'
                }`}></div>
                <div>
                  <p className="font-medium text-gray-800">Room: {(room.id || '').substring(0, 8)}...</p>
                  <p className="text-sm text-gray-500">
                    {room.mode || 'unknown'} mode • {room.actual_participant_count || 0} participants
                    {room.participant_names && room.participant_names.length > 0 && (
                      <span className="ml-2">({room.participant_names.slice(0, 2).join(', ')}{room.participant_names.length > 2 ? '...' : ''})</span>
                    )}
                  </p>
                </div>
              </div>
              <span className="text-sm text-gray-500">
                {room.created_at ? new Date(room.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Unknown'}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* System Stats */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="card p-6">
            <h3 className="text-lg font-bold text-gray-800 mb-4">Participant Stats</h3>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600">Total Participants:</span>
                <span className="font-semibold">{stats.participants?.total || 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Unique Users:</span>
                <span className="font-semibold">{stats.participants?.unique_users || 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Today's Participants:</span>
                <span className="font-semibold">{stats.participants?.participants_today || 0}</span>
              </div>
            </div>
          </div>
          
          <div className="card p-6">
            <h3 className="text-lg font-bold text-gray-800 mb-4">Message Stats</h3>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600">Total Messages:</span>
                <span className="font-semibold">{stats.messages?.total || 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Today's Messages:</span>
                <span className="font-semibold">{stats.messages?.messages_today || 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Chat Messages:</span>
                <span className="font-semibold">{stats.messages?.chat || 0}</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Modern Stat Card Component
function StatCard({ title, value, icon, color, change }) {
  const colorClasses = {
    blue: { bg: 'bg-blue-50/60', text: 'text-blue-600 border-blue-100/60', accent: 'text-blue-700' },
    green: { bg: 'bg-emerald-50/60', text: 'text-emerald-600 border-emerald-100/60', accent: 'text-emerald-700' },
    purple: { bg: 'bg-purple-50/60', text: 'text-purple-600 border-purple-100/60', accent: 'text-purple-700' },
    orange: { bg: 'bg-amber-50/60', text: 'text-amber-600 border-amber-100/60', accent: 'text-amber-700' }
  };

  const colors = colorClasses[color] || colorClasses.blue;

  return (
    <div className={`glass-card p-6 border ${colors.text.split(' ')[1] || 'border-slate-100'}`}>
      <div className="flex items-center justify-between mb-4">
        <div className={`p-3 rounded-2xl ${colors.bg} ${colors.text.split(' ')[0]}`}>
          {icon}
        </div>
        <span className="badge badge-success text-[10px]">
          {change}
        </span>
      </div>
      <h3 className="text-3xl font-extrabold text-slate-800 mb-1.5">{value}</h3>
      <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">{title}</p>
    </div>
  );
}

// Rooms List View
function RoomsView({ rooms, onViewDetails, onDeleteRoom, onRefresh, onCreateRoom, onExportChat, onEndSession, onUpdateStatus, loading }) {
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');

  const filteredRooms = rooms.filter(room => {
    if (filter === 'all') return true;
    if (filter === 'active') return room.status === 'active';
    if (filter === 'waiting') return room.status === 'waiting';
    if (filter === 'completed') return room.status === 'completed';
    return true;
  }).filter(room => {
    if (!search) return true;
    const searchLower = search.toLowerCase();
    return (
      room.id.toLowerCase().includes(searchLower) ||
      (room.story_id && room.story_id.toLowerCase().includes(searchLower)) ||
      (room.participant_names && room.participant_names.some(name => 
        name.toLowerCase().includes(searchLower)
      ))
    );
  });

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-800">Rooms Management</h2>
        <div className="flex gap-3">
          <button
            onClick={onCreateRoom}
            className="btn-primary flex items-center gap-2"
          >
            <MdAdd /> Create Room
          </button>
          <button
            onClick={onRefresh}
            disabled={loading}
            className="btn-secondary flex items-center gap-2"
          >
            <MdRefresh className={loading ? 'animate-spin' : ''} />
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Filters and Search */}
      <div className="card p-4 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Filter by Status</label>
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="border border-gray-300 rounded-lg px-4 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 w-full"
            >
              <option value="all">All Rooms</option>
              <option value="waiting">Waiting</option>
              <option value="active">Active</option>
              <option value="completed">Completed</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Search Rooms</label>
            <input
              type="text"
              placeholder="Search by ID, story, or participant..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="border border-gray-300 rounded-lg px-4 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 w-full"
            />
          </div>
        </div>
      </div>

      {filteredRooms.length === 0 ? (
        <div className="card p-12 text-center">
          <div className="w-20 h-20 rounded-full bg-gray-100 flex items-center justify-center mx-auto mb-4">
            <MdPeople className="text-3xl text-gray-400" />
          </div>
          <p className="text-gray-500 text-lg">No rooms found</p>
          <p className="text-gray-400 mt-2">Try changing your filter or create a new room</p>
          <button
            onClick={onCreateRoom}
            className="mt-4 btn-primary"
          >
            <MdAdd className="mr-2" /> Create First Room
          </button>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Room ID</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Mode</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Participants</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredRooms.map((room) => (
                  <tr key={room.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4">
                      <div className="text-sm font-mono text-gray-900">{(room.id || '').substring(0, 10)}...</div>
                      <div className="text-xs text-gray-500 truncate max-w-xs">
                        Story: {room.story_id || 'default'}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                        room.mode === 'active' 
                          ? 'bg-blue-100 text-blue-800' 
                          : 'bg-purple-100 text-purple-800'
                      }`}>
                        {room.mode || 'unknown'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                        room.status === 'active' ? 'bg-green-100 text-green-800' :
                        room.status === 'waiting' ? 'bg-yellow-100 text-yellow-800' :
                        'bg-gray-100 text-gray-800'
                      }`}>
                        {room.status || 'unknown'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-gray-900">
                            {room.actual_participant_count || 0} / {room.max_participants || 3}
                          </span>
                          <div className="w-16 bg-gray-200 rounded-full h-2">
                            <div 
                              className="bg-green-500 h-2 rounded-full"
                              style={{ 
                                width: `${((room.actual_participant_count || 0) / (room.max_participants || 3)) * 100}%`,
                                maxWidth: '100%'
                              }}
                            ></div>
                          </div>
                        </div>
                        {room.participant_names && room.participant_names.length > 0 && (
                          <div className="text-xs text-gray-500 truncate max-w-xs">
                            {room.participant_names.slice(0, 3).join(', ')}
                            {room.participant_names.length > 3 && '...'}
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-500">
                      {room.created_at ? new Date(room.created_at).toLocaleDateString() : 'Unknown'}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => onViewDetails(room.id)}
                          className="flex items-center gap-1 px-3 py-1.5 bg-indigo-50 text-indigo-700 rounded-lg hover:bg-indigo-100 transition-colors text-sm"
                          title="View Details"
                        >
                          <MdVisibility size={14} />
                        </button>
                        <button
                          onClick={() => onExportChat(room.id, 'json')}
                          className="flex items-center gap-1 px-3 py-1.5 bg-green-50 text-green-700 rounded-lg hover:bg-green-100 transition-colors text-sm"
                          title="Export Chat"
                        >
                          <MdDownload size={14} />
                        </button>
                        <button
                          onClick={() => onEndSession(room.id, 'session')}
                          className="flex items-center gap-1 px-3 py-1.5 bg-red-50 text-red-700 rounded-lg hover:bg-red-100 transition-colors text-sm"
                          title="End Session"
                        >
                          <MdStop size={14} />
                        </button>
                        <button
                          onClick={() => onDeleteRoom(room.id)}
                          className="flex items-center gap-1 px-3 py-1.5 bg-gray-50 text-gray-700 rounded-lg hover:bg-gray-100 transition-colors text-sm"
                          title="Delete Room"
                        >
                          <MdDelete size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// Create Room Modal Component
function CreateRoomModal({ newRoomData, setNewRoomData, onCreate, onCancel, loading }) {
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full">
        <div className="p-6">
          <h3 className="text-xl font-bold text-gray-800 mb-4">Create New Room</h3>
          
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Mode
              </label>
              <select
                value={newRoomData.mode}
                onChange={(e) => setNewRoomData({...newRoomData, mode: e.target.value})}
                className="border border-gray-300 rounded-lg px-4 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 w-full"
              >
                <option value="active">Active (AI Moderated)</option>
                <option value="passive">Passive (Auto-progress)</option>
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Max Participants
              </label>
              <input
                type="number"
                min="1"
                max="10"
                value={newRoomData.max_participants}
                onChange={(e) => setNewRoomData({...newRoomData, max_participants: parseInt(e.target.value)})}
                className="border border-gray-300 rounded-lg px-4 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 w-full"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Story ID (Optional)
              </label>
              <input
                type="text"
                placeholder="Leave empty for random story"
                value={newRoomData.story_id}
                onChange={(e) => setNewRoomData({...newRoomData, story_id: e.target.value})}
                className="border border-gray-300 rounded-lg px-4 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 w-full"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Admin Note (Optional)
              </label>
              <textarea
                rows="2"
                placeholder="Add a note for this room..."
                value={newRoomData.admin_note}
                onChange={(e) => setNewRoomData({...newRoomData, admin_note: e.target.value})}
                className="border border-gray-300 rounded-lg px-4 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 w-full resize-none"
              />
            </div>
          </div>
          
          <div className="flex gap-3 mt-6">
            <button
              onClick={onCancel}
              className="flex-1 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
              disabled={loading}
            >
              Cancel
            </button>
            <button
              onClick={onCreate}
              disabled={loading}
              className="flex-1 py-2 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-lg hover:from-indigo-700 hover:to-purple-700 transition-all disabled:opacity-50"
            >
              {loading ? 'Creating...' : 'Create Room'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// Room Detail View
function RoomDetailView({ room, onBack, onDelete, onExportChat, onDownloadRecording, onExportMetrics, onEndSession, onUpdateStatus, exportingRecordingId }) {
  const safeRoom = room || {};
  const safeRoomData = safeRoom.room || {};
  const safeStats = safeRoom.stats || {};
  const safeParticipants = safeRoom.participants || [];
  const safeMessages = safeRoom.messages || [];

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-indigo-600 hover:text-indigo-900 font-medium"
        >
          ← Back to Rooms
        </button>
        <div className="flex gap-2">
          <button
            onClick={() => onDelete(safeRoomData.id)}
            className="flex items-center gap-2 bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700 transition-colors"
          >
            <MdDelete /> Delete Room
          </button>
        </div>
      </div>

      <div className="card p-6 mb-6">
        <h2 className="text-2xl font-bold mb-6">Room Details</h2>
        
        {/* Room Info Header */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <div className="bg-gray-50 p-4 rounded-xl">
            <p className="text-sm text-gray-600 mb-1">Room ID</p>
            <p className="font-mono text-sm break-all">{safeRoomData.id || 'N/A'}</p>
          </div>
          <div className="bg-gray-50 p-4 rounded-xl">
            <p className="text-sm text-gray-600 mb-1">Mode</p>
            <p className="font-semibold capitalize">{safeRoomData.mode || 'unknown'}</p>
          </div>
          <div className="bg-gray-50 p-4 rounded-xl">
            <p className="text-sm text-gray-600 mb-1">Status</p>
            <div className="flex items-center gap-2">
              <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                safeRoomData.status === 'active' ? 'bg-green-100 text-green-800' :
                safeRoomData.status === 'waiting' ? 'bg-yellow-100 text-yellow-800' :
                'bg-gray-100 text-gray-800'
              }`}>
                {safeRoomData.status || 'unknown'}
              </span>
              {safeRoomData.story_finished && (
                <span className="px-2 py-1 bg-purple-100 text-purple-800 text-xs rounded-full">
                  Story Ended
                </span>
              )}
            </div>
          </div>
          <div className="bg-gray-50 p-4 rounded-xl">
            <p className="text-sm text-gray-600 mb-1">Story</p>
            <p className="font-medium truncate">{safeRoomData.story_id || 'default'}</p>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap gap-3 mb-8">
          <div className="flex gap-2">
            <button
              onClick={() => onExportChat(safeRoomData.id, 'json')}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
            >
              <MdDownload /> Export JSON
            </button>
            <button
              onClick={() => onExportChat(safeRoomData.id, 'csv')}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              <MdFileDownload /> Export CSV
            </button>
            <button
              onClick={() => onExportChat(safeRoomData.id, 'tsv')}
              className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
            >
              <MdFileDownload /> Export TSV
            </button>
            <button
              onClick={() => onDownloadRecording(safeRoomData.id)}
              disabled={exportingRecordingId === safeRoomData.id}
              className={`flex items-center gap-2 px-4 py-2 bg-rose-600 text-white rounded-lg hover:bg-rose-700 transition-colors ${
                exportingRecordingId === safeRoomData.id ? 'opacity-50 cursor-not-allowed' : ''
              }`}
              title="Assemble all participant + moderator audio into one ordered file"
            >
              {exportingRecordingId === safeRoomData.id ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  <span>Assembling Recording...</span>
                </>
              ) : (
                <>
                  <MdVolumeUp /> Download Conversation Recording
                </>
              )}
            </button>
            <button
              onClick={() => onExportMetrics && onExportMetrics(safeRoomData.id, 'participant')}
              className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 transition-colors"
              title="Authoritative research metrics — one row per participant (CSV)"
            >
              <MdFileDownload /> Export Metrics (CSV)
            </button>
            <button
              onClick={() => onExportMetrics && onExportMetrics(safeRoomData.id, 'summary')}
              className="flex items-center gap-2 px-4 py-2 bg-teal-700 text-white rounded-lg hover:bg-teal-800 transition-colors"
              title="Room-level summary metrics (CSV)"
            >
              <MdFileDownload /> Export Summary (CSV)
            </button>
          </div>

          <div className="flex gap-2">
            {safeRoomData.status === 'active' && !safeRoomData.story_finished && (
              <button
                onClick={() => onEndSession(safeRoomData.id, 'story')}
                className="flex items-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 transition-colors"
              >
                <MdStop /> End Story Only
              </button>
            )}
            {safeRoomData.status === 'active' && (
              <button
                onClick={() => onEndSession(safeRoomData.id, 'session')}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                <MdExitToApp /> End Session
              </button>
            )}
          </div>
          
          <div className="flex gap-2">
            <select
              onChange={(e) => onUpdateStatus(safeRoomData.id, e.target.value)}
              value={safeRoomData.status || ''}
              className="border border-gray-300 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200"
            >
              <option value="waiting">Waiting</option>
              <option value="active">Active</option>
              <option value="completed">Completed</option>
            </select>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
          <div className="bg-gradient-to-br from-blue-50 to-blue-100 p-6 rounded-2xl">
            <div className="flex items-center justify-between mb-2">
              <MdPeople className="text-2xl text-blue-600" />
              <span className="text-3xl font-bold text-blue-700">{safeStats.participant_count || 0}</span>
            </div>
            <h4 className="font-semibold text-blue-900">Participants</h4>
          </div>
          <div className="bg-gradient-to-br from-green-50 to-green-100 p-6 rounded-2xl">
            <div className="flex items-center justify-between mb-2">
              <MdChat className="text-2xl text-green-600" />
              <span className="text-3xl font-bold text-green-700">{safeStats.message_count || 0}</span>
            </div>
            <h4 className="font-semibold text-green-900">Messages</h4>
          </div>
          <div className="bg-gradient-to-br from-purple-50 to-purple-100 p-6 rounded-2xl">
            <div className="flex items-center justify-between mb-2">
              <MdHistory className="text-2xl text-purple-600" />
              <span className="text-3xl font-bold text-purple-700">{safeStats.session_count || 0}</span>
            </div>
            <h4 className="font-semibold text-purple-900">Sessions</h4>
          </div>
        </div>

        {/* Participants Section */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <MdPeople /> Participants ({safeParticipants.length})
            </h3>
          </div>
          <div className="space-y-3">
            {safeParticipants.length > 0 ? (
              safeParticipants.map((p, index) => (
                <div key={p?.id || index} className="flex justify-between items-center bg-gray-50 p-4 rounded-xl hover:bg-gray-100 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-gradient-to-r from-indigo-400 to-purple-400 flex items-center justify-center text-white font-semibold">
                      {(p?.display_name || p?.username || 'U').charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <span className="font-medium">{p?.display_name || p?.username || 'Anonymous User'}</span>
                      <p className="text-xs text-gray-500">
                        Username: {p?.username || 'N/A'} • 
                        ID: {p?.id ? p.id.substring(0, 8) + '...' : 'N/A'}
                      </p>
                    </div>
                  </div>
                  <span className="text-sm text-gray-500">
                    {p?.joined_at ? new Date(p.joined_at).toLocaleTimeString() : 'Unknown'}
                  </span>
                </div>
              ))
            ) : (
              <div className="text-center py-6 text-gray-500 bg-gray-50 rounded-xl">
                No participants found
              </div>
            )}
          </div>
        </div>

        {/* Messages Section */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <MdChat /> Conversation ({safeMessages.length} messages)
            </h3>
          </div>
          <div className="bg-gray-50 rounded-2xl p-4 max-h-96 overflow-y-auto">
            {safeMessages.length > 0 ? (
              safeMessages.map((msg, idx) => {
                const username = msg?.username || msg?.sender || 'Unknown';
                const message = msg?.message || msg?.message_text || 'No message content';
                const isModerator = username.toLowerCase() === 'moderator';
                const timestamp = msg?.created_at ? new Date(msg.created_at).toLocaleTimeString([], { 
                  hour: '2-digit', 
                  minute: '2-digit',
                  second: '2-digit'
                }) : '';
                
                return (
                  <div
                    key={idx}
                    className={`mb-4 p-4 rounded-xl ${
                      isModerator 
                        ? 'bg-gradient-to-r from-amber-50 to-yellow-50 border border-amber-100' 
                        : 'bg-white border border-gray-200'
                    }`}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <div className="flex items-center gap-2">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-semibold ${
                          isModerator 
                            ? 'bg-gradient-to-r from-amber-500 to-orange-500' 
                            : 'bg-gradient-to-r from-indigo-500 to-blue-500'
                        }`}>
                          {username.charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <span className="font-semibold text-sm">{username}</span>
                          {msg?.message_type && (
                            <span className="ml-2 px-1.5 py-0.5 bg-gray-100 text-gray-600 text-xs rounded">
                              {msg.message_type}
                            </span>
                          )}
                        </div>
                      </div>
                      <span className="text-xs text-gray-500">
                        {timestamp}
                      </span>
                    </div>
                    <p className="text-sm text-gray-700 whitespace-pre-wrap">{message}</p>
                  </div>
                );
              })
            ) : (
              <div className="text-center py-8 text-gray-500">
                <MdChat className="text-4xl mx-auto mb-3 text-gray-400" />
                No messages in this conversation
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// Admin Logs View Component
function AdminLogsView({ logs }) {
  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-800">Admin Activity Logs</h2>
        <span className="text-sm text-gray-500">{logs.length} log entries</span>
      </div>
      
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Action</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Admin User</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Entity</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Details</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {logs.map((log, index) => (
                <tr key={index} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4">
                    <div className="text-sm text-gray-900">
                      {log.created_at ? new Date(log.created_at).toLocaleString() : 'Unknown'}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">
                      {log.action}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-gray-900">{log.admin_user || 'system'}</div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-gray-900">
                      {log.entity_type}: {log.entity_id ? log.entity_id.substring(0, 8) + '...' : 'N/A'}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-xs text-gray-500 max-w-xs truncate">
                      {JSON.stringify(log.details || {})}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function LinksView() {
  const activeLink = `${FRONTEND_URL}/join/active`;
  const passiveLink = `${FRONTEND_URL}/join/passive`;
  const [copiedActive, setCopiedActive] = useState(false);
  const [copiedPassive, setCopiedPassive] = useState(false);

  const copyToClipboard = async (text, setterFunc) => {
    try {
      await navigator.clipboard.writeText(text);
      setterFunc(true);
      setTimeout(() => setterFunc(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
      alert('Failed to copy link');
    }
  };

  return (
    <div className="glass-card p-6 md:p-8 animate-slide-up max-w-4xl mx-auto">
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-slate-805 mb-2">Invite Gateway Manager</h2>
        <p className="text-sm text-slate-500">Provide direct auto-join URLs to study groups</p>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Active Mode Link */}
        <div className="bg-white/50 border border-slate-100 rounded-2xl p-5 hover:border-indigo-200 hover:shadow-md transition-all duration-300 group">
          <div className="flex items-center mb-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center text-indigo-600 mr-3 group-hover:scale-110 transition-transform">
              <MdPsychology className="text-2xl" />
            </div>
            <div>
              <h3 className="font-bold text-slate-800 text-sm leading-tight">
                Active Mode Link
              </h3>
              <p className="text-[11px] text-slate-400 mt-0.5">
                AI active prompts and guidance
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 mt-4">
            <input
              type="text"
              value={activeLink}
              readOnly
              className="flex-1 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-mono text-indigo-700 outline-none"
            />
            <button
              onClick={() => copyToClipboard(activeLink, setCopiedActive)}
              className={`px-3 py-2 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-all duration-200 ${
                copiedActive 
                  ? 'bg-emerald-500 text-white shadow-sm' 
                  : 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm'
              }`}
            >
              {copiedActive ? <MdCheckCircle /> : <MdContentCopy />}
              <span>{copiedActive ? 'Copied' : 'Copy'}</span>
            </button>
          </div>
        </div>

        {/* Passive Mode Link */}
        <div className="bg-white/50 border border-slate-100 rounded-2xl p-5 hover:border-purple-200 hover:shadow-md transition-all duration-300 group">
          <div className="flex items-center mb-3">
            <div className="w-10 h-10 rounded-xl bg-purple-50 flex items-center justify-center text-purple-600 mr-3 group-hover:scale-110 transition-transform">
              <MdAutoMode className="text-2xl" />
            </div>
            <div>
              <h3 className="font-bold text-slate-800 text-sm leading-tight">
                Passive Mode Link
              </h3>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Automatic sentence progress only
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 mt-4">
            <input
              type="text"
              value={passiveLink}
              readOnly
              className="flex-1 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-mono text-purple-700 outline-none"
            />
            <button
              onClick={() => copyToClipboard(passiveLink, setCopiedPassive)}
              className={`px-3 py-2 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-all duration-200 ${
                copiedPassive 
                  ? 'bg-emerald-500 text-white shadow-sm' 
                  : 'bg-purple-600 hover:bg-purple-700 text-white shadow-sm'
              }`}
            >
              {copiedPassive ? <MdCheckCircle /> : <MdContentCopy />}
              <span>{copiedPassive ? 'Copied' : 'Copy'}</span>
            </button>
          </div>
        </div>
      </div>

      <div className="mt-6 p-4 bg-gradient-to-r from-blue-50/50 to-indigo-50/50 rounded-2xl border border-indigo-50/50">
        <h4 className="font-bold text-indigo-900 text-xs uppercase mb-2">📋 Operational Summary</h4>
        <ul className="text-xs text-slate-650 space-y-1.5 leading-relaxed font-semibold">
          <li>• Participants click the generated link to auto-enter empty or newly structured rooms.</li>
          <li>• Rooms automatically seal once capacity limits are achieved.</li>
          <li>• Administrative key validation matches automatically (no registration workflow).</li>
        </ul>
      </div>
    </div>
  );
}

// Settings View (simplified)
function SettingsView({ settings, onUpdate, loading }) {
  const [editingKey, setEditingKey] = useState(null);
  const [editValue, setEditValue] = useState('');

  const startEdit = (key, currentValue) => {
    setEditingKey(key);
    setEditValue(currentValue);
  };

  const saveEdit = async () => {
    if (editingKey) {
      await onUpdate(editingKey, editValue);
      setEditingKey(null);
    }
  };

  const cancelEdit = () => {
    setEditingKey(null);
  };

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-800 mb-6">System Settings</h2>
      
      <div className="card p-6">
        <div className="space-y-4">
          {settings.map((setting) => (
            <div key={setting.key} className="border-b border-gray-200 pb-4 last:border-0">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <h3 className="font-semibold text-gray-800">{setting.key}</h3>
                  <p className="text-sm text-gray-600">{setting.description || ''}</p>
                  
                  {editingKey === setting.key ? (
                    <div className="mt-2 flex gap-2">
                      <input
                        type="text"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        className="flex-1 border border-gray-300 rounded-lg px-3 py-1 text-sm"
                        autoFocus
                      />
                      <button
                        onClick={saveEdit}
                        className="p-1 bg-green-100 text-green-700 rounded hover:bg-green-200"
                        disabled={loading}
                      >
                        <MdSave size={18} />
                      </button>
                      <button
                        onClick={cancelEdit}
                        className="p-1 bg-red-100 text-red-700 rounded hover:bg-red-200"
                      >
                        <MdCancel size={18} />
                      </button>
                    </div>
                  ) : (
                    <div className="mt-1 flex items-center gap-2">
                      <span className="text-sm font-mono bg-gray-100 px-2 py-1 rounded">
                        {setting.value}
                      </span>
                      <span className="text-xs text-gray-500">({setting.data_type})</span>
                    </div>
                  )}
                </div>
                
                {editingKey !== setting.key && (
                  <button
                    onClick={() => startEdit(setting.key, setting.value)}
                    className="p-2 text-gray-600 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                  >
                    <MdEdit size={18} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}