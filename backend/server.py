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
import json
import re
from datetime import datetime

# Try to import Google Drive API (optional)
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_IMPORTS_AVAILABLE = True
except ImportError:
    GOOGLE_IMPORTS_AVAILABLE = False
    logging.warning("Google API libraries not installed - Drive integration disabled")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Madrid Rock Radio")
api_router = APIRouter(prefix="/api")

# ==================== GOOGLE DRIVE CONFIG ====================
DRIVE_FOLDER_ID = "10bt7zLoZrZH6JOJQQqPNauUsZ82x3_sm"
DRIVE_API_ENABLED = False
drive_service = None

# Try to set up Drive API from environment variable
if GOOGLE_IMPORTS_AVAILABLE:
    service_account_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
    
    if service_account_json:
        try:
            # Parse JSON from environment variable
            creds_dict = json.loads(service_account_json)
            credentials = service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
            drive_service = build('drive', 'v3', credentials=credentials)
            DRIVE_API_ENABLED = True
            logger.info("✅ Google Drive API enabled (from environment variable)")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Drive API: {e}")
    else:
        logger.info("ℹ️  No GOOGLE_SERVICE_ACCOUNT_JSON environment variable - Drive API disabled")
else:
    logger.info("ℹ️  Google API libraries not installed - using YouTube only")

# ==================== MODELS ====================
class Track(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    youtube_url: Optional[str] = None  # Optional now (for Drive files)
    file_id: Optional[str] = None  # Google Drive file ID
    title: str = ""
    artist: str = ""
    duration: int = 0
    audio_url: Optional[str] = None
    thumbnail: Optional[str] = None
    source: str = "youtube"  # 'youtube' or 'drive'

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
    history: List[Track] = []

class UserFavorite(BaseModel):
    track: Optional[Track] = None
    saved_at: float = 0

# ==================== GLOBAL STATE ====================
radio_state = RadioState()
user_favorites = {}

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
    """Refresh audio URL for a track - ALWAYS refresh to ensure fresh URLs"""
    try:
        logger.info(f"Fetching fresh URL for: {track.title}")
        info = await asyncio.to_thread(get_audio_url, track.youtube_url)
        if info:
            track.audio_url = info['audio_url']
            track.title = track.title or info['title']
            track.artist = track.artist or info['artist']
            track.duration = info['duration']
            track.thumbnail = info['thumbnail']
            logger.info(f"✓ Fresh URL ready for: {track.title}")
    except Exception as e:
        logger.error(f"Error refreshing URL: {e}")
    return track

# ==================== GOOGLE DRIVE HELPERS ====================
def parse_filename(filename: str) -> dict:
    """Parse MP3 filename to extract artist and title"""
    # Remove extension
    name = filename.rsplit('.', 1)[0]
    
    # Remove track numbers
    name = re.sub(r'^\d+\s*[-_.]?\s*', '', name)
    
    # Split by " - "
    if ' - ' in name:
        parts = name.split(' - ', 1)
        return {"artist": parts[0].strip(), "title": parts[1].strip()}
    
    if '-' in name:
        parts = name.split('-', 1)
        return {"artist": parts[0].strip(), "title": parts[1].strip()}
    
    return {"artist": "Unknown Artist", "title": name.strip()}

def get_drive_direct_link(file_id: str) -> str:
    """Get streamable URL for Google Drive file
    
    For public files, this URL format works for direct streaming:
    - No virus scan redirect
    - Works in HTML5 audio elements
    - Proper CORS headers
    
    IMPORTANT: Files must be set to "Anyone with the link can view"
    """
    return f"https://docs.google.com/uc?export=open&id={file_id}"

async def fetch_drive_playlist() -> List[Track]:
    """Fetch MP3 files from Google Drive folder"""
    if not DRIVE_API_ENABLED:
        return []
    
    try:
        logger.info("🔄 Scanning Google Drive folder...")
        
        query = f"'{DRIVE_FOLDER_ID}' in parents and (mimeType='audio/mpeg' or name contains '.mp3') and trashed=false"
        
        results = drive_service.files().list(
            q=query,
            fields="files(id, name, size)",
            orderBy="name",
            pageSize=100
        ).execute()
        
        files = results.get('files', [])
        logger.info(f"✅ Found {len(files)} MP3 files in Drive")
        
        tracks = []
        for file_info in files:
            file_id = file_info['id']
            filename = file_info['name']
            
            parsed = parse_filename(filename)
            
            track = Track(
                file_id=file_id,
                title=parsed["title"],
                artist=parsed["artist"],
                filename=filename,
                audio_url=get_drive_direct_link(file_id),
                source="drive",
                duration=180  # Default 3 min
            )
            tracks.append(track)
            logger.info(f"📀 {track.artist} - {track.title}")
        
        return tracks
        
    except Exception as e:
        logger.error(f"❌ Error fetching from Drive: {e}")
        return []

# ==================== RADIO MANAGEMENT ====================
async def initialize_radio():
    """Initialize radio - prefer Google Drive, fall back to YouTube"""
    global radio_state
    
    if not radio_state.playlist:
        # Try Google Drive first
        if DRIVE_API_ENABLED:
            logger.info("🎵 Loading playlist from Google Drive...")
            drive_tracks = await fetch_drive_playlist()
            if drive_tracks:
                radio_state.playlist = drive_tracks
                random.shuffle(radio_state.playlist)
                await play_next_track()
                logger.info(f"✅ Radio started with {len(drive_tracks)} Drive tracks")
                return
        
        # Fall back to YouTube
        logger.info("🎵 Loading playlist from YouTube...")
        for track_data in DEFAULT_PLAYLIST:
            track = Track(**track_data, source="youtube")
            radio_state.playlist.append(track)
        
        random.shuffle(radio_state.playlist)
        await play_next_track()
        logger.info(f"✅ Radio started with {len(DEFAULT_PLAYLIST)} YouTube tracks")

async def play_next_track():
    """Advance to next track"""
    global radio_state
    
    if not radio_state.playlist:
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
    
    logger.info(f"=== Changing to: {radio_state.current_track.title} ({radio_state.current_track.source}) ===")
    
    # Only refresh YouTube URLs (Drive URLs don't expire)
    if radio_state.current_track.source == "youtube":
        radio_state.current_track = await refresh_track_url(radio_state.current_track)
    
    radio_state.started_at = time.time()
    radio_state.position = 0
    radio_state.is_playing = True
    
    logger.info(f"▶ Now playing: {radio_state.current_track.title}")

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
    
    # Check if track ended - advance to next
    if (radio_state.current_track and 
        current_position >= radio_state.current_track.duration - 1):
        logger.info(f"Track ended: {radio_state.current_track.title}")
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
    """Get audio stream URL - refresh YouTube, Drive URLs are permanent"""
    if not radio_state.current_track:
        raise HTTPException(status_code=404, detail="No track playing")
    
    # Only refresh YouTube URLs
    if radio_state.current_track.source == "youtube":
        logger.info(f"Refreshing YouTube stream: {radio_state.current_track.title}")
        radio_state.current_track = await refresh_track_url(radio_state.current_track)
    
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
    """Save current track as favorite"""
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
    
    return {"favorite": fav.track.model_dump()}

@api_router.get("/favorites/stream")
async def get_favorite_stream():
    """Get favorite track stream URL - always fresh"""
    fav = user_favorites.get("main")
    if not fav or not fav.track:
        raise HTTPException(status_code=404, detail="No favorite saved")
    
    # Always refresh URL
    logger.info(f"Favorite stream requested: {fav.track.title}")
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
    share_url = f"https://madridrock.radio/?track={track.id}"
    
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
