import { useState, useEffect, useRef, useCallback } from "react";
import "./App.css";
import axios from "axios";
import { Play, VolumeX, Volume2, Share2, Heart, Radio as RadioIcon, Power, ExternalLink } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || `http://${window.location.hostname}:8000`;
const API = `${BACKEND_URL}/api`;
const SYNC_INTERVAL = 2000;

const BG_IMAGES = {
  morning: [
    'https://images.pexels.com/photos/19130909/pexels-photo-19130909.jpeg',
    'https://images.pexels.com/photos/28487253/pexels-photo-28487253.jpeg',
    'https://images.pexels.com/photos/9241631/pexels-photo-9241631.jpeg'
  ],
  afternoon: [
    'https://images.pexels.com/photos/10945402/pexels-photo-10945402.jpeg',
    'https://images.pexels.com/photos/11092356/pexels-photo-11092356.jpeg',
    'https://images.pexels.com/photos/5006024/pexels-photo-5006024.jpeg'
  ],
  sunset: [
    'https://images.pexels.com/photos/13221400/pexels-photo-13221400.jpeg',
    'https://images.pexels.com/photos/17357318/pexels-photo-17357318.jpeg',
    'https://images.pexels.com/photos/31515690/pexels-photo-31515690.jpeg'
  ],
  night: [
    'https://images.pexels.com/photos/10945679/pexels-photo-10945679.jpeg',
    'https://images.pexels.com/photos/10945664/pexels-photo-10945664.jpeg',
    'https://images.pexels.com/photos/11269164/pexels-photo-11269164.jpeg'
  ]
};

// Helper function to get time of day
const getTimeOfDay = () => {
  const hour = new Date().getHours();
  if (hour >= 6 && hour < 12) return 'morning';
  if (hour >= 12 && hour < 18) return 'afternoon';
  if (hour >= 18 && hour < 21) return 'sunset';
  return 'night';
};

function App() {
  const [radioState, setRadioState] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [volume, setVolume] = useState(7);
  const [isTunedIn, setIsTunedIn] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [error, setError] = useState(null);
  const [favorite, setFavorite] = useState(null);
  const [playingFavorite, setPlayingFavorite] = useState(false);
  const [favoritePosition, setFavoritePosition] = useState(0);
  
  const audioRef = useRef(null);
  const syncIntervalRef = useRef(null);

  // Fetch radio state
  const fetchRadioState = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/radio/state`);
      const state = response.data;
      setRadioState(state);
      setError(null);
      
      // Update audio if needed (only when listening to radio, not favorite)
      if (!playingFavorite && state.current_track && audioRef.current && isTunedIn) {
        const currentSrc = audioRef.current.src;
        
        // Check if track changed
        if (state.current_track.audio_url && 
            !currentSrc.includes(state.current_track.audio_url.split('?')[0].slice(-20))) {
          const streamResponse = await axios.get(`${API}/radio/stream`);
          if (streamResponse.data.audio_url) {
            audioRef.current.src = streamResponse.data.audio_url;
            audioRef.current.currentTime = state.position;
            audioRef.current.volume = isMuted ? 0 : volume / 10;
            // Play even if muted - browser needs it running
            audioRef.current.play().catch(console.error);
          }
        }
        
        // Sync position if playing
        if (!audioRef.current.paused) {
          const drift = Math.abs(audioRef.current.currentTime - state.position);
          if (drift > 3) {
            audioRef.current.currentTime = state.position;
          }
        }
      }
      
      setIsLoading(false);
    } catch (e) {
      console.error("Error fetching radio state:", e);
      setError("Unable to connect to radio");
      setIsLoading(false);
    }
  }, [isTunedIn, playingFavorite, volume, isMuted]);

  // Fetch favorite
  const fetchFavorite = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/favorites/get`);
      setFavorite(response.data.favorite);
    } catch (e) {
      console.error("Error fetching favorite:", e);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchRadioState();
    fetchFavorite();
    syncIntervalRef.current = setInterval(fetchRadioState, SYNC_INTERVAL);
    
    return () => {
      if (syncIntervalRef.current) {
        clearInterval(syncIntervalRef.current);
      }
    };
  }, [fetchRadioState, fetchFavorite]);

  // Background carousel - 2 layers alternating with time-based images
  useEffect(() => {
    let currentIndex = 0;
    let currentTimeOfDay = getTimeOfDay();
    let currentImageArray = BG_IMAGES[currentTimeOfDay];
    let useFirstLayer = true;
    
    // Initialize with current time period's first image
    document.documentElement.style.setProperty('--bg-image', `url(${currentImageArray[0]})`);
    document.documentElement.style.setProperty('--bg-opacity-1', '1');
    document.documentElement.style.setProperty('--bg-opacity-2', '0');
    
    const interval = setInterval(() => {
      // Check if time of day changed
      const newTimeOfDay = getTimeOfDay();
      if (newTimeOfDay !== currentTimeOfDay) {
        // Time period changed! Reset to new period's images
        currentTimeOfDay = newTimeOfDay;
        currentImageArray = BG_IMAGES[currentTimeOfDay];
        currentIndex = 0;
      } else {
        // Same time period, advance to next image
        currentIndex = (currentIndex + 1) % currentImageArray.length;
      }
      
      if (useFirstLayer) {
        // Layer 1 visible -> transition to layer 2
        document.documentElement.style.setProperty('--bg-image-2', `url(${currentImageArray[currentIndex]})`);
        setTimeout(() => {
          document.documentElement.style.setProperty('--bg-opacity-1', '0');
          document.documentElement.style.setProperty('--bg-opacity-2', '1');
        }, 50);
      } else {
        // Layer 2 visible -> transition to layer 1
        document.documentElement.style.setProperty('--bg-image', `url(${currentImageArray[currentIndex]})`);
        setTimeout(() => {
          document.documentElement.style.setProperty('--bg-opacity-1', '1');
          document.documentElement.style.setProperty('--bg-opacity-2', '0');
        }, 50);
      }
      
      useFirstLayer = !useFirstLayer;
    }, 60000); // 1 minute for testing (change to 3600000 for 1 hour)
    
    return () => clearInterval(interval);
  }, []); // No dependencies - runs once on mount

  // Toggle tune in/mute
  const toggleTuneIn = async () => {
    if (!audioRef.current) return;
    
    if (!isTunedIn) {
      // Tune in - start playing radio
      try {
        const response = await axios.get(`${API}/radio/stream`);
        if (response.data.audio_url) {
          audioRef.current.src = response.data.audio_url;
          audioRef.current.currentTime = response.data.position;
          audioRef.current.volume = volume / 10;
          await audioRef.current.play();
          setIsTunedIn(true);
          setIsMuted(false);
          setPlayingFavorite(false);
        }
      } catch (e) {
        console.error("Error tuning in:", e);
      }
    } else {
      // Toggle mute
      if (isMuted) {
        // Unmuting - check if we were playing favorite or live radio
        if (playingFavorite) {
          // Resume favorite from saved position
          try {
            const favResponse = await axios.get(`${API}/favorites/stream`);
            if (favResponse.data.audio_url) {
              audioRef.current.src = favResponse.data.audio_url;
              audioRef.current.currentTime = favoritePosition;
              audioRef.current.volume = volume / 10;
              await audioRef.current.play();
            }
          } catch (e) {
            console.error("Error resuming favorite:", e);
            audioRef.current.volume = volume / 10;
            if (audioRef.current.paused) {
              audioRef.current.play().catch(console.error);
            }
          }
        } else {
          // Resume live radio - fetch fresh stream
          try {
            const streamResponse = await axios.get(`${API}/radio/stream`);
            if (streamResponse.data.audio_url) {
              audioRef.current.src = streamResponse.data.audio_url;
              audioRef.current.currentTime = streamResponse.data.position;
              audioRef.current.volume = volume / 10;
              await audioRef.current.play();
            }
          } catch (e) {
            console.error("Error unmuting:", e);
            audioRef.current.volume = volume / 10;
            if (audioRef.current.paused) {
              audioRef.current.play().catch(console.error);
            }
          }
        }
        setIsMuted(false);
      } else {
        // Muting - save position if playing favorite
        if (playingFavorite && audioRef.current) {
          setFavoritePosition(audioRef.current.currentTime);
        }
        audioRef.current.volume = 0;
        setIsMuted(true);
      }
    }
  };

  // Save favorite
  const saveFavorite = async () => {
    try {
      const response = await axios.post(`${API}/favorites/save`);
      setFavorite(response.data.track);
      // Visual feedback via filled heart icon, no toast
    } catch (e) {
      console.error("Error saving favorite:", e);
      showToast("Couldn't save favorite", "error");
    }
  };

  // Play favorite
  const playFav = async () => {
    if (!favorite || !audioRef.current) return;
    
    try {
      const response = await axios.get(`${API}/favorites/stream`);
      if (response.data.audio_url) {
        audioRef.current.src = response.data.audio_url;
        audioRef.current.currentTime = 0;
        audioRef.current.volume = volume / 10;
        await audioRef.current.play();
        setPlayingFavorite(true);
        setIsTunedIn(true);
        setIsMuted(false);
        showToast(`Playing: ${favorite.title}`);
      }
    } catch (e) {
      console.error("Error playing favorite:", e);
      showToast("Couldn't play favorite", "error");
    }
  };

  // Back to live radio
  const backToLive = async () => {
    if (!audioRef.current) return;
    
    try {
      const response = await axios.get(`${API}/radio/stream`);
      if (response.data.audio_url) {
        audioRef.current.src = response.data.audio_url;
        audioRef.current.currentTime = response.data.position;
        audioRef.current.volume = Math.max(volume / 100, 0.001);
        await audioRef.current.play();
        setPlayingFavorite(false);
        setIsMuted(false);
        showToast("Back to live radio! 📻");
      }
    } catch (e) {
      console.error("Error returning to live:", e);
    }
  };

  // Share current track
  const shareTrack = async () => {
    try {
      const response = await axios.get(`${API}/share/current`);
      const data = response.data;
      
      // Copy to clipboard
      await navigator.clipboard.writeText(`${data.title}\n${data.url}`);
      showToast("Share link copied! 📋");
    } catch (e) {
      console.error("Error sharing:", e);
      showToast("Couldn't copy share link", "error");
    }
  };

  // Volume control
  const handleVolumeChange = (newVolume) => {
    setVolume(newVolume);
    if (audioRef.current) {
      if (newVolume === 0) {
        // Position 0 = muted (volume 0 but audio keeps playing for track sync)
        audioRef.current.volume = 0;
      } else {
        // Map 1-10 slider to 10%-100% audio volume
        const audioVolume = newVolume / 10;
        audioRef.current.volume = audioVolume;
      }
    }
  };

  // Update current time display
  useEffect(() => {
    const updateTime = () => {
      if (isTunedIn) {
        if (playingFavorite && audioRef.current) {
          // For favorites, use actual audio time
          setCurrentTime(audioRef.current.currentTime);
        } else if (radioState?.current_track) {
          // For radio, calculate from server time (works even when muted)
          const elapsed = Date.now() / 1000 - radioState.started_at;
          const position = elapsed % Math.max(radioState.current_track.duration, 1);
          setCurrentTime(position);
        }
      }
    };
    
    const interval = setInterval(updateTime, 500);
    return () => clearInterval(interval);
  }, [isTunedIn, playingFavorite, radioState]);

  // Toast notification
  const [toast, setToast] = useState(null);
  const showToast = (message, type = "success") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // Format time
  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const currentTrack = playingFavorite ? favorite : radioState?.current_track;
  const progressPercent = currentTrack?.duration 
    ? (currentTime / currentTrack.duration) * 100 
    : 0;

  return (
    <div className="radio-container">
      {/* Toast */}
      {toast && (
        <div className={`toast toast-${toast.type}`}>
          {toast.message}
        </div>
      )}
      
      {/* Audio Element */}
      <audio ref={audioRef} onEnded={() => !playingFavorite && fetchRadioState()} />
      
      {/* Head Unit */}
      <div className="head-unit">
        
        {/* Main LCD Display */}
        <div className="lcd-screen">
          {/* Top Row */}
          <div className="lcd-header">
            <div className="station-badge">
              <RadioIcon size={14} />
              MADRID ROCK
            </div>
            <div className="status-indicators">
              <div className={`led ${isTunedIn ? 'active' : ''}`}></div>
              <span className="status-text">
                {playingFavorite ? "FAV" : "LIVE"}
              </span>
            </div>
          </div>
          
          {/* Track Info */}
          {isLoading ? (
            <div className="lcd-text loading">TUNING...</div>
          ) : error ? (
            <div className="lcd-text error">{error}</div>
          ) : currentTrack ? (
            <div className="track-display">
              <div className={`track-title ${currentTrack.title.length > 40 ? 'scrolling' : ''}`}>
                {currentTrack.title}
              </div>
              <div className="track-artist">
                {currentTrack.artist}
              </div>
              
              {/* Time */}
              <div className="time-display">
                <span>{formatTime(currentTime)}</span>
                <span>{formatTime(currentTrack.duration || 0)}</span>
              </div>
              
              {/* Progress */}
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${progressPercent}%` }}></div>
              </div>
            </div>
          ) : (
            <div className="lcd-text">NO SIGNAL</div>
          )}
        </div>
        
        {/* Up Next Section OR Promo Message */}
        {!playingFavorite && radioState && radioState.up_next && radioState.up_next.length > 0 ? (
          <div className="queue-display-single">
            <div className="queue-label">UP NEXT</div>
            <div className="queue-text scrolling">
              {/* Duplicate content twice for seamless loop */}
              {[...Array(2)].map((_, copyIndex) => (
                <span key={`copy-${copyIndex}`}>
                  {radioState.up_next.map((t, i) => (
                    <span key={`${copyIndex}-${i}`} className="scroll-item">
                      {i === 0 && copyIndex === 0 ? '' : ' • '}
                      {`${t.title} - ${t.artist}`}
                    </span>
                  ))}
                </span>
              ))}
            </div>
          </div>
        ) : playingFavorite ? (
          <div className="queue-display-single promo">
            <div className="queue-label">SHARE THIS SONG WITH YOUR FRIENDS!</div>
            <div className="queue-text scrolling">
              {[...Array(2)].map((_, copyIndex) => (
                <span key={`promo-${copyIndex}`} className="scroll-item">
                  Use the share button to get this song's link on Madrid Rock Radio
                </span>
              ))}
            </div>
          </div>
        ) : null}
        
        {/* Controls */}
        <div className="controls">
          {/* Volume Slider */}
          <div className="volume-control horizontal">
            <label className="control-label">VOL</label>
            <input
              type="range"
              min="0"
              max="10"
              step="1"
              value={volume}
              onChange={(e) => handleVolumeChange(Number(e.target.value))}
              className="volume-slider horizontal"
            />
          </div>
          
          {/* Button Group */}
          <div className="button-group">
          
          {/* Main Button - Tune In / Mute */}
          <button 
            className={`control-btn primary icon-only ${isTunedIn ? 'active' : ''} ${isMuted ? 'muted' : ''}`}
            onClick={toggleTuneIn}
            title={!isTunedIn ? "Tune in to radio" : isMuted ? "Unmute" : "Mute"}
          >
            {!isTunedIn ? (
              <Power size={24} />
            ) : isMuted ? (
              <VolumeX size={24} />
            ) : (
              <Volume2 size={24} />
            )}
          </button>
          
          {/* Favorites OR Back to Live */}
          {!playingFavorite ? (
            <div className="fav-controls split">
              <button 
                className="control-btn fav-btn icon-only"
                onClick={saveFavorite}
                disabled={!currentTrack}
                title="Save current track as favorite"
              >
                <Heart size={22} fill={favorite ? "currentColor" : "none"} />
              </button>
              <button 
                className="control-btn fav-btn icon-only"
                onClick={playFav}
                disabled={!favorite}
                title="Play saved favorite"
              >
                <Play size={22} />
              </button>
            </div>
          ) : (
            <button 
              className="control-btn secondary back-to-live-btn" 
              onClick={backToLive} 
              title="Back to live radio"
            >
              <RadioIcon size={22} />
            </button>
          )}
          
          {/* Band Info Link */}
          <button 
            className="control-btn icon-only"
            onClick={() => {
              if (currentTrack?.youtube_url) {
                window.open(currentTrack.youtube_url, '_blank');
              }
            }}
            disabled={!currentTrack}
            title="Visit band page"
          >
            <ExternalLink size={22} />
          </button>
          
          {/* Share */}
          <button 
            className="control-btn icon-only"
            onClick={shareTrack}
            disabled={!currentTrack}
            title="Share this track"
          >
            <Share2 size={22} />
          </button>
          </div>{/* End button-group */}
        </div>
        
        {/* Footer */}
        <div className="footer">
          MADRID ROCK RADIO • {radioState?.playlist_count || 0} tracks
        </div>
      </div>
    </div>
  );
}

export default App;
