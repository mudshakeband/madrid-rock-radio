from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, Response
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
import io
from datetime import datetime

# Try to import Google Drive API (optional)
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
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
    youtube_url: Optional[str] = None
    file_id: Optional[str] = None
    title: str = ""
    artist: str = ""
    duration: int = 0
    audio_url: Optional[str] = None
    thumbnail: Optional[str] = None
    source: str = "youtube"

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
    name = filename.rsplit('.', 1)[0]
    name = re.sub(r'^\d+\s*[-_.]?\s*', '', name)
    
    if ' - ' in name:
        parts = name.split(' - ', 1)
        return {"artist": parts[0].strip(), "title": parts[1].strip()}
    
    if '-' in name:
        parts = name.split('-', 1)
        return {"artist": parts[0].strip(), "title": parts[1].strip()}
    
    return {"artist": "Unknown Artist", "title": name.strip()}

def get_drive_direct_link(file_id: str) -> str:
    """Get streamable URL for Google Drive file via backend proxy"""
    return f"/api/radio/proxy/{file_id}"

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
                audio_url=get_drive_direct_link(file_id),
                source="drive",
                duration=180
            )
            tracks.append(track)
            logger.info(f"📀 {track.artist} - {track.title}")
        
        return tracks
        
    except Exception as e:
        logger.error(f"Error fetching Drive playlist: {e}")
        return []

# ==================== RADIO LOGIC ====================
async def play_next_track():
    """Move to next track in playlist"""
    if not radio_state.playlist:
        return
    
    if radio_state.current_track:
        radio_state.history.append(radio_state.current_track)
        if len(radio_state.history) > 50:
            radio_state.history = radio_state.history[-50:]
    
    radio_state.current_track = radio_state.playlist.pop(0)
    radio_state.position = 0
    radio_state.started_at = time.time()
    
    # For YouTube tracks, refresh the URL
    if radio_state.current_track.source == "youtube":
        radio_state.current_track = await refresh_track_url(radio_state.current_track)
    
    logger.info(f"▶️  Now playing: {radio_state.current_track.title}")

async def initialize_radio():
    """Initialize radio with playlist"""
    logger.info("🎸 Initializing Madrid Rock Radio...")
    
    # Try to load from Drive first
    drive_tracks = await fetch_drive_playlist()
    
    if drive_tracks:
        logger.info(f"✅ Using {len(drive_tracks)} tracks from Google Drive")
        radio_state.playlist = drive_tracks
    else:
        logger.info("⚠️  No Drive tracks found, using YouTube fallback")
        for item in DEFAULT_PLAYLIST:
            info = await asyncio.to_thread(get_audio_url, item["youtube_url"])
            if info:
                track = Track(
                    youtube_url=item["youtube_url"],
                    title=item.get("title") or info['title'],
                    artist=item.get("artist") or info['artist'],
                    duration=info['duration'],
                    audio_url=info['audio_url'],
                    thumbnail=info['thumbnail'],
                    source="youtube"
                )
                radio_state.playlist.append(track)
    
    if radio_state.playlist:
        random.shuffle(radio_state.playlist)
        await play_next_track()
        logger.info("✅ Radio initialized and playing")
    else:
        logger.error("❌ Failed to initialize playlist")

# ==================== API ENDPOINTS ====================
@api_router.get("/radio/state")
async def get_radio_state():
    """Get current radio state"""
    current_pos = radio_state.position
    if radio_state.is_playing and radio_state.current_track:
        elapsed = time.time() - radio_state.started_at
        current_pos = elapsed
        
        if current_pos >= radio_state.current_track.duration:
            await play_next_track()
            current_pos = 0
    
    return {
        "current_track": radio_state.current_track.model_dump() if radio_state.current_track else None,
        "position": current_pos,
        "is_playing": radio_state.is_playing,
        "queue": [t.model_dump() for t in radio_state.playlist[:5]],
        "history": [t.model_dump() for t in radio_state.history[-5:]]
    }

@api_router.post("/radio/next")
async def skip_track():
    """Skip to next track"""
    await play_next_track()
    return {"message": "Skipped to next track"}

@api_router.get("/radio/proxy/{file_id}")
async def proxy_drive_audio(file_id: str, request: Request):
    """Proxy Google Drive audio with proper Range request support for HTML5 audio"""
    
    if not DRIVE_API_ENABLED:
        raise HTTPException(status_code=503, detail="Drive API not configured")
    
    try:
        # Get file metadata
        file_metadata = drive_service.files().get(
            fileId=file_id,
            fields="name,mimeType,size"
        ).execute()
        
        file_size = int(file_metadata.get('size', 0))
        file_name = file_metadata.get('name', 'unknown.mp3')
        logger.info(f"📀 Streaming: {file_name} ({file_size} bytes)")
        
        # Parse range header
        range_header = request.headers.get("range")
        
        if range_header:
            # Handle partial content request (HTTP 206)
            logger.info(f"🎵 Range request: {range_header}")
            range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
            
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                end = min(end, file_size - 1)
                chunk_size = end - start + 1
                
                logger.info(f"📦 Serving bytes {start}-{end}/{file_size}")
                
                # Get media from Drive
                media_request = drive_service.files().get_media(fileId=file_id)
                media_request.headers['Range'] = f'bytes={start}-{end}'
                
                # Download chunk
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, media_request, chunksize=chunk_size)
                
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                
                chunk_data = fh.getvalue()
                
                return Response(
                    content=chunk_data,
                    status_code=206,
                    headers={
                        "Content-Type": "audio/mpeg",
                        "Content-Range": f"bytes {start}-{end}/{file_size}",
                        "Content-Length": str(len(chunk_data)),
                        "Accept-Ranges": "bytes",
                        "Cache-Control": "public, max-age=3600",
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
                    },
                    media_type="audio/mpeg"
                )
        else:
            # Full file request (rare)
            logger.info(f"🎵 Full file request")
            
            media_request = drive_service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, media_request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            file_data = fh.getvalue()
            
            return Response(
                content=file_data,
                status_code=200,
                headers={
                    "Content-Type": "audio/mpeg",
                    "Content-Length": str(len(file_data)),
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=3600",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Expose-Headers": "Content-Length, Accept-Ranges",
                },
                media_type="audio/mpeg"
            )
            
    except Exception as e:
        logger.error(f"❌ Error proxying Drive audio for {file_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")

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
    """Get favorite track stream URL"""
    fav = user_favorites.get("main")
    if not fav or not fav.track:
        raise HTTPException(status_code=404, detail="No favorite saved")
    
    logger.info(f"Favorite stream requested: {fav.track.title}")
    if fav.track.source == "youtube":
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

@app.get("/")
async def root():
    return {"message": "Madrid Rock Radio API", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "drive_enabled": DRIVE_API_ENABLED}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
