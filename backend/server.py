from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from analytics import record_listener, record_track_play, get_stats
import os
import logging
import asyncio
import random
import time
import uuid
import json
import httpx
from datetime import datetime
import pytz

# Configure logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Madrid Rock Radio - Telegram Edition")
api_router = APIRouter(prefix="/api")

# ==================== TELEGRAM CONFIG ====================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN environment variable not set!")
    raise ValueError("TELEGRAM_BOT_TOKEN is required")
PLAYLIST_FILE = os.path.join(os.path.dirname(__file__), 'playlist.json')

logger.info(f"📁 Playlist file: {PLAYLIST_FILE}")

# ==================== MODELS ====================
class Track(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_id: str  # Telegram file ID
    file_unique_id: Optional[str] = None
    title: str = ""
    artist: str = ""
    duration: int = 180
    audio_url: Optional[str] = None
    source: str = "telegram"
    band_link: Optional[str] = None
    playlist_index: Optional[int] = None  # fixed position in playlist.json

class RadioState(BaseModel):
    current_track: Optional[Track] = None
    position: float = 0
    is_playing: bool = True
    started_at: float = 0
    playlist: List[Track] = []
    history: List[Track] = []

class UserFavorite(BaseModel):
    track: Optional[Track] = None
    saved_at: float = 0

# ==================== GLOBAL STATE ====================
radio_state = RadioState()
user_favorites = {}

# ==================== SCHEDULING ====================

MADRID_TZ = pytz.timezone("Europe/Madrid")
scheduled_tracks: list = []  # list of {"track": Track, "play_at": datetime, "origin": "staged"|"main"}

# ==================== TELEGRAM HELPERS ====================
def get_telegram_audio_url(file_id: str) -> Optional[str]:
    """Get streaming URL from Telegram file_id"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
        response = httpx.get(url, timeout=10.0)
        data = response.json()
        
        if data.get('ok'):
            file_path = data['result']['file_path']
            audio_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
            return audio_url
        else:
            logger.error(f"Telegram API error: {data}")
            return None
    
    except Exception as e:
        logger.error(f"Error getting Telegram URL: {e}")
        return None

def load_playlist_from_json() -> List[Track]:
    """Load playlist from persistent JSON file"""
    try:
        if not os.path.exists(PLAYLIST_FILE):
            logger.warning("📭 No playlist.json found - send YouTube links to bot to build playlist!")
            return []
        
        with open(PLAYLIST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            tracks = []
            
            for original_idx, track_data in enumerate(data.get('tracks', []), start=1):
                # Get fresh Telegram URL
                if track_data.get('file_id'):
                    track_data['audio_url'] = get_telegram_audio_url(track_data['file_id'])
                
                track = Track(**track_data)
                track.playlist_index = original_idx  # preserve original position
                tracks.append(track)
            
            logger.info(f"✅ Loaded {len(tracks)} tracks from playlist.json")
            return tracks
    
    except Exception as e:
        logger.error(f"❌ Error loading playlist: {e}")
        return []

# ==================== RADIO MANAGEMENT ====================
async def initialize_radio():
    """Initialize radio from playlist.json"""
    global radio_state
    
    if not radio_state.playlist:
        logger.info("🎵 Initializing Madrid Rock Radio...")
        
        # Load from Telegram bot's playlist
        tracks = load_playlist_from_json()
        
        if tracks:
            radio_state.playlist = tracks
            random.shuffle(radio_state.playlist)
            await play_next_track()
            logger.info(f"🎸 Radio started with {len(tracks)} Telegram tracks!")
        else:
            logger.warning("⚠️  No tracks in playlist.json!")
            logger.warning("📲 Send YouTube links to @madridrockradio_bot to add songs!")

async def play_next_track():
    """Advance to next track"""
    global radio_state
    
    if not radio_state.playlist:
        logger.error("No playlist available")
        return
    
    # Move current to history
    if radio_state.current_track:
        radio_state.history.insert(0, radio_state.current_track)
        radio_state.history = radio_state.history[:5]
    
    # Get next track (rotate playlist)
    if radio_state.current_track:
        current_idx = next((i for i, t in enumerate(radio_state.playlist) 
                          if t.id == radio_state.current_track.id), -1)
        next_idx = (current_idx + 1) % len(radio_state.playlist)
        radio_state.current_track = radio_state.playlist[next_idx]
    else:
        radio_state.current_track = radio_state.playlist[0]
    
    # Refresh Telegram URL (they can expire)
    if radio_state.current_track.file_id:
        new_url = get_telegram_audio_url(radio_state.current_track.file_id)
        if new_url:
            radio_state.current_track.audio_url = new_url
    
    # Check if any scheduled tracks are due
    global scheduled_tracks
    now = datetime.now(MADRID_TZ)
    still_pending = []
    for entry in scheduled_tracks:
        if now >= entry["play_at"]:
            logger.info(f"⏰ Auto-queuing scheduled track: {entry['track'].artist} - {entry['track'].title}")
            # Treat exactly like a manual /queue command
            track = entry["track"]
            insert_offset = 5
            current_idx = next((i for i, t in enumerate(radio_state.playlist)
                                if radio_state.current_track and t.id == radio_state.current_track.id), 0)
            # Remove if already in playlist (main track case)
            radio_state.playlist = [t for t in radio_state.playlist
                                     if t.file_unique_id != track.get("file_unique_id")]
            current_idx = next((i for i, t in enumerate(radio_state.playlist)
                                if radio_state.current_track and t.id == radio_state.current_track.id), 0)
            insert_idx = min(current_idx + insert_offset, len(radio_state.playlist))
            radio_state.playlist.insert(insert_idx, Track(**track))
            logger.info(f"🎯 Scheduled track queued at position ~{insert_offset}")
        else:
            still_pending.append(entry)
    scheduled_tracks = still_pending
            
    radio_state.started_at = time.time()
    radio_state.position = 0
    radio_state.is_playing = True
    
    logger.info(f"▶ Now playing: {radio_state.current_track.artist} - {radio_state.current_track.title}")
    record_track_play(radio_state.current_track.id)

def get_current_position() -> float:
    """Calculate current playback position"""
    if not radio_state.is_playing or not radio_state.current_track:
        return radio_state.position
    
    elapsed = time.time() - radio_state.started_at
    return elapsed

def get_upcoming_tracks(count: int = 3) -> List[Track]:
    """Get next N tracks in queue"""
    if not radio_state.current_track or not radio_state.playlist:
        return []
    
    current_idx = next((i for i, t in enumerate(radio_state.playlist) 
                       if t.id == radio_state.current_track.id), 0)
    
    upcoming = []
    for i in range(1, count + 1):
        next_idx = (current_idx + i) % len(radio_state.playlist)
        upcoming.append(radio_state.playlist[next_idx])
    
    return upcoming

# ==================== API ROUTES ====================
@api_router.get("/radio/state")
async def get_radio_state(request: Request):
    record_listener(request.client.host)
    
    """Get current radio state"""
    current_position = get_current_position()
    
    # Check if track ended
    if (radio_state.current_track and 
        current_position >= radio_state.current_track.duration):
        await play_next_track()
        current_position = 0
    
    return {
        "current_track": radio_state.current_track.model_dump() if radio_state.current_track else None,
        "position": current_position,
        "is_playing": radio_state.is_playing,
        "started_at": radio_state.started_at,
        "playlist_count": len(radio_state.playlist),
        "just_played": radio_state.history[0].model_dump() if radio_state.history else None,
        "up_next": [t.model_dump() for t in get_upcoming_tracks(3)]
    }

@api_router.get("/radio/stream")
async def get_stream_url():
    """Get audio stream URL"""
    if not radio_state.current_track:
        raise HTTPException(status_code=404, detail="No track playing")
    
    # Refresh Telegram URL
    if radio_state.current_track.file_id:
        new_url = get_telegram_audio_url(radio_state.current_track.file_id)
        if new_url:
            radio_state.current_track.audio_url = new_url
    
    if not radio_state.current_track.audio_url:
        raise HTTPException(status_code=404, detail="Could not get audio URL")
    
    return {
        "audio_url": radio_state.current_track.audio_url,
        "position": get_current_position()
    }

@api_router.get("/radio/playlist")
async def get_playlist():
    """Get full playlist"""
    return {"playlist": [t.model_dump() for t in radio_state.playlist]}

@api_router.post("/radio/refresh")
async def refresh_playlist():
    """Manually reload playlist from file"""
    global radio_state
    
    old_count = len(radio_state.playlist)
    tracks = load_playlist_from_json()
    
    if tracks:
        radio_state.playlist = tracks
        if not radio_state.current_track:
            random.shuffle(radio_state.playlist)
            await play_next_track()
    
    return {
        "message": f"Playlist refreshed: {old_count} → {len(radio_state.playlist)} tracks",
        "playlist_count": len(radio_state.playlist)
    }

# ==================== FAVORITES ====================
@api_router.post("/favorites/save")
async def save_favorite():
    """Save current track as favorite"""
    if not radio_state.current_track:
        raise HTTPException(status_code=404, detail="No track playing")
    
    user_favorites["main"] = UserFavorite(
        track=radio_state.current_track,
        saved_at=time.time()
    )
    
    return {
        "message": "Track saved",
        "track": radio_state.current_track.model_dump()
    }

@api_router.get("/favorites/get")
async def get_favorite():
    """Get saved favorite"""
    fav = user_favorites.get("main")
    if not fav or not fav.track:
        return {"favorite": None}
    
    return {"favorite": fav.track.model_dump()}

@api_router.get("/favorites/stream")
async def get_favorite_stream():
    """Get favorite track stream URL"""
    fav = user_favorites.get("main")
    if not fav or not fav.track:
        raise HTTPException(status_code=404, detail="No favorite saved")
    
    # Refresh URL
    if fav.track.file_id:
        new_url = get_telegram_audio_url(fav.track.file_id)
        if new_url:
            fav.track.audio_url = new_url
    
    return {
        "audio_url": fav.track.audio_url,
        "track": fav.track.model_dump()
    }

# ==================== SHARE ====================
@api_router.get("/share/current")
async def get_share_data():
    """Get shareable data for current track"""
    if not radio_state.current_track:
        raise HTTPException(status_code=404, detail="No track playing")
    
    track = radio_state.current_track
    share_url = "https://madrid-rock-radio.onrender.com"
    
    return {
        "url": share_url,
        "title": f"🎸 {track.title} - {track.artist}",
        "description": "madrid-rock-radio.onrender.com",
        "track": track.model_dump()
    }

# ==================== SCHEDULING ENDPOINTS ====================

class QueueRequest(BaseModel):
    track: Track
    origin: str = "staged"
    time_str: Optional[str] = None  # "HH:MM" - if provided, queue at that time
    date_str: Optional[str] = None  # "DD/MM" - optional date

@api_router.post("/schedule/queue")
async def queue_track(req: QueueRequest):
    """Queue a track immediately or at a scheduled time"""
    global scheduled_tracks

    if not radio_state.playlist:
        raise HTTPException(status_code=400, detail="Playlist is empty")

    # If time provided, schedule for later
    if req.time_str:
        now = datetime.now(MADRID_TZ)
        try:
            hour, minute = map(int, req.time_str.split(":"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM")

        if req.date_str:
            try:
                day, month = map(int, req.date_str.split("/"))
                play_at = MADRID_TZ.localize(datetime(now.year, month, day, hour, minute))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format. Use DD/MM")
        else:
            play_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if play_at <= now:
                from datetime import timedelta
                play_at += timedelta(days=1)

        if play_at <= now:
            raise HTTPException(status_code=400, detail="Scheduled time is in the past")

        scheduled_tracks.append({
            "track": req.track,
            "play_at": play_at,
            "origin": req.origin
        })
        logger.info(f"📅 Scheduled: {req.track.artist} - {req.track.title} for {play_at.strftime('%d/%m at %H:%M')} Madrid time")
        logger.info(f"📋 scheduled_tracks now has {len(scheduled_tracks)} entries")
        time_str = play_at.strftime("%d/%m at %H:%M")
        return {"message": f"Scheduled '{req.track.title}' for {time_str} (Madrid time)"}

    # Otherwise queue immediately at position 5
    actual_track = next(
        (t for t in radio_state.playlist if t.file_unique_id == req.track.file_unique_id),
        None
    )

    if not actual_track:
        actual_track = req.track

    radio_state.playlist = [t for t in radio_state.playlist
                         if t.file_unique_id != track.file_unique_id]

    current_idx = next((i for i, t in enumerate(radio_state.playlist)
                        if radio_state.current_track and t.id == radio_state.current_track.id), 0)
    insert_idx = min(current_idx + 5, len(radio_state.playlist))
    radio_state.playlist.insert(insert_idx, actual_track)

    logger.info(f"🎯 Queued: {actual_track.artist} - {actual_track.title} at position 5")
    return {"message": f"Queued '{actual_track.title}' to play in approximately 5 songs"}


@api_router.get("/schedule/status")
async def get_schedule_status():
    """Check current schedule"""
    if not scheduled_tracks:
        return {"scheduled": []}
    return {
        "scheduled": [
            {
                "title": s["track"].title,
                "artist": s["track"].artist,
                "play_at": s["play_at"].strftime("%d/%m at %H:%M"),
                "origin": s["origin"]
            } for s in scheduled_tracks
        ]
    }
    
# ==================== STATS ====================
STATS_KEY = os.getenv('STATS_KEY', 'madridrock')

@api_router.get("/stats")
async def get_radio_stats(key: str = ""):
    if key != STATS_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Build upcoming list from current position
    upcoming = get_upcoming_tracks(20)

    stats = get_stats(radio_state.playlist, radio_state.current_track, upcoming)

    # Add scheduled track info if any
    stats["current"] = (
        f"#{radio_state.current_track.playlist_index or '?'} - "
        f"{radio_state.current_track.artist} - {radio_state.current_track.title}"
    ) if radio_state.current_track else None

    stats["scheduled"] = [
        {
            "title": s["track"].title,
            "artist": s["track"].artist,
            "play_at": s["play_at"].strftime("%d/%m at %H:%M")
        } for s in scheduled_tracks
    ] or None

    return stats

# ==================== SETUP ====================
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await initialize_radio()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
