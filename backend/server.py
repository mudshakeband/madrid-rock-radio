from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import logging
import asyncio
import time
import uuid
import re
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Madrid Rock Radio")
api_router = APIRouter(prefix="/api")

# ==================== TELEGRAM CONFIG ====================
# Get these from environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '')

# You'll set these in Render dashboard:
# TELEGRAM_BOT_TOKEN = your bot token from BotFather
# TELEGRAM_CHANNEL_ID = your channel ID (we'll show you how to get this)

# ==================== MODELS ====================
class Track(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_id: str  # Telegram file_id
    title: str = ""
    artist: str = ""
    duration: int = 0
    audio_url: Optional[str] = None
    thumbnail: Optional[str] = None

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

# ==================== TELEGRAM HELPERS ====================
def parse_filename(filename: str) -> dict:
    """Parse audio filename to extract artist and title"""
    # Remove extension
    name = filename.rsplit('.', 1)[0]
    
    # Remove leading numbers (e.g., "01 - " or "01.")
    name = re.sub(r'^\d+\s*[-_.]?\s*', '', name)
    
    # Try to split by " - " or "-"
    if ' - ' in name:
        parts = name.split(' - ', 1)
        return {"artist": parts[0].strip(), "title": parts[1].strip()}
    
    if '-' in name:
        parts = name.split('-', 1)
        return {"artist": parts[0].strip(), "title": parts[1].strip()}
    
    return {"artist": "Unknown Artist", "title": name.strip()}

async def fetch_telegram_playlist() -> List[Track]:
    """Fetch audio files from Telegram channel"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        logger.error("❌ Telegram credentials not configured!")
        return []
    
    try:
        logger.info("🔄 Fetching songs from Telegram channel...")
        
        # Use Telegram Bot API to get updates/messages
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            data = response.json()
            
            if not data.get('ok'):
                logger.error(f"❌ Telegram API error: {data}")
                return []
            
            tracks = []
            seen_file_ids = set()
            
            # Parse messages for audio files
            for update in data.get('result', []):
                message = update.get('message', {})
                
                # Check if message is from our channel
                chat = message.get('chat', {})
                chat_id = str(chat.get('id', ''))
                
                if chat_id != TELEGRAM_CHANNEL_ID:
                    continue
                
                # Get audio file info
                audio = message.get('audio')
                document = message.get('document')
                
                file_info = None
                if audio:
                    file_info = audio
                elif document and document.get('mime_type') == 'audio/mpeg':
                    file_info = document
                
                if not file_info:
                    continue
                
                file_id = file_info['file_id']
                
                # Avoid duplicates
                if file_id in seen_file_ids:
                    continue
                seen_file_ids.add(file_id)
                
                # Get filename and parse artist/title
                filename = file_info.get('file_name', 'Unknown Track.mp3')
                parsed = parse_filename(filename)
                
                # Get duration
                duration = file_info.get('duration', 180)
                
                # Get thumbnail if available
                thumbnail_file_id = None
                if 'thumb' in file_info:
                    thumbnail_file_id = file_info['thumb'].get('file_id')
                
                track = Track(
                    file_id=file_id,
                    title=parsed["title"],
                    artist=parsed["artist"],
                    duration=duration,
                    audio_url=f"/api/radio/stream/{file_id}",  # Our proxy endpoint
                    thumbnail=thumbnail_file_id
                )
                
                tracks.append(track)
                logger.info(f"📀 {track.artist} - {track.title} ({duration}s)")
            
            logger.info(f"✅ Found {len(tracks)} songs in Telegram channel")
            return tracks
            
    except Exception as e:
        logger.error(f"❌ Error fetching Telegram playlist: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []

async def get_telegram_file_url(file_id: str) -> str:
    """Get direct download URL for Telegram file"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
        params = {"file_id": file_id}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            data = response.json()
            
            if not data.get('ok'):
                raise Exception(f"Telegram API error: {data}")
            
            file_path = data['result']['file_path']
            download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
            
            return download_url
            
    except Exception as e:
        logger.error(f"❌ Error getting Telegram file URL: {e}")
        raise

# ==================== RADIO LOGIC ====================
async def initialize_radio():
    """Initialize radio with Telegram playlist"""
    logger.info("🎸 Madrid Rock Radio - Initializing...")
    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN not set! Add it in Render dashboard.")
        logger.error("   Go to: Dashboard → Environment → Add TELEGRAM_BOT_TOKEN")
        return
    
    if not TELEGRAM_CHANNEL_ID:
        logger.error("❌ TELEGRAM_CHANNEL_ID not set! Add it in Render dashboard.")
        logger.error("   Go to: Dashboard → Environment → Add TELEGRAM_CHANNEL_ID")
        return
    
    # Fetch songs from Telegram
    tracks = await fetch_telegram_playlist()
    
    if not tracks:
        logger.error("❌ No songs found! Make sure:")
        logger.error("   1. Bot is admin in your channel")
        logger.error("   2. You've sent audio files to the channel")
        logger.error("   3. TELEGRAM_CHANNEL_ID is correct (including the minus sign!)")
        return
    
    # Shuffle and load playlist
    import random
    random.shuffle(tracks)
    radio_state.playlist = tracks
    
    # Start playing first track
    await play_next_track()
    
    logger.info(f"✅ Radio ready! {len(tracks)} songs loaded")

async def play_next_track():
    """Move to next track in playlist"""
    if not radio_state.playlist:
        logger.warning("⚠️  Playlist empty, reloading...")
        await initialize_radio()
        return
    
    # Save current track to history
    if radio_state.current_track:
        radio_state.history.append(radio_state.current_track)
        if len(radio_state.history) > 50:
            radio_state.history = radio_state.history[-50:]
    
    # Get next track
    radio_state.current_track = radio_state.playlist.pop(0)
    radio_state.position = 0
    radio_state.started_at = time.time()
    
    logger.info(f"▶️  Now playing: {radio_state.current_track.artist} - {radio_state.current_track.title}")
    
    # Add track back to end of playlist (infinite loop)
    radio_state.playlist.append(radio_state.current_track)

# ==================== API ENDPOINTS ====================
@api_router.get("/radio/state")
async def get_radio_state():
    """Get current radio state"""
    if not radio_state.current_track:
        return {
            "current_track": None,
            "position": 0,
            "is_playing": False,
            "queue": [],
            "history": []
        }
    
    # Calculate current position
    current_pos = radio_state.position
    if radio_state.is_playing:
        elapsed = time.time() - radio_state.started_at
        current_pos = elapsed
        
        # Auto-advance if track finished
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

@api_router.get("/radio/stream/{file_id}")
async def stream_telegram_audio(file_id: str):
    """Stream audio from Telegram"""
    try:
        logger.info(f"🎵 Streaming file: {file_id}")
        
        # Get download URL from Telegram
        download_url = await get_telegram_file_url(file_id)
        
        # Stream the file
        async with httpx.AsyncClient() as client:
            response = await client.get(download_url, timeout=30.0)
            
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to fetch audio from Telegram")
            
            return Response(
                content=response.content,
                media_type="audio/mpeg",
                headers={
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=3600",
                    "Access-Control-Allow-Origin": "*",
                }
            )
            
    except Exception as e:
        logger.error(f"❌ Error streaming audio: {e}")
        raise HTTPException(status_code=500, detail=f"Stream error: {str(e)}")

@api_router.get("/radio/playlist")
async def get_playlist():
    """Get full playlist"""
    return {"playlist": [t.model_dump() for t in radio_state.playlist]}

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
    
    logger.info(f"❤️  Playing favorite: {fav.track.title}")
    
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
    return {
        "message": "Madrid Rock Radio API 🎸",
        "status": "running",
        "source": "telegram"
    }

@app.get("/health")
async def health_check():
    telegram_configured = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID)
    return {
        "status": "healthy",
        "telegram_configured": telegram_configured,
        "tracks_loaded": len(radio_state.playlist)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
