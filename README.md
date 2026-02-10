# Madrid Rock Radio 🎸📻

An online radio station that plays music continuously from YouTube links. Features a retro car radio aesthetic with LCD display, volume knob, and synchronized playback across all listeners.

## Features

✅ **Continuous Playback** - Radio always plays, users tune in to hear what's live
✅ **YouTube Audio** - Extracts audio from YouTube using yt-dlp
✅ **Car Radio UI** - Retro dashboard with amber LCD display
✅ **Favorites** - Save one track to play on-demand
✅ **Queue Display** - See what just played and what's up next
✅ **Share** - Share currently playing track
✅ **Mute (not Pause)** - Radio keeps playing in background

## Quick Start (Local Development)

### Backend
```bash
cd backend
pip install -r requirements.txt
python server.py
```

Backend runs on `http://localhost:8000`

### Frontend
```bash
cd frontend
npm install
REACT_APP_BACKEND_URL=http://localhost:8000 npm start
```

Frontend runs on `http://localhost:3000`

## Deploy to Render (Free)

1. **Push code to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial Madrid Rock Radio"
   git remote add origin YOUR_GITHUB_REPO
   git push -u origin main
   ```

2. **Deploy on Render**
   - Go to [render.com](https://render.com)
   - Click "New" → "Blueprint"
   - Connect your GitHub repo
   - Render will auto-detect `render.yaml` and deploy both services
   - Choose your subdomain (e.g., `madridrock.onrender.com`)

3. **Set Environment Variable**
   - In Render dashboard, go to frontend service
   - Set `REACT_APP_BACKEND_URL` to your backend URL (e.g., `https://madrid-rock-api.onrender.com`)

## Adding Tracks

Use the API to add Madrid band tracks:

```bash
curl -X POST "YOUR_BACKEND_URL/api/radio/playlist" \
  -H "Content-Type: application/json" \
  -d '{
    "youtube_url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "title": "Song Name",
    "artist": "Band Name"
  }'
```

## API Endpoints

- `GET /api/radio/state` - Current track, position, queue
- `GET /api/radio/stream` - Audio stream URL
- `POST /api/radio/playlist` - Add track
- `POST /api/favorites/save` - Save current as favorite
- `GET /api/favorites/get` - Get saved favorite
- `GET /api/share/current` - Get share data

## Tech Stack

- **Backend**: FastAPI + yt-dlp
- **Frontend**: React + Axios
- **Styling**: Custom CSS (car radio aesthetic)
- **Icons**: Lucide React

## Notes

- YouTube URLs expire after ~6 hours (app auto-refreshes them)
- Free Render plan: backend sleeps after 15min inactivity
- For 24/7 uptime: upgrade to paid Render plan ($7/mo)

## Future Enhancements

- [ ] MongoDB persistence (survive server restarts)
- [ ] Admin panel for playlist management
- [ ] Multiple radio stations/channels
- [ ] Listener count display
- [ ] Song request system

---

Built with ❤️ for Madrid's local music scene
