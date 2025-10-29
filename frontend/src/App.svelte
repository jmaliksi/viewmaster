<script>
  import { onMount } from 'svelte';
  import Login from './Login.svelte';
  import { isAuthenticated, authenticatedFetch, clearAuthCache } from './auth.js';

  const IMAGES_STORAGE_KEY = 'viewmaster_images';
  const MAX_HISTORY_SIZE = 50;
  const MOUSE_INACTIVITY_TIMEOUT = 2000; // 2 seconds

  let authenticated = $state(false);
  let currentPath = $state('/');
  let checkingAuth = $state(true);
  let images = $state(null);
  let currentImage = $state(null);
  let loadingImages = $state(false);
  let imageError = $state(null);
  let imageHistory = $state([]);
  let historyIndex = $state(-1);
  let mouseActive = $state(true);
  let mouseTimeout = null;
  
  // Timer state
  let isPlaying = $state(false);
  let timerSeconds = $state(30); // Default 30 seconds
  let timeRemaining = $state(30);
  let timerInterval = null;
  let isEditingTimer = $state(false);
  let timerInputValue = $state('30');

  // Simple router
  async function checkRoute() {
    currentPath = window.location.pathname;
    
    // Check authentication status
    const authStatus = await isAuthenticated();
    
    // If not authenticated and not on login page, redirect to login
    if (!authStatus && currentPath !== '/login') {
      window.history.pushState({}, '', '/login');
      currentPath = '/login';
      authenticated = false;
      checkingAuth = false;
      return;
    }

    // If authenticated and on login page, redirect to home
    if (authStatus && currentPath === '/login') {
      window.history.pushState({}, '', '/');
      currentPath = '/';
      authenticated = true;
      checkingAuth = false;
      // Load images after authentication
      await loadImages();
      return;
    }

    authenticated = authStatus;
    checkingAuth = false;
    
    // If authenticated and not on login page, load images
    if (authenticated && currentPath !== '/login') {
      await loadImages();
    }
  }

  async function loadImages() {
    // Check localStorage first
    const stored = localStorage.getItem(IMAGES_STORAGE_KEY);
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        images = parsed;
        pickRandomImage();
        return;
      } catch (e) {
        console.error('Error parsing stored images:', e);
        localStorage.removeItem(IMAGES_STORAGE_KEY);
      }
    }

    // Fetch from API
    loadingImages = true;
    imageError = null;

    try {
      const response = await fetch('/api/load', {
        credentials: 'include', // Include cookies for authentication
      });

      if (!response.ok) {
        throw new Error(`Failed to load images: ${response.statusText}`);
      }

      const data = await response.json();
      
      // Store in localStorage
      localStorage.setItem(IMAGES_STORAGE_KEY, JSON.stringify(data));
      images = data;
      pickRandomImage();
    } catch (err) {
      console.error('Error loading images:', err);
      imageError = err.message || 'Failed to load images';
    } finally {
      loadingImages = false;
    }
  }

  function pickRandomImage() {
    if (!images || !images.images || images.images.length === 0) {
      currentImage = null;
      return;
    }

    const randomIndex = Math.floor(Math.random() * images.images.length);
    const newImage = images.images[randomIndex];
    
    // Add new image to history
    imageHistory = [...imageHistory, newImage];
    historyIndex = imageHistory.length - 1;
    
    // Keep history bounded
    if (imageHistory.length > MAX_HISTORY_SIZE) {
      imageHistory = imageHistory.slice(-MAX_HISTORY_SIZE);
      historyIndex = imageHistory.length - 1;
    }
    
    currentImage = newImage;
  }

  function goToNextImage() {
    resetMouseTimeout();
    // If we're not at the end of history, go forward
    if (historyIndex < imageHistory.length - 1) {
      historyIndex++;
      currentImage = imageHistory[historyIndex];
    } else {
      // Otherwise, pick a new random image
      pickRandomImage();
    }
    // Reset timer when image changes if playing
    if (isPlaying) {
      timeRemaining = timerSeconds;
    }
  }

  function goToPreviousImage() {
    resetMouseTimeout();
    if (historyIndex > 0) {
      historyIndex--;
      currentImage = imageHistory[historyIndex];
    }
  }

  function getCurrentImageIndex() {
    if (!currentImage || !images || !images.images) {
      return -1;
    }
    return images.images.findIndex(img => img.url === currentImage.url);
  }

  function goToNextSequential() {
    resetMouseTimeout();
    if (!images || !images.images || images.images.length === 0) {
      return;
    }
    const currentIndex = getCurrentImageIndex();
    if (currentIndex === -1) {
      // If current image not found, go to first image
      currentImage = images.images[0];
      return;
    }
    const nextIndex = (currentIndex + 1) % images.images.length;
    currentImage = images.images[nextIndex];
  }

  function goToPreviousSequential() {
    resetMouseTimeout();
    if (!images || !images.images || images.images.length === 0) {
      return;
    }
    const currentIndex = getCurrentImageIndex();
    if (currentIndex === -1) {
      // If current image not found, go to last image
      currentImage = images.images[images.images.length - 1];
      return;
    }
    const prevIndex = (currentIndex - 1 + images.images.length) % images.images.length;
    currentImage = images.images[prevIndex];
  }

  async function handleLogout() {
    try {
      // Call logout endpoint to clear cookie
      await fetch('/api/logout', {
        method: 'POST',
        credentials: 'include', // Include cookies
      });
    } catch (err) {
      console.error('Logout error:', err);
    }
    
    // Clear auth cache and images
    clearAuthCache();
    localStorage.removeItem(IMAGES_STORAGE_KEY);
    authenticated = false;
    images = null;
    currentImage = null;
    imageHistory = [];
    historyIndex = -1;
    
    // Redirect to login
    window.history.pushState({}, '', '/login');
    currentPath = '/login';
  }

  function resetMouseTimeout() {
    mouseActive = true;
    if (mouseTimeout) {
      clearTimeout(mouseTimeout);
    }
    mouseTimeout = setTimeout(() => {
      mouseActive = false;
    }, MOUSE_INACTIVITY_TIMEOUT);
  }

  function startTimer() {
    if (timerInterval) {
      clearInterval(timerInterval);
    }
    timerInterval = setInterval(() => {
      if (timeRemaining > 0) {
        timeRemaining--;
      } else {
        // Timer expired - go to next image (which will reset timer)
        goToNextImage();
      }
    }, 1000);
  }

  function stopTimer() {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
  }

  function togglePlayPause() {
    isPlaying = !isPlaying;
    if (isPlaying) {
      startTimer();
    } else {
      stopTimer();
    }
  }

  function handleTimerInputChange(e) {
    const value = e.target.value;
    timerInputValue = value;
    const numValue = parseInt(value, 10);
    if (!isNaN(numValue) && numValue > 0) {
      timerSeconds = numValue;
      if (!isPlaying) {
        timeRemaining = numValue;
      }
    }
  }

  function handleTimerInputBlur() {
    isEditingTimer = false;
    const numValue = parseInt(timerInputValue, 10);
    if (isNaN(numValue) || numValue <= 0) {
      // Reset to previous valid value
      timerInputValue = timerSeconds.toString();
      timeRemaining = timerSeconds;
    } else {
      timerSeconds = numValue;
      timeRemaining = numValue;
    }
  }

  function handleTimerInputFocus() {
    if (!isPlaying) {
      isEditingTimer = true;
    }
  }

  function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  // Check route on mount and when path changes
  onMount(() => {
    checkRoute();
    
    // Listen for popstate events (back/forward navigation)
    window.addEventListener('popstate', checkRoute);
    
    // Track mouse activity
    resetMouseTimeout();
    window.addEventListener('mousemove', resetMouseTimeout);
    window.addEventListener('mouseenter', resetMouseTimeout);

    return () => {
      window.removeEventListener('popstate', checkRoute);
      window.removeEventListener('mousemove', resetMouseTimeout);
      window.removeEventListener('mouseenter', resetMouseTimeout);
      if (mouseTimeout) {
        clearTimeout(mouseTimeout);
      }
      stopTimer();
    };
  });
</script>

{#if !authenticated || currentPath === '/login'}
  <Login />
{:else}
  <main onmouseenter={resetMouseTimeout} onmousemove={resetMouseTimeout}>
    <header class:inactive={!mouseActive}>
      <h1>ViewMaster</h1>
      <div class="header-center">
        <div class="playback-controls">
          <button 
            class="prev-btn" 
            onclick={goToPreviousImage}
            disabled={historyIndex <= 0}
          >
            Prev
          </button>
          <button 
            class="play-pause-btn" 
            onclick={togglePlayPause}
            disabled={!images || !images.images || images.images.length === 0}
            aria-label={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? '⏸' : '▶'}
          </button>
          <div class="timer-container">
            {#if isEditingTimer && !isPlaying}
              <input
                type="number"
                class="timer-input"
                value={timerInputValue}
                min="1"
                max="600"
                oninput={handleTimerInputChange}
                onblur={handleTimerInputBlur}
                onkeydown={(e) => {
                  if (e.key === 'Enter') {
                    e.target.blur();
                  } else if (e.key === 'Escape') {
                    timerInputValue = timerSeconds.toString();
                    e.target.blur();
                  }
                }}
              />
              <span class="timer-label">s</span>
            {:else}
              <button
                class="timer-display"
                onclick={handleTimerInputFocus}
                disabled={isPlaying}
                aria-label="Edit timer duration"
              >
                {formatTime(timeRemaining)}
              </button>
            {/if}
          </div>
          <button 
            class="next-btn" 
            onclick={goToNextImage}
            disabled={!images || !images.images || images.images.length === 0}
          >
            Next
          </button>
        </div>
      </div>
      <div class="header-actions">
        <button class="logout-btn" onclick={handleLogout}>Logout</button>
      </div>
    </header>
    <div class="content">
      {#if checkingAuth}
        <p>Checking authentication...</p>
      {:else if loadingImages}
        <p>Loading images...</p>
      {:else if imageError}
        <div class="error-message">
          <p>Error: {imageError}</p>
          <button onclick={loadImages}>Retry</button>
        </div>
      {:else if currentImage}
        <div class="image-container">
          <button 
            class="arrow-btn left-arrow" 
            class:inactive={!mouseActive}
            onclick={goToPreviousSequential}
            disabled={!images || !images.images || images.images.length === 0}
            aria-label="Previous image"
          >
            ←
          </button>
          <img 
            src={currentImage.url} 
            alt={currentImage.filename}
            class="display-image"
          />
          <button 
            class="arrow-btn right-arrow" 
            class:inactive={!mouseActive}
            onclick={goToNextSequential}
            disabled={!images || !images.images || images.images.length === 0}
            aria-label="Next image"
          >
            →
          </button>
        </div>
      {:else if images && images.images && images.images.length === 0}
        <p>No images available.</p>
      {:else}
        <p>Loading...</p>
      {/if}
    </div>
  </main>
{/if}
