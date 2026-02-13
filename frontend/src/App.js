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
  const [currentTrackId, setCurrentTrackId] = useState(null);
  
  const audioRef = useRef(null);
  const syncIntervalRef = useRef(null);
  const isLoadingTrackRef = useRef(false); // Prevent concurrent loads
  const errorCountRef = useRef(0); // Track consecutive errors

  // Fetch radio state
  const fetchRadioState = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/radio/state`);
      const state = response.data;
      setRadioState(state);
      setError(null);
      errorCountRef.current = 0; // Reset error count on success
      
      // Update audio if needed (only when listening to radio, not favorite)
      if (!playingFavorite && state.current_track && audioRef.current && isTunedIn && !isLoadingTrackRef.current) {
        // Check if track changed by comparing track IDs
        const newTrackId = state.current_track.id;
        
        if (newTrackId !== currentTrackId) {
          console.log(`🔄 Track changed from ${currentTrackId} to ${newTrackId}`);
          await loadTrack(newTrackId, state.position);
        } else {
          // Same track - just sync position if drift is significant
          if (!audioRef.current.paused && audioRef.current.readyState >= 2) {
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
      errorCountRef.current++;
      
      // Only show error if we have multiple failures
      if (errorCountRef.current > 3) {
        setError("Unable to connect to radio");
      }
      setIsLoading(false);
    }
  }, [isTunedIn, playingFavorite, currentTrackId]);

  // Load track helper function
  const loadTrack = async (trackId, position = 0) => {
    if (isLoadingTrackRef.current) {
      console.log('⚠️ Track load already in progress, skipping');
      return;
    }

    isLoadingTrackRef.current = true;

    try {
      const streamResponse = await axios.get(`${API}/radio/stream`);
      if (streamResponse.data.audio_url && audioRef.current) {
        // Add cache buster with timestamp
        const audioUrl = `${streamResponse.data.audio_url}?t=${Date.now()}`;
        
        console.log(`🎵 Loading track: ${audioUrl}`);
        
        // Important: Set src and immediately set currentTime to avoid playback from start
        audioRef.current.src = audioUrl;
        audioRef.current.currentTime = position || 0;
        audioRef.current.volume = isMuted ? 0 : volume / 10;
        setCurrentTrackId(trackId);
        
        // Wait for audio to be ready before playing
        await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('Load timeout')), 10000);
          
          const onCanPlay = () => {
            clearTimeout(timeout);
            audioRef.current.removeEventListener('canplay', onCanPlay);
            audioRef.current.removeEventListener('error', onError);
            resolve();
          };
          
          const onError = (e) => {
            clearTimeout(timeout);
            audioRef.current.removeEventListener('canplay', onCanPlay);
            audioRef.current.removeEventListener('error', onError);
            reject(e);
          };
          
          audioRef.current.addEventListener('canplay', onCanPlay, { once: true });
          audioRef.current.addEventListener('error', onError, { once: true });
        });
        
        // Now play
        await audioRef.current.play();
        console.log('✅ Track loaded and playing');
      }
    } catch (err) {
      console.error("Error loading track:", err);
      errorCountRef.current++;
      
      // Only show error after multiple failures
      if (errorCountRef.current > 2) {
        setError("Playback failed. Try refreshing.");
      }
    } finally {
      isLoadingTrackRef.current = false;
    }
  };

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
  }, []);

  // Toggle tune in/mute
  const toggleTuneIn = async () => {
    if (!audioRef.current) return;
    
    if (!isTunedIn) {
      // Tune in - start playing radio
      try {
        const response = await axios.get(`${API}/radio/stream`);
        if (response.data.audio_url) {
          // Add cache buster
          const audioUrl = `${response.data.audio_url}?t=${Date.now()}`;
          
          console.log(`🎵 Tuning in: ${audioUrl}`);
          audioRef.current.src = audioUrl;
          audioRef.current.currentTime = response.data.position || 0;
          audioRef.current.volume = volume / 10;
          
          // Set current track ID
          if (radioState?.current_track?.id) {
            setCurrentTrackId(radioState.current_track.id);
          }
          
          // Wait for canplay before attempting to play
          await new Promise((resolve, reject) => {
            const timeout = setTimeout(() => reject(new Error('Tune in timeout')), 10000);
            
            const onCanPlay = () => {
              clearTimeout(timeout);
              audioRef.current.removeEventListener('canplay', onCanPlay);
              audioRef.current.removeEventListener('error', onError);
              resolve();
            };
            
            const onError = (e) => {
              clearTimeout(timeout);
              audioRef.current.removeEventListener('canplay', onCanPlay);
              audioRef.current.removeEventListener('error', onError);
              reject(e);
            };
            
            audioRef.current.addEventListener('canplay', onCanPlay, { once: true });
            audioRef.current.addEventListener('error', onError, { once: true });
          });
          
          await audioRef.current.play();
          setIsTunedIn(true);
          setIsMuted(false);
          setPlayingFavorite(false);
          errorCountRef.current = 0; // Reset error count
        }
      } catch (e) {
        console.error("Error tuning in:", e);
        setError("Failed to tune in. Try again.");
      }
    } else {
      // Toggle mute
      if (isMuted) {
        // Unmuting
        if (audioRef.current && audioRef.current.src) {
          audioRef.current.volume = volume / 10;
          if (audioRef.current.paused) {
            await audioRef.current.play().catch(console.error);
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

  // Update time
  useEffect(() => {
    if (!audioRef.current) return;
    
    const updateTime = () => {
      if (isTunedIn && !playingFavorite) {
        setCurrentTime(audioRef.current?.currentTime || 0);
      } else if (playingFavorite) {
        setCurrentTime(audioRef.current?.currentTime || 0);
      }
    };
    
    const interval = setInterval(updateTime, 100);
    return () => clearInterval(interval);
  }, [isTunedIn, playingFavorite]);

  // Volume change
  const handleVolumeChange = (newVolume) => {
    setVolume(newVolume);
    if (audioRef.current && !isMuted) {
      audioRef.current.volume = newVolume / 10;
    }
  };

  // Save favorite
  const saveFavorite = async () => {
    try {
      await axios.post(`${API}/favorites/save`);
      await fetchFavorite();
      showToast("Favorite saved!");
    } catch (e) {
      console.error("Error saving favorite:", e);
      showToast("Error saving favorite", "error");
    }
  };

  // Play favorite
  const playFav = async () => {
    if (!favorite || !audioRef.current) return;
    
    try {
      const response = await axios.get(`${API}/favorites/stream`);
      if (response.data.audio_url) {
        // Add cache buster
        const audioUrl = `${response.data.audio_url}?t=${Date.now()}`;
        
        console.log(`❤️  Playing favorite: ${audioUrl}`);
        audioRef.current.src = audioUrl;
        audioRef.current.currentTime = favoritePosition;
        audioRef.current.volume = volume / 10;
        
        await audioRef.current.play();
        setPlayingFavorite(true);
        setIsTunedIn(true);
        setIsMuted(false);
      }
    } catch (e) {
      console.error("Error playing favorite:", e);
      showToast("Error playing favorite", "error");
    }
  };

  // Back to live
  const backToLive = async () => {
    setPlayingFavorite(false);
    setIsTunedIn(false);
    
    // Refresh state and tune in
    await fetchRadioState();
    
    setTimeout(async () => {
      if (radioState?.current_track) {
        await toggleTuneIn();
      }
    }, 100);
  };

  // Share track
  const shareTrack = async () => {
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
        showToast("Link copied to clipboard!");
      }
    } catch (e) {
      console.error("Error sharing:", e);
      showToast("Error sharing", "error");
    }
  };

  // Toast
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
        preload="auto"
        onEnded={() => !playingFavorite && fetchRadioState()}
        onError={(e) => {
          // Log the error but DON'T immediately try to reload
          console.error("Audio error:", e.target.error);
          
          // Only increment error count and show message
          errorCountRef.current++;
          
          // Only try to recover after multiple errors AND if we're actually tuned in
          if (errorCountRef.current > 3 && isTunedIn && !playingFavorite) {
            setError("Connection issue. Reconnecting...");
            // Wait 2 seconds before attempting recovery
            setTimeout(() => {
              if (isTunedIn) {
                fetchRadioState();
              }
            }, 2000);
          }
        }}
        onLoadStart={() => {
          console.log('🔄 Audio load started');
        }}
        onCanPlay={() => {
          console.log('✅ Audio can play');
          setError(null);
        }}
        onAbort={() => {
          console.log('⚠️ Audio load aborted');
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
