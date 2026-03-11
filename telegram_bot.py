import os
import json
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8060531889:AAFC4j3f0KLie_tV7Wu9i3jH95XCEh7hSDY')
PLAYLIST_FILE = Path(__file__).parent / 'backend' / 'playlist.json'

# Conversation states
WAITING_FOR_EDIT = 1

# ==================== PLAYLIST MANAGEMENT ====================
def load_playlist():
    """Load playlist from JSON file"""
    if PLAYLIST_FILE.exists():
        try:
            with open(PLAYLIST_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"✅ Loaded {len(data.get('tracks', []))} tracks from playlist")
                return data
        except Exception as e:
            logger.error(f"Error loading playlist: {e}")
    
    return {"tracks": []}

def save_playlist(playlist_data):
    """Save playlist to JSON file"""
    try:
        with open(PLAYLIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(playlist_data, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Saved playlist ({len(playlist_data['tracks'])} tracks)")
        return True
    except Exception as e:
        logger.error(f"Error saving playlist: {e}")
        return False

def add_track_to_playlist(file_id, title, artist, duration, file_unique_id):
    """Add a track to the playlist"""
    playlist = load_playlist()
    
    # Check if track already exists (by file_unique_id)
    for track in playlist['tracks']:
        if track.get('file_unique_id') == file_unique_id:
            logger.info(f"Track already in playlist: {title}")
            return False, len(playlist['tracks'])
    
    # Add new track
    track = {
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "title": title,
        "artist": artist,
        "duration": duration,
        "source": "telegram"
    }
    
    playlist['tracks'].append(track)
    save_playlist(playlist)
    return True, len(playlist['tracks'])

def delete_track_from_playlist(index):
    """Delete a track by index (1-based)"""
    playlist = load_playlist()
    tracks = playlist.get('tracks', [])
    
    if index < 1 or index > len(tracks):
        return None, len(tracks)
    
    # Remove track (convert to 0-based index)
    deleted_track = tracks.pop(index - 1)
    playlist['tracks'] = tracks
    save_playlist(playlist)
    
    return deleted_track, len(tracks)

def update_track_metadata(index, artist, title, band_link=None):
    """Update track artist, title, and optional band link"""
    playlist = load_playlist()
    tracks = playlist.get('tracks', [])
    
    if index < 1 or index > len(tracks):
        return None
    
    # Update track (convert to 0-based index)
    tracks[index - 1]['artist'] = artist
    tracks[index - 1]['title'] = title
    if band_link:
        tracks[index - 1]['band_link'] = band_link
    save_playlist(playlist)
    
    return tracks[index - 1]

# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    welcome_text = """
🎸 **Madrid Rock Radio Bot** 📻

Send me audio files and I'll add them to the radio playlist!

**Commands:**
/start - Show this message
/playlist - Show current playlist
/edit <number> - Edit song artist/title
/delete <number> - Delete song by number
/clear - Clear entire playlist

**How to use:**
1. Send me an MP3 audio file
2. I'll add it to playlist.json
3. When done, push to GitHub:
   `git add backend/playlist.json`
   `git commit -m "Updated playlist"`
   `git push`
4. Render will auto-update! 🎵

**Note:** Run this bot only when managing your playlist, then close it!
    """
    await update.message.reply_text(welcome_text)

async def show_playlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current playlist with numbers"""
    playlist = load_playlist()
    tracks = playlist.get('tracks', [])
    
    if not tracks:
        await update.message.reply_text("📭 Playlist is empty! Send me some audio files!")
        return
    
    message = f"🎵 **Current Playlist** ({len(tracks)} tracks):\n\n"
    
    for i, track in enumerate(tracks, 1):
        message += f"{i}. {track['artist']} - {track['title']}\n"
    
    message += f"\n💡 Use `/edit <number>` to change artist/title"
    message += f"\n💡 Use `/delete <number>` to remove a song"
    
    await update.message.reply_text(message)

async def edit_song_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start editing a song"""
    
    # Get song number from command
    try:
        if not context.args or len(context.args) == 0:
            await update.message.reply_text(
                "❌ Please specify a song number!\n\n"
                "Usage: `/edit 3` to edit song #3\n"
                "Use `/playlist` to see song numbers"
            )
            return ConversationHandler.END
        
        song_number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Please use a valid number! Example: `/edit 3`")
        return ConversationHandler.END
    
    # Check if song exists
    playlist = load_playlist()
    tracks = playlist.get('tracks', [])
    
    if song_number < 1 or song_number > len(tracks):
        await update.message.reply_text(
            f"❌ Song #{song_number} not found!\n\n"
            f"Playlist has {len(tracks)} songs. Use `/playlist` to see them."
        )
        return ConversationHandler.END
    
    # Store song number in context
    context.user_data['editing_song'] = song_number
    
    # Show current info
    track = tracks[song_number - 1]
    current_link = track.get('band_link', 'No link')
    
    await update.message.reply_text(
        f"✏️ **Editing Song #{song_number}**\n\n"
        f"**Current:**\n"
        f"Artist: {track['artist']}\n"
        f"Title: {track['title']}\n"
        f"Link: {current_link}\n\n"
        f"**Send new info in this format:**\n"
        f"`Artist - Title - Link`\n"
        f"(Link is optional)\n\n"
        f"Examples:\n"
        f"`Mud Shake - Song Name - https://instagram.com/mudshake`\n"
        f"`Mud Shake - Song Name` (no link)\n\n"
        f"Or send /cancel to abort"
    )
    
    return WAITING_FOR_EDIT

async def edit_song_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and apply the new song info"""
    
    song_number = context.user_data.get('editing_song')
    if not song_number:
        await update.message.reply_text("❌ Error: No song being edited")
        return ConversationHandler.END
    
    # Parse the input
    text = update.message.text.strip()
    
    if ' - ' not in text:
        await update.message.reply_text(
            "❌ Invalid format! Please use:\n"
            "`Artist - Title` or `Artist - Title - Link`\n\n"
            "Example: `Mud Shake - Better Song Name`\n\n"
            "Or send /cancel to abort"
        )
        return WAITING_FOR_EDIT
    
    # Split into parts (artist - title - link)
    parts = text.split(' - ')
    artist = parts[0].strip()
    title = parts[1].strip() if len(parts) > 1 else "Unknown"
    band_link = parts[2].strip() if len(parts) > 2 else None
    
    # Update the track
    updated_track = update_track_metadata(song_number, artist, title, band_link)
    
    if updated_track:
        link_text = f"\n🔗 Link: {band_link}" if band_link else ""
        await update.message.reply_text(
            f"✅ **Updated Song #{song_number}**\n\n"
            f"🎵 {artist} - {title}{link_text}\n\n"
            f"💡 Don't forget to push to GitHub when done!"
        )
    else:
        await update.message.reply_text("❌ Failed to update song")
    
    # Clear context
    context.user_data.pop('editing_song', None)
    
    return ConversationHandler.END

async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel editing"""
    context.user_data.pop('editing_song', None)
    await update.message.reply_text("❌ Edit cancelled")
    return ConversationHandler.END

async def delete_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a song by number"""
    
    # Get song number from command
    try:
        if not context.args or len(context.args) == 0:
            await update.message.reply_text(
                "❌ Please specify a song number!\n\n"
                "Usage: `/delete 3` to delete song #3\n"
                "Use `/playlist` to see song numbers"
            )
            return
        
        song_number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Please use a valid number! Example: `/delete 3`")
        return
    
    # Delete the track
    deleted_track, remaining = delete_track_from_playlist(song_number)
    
    if deleted_track:
        await update.message.reply_text(
            f"🗑️ **Deleted:**\n"
            f"{deleted_track['artist']} - {deleted_track['title']}\n\n"
            f"📊 {remaining} songs remaining in playlist\n\n"
            f"💡 Don't forget to push to GitHub when done!"
        )
    else:
        playlist = load_playlist()
        total = len(playlist.get('tracks', []))
        await update.message.reply_text(
            f"❌ Song #{song_number} not found!\n\n"
            f"Playlist has {total} songs. Use `/playlist` to see them."
        )

async def clear_playlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear the entire playlist"""
    playlist = load_playlist()
    track_count = len(playlist.get('tracks', []))
    
    if track_count == 0:
        await update.message.reply_text("📭 Playlist is already empty!")
        return
    
    # Ask for confirmation
    if not context.args or context.args[0] != "confirm":
        await update.message.reply_text(
            f"⚠️ **WARNING:** This will delete all {track_count} songs!\n\n"
            f"To confirm, use: `/clear confirm`"
        )
        return
    
    # Clear playlist
    empty_playlist = {"tracks": []}
    save_playlist(empty_playlist)
    await update.message.reply_text(
        f"🗑️ Cleared {track_count} songs from playlist!\n\n"
        f"💡 Don't forget to push to GitHub when done!"
    )

async def handle_audio_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle audio files sent directly to the bot"""
    
    audio = update.message.audio
    
    if not audio:
        return
    
    # Extract metadata
    title = audio.title or audio.file_name or "Unknown Title"
    artist = audio.performer or "Unknown Artist"
    duration = audio.duration or 180
    file_id = audio.file_id
    file_unique_id = audio.file_unique_id
    
    # Add to playlist
    added, total_tracks = add_track_to_playlist(
        file_id=file_id,
        title=title,
        artist=artist,
        duration=duration,
        file_unique_id=file_unique_id
    )
    
    if added:
        await update.message.reply_text(
            f"✅ **Added to playlist!**\n\n"
            f"🎵 {artist} - {title}\n"
            f"📊 Playlist now has {total_tracks} songs\n\n"
            f"💡 Use `/edit {total_tracks}` if artist/title is wrong\n"
            f"💡 Send more files or use `/playlist` to view all"
        )
    else:
        await update.message.reply_text(
            f"ℹ️ **Already in playlist!**\n\n"
            f"🎵 {artist} - {title}\n"
            f"📊 Playlist has {total_tracks} songs"
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle documents that might be audio files"""
    
    document = update.message.document
    
    if not document:
        return
    
    # Check if it's an audio file
    mime_type = document.mime_type or ""
    file_name = document.file_name or ""
    
    if not (mime_type.startswith('audio/') or file_name.endswith(('.mp3', '.m4a', '.ogg', '.wav'))):
        await update.message.reply_text(
            "ℹ️ Please send audio files only!\n\n"
            "Supported formats: MP3, M4A, OGG, WAV"
        )
        return
    
    # Extract what we can
    title = file_name.rsplit('.', 1)[0] if file_name else "Unknown Title"
    artist = "Unknown Artist"
    file_id = document.file_id
    file_unique_id = document.file_unique_id
    
    # Try to parse artist - title from filename
    if ' - ' in title:
        parts = title.split(' - ', 1)
        artist = parts[0].strip()
        title = parts[1].strip()
    
    # Add to playlist
    added, total_tracks = add_track_to_playlist(
        file_id=file_id,
        title=title,
        artist=artist,
        duration=180,  # Default
        file_unique_id=file_unique_id
    )
    
    if added:
        await update.message.reply_text(
            f"✅ **Added to playlist!**\n\n"
            f"🎵 {artist} - {title}\n"
            f"📊 Playlist now has {total_tracks} songs\n\n"
            f"💡 Use `/edit {total_tracks}` to fix artist/title\n"
            f"💡 Tip: Send as 'Audio' instead of 'File' for better metadata"
        )
    else:
        await update.message.reply_text(
            f"ℹ️ **Already in playlist!**\n\n"
            f"🎵 {artist} - {title}"
        )

# ==================== MAIN ====================
def main():
    """Start the bot"""
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add conversation handler for editing
    edit_handler = ConversationHandler(
        entry_points=[CommandHandler("edit", edit_song_start)],
        states={
            WAITING_FOR_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_song_receive)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("playlist", show_playlist))
    application.add_handler(edit_handler)
    application.add_handler(CommandHandler("delete", delete_song))
    application.add_handler(CommandHandler("clear", clear_playlist))
    
    # Handle audio files
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio_file))
    
    # Handle documents (in case someone sends audio as file)
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Start the bot
    logger.info("🤖 Madrid Rock Radio Bot started!")
    logger.info(f"📁 Playlist file: {PLAYLIST_FILE}")
    
    # Load existing playlist
    playlist = load_playlist()
    logger.info(f"🎵 Current playlist: {len(playlist.get('tracks', []))} tracks")
    
    print("\n" + "="*50)
    print("🎸 BOT IS RUNNING 🎸")
    print("="*50)
    print("\nSend audio files to @madridrockradio_bot")
    print("\nCommands available:")
    print("  /playlist - View songs")
    print("  /edit <number> - Change artist/title")
    print("  /delete <number> - Remove a song")
    print("  /clear confirm - Clear all songs")
    print("\nPress Ctrl+C to stop the bot")
    print("="*50 + "\n")
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
