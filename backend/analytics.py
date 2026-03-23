from datetime import datetime
from collections import defaultdict

# ==================== SESSION TRACKING ====================
session_start = datetime.now()
active_listeners = {}  # ip -> last_seen timestamp
total_sessions = 0
track_plays = defaultdict(int)  # track_id -> play count
track_last_played = {}  # track_id -> datetime of last play
time_of_day_counts = defaultdict(int)  # morning/afternoon/sunset/night -> count
peak_listeners_per_track = {}  # track_id -> peak simultaneous listeners (session only)

def get_time_of_day():
    hour = datetime.now().hour
    if 6 <= hour < 12: return "morning"
    if 12 <= hour < 18: return "afternoon"
    if 18 <= hour < 21: return "sunset"
    return "night"

def record_listener(ip: str):
    global total_sessions
    now = datetime.now()
    if ip not in active_listeners:
        total_sessions += 1
        time_of_day_counts[get_time_of_day()] += 1
    active_listeners[ip] = now

def cleanup_inactive(timeout_seconds=10):
    now = datetime.now()
    inactive = [ip for ip, last in active_listeners.items()
                if (now - last).seconds > timeout_seconds]
    for ip in inactive:
        del active_listeners[ip]

def record_track_play(track_id: str):
    track_plays[track_id] += 1
    track_last_played[track_id] = datetime.now()
    # Snapshot listener count at track start — can be enhanced to track peak during playback
    peak_listeners_per_track[track_id] = max(
        peak_listeners_per_track.get(track_id, 0),
        len(active_listeners)
    )

def get_stats(playlist, current_track=None, upcoming_tracks=None, current_label=None):
    cleanup_inactive()
    uptime = datetime.now() - session_start

    # Build index map: track_id -> fixed index (1-based, order in playlist.json)
    index_map = {track.id: i + 1 for i, track in enumerate(playlist)}

    def format_track(track, plays):
        idx = getattr(track, 'playlist_index', None) or index_map.get(track.id, "?")
        play_word = "play" if plays == 1 else "plays"
        return f"#{idx} - {track.artist} - {track.title} · {plays} {play_word}"

    # ── UP NEXT (20 songs) ──────────────────────────────
    up_next_list = []
    if upcoming_tracks:
        for track in upcoming_tracks[:20]:
            plays = track_plays.get(track.id, 0)
            up_next_list.append(format_track(track, plays))

    # ── ALREADY PLAYED (most recent first) ──────────────
    already_played_list = []
    played_tracks = [(track, track_plays.get(track.id, 0))
                     for track in playlist
                     if track_plays.get(track.id, 0) > 0]

    # Exclude current track from already played
    if current_track:
        played_tracks = [(t, p) for t, p in played_tracks if t.id != current_track.id]

    # Sort by most recently played
    played_tracks.sort(
        key=lambda x: track_last_played.get(x[0].id, datetime.min),
        reverse=True
    )
    for track, plays in played_tracks:
        already_played_list.append(format_track(track, plays))

    # ── TOP 5 (collapsed) ───────────────────────────────
    top_tracks = sorted(
        [(track, peak_listeners_per_track.get(track.id, 0)) for track in playlist
         if track_plays.get(track.id, 0) > 0],
        key=lambda x: x[1],
        reverse=True
    )[:5]
    top_5_list = [
        f"#{getattr(t, 'playlist_index', None) or index_map.get(t.id, '?')} - {t.artist} - {t.title} · {p} listeners peak"
        for t, p in top_tracks
    ]

    return {
        "current": current_label,
        "current_listeners": len(active_listeners),
        "total_sessions": total_sessions,
        "session_start": session_start.strftime("%Y-%m-%d %H:%M:%S"),
        "uptime_hours": round(uptime.total_seconds() / 3600, 1),
        "up_next": up_next_list,
        "already_played": already_played_list,
        "top_5": top_5_list
    }