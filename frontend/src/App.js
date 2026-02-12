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
  const [currentTrackId, setCurrentTrackId] = useState(null); // Track which song is loaded
  
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
        // Check if track changed by comparing track IDs, not URLs
        const newTrackId = state.current_track.id;
        
        if (newTrackId !== currentTrackId) {
          console.log(`🔄 Track changed from ${currentTrackId} to ${newTrackId}`);
          const streamResponse = await axios.get(`${API}/radio/stream`);
          if (streamResponse.data.audio_url) {
            // CRITICAL FIX: Add cache buster for Drive URLs
            let audioUrl = streamResponse.data.audio_url;
            if (audioUrl.includes('/api/radio/proxy/')) {
              audioUrl = `${audioUrl}?t=${Date.now()}`;
            }
            
            console.log(`🎵 Loading new track: ${audioUrl}`);
            audioRef.current.src = audioUrl;
            audioRef.current.currentTime = state.position || 0;
            audioRef.current.volume = isMuted ? 0 : volume / 10;
            setCurrentTrackId(newTrackId);
            
            // Play
            audioRef.current.play().catch(err => {
              console.error("Error playing audio:", err);
              setError("Playback failed. Try refreshing.");
            });
          }
        } else {
          // Same track - just sync position if drift is significant
          if (!audioRef.current.paused) {
            const drift = Math.abs(audioRef.current.currentTime - state.position);
            if (drift > 3) {
              console.log(`⏩ Syncing position: ${drift.toFixed(1)}s drift`);
              audioRef.current.currentTime = state.position;
            }
          }
        }
      }
      
      setIsLoading(false);
    } catch (e) {
      console.error("Error fetching radio state:", e);
      setError("Unable to connect to radio");
      setIsLoading(false);
    }
  }, [isTunedIn, playingFavorite, volume, isMuted, currentTrackId]);

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
          // Add cache buster for Drive URLs
          let audioUrl = response.data.audio_url;
          if (audioUrl.includes('/api/radio/proxy/')) {
            audioUrl = `${audioUrl}?t=${Date.now()}`;
          }
          
          console.log(`🎵 Tuning in: ${audioUrl}`);
          audioRef.current.src = audioUrl;
          audioRef.current.currentTime = response.data.position || 0;
          audioRef.current.volume = volume / 10;
          
          // Set current track ID
          if (radioState?.current_track?.id) {
            setCurrentTrackId(radioState.current_track.id);
          }
          
          await audioRef.current.play();
          setIsTunedIn(true);
          setIsMuted(false);
          setPlayingFavorite(false);
        }
      } catch (e) {
        console.error("Error tuning in:", e);
        setError("Failed to tune in. Try again.");
      }
    } else {
      // Toggle mute
      if (isMuted) {
        // Unmuting - just restore volume if audio is already playing
        if (audioRef.current && audioRef.current.src) {
          audioRef.current.volume = volume / 10;
          if (audioRef.current.paused) {
            audioRef.current.play().catch(console.error);
          }
        } else if (playingFavorite) {
          // No audio loaded, need to fetch favorite
          try {
            const favResponse = await axios.get(`${API}/favorites/stream`);
            if (favResponse.data.audio_url) {
              // Add cache buster
              let audioUrl = favResponse.data.audio_url;
              if (audioUrl.includes('/api/radio/proxy/')) {
                audioUrl = `${audioUrl}?t=${Date.now()}`;
              }
              
              audioRef.current.src = audioUrl;
              audioRef.current.currentTime = favoritePosition;
              audioRef.current.volume = volume / 10;
              await audioRef.current.play();
            }
          } catch (e) {
            console.error("Error resuming favorite:", e);
          }
        } else {
          // No audio loaded, need to fetch radio stream
          try {
            const streamResponse = await axios.get(`${API}/radio/stream`);
            if (streamResponse.data.audio_url) {
              // Add cache buster
              let audioUrl = streamResponse.data.audio_url;
              if (audioUrl.includes('/api/radio/proxy/')) {
                audioUrl = `${audioUrl}?t=${Date.now()}`;
              }
              
              audioRef.current.src = audioUrl;
              audioRef.current.currentTime = streamResponse.data.position || 0;
              audioRef.current.volume = volume / 10;
              await audioRef.current.play();
            }
          } catch (e) {
            console.error("Error reloading stream:", e);
          }
        }
        setIsMuted(false);
      } else {
        // Muting
        if (audioRef.current) {
          audioRef.current.volume = 0;
        }
        setIsMuted(true);
      }
    }
  };

  const handleVolumeChange = (newVolume) => {
    setVolume(newVolume);
    if (audioRef.current && !isMuted) {
      audioRef.current.volume = newVolume / 10;
    }
  };

  const saveFavorite = async () => {
    try {
      await axios.post(`${API}/favorites/save`);
      await fetchFavorite();
      showToast("Track saved as favorite! ❤️");
    } catch (e) {
      console.error("Error saving favorite:", e);
      showToast("Failed to save favorite", "error");
    }
  };

  const playFav = async () => {
    if (!favorite) return;
    
    try {
      const response = await axios.get(`${API}/favorites/stream`);
      if (response.data.audio_url && audioRef.current) {
        // Add cache buster
        let audioUrl = response.data.audio_url;
        if (audioUrl.includes('/api/radio/proxy/')) {
          audioUrl = `${audioUrl}?t=${Date.now()}`;
        }
        
        console.log(`🎵 Playing favorite: ${audioUrl}`);
        audioRef.current.src = audioUrl;
        audioRef.current.currentTime = 0;
        audioRef.current.volume = isMuted ? 0 : volume / 10;
        
        await audioRef.current.play();
        setPlayingFavorite(true);
        setIsTunedIn(true);
        setFavoritePosition(0);
        setCurrentTrackId(null); // Clear track ID when playing favorite
        showToast("Now playing your favorite! 🎶");
      }
    } catch (e) {
      console.error("Error playing favorite:", e);
      showToast("Failed to play favorite", "error");
    }
  };

  const backToLive = async () => {
    if (!audioRef.current) return;
    
    try {
      const response = await axios.get(`${API}/radio/stream`);
      if (response.data.audio_url) {
        // Add cache buster
        let audioUrl = response.data.audio_url;
        if (audioUrl.includes('/api/radio/proxy/')) {
          audioUrl = `${audioUrl}?t=${Date.now()}`;
        }
        
        console.log(`🎵 Back to live: ${audioUrl}`);
        audioRef.current.src = audioUrl;
        audioRef.current.currentTime = response.data.position || 0;
        audioRef.current.volume = isMuted ? 0 : volume / 10;
        
        // Set current track ID
        if (radioState?.current_track?.id) {
          setCurrentTrackId(radioState.current_track.id);
        }
        
        await audioRef.current.play();
        setPlayingFavorite(false);
        showToast("Back to live radio! 📻");
      }
    } catch (e) {
      console.error("Error returning to live:", e);
      showToast("Failed to return to live", "error");
    }
  };

  const shareTrack = async () => {
    if (!radioState?.current_track && !favorite) return;
    
    try {
      const response = await axios.get(`${API}/share/current`);
      const shareData = response.data;
      
      if (navigator.share) {
        await navigator.share({
          title: shareData.title,
          text: shareData.description,
          url: shareData.url
        });
      } else {
        await navigator.clipboard.writeText(shareData.url);
        showToast("Link copied to clipboard! 🔗");
      }
    } catch (e) {
      console.error("Error sharing:", e);
      showToast("Failed to share", "error");
    }
  };

  // Update current time
  useEffect(() => {
    const updateTime = () => {
      if (playingFavorite && audioRef.current) {
        setCurrentTime(audioRef.current.currentTime);
        setFavoritePosition(audioRef.current.currentTime);
      } else if (isTunedIn && radioState?.current_track) {
        if (audioRef.current && !audioRef.current.paused) {
          setCurrentTime(audioRef.current.currentTime);
        } else {
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
      <audio 
        ref={audioRef} 
        onEnded={() => !playingFavorite && fetchRadioState()}
        onError={(e) => {
          console.error("Audio error:", e);
          setError("Audio playback error. Refreshing...");
          // Try to recover by fetching new stream
          if (!playingFavorite) {
            setTimeout(() => fetchRadioState(), 1000);
          }
        }}
      />
      
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
