from datetime import datetime
from collections import defaultdict

# ==================== SESSION TRACKING ====================
session_start = datetime.now()
active_listeners = {}  # ip -> last_seen timestamp
total_sessions = 0
track_plays = defaultdict(int)  # track_id -> play count
time_of_day_counts = defaultdict(int)  # morning/afternoon/sunset/night -> count

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

def get_stats(playlist):
    cleanup_inactive()
    uptime = datetime.now() - session_start

    top_tracks = []
    for track in playlist:
        plays = track_plays.get(track.id, 0)
        if plays > 0:
            top_tracks.append({
                "title": track.title,
                "artist": track.artist,
                "plays": plays
            })
    top_tracks.sort(key=lambda x: x["plays"], reverse=True)

    return {
        "session_start": session_start.strftime("%Y-%m-%d %H:%M:%S"),
        "uptime_hours": round(uptime.total_seconds() / 3600, 1),
        "current_listeners": len(active_listeners),
        "total_sessions": total_sessions,
        "time_of_day_breakdown": dict(time_of_day_counts),
        "top_tracks": top_tracks[:10]
    }