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
  const [loadedSrc, setLoadedSrc] = useState(null); // Track what's actually loaded
  
  const audioRef = useRef(null);
  const syncIntervalRef = useRef(null);
  const isLoadingTrackRef = useRef(false);
  const abortControllerRef = useRef(null);

  // Fetch radio state - but DON'T automatically reload audio
  const fetchRadioState = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/radio/state`);
      const state = response.data;
      setRadioState(state);
      setError(null);
      
      // CRITICAL: Only check for track changes, don't auto-load
      if (!playingFavorite && state.current_track && isTunedIn) {
        const newTrackId = state.current_track.id;
        
        // Track changed - we need to load new audio
        if (newTrackId !== currentTrackId && !isLoadingTrackRef.current) {
          console.log(`🔄 Track changed from ${currentTrackId} to ${newTrackId}`);
          loadTrack(state.current_track.audio_url, state.position, newTrackId);
        } else if (newTrackId === currentTrackId && audioRef.current && !audioRef.current.paused) {
          // Same track - gentle position sync only if playing
          const drift = Math.abs(audioRef.current.currentTime - state.position);
          if (drift > 5) { // Increased threshold
            console.log(`⏩ Syncing position: ${drift.toFixed(1)}s drift`);
            audioRef.current.currentTime = state.position;
          }
        }
      }
      
      setIsLoading(false);
    } catch (e) {
      console.error("Error fetching radio state:", e);
      setIsLoading(false);
    }
  }, [isTunedIn, playingFavorite, currentTrackId]);

  // Load track - completely isolated function
  const loadTrack = useCallback(async (audioUrl, position = 0, trackId = null) => {
    // Prevent concurrent loads
    if (isLoadingTrackRef.current) {
      console.log('⚠️  Load already in progress, skipping');
      return;
    }

    // If we're already playing this exact URL, don't reload
    if (loadedSrc === audioUrl) {
      console.log('✅ Already playing this source, skipping load');
      return;
    }

    isLoadingTrackRef.current = true;
    console.log(`🎵 Loading: ${audioUrl}`);

    try {
      // Abort any pending loads
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      abortControllerRef.current = new AbortController();

      // Add cache buster only once
      const finalUrl = audioUrl.includes('?') 
        ? audioUrl 
        : `${audioUrl}?t=${Date.now()}`;

      // CRITICAL: Load the new source
      if (audioRef.current) {
        // Stop current playback cleanly
        audioRef.current.pause();
        
        // Set new source
        audioRef.current.src = finalUrl;
        setLoadedSrc(audioUrl); // Store the base URL (without cache buster)
        
        // Set position
        audioRef.current.currentTime = position || 0;
        audioRef.current.volume = isMuted ? 0 : volume / 10;
        
        if (trackId) {
          setCurrentTrackId(trackId);
        }

        // Wait for enough data to play
        await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => {
            cleanup();
            reject(new Error('Load timeout'));
          }, 15000);

          const cleanup = () => {
            clearTimeout(timeout);
            if (audioRef.current) {
              audioRef.current.removeEventListener('canplaythrough', onCanPlay);
              audioRef.current.removeEventListener('error', onError);
            }
          };

          const onCanPlay = () => {
            console.log('✅ Can play through');
            cleanup();
            resolve();
          };

          const onError = (e) => {
            console.error('❌ Load error:', e);
            cleanup();
            reject(e);
          };

          if (audioRef.current) {
            audioRef.current.addEventListener('canplaythrough', onCanPlay, { once: true });
            audioRef.current.addEventListener('error', onError, { once: true });
            audioRef.current.load(); // Explicitly trigger load
          } else {
            cleanup();
            reject(new Error('No audio element'));
          }
        });

        // Now play
        await audioRef.current.play();
        console.log('▶️  Playing');
        setError(null);
      }
    } catch (err) {
      console.error("❌ Load failed:", err);
      
      // Don't show error for aborted loads
      if (err.name !== 'AbortError') {
        setError("Playback issue. Retrying...");
        
        // Retry once after a delay
        setTimeout(() => {
          if (isTunedIn && !playingFavorite) {
            isLoadingTrackRef.current = false;
            loadTrack(audioUrl, position, trackId);
          }
        }, 2000);
      }
    } finally {
      isLoadingTrackRef.current = false;
      abortControllerRef.current = null;
    }
  }, [volume, isMuted, isTunedIn, playingFavorite, loadedSrc]);

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
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [fetchRadioState, fetchFavorite]);

  // Background carousel
  useEffect(() => {
    let currentIndex = 0;
    let currentTimeOfDay = getTimeOfDay();
    let currentImageArray = BG_IMAGES[currentTimeOfDay];
    let useFirstLayer = true;
    
    document.documentElement.style.setProperty('--bg-image', `url(${currentImageArray[0]})`);
    document.documentElement.style.setProperty('--bg-opacity-1', '1');
    document.documentElement.style.setProperty('--bg-opacity-2', '0');
    
    const interval = setInterval(() => {
      const newTimeOfDay = getTimeOfDay();
      if (newTimeOfDay !== currentTimeOfDay) {
        currentTimeOfDay = newTimeOfDay;
        currentImageArray = BG_IMAGES[currentTimeOfDay];
        currentIndex = 0;
      } else {
        currentIndex = (currentIndex + 1) % currentImageArray.length;
      }
      
      if (useFirstLayer) {
        document.documentElement.style.setProperty('--bg-image-2', `url(${currentImageArray[currentIndex]})`);
        setTimeout(() => {
          document.documentElement.style.setProperty('--bg-opacity-1', '0');
          document.documentElement.style.setProperty('--bg-opacity-2', '1');
        }, 50);
      } else {
        document.documentElement.style.setProperty('--bg-image', `url(${currentImageArray[currentIndex]})`);
        setTimeout(() => {
          document.documentElement.style.setProperty('--bg-opacity-1', '1');
          document.documentElement.style.setProperty('--bg-opacity-2', '0');
        }, 50);
      }
      
      useFirstLayer = !useFirstLayer;
    }, 60000);
    
    return () => clearInterval(interval);
  }, []);

  // Toggle tune in
  const toggleTuneIn = async () => {
    if (!audioRef.current) return;
    
    if (!isTunedIn) {
      // Tune in
      try {
        const response = await axios.get(`${API}/radio/stream`);
        if (response.data.audio_url && radioState?.current_track) {
          setIsTunedIn(true);
          setIsMuted(false);
          setPlayingFavorite(false);
          
          // Load the track
          await loadTrack(
            response.data.audio_url,
            response.data.position || 0,
            radioState.current_track.id
          );
        }
      } catch (e) {
        console.error("Error tuning in:", e);
        setError("Failed to tune in");
        setIsTunedIn(false);
      }
    } else {
      // Toggle mute
      if (isMuted) {
        if (audioRef.current) {
          audioRef.current.volume = volume / 10;
          if (audioRef.current.paused) {
            audioRef.current.play().catch(console.error);
          }
        }
        setIsMuted(false);
      } else {
        if (audioRef.current) {
          audioRef.current.volume = 0;
        }
        setIsMuted(true);
      }
    }
  };

  // Update time display
  useEffect(() => {
    if (!audioRef.current) return;
    
    const updateTime = () => {
      if (audioRef.current && (isTunedIn || playingFavorite)) {
        setCurrentTime(audioRef.current.currentTime || 0);
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
        setPlayingFavorite(true);
        setIsTunedIn(true);
        setIsMuted(false);
        
        await loadTrack(
          response.data.audio_url,
          favoritePosition,
          favorite.id
        );
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
    setLoadedSrc(null);
    
    if (audioRef.current) {
      audioRef.current.pause();
    }
    
    await fetchRadioState();
    
    setTimeout(() => toggleTuneIn(), 300);
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
        showToast("Link copied!");
      }
    } catch (e) {
      console.error("Error sharing:", e);
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
      {toast && (
        <div className={`toast toast-${toast.type}`}>
          {toast.message}
        </div>
      )}
      
      {/* Audio Element - key prop prevents React from reusing */}
      <audio 
        ref={audioRef}
        key="radio-audio"
        preload="auto"
        onEnded={() => {
          console.log('🎵 Track ended');
          if (!playingFavorite) {
            setLoadedSrc(null);
            setCurrentTrackId(null);
            fetchRadioState();
          }
        }}
        onError={(e) => {
          const error = e.target.error;
          console.error('🔴 Audio error:', {
            code: error?.code,
            message: error?.message,
            src: e.target.src
          });
          
          // Only handle real errors, not aborts
          if (error?.code !== 1 && error?.code !== 4) { // 1=ABORTED, 4=SRC_NOT_SUPPORTED
            setError("Connection issue");
          }
        }}
        onAbort={() => {
          console.log('⚠️  Audio aborted');
        }}
        onLoadStart={() => {
          console.log('🔄 Load start');
        }}
        onLoadedMetadata={() => {
          console.log('📊 Metadata loaded');
        }}
        onCanPlay={() => {
          console.log('✅ Can play');
        }}
        onPlaying={() => {
          console.log('▶️  Playing');
          setError(null);
        }}
      />
      
      {/* Head Unit */}
      <div className="head-unit">
        
        {/* Main LCD Display */}
        <div className="lcd-screen">
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
              
              <div className="time-display">
                <span>{formatTime(currentTime)}</span>
                <span>{formatTime(currentTrack.duration || 0)}</span>
              </div>
              
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${progressPercent}%` }}></div>
              </div>
            </div>
          ) : (
            <div className="lcd-text">NO SIGNAL</div>
          )}
        </div>
        
        {!playingFavorite && radioState && radioState.up_next && radioState.up_next.length > 0 ? (
          <div className="queue-display-single">
            <div className="queue-label">UP NEXT</div>
            <div className="queue-text scrolling">
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
            <div className="queue-label">SHARE THIS SONG!</div>
            <div className="queue-text scrolling">
              {[...Array(2)].map((_, copyIndex) => (
                <span key={`promo-${copyIndex}`} className="scroll-item">
                  Use the share button to get this song's link
                </span>
              ))}
            </div>
          </div>
        ) : null}
        
        <div className="controls">
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
          
          <div className="button-group">
          
          <button 
            className={`control-btn primary icon-only ${isTunedIn ? 'active' : ''} ${isMuted ? 'muted' : ''}`}
            onClick={toggleTuneIn}
            title={!isTunedIn ? "Tune in" : isMuted ? "Unmute" : "Mute"}
          >
            {!isTunedIn ? (
              <Power size={24} />
            ) : isMuted ? (
              <VolumeX size={24} />
            ) : (
              <Volume2 size={24} />
            )}
          </button>
          
          {!playingFavorite ? (
            <div className="fav-controls split">
              <button 
                className="control-btn fav-btn icon-only"
                onClick={saveFavorite}
                disabled={!currentTrack}
                title="Save favorite"
              >
                <Heart size={22} fill={favorite ? "currentColor" : "none"} />
              </button>
              <button 
                className="control-btn fav-btn icon-only"
                onClick={playFav}
                disabled={!favorite}
                title="Play favorite"
              >
                <Play size={22} />
              </button>
            </div>
          ) : (
            <button 
              className="control-btn secondary back-to-live-btn" 
              onClick={backToLive} 
              title="Back to live"
            >
              <RadioIcon size={22} />
            </button>
          )}
          
          <button 
            className="control-btn icon-only"
            onClick={() => {
              if (currentTrack?.youtube_url) {
                window.open(currentTrack.youtube_url, '_blank');
              }
            }}
            disabled={!currentTrack}
            title="Band info"
          >
            <ExternalLink size={22} />
          </button>
          
          <button 
            className="control-btn icon-only"
            onClick={shareTrack}
            disabled={!currentTrack}
            title="Share"
          >
            <Share2 size={22} />
          </button>
          </div>
        </div>
        
        <div className="footer">
          MADRID ROCK RADIO • {radioState?.playlist_count || 0} tracks
        </div>
      </div>
    </div>
  );
}

export default App;
