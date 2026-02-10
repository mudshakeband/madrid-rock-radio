from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import logging
import yt_dlp
import asyncio
import random
import time
import uuid
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Madrid Rock Radio")
api_router = APIRouter(prefix="/api")

# ==================== MODELS ====================
class Track(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    youtube_url: str
    title: str = ""
    artist: str = ""
    duration: int = 0
    audio_url: Optional[str] = None
    thumbnail: Optional[str] = None

class TrackCreate(BaseModel):
    youtube_url: str
    title: Optional[str] = None
    artist: Optional[str] = None

class RadioState(BaseModel):
    current_track: Optional[Track] = None
    position: float = 0
    is_playing: bool = True
    started_at: float = 0
    playlist: List[Track] = []
    history: List[Track] = []  # Last 5 played tracks

class UserFavorite(BaseModel):
    track: Optional[Track] = None
    saved_at: float = 0

# ==================== GLOBAL STATE ====================
radio_state = RadioState()
user_favorites = {}  # In production, this would be per-user in DB

# Default playlist
DEFAULT_PLAYLIST = [
    {"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Never Gonna Give You Up", "artist": "Rick Astley"},
    {"youtube_url": "https://www.youtube.com/watch?v=fJ9rUzIMcZQ", "title": "Bohemian Rhapsody", "artist": "Queen"},
    {"youtube_url": "https://www.youtube.com/watch?v=hTWKbfoikeg", "title": "Smells Like Teen Spirit", "artist": "Nirvana"},
    {"youtube_url": "https://www.youtube.com/watch?v=kJQP7kiw5Fk", "title": "Despacito", "artist": "Luis Fonsi"},
    {"youtube_url": "https://www.youtube.com/watch?v=9bZkp7q19f0", "title": "Gangnam Style", "artist": "PSY"},
    {"youtube_url": "https://www.youtube.com/watch?v=60ItHLz5WEA", "title": "Faded", "artist": "Alan Walker"},
    {"youtube_url": "https://www.youtube.com/watch?v=RgKAFK5djSk", "title": "Waka Waka", "artist": "Shakira"},
]

# ==================== YT-DLP HELPERS ====================
def get_audio_url(youtube_url: str) -> dict:
    """Extract audio URL and metadata from YouTube"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            audio_url = info.get('url')
            
            if not audio_url:
                formats = info.get('formats', [])
                audio_formats = [f for f in formats if f.get('acodec') != 'none']
                if audio_formats:
                    audio_url = audio_formats[-1].get('url')
            
            return {
                'audio_url': audio_url,
                'title': info.get('title', 'Unknown Track'),
                'artist': info.get('uploader', 'Unknown Artist'),
                'duration': info.get('duration', 180),
                'thumbnail': info.get('thumbnail', None)
            }
    except Exception as e:
        logger.error(f"Error extracting audio: {e}")
        return None

async def refresh_track_url(track: Track) -> Track:
    """Refresh audio URL for a track"""
    try:
        info = await asyncio.to_thread(get_audio_url, track.youtube_url)
        if info:
            track.audio_url = info['audio_url']
            track.title = track.title or info['title']
            track.artist = track.artist or info['artist']
            track.duration = info['duration']
            track.thumbnail = info['thumbnail']
    except Exception as e:
        logger.error(f"Error refreshing URL: {e}")
    return track

# ==================== RADIO MANAGEMENT ====================
async def initialize_radio():
    """Initialize radio with default playlist"""
    global radio_state
    
    if not radio_state.playlist:
        for track_data in DEFAULT_PLAYLIST:
            track = Track(**track_data)
            radio_state.playlist.append(track)
        
        random.shuffle(radio_state.playlist)
        await play_next_track()

async def play_next_track():
    """Advance to next track
    
    Playlist behavior:
    - Shuffles once on initialization
    - Plays through in order (no re-shuffling between tracks)
    - Loops back to start when reaching the end
    - "Up Next" shows the next 3 tracks in rotation order
    """
    global radio_state
    
    if not radio_state.playlist:
        return
    
    # Move current to history
    if radio_state.current_track:
        radio_state.history.insert(0, radio_state.current_track)
        radio_state.history = radio_state.history[:5]  # Keep last 5
    
    # Get next track (rotate playlist)
    if radio_state.current_track:
        current_idx = next((i for i, t in enumerate(radio_state.playlist) 
                          if t.id == radio_state.current_track.id), -1)
        next_idx = (current_idx + 1) % len(radio_state.playlist)
        radio_state.current_track = radio_state.playlist[next_idx]
    else:
        radio_state.current_track = radio_state.playlist[0]
    
    # Refresh audio URL
    radio_state.current_track = await refresh_track_url(radio_state.current_track)
    radio_state.started_at = time.time()
    radio_state.position = 0
    radio_state.is_playing = True
    
    logger.info(f"Now playing: {radio_state.current_track.title}")

def get_current_position() -> float:
    """Calculate current playback position"""
    if not radio_state.is_playing or not radio_state.current_track:
        return radio_state.position
    
    elapsed = time.time() - radio_state.started_at
    return elapsed % max(radio_state.current_track.duration, 1)

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
async def get_radio_state():
    """Get current radio state"""
    current_position = get_current_position()
    
    # Check if track ended
    if (radio_state.current_track and 
        current_position >= radio_state.current_track.duration - 1):
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
    if not radio_state.current_track or not radio_state.current_track.audio_url:
        if radio_state.current_track:
            radio_state.current_track = await refresh_track_url(radio_state.current_track)
        
        if not radio_state.current_track or not radio_state.current_track.audio_url:
            raise HTTPException(status_code=404, detail="No track playing")
    
    return {
        "audio_url": radio_state.current_track.audio_url,
        "position": get_current_position()
    }

@api_router.get("/radio/playlist")
async def get_playlist():
    """Get full playlist"""
    return {"playlist": [t.model_dump() for t in radio_state.playlist]}

@api_router.post("/radio/playlist")
async def add_to_playlist(track_data: TrackCreate):
    """Add track to playlist"""
    info = await asyncio.to_thread(get_audio_url, track_data.youtube_url)
    if not info:
        raise HTTPException(status_code=400, detail="Could not extract audio")
    
    track = Track(
        youtube_url=track_data.youtube_url,
        title=track_data.title or info['title'],
        artist=track_data.artist or info['artist'],
        duration=info['duration'],
        audio_url=info['audio_url'],
        thumbnail=info['thumbnail']
    )
    
    radio_state.playlist.append(track)
    
    if not radio_state.current_track:
        await play_next_track()
    
    return track

# ==================== FAVORITES ====================
@api_router.post("/favorites/save")
async def save_favorite():
    """Save current track as favorite (overwrites previous)"""
    if not radio_state.current_track:
        raise HTTPException(status_code=404, detail="No track playing")
    
    user_favorites["main"] = UserFavorite(
        track=radio_state.current_track,
        saved_at=time.time()
    )
    
    return {
        "message": "Track saved as favorite",
        "track": radio_state.current_track.model_dump()
    }

@api_router.get("/favorites/get")
async def get_favorite():
    """Get saved favorite"""
    fav = user_favorites.get("main")
    if not fav or not fav.track:
        return {"favorite": None}
    
    # Refresh URL if needed
    fav.track = await refresh_track_url(fav.track)
    
    return {"favorite": fav.track.model_dump()}

@api_router.get("/favorites/stream")
async def get_favorite_stream():
    """Get favorite track stream URL"""
    fav = user_favorites.get("main")
    if not fav or not fav.track:
        raise HTTPException(status_code=404, detail="No favorite saved")
    
    # Refresh URL
    fav.track = await refresh_track_url(fav.track)
    
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
    share_url = f"https://madridrock.radio/?track={track.id}"  # Will update with real domain
    
    return {
        "url": share_url,
        "title": f"🎸 {track.title} - {track.artist}",
        "description": "Now playing on Madrid Rock Radio",
        "image": track.thumbnail,
        "track": track.model_dump()
    }

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
