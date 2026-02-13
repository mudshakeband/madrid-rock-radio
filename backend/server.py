from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import os
import logging
import asyncio
import time
import uuid
import re
import httpx
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Madrid Rock Radio")
api_router = APIRouter(prefix="/api")

# ==================== TELEGRAM CONFIG ====================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')  # Your personal chat ID

# Store songs in memory (will be rebuilt from Telegram on startup)
SONGS_DB = {}  # file_id -> Track data

# Track last update_id to avoid processing duplicates
last_update_id = 0

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
async def scan_telegram_history():
    """Scan Telegram chat history to rebuild song database from all previously sent MP3s"""
    global SONGS_DB
    
    if not TELEGRAM_BOT_TOKEN:
        return
    
    logger.info("🔍 Scanning Telegram chat history for MP3 files...")
    
    try:
        # Get all updates (Telegram keeps up to 24 hours of history)
        # But we'll use a better approach: get updates with a large limit
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {
            "offset": 0,  # Start from beginning
            "limit": 100  # Max allowed per request
        }
        
        all_songs_found = {}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=30.0)
            data = response.json()
            
            if not data.get('ok'):
                logger.error(f"❌ Failed to get Telegram history: {data}")
                return
            
            updates = data.get('result', [])
            logger.info(f"📥 Processing {len(updates)} messages from Telegram history...")
            
            for update in updates:
                message = update.get('message', {})
                
                # Check for audio file
                audio = message.get('audio')
                document = message.get('document')
                
                file_info = None
                if audio:
                    file_info = audio
                elif document and document.get('mime_type') == 'audio/mpeg':
                    file_info = document
                
                if file_info:
                    file_id = file_info['file_id']
                    filename = file_info.get('file_name', 'Unknown Track.mp3')
                    parsed = parse_filename(filename)
                    duration = file_info.get('duration', 180)
                    
                    track = Track(
                        file_id=file_id,
                        title=parsed["title"],
                        artist=parsed["artist"],
                        duration=duration,
                        audio_url=f"/api/radio/stream/{file_id}",
                        thumbnail=None
                    )
                    
                    all_songs_found[file_id] = track
                    logger.info(f"  ✓ Found: {track.artist} - {track.title}")
        
        # Update the global database
        SONGS_DB = all_songs_found
        logger.info(f"✅ Loaded {len(SONGS_DB)} songs from Telegram history")
        
        if SONGS_DB:
            await reload_playlist()
        
    except Exception as e:
        logger.error(f"❌ Error scanning Telegram history: {e}")
        import traceback
        logger.error(traceback.format_exc())

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

async def send_telegram_message(chat_id: str, text: str):
    """Send a message via Telegram bot"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, timeout=10.0)
            return response.json()
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")

async def process_telegram_updates():
    """Process incoming Telegram messages (audio files)"""
    global last_update_id
    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN not set!")
        return
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {
            "offset": last_update_id + 1,
            "timeout": 30
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=35.0)
            data = response.json()
            
            if not data.get('ok'):
                logger.error(f"❌ Telegram API error: {data}")
                return
            
            updates = data.get('result', [])
            
            for update in updates:
                update_id = update.get('update_id')
                last_update_id = max(last_update_id, update_id)
                
                message = update.get('message', {})
                chat_id = message.get('chat', {}).get('id')
                
                # Check for audio file
                audio = message.get('audio')
                document = message.get('document')
                
                file_info = None
                if audio:
                    file_info = audio
                elif document and document.get('mime_type') == 'audio/mpeg':
                    file_info = document
                
                if file_info:
                    # Add song to database
                    file_id = file_info['file_id']
                    filename = file_info.get('file_name', 'Unknown Track.mp3')
                    parsed = parse_filename(filename)
                    duration = file_info.get('duration', 180)
                    
                    track = Track(
                        file_id=file_id,
                        title=parsed["title"],
                        artist=parsed["artist"],
                        duration=duration,
                        audio_url=f"/api/radio/stream/{file_id}",
                        thumbnail=None
                    )
                    
                    SONGS_DB[file_id] = track
                    logger.info(f"✅ Added song: {track.artist} - {track.title}")
                    
                    # Confirm to user
                    await send_telegram_message(
                        chat_id,
                        f"✅ *Added to radio:*\n🎵 {track.artist} - {track.title}\n\nTotal songs: {len(SONGS_DB)}"
                    )
                    
                    # Reload playlist
                    await reload_playlist()
                
                # Check for /list command
                text = message.get('text', '')
                if text.startswith('/list'):
                    if not SONGS_DB:
                        await send_telegram_message(chat_id, "📭 No songs yet! Send me some MP3 files.")
                    else:
                        song_list = "\n".join([
                            f"{i+1}. {t.artist} - {t.title}"
                            for i, t in enumerate(SONGS_DB.values())
                        ])
                        await send_telegram_message(
                            chat_id,
                            f"🎸 *Madrid Rock Radio Playlist* ({len(SONGS_DB)} songs)\n\n{song_list}"
                        )
                
                # Check for /clear command
                if text.startswith('/clear'):
                    SONGS_DB.clear()
                    await send_telegram_message(chat_id, "🗑️ Playlist cleared!")
                    await reload_playlist()
                
                # Check for /start or /help
                if text.startswith('/start') or text.startswith('/help'):
                    help_text = """🎸 *Madrid Rock Radio Bot*

Just send me MP3 files and I'll add them to the radio playlist!

*Commands:*
/list - Show all songs
/clear - Clear playlist
/help - Show this message

*How to add songs:*
1. Send MP3 file to this chat
2. Filename format: `Artist - Title.mp3`
3. That's it! Song is live on the radio 📻"""
                    await send_telegram_message(chat_id, help_text)
            
    except Exception as e:
        logger.error(f"❌ Error processing Telegram updates: {e}")
        import traceback
        logger.error(traceback.format_exc())

async def reload_playlist():
    """Reload radio playlist from songs database"""
    import random
    
    tracks = list(SONGS_DB.values())
    random.shuffle(tracks)
    radio_state.playlist = tracks
    
    # If no current track, start playing
    if not radio_state.current_track and tracks:
        await play_next_track()
    
    logger.info(f"🔄 Playlist reloaded: {len(tracks)} songs")

async def telegram_polling_loop():
    """Background task that polls Telegram for new messages"""
    logger.info("🤖 Starting Telegram polling loop...")
    
    while True:
        try:
            await process_telegram_updates()
            await asyncio.sleep(2)  # Poll every 2 seconds
        except Exception as e:
            logger.error(f"Error in polling loop: {e}")
            await asyncio.sleep(5)

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
    """Initialize radio"""
    logger.info("🎸 Madrid Rock Radio - Initializing...")
    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN not set!")
        logger.error("   Get your token from @BotFather on Telegram")
        logger.error("   Then add it to Render environment variables")
        return
    
    logger.info("✅ Telegram bot configured")
    
    # Scan Telegram history to rebuild song database
    await scan_telegram_history()
    
    logger.info(f"📻 Songs in database: {len(SONGS_DB)}")
    
    if not SONGS_DB:
        logger.info("💡 No songs yet! Send MP3 files to your bot on Telegram to get started.")
        logger.info("   1. Open Telegram and search for your bot")
        logger.info("   2. Send /start")
        logger.info("   3. Send MP3 files directly to the bot")

async def play_next_track():
    """Move to next track in playlist"""
    if not radio_state.playlist:
        logger.warning("⚠️  Playlist empty")
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
            "started_at": 0,
            "playlist_count": len(SONGS_DB),
            "just_played": None,
            "up_next": []
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
    
    # Get upcoming tracks
    up_next = radio_state.playlist[:3] if len(radio_state.playlist) >= 3 else radio_state.playlist
    
    # Get last played
    just_played = radio_state.history[-1] if radio_state.history else None
    
    return {
        "current_track": radio_state.current_track.model_dump() if radio_state.current_track else None,
        "position": current_pos,
        "is_playing": radio_state.is_playing,
        "started_at": radio_state.started_at,
        "playlist_count": len(SONGS_DB),
        "just_played": just_played.model_dump() if just_played else None,
        "up_next": [t.model_dump() for t in up_next]
    }

@api_router.post("/radio/next")
async def skip_track():
    """Skip to next track"""
    await play_next_track()
    return {"message": "Skipped to next track"}

@api_router.get("/radio/stream")
async def get_stream_url():
    """Get current track stream URL - required by frontend"""
    if not radio_state.current_track:
        raise HTTPException(status_code=404, detail="No track playing")
    
    # Calculate current position
    current_pos = radio_state.position
    if radio_state.is_playing:
        elapsed = time.time() - radio_state.started_at
        current_pos = elapsed
    
    # Return the audio URL and current position
    return {
        "audio_url": radio_state.current_track.audio_url,
        "position": current_pos
    }

@api_router.get("/radio/stream/{file_id}")
async def stream_telegram_audio(file_id: str, request: Request):
    """Stream audio from Telegram with range request support"""
    try:
        logger.info(f"🎵 Streaming request for file_id: {file_id}")
        
        # Validate file_id format (basic check)
        if not file_id or len(file_id) < 20:
            logger.error(f"❌ Invalid file_id: {file_id}")
            raise HTTPException(status_code=400, detail="Invalid file_id")
        
        # Get download URL from Telegram
        try:
            download_url = await get_telegram_file_url(file_id)
            logger.info(f"✅ Got Telegram URL: {download_url[:50]}...")
        except Exception as e:
            logger.error(f"❌ Failed to get Telegram file URL: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to get file from Telegram: {str(e)}"
            )
        
        # Parse range header from browser
        range_header = request.headers.get("range")
        
        headers_to_send = {}
        if range_header:
            headers_to_send["Range"] = range_header
            logger.info(f"📦 Range request: {range_header}")
        
        # Stream the file from Telegram
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", download_url, headers=headers_to_send, timeout=60.0) as response:
                    
                    if response.status_code not in [200, 206]:
                        logger.error(f"❌ Telegram returned {response.status_code}")
                        # Read error response
                        error_body = await response.aread()
                        logger.error(f"❌ Error body: {error_body[:200]}")
                        raise HTTPException(
                            status_code=response.status_code,
                            detail=f"Telegram API error: {response.status_code}"
                        )
                    
                    # Prepare response headers
                    response_headers = {
                        "Content-Type": "audio/mpeg",
                        "Accept-Ranges": "bytes",
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "Expires": "0",
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
                        "Access-Control-Allow-Headers": "Range",
                    }
                    
                    # Forward content-length if available
                    if "content-length" in response.headers:
                        response_headers["Content-Length"] = response.headers["content-length"]
                        logger.info(f"📦 Content-Length: {response.headers['content-length']}")
                    
                    # Forward content-range for partial responses
                    if "content-range" in response.headers:
                        response_headers["Content-Range"] = response.headers["content-range"]
                        logger.info(f"📦 Content-Range: {response.headers['content-range']}")
                    
                    # Stream the content in chunks
                    from fastapi.responses import StreamingResponse
                    
                    async def stream_generator():
                        try:
                            chunk_count = 0
                            async for chunk in response.aiter_bytes(chunk_size=65536):
                                chunk_count += 1
                                if chunk_count == 1:
                                    logger.info(f"📡 Streaming started, first chunk: {len(chunk)} bytes")
                                yield chunk
                            logger.info(f"✅ Streaming complete: {chunk_count} chunks")
                        except Exception as e:
                            logger.error(f"❌ Error streaming chunk: {e}")
                            raise
                    
                    # Return 206 for range requests, 200 otherwise
                    status_code = 206 if response.status_code == 206 else 200
                    logger.info(f"📤 Returning {status_code} response")
                    
                    return StreamingResponse(
                        stream_generator(),
                        status_code=status_code,
                        headers=response_headers,
                        media_type="audio/mpeg"
                    )
        except httpx.RequestError as e:
            logger.error(f"❌ Network error streaming from Telegram: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Network error contacting Telegram: {str(e)}"
            )
            
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error in stream_telegram_audio: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

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

# ==================== ADMIN ====================
@api_router.get("/admin/songs")
async def get_all_songs():
    """Get all songs in database (for debugging)"""
    return {
        "total": len(SONGS_DB),
        "songs": [t.model_dump() for t in SONGS_DB.values()]
    }

@api_router.get("/admin/test-stream/{file_id}")
async def test_stream(file_id: str):
    """Test if a file_id can be streamed (for debugging)"""
    try:
        logger.info(f"🧪 Testing file_id: {file_id}")
        
        # Try to get the download URL
        download_url = await get_telegram_file_url(file_id)
        logger.info(f"✅ Got URL: {download_url}")
        
        # Try to fetch first few bytes
        async with httpx.AsyncClient() as client:
            response = await client.get(download_url, headers={"Range": "bytes=0-1023"}, timeout=10.0)
            
            return {
                "file_id": file_id,
                "download_url": download_url,
                "telegram_status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "content_length": response.headers.get("content-length"),
                "first_bytes": len(await response.aread()),
                "success": response.status_code in [200, 206]
            }
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        return {
            "file_id": file_id,
            "error": str(e),
            "success": False
        }

@api_router.post("/admin/rescan")
async def manual_rescan():
    """Manually rescan Telegram history for songs"""
    await scan_telegram_history()
    return {
        "message": "Telegram history rescanned",
        "total": len(SONGS_DB)
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
    # Initialize radio
    await initialize_radio()
    
    # Start Telegram polling in background
    asyncio.create_task(telegram_polling_loop())
    logger.info("🤖 Telegram bot is listening for songs...")

@app.get("/")
async def root():
    return {
        "message": "Madrid Rock Radio API 🎸",
        "status": "running",
        "source": "telegram",
        "songs": len(SONGS_DB)
    }

@app.get("/health")
async def health_check():
    telegram_configured = bool(TELEGRAM_BOT_TOKEN)
    return {
        "status": "healthy",
        "telegram_configured": telegram_configured,
        "songs_in_db": len(SONGS_DB),
        "tracks_loaded": len(radio_state.playlist)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
