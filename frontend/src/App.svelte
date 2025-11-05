<script>
  import { onMount } from 'svelte';
  import Login from './Login.svelte';
  import { isAuthenticated, authenticatedFetch, clearAuthCache } from './auth.js';
  import { fabric } from 'fabric';

  const IMAGES_STORAGE_KEY = 'viewmaster_images';
  const CHECKED_FOLDERS_STORAGE_KEY = 'viewmaster_checked_folders';
  const MAX_HISTORY_SIZE = 50;
  const MOUSE_INACTIVITY_TIMEOUT = 2000; // 2 seconds

  // Main app mode state machine
  let appMode = $state('loading'); // 'login' | 'loading' | 'start' | 'viewing' | 'drawing' | 'stopped' | 'error'
  
  let currentPath = $state('/');
  let images = $state(null);
  let currentImage = $state(null);
  let imageError = $state(null);
  let imageHistory = $state([]);
  let historyIndex = $state(-1);
  let mouseTimeout = null;
  
  // Image preloading state
  let nextRandomImages = $state([]); // buffer of upcoming random images
  
  // Folder filtering state
  let availableFolders = $state([]);
  let checkedFolders = $state(new Set());
  let folderDropdownOpen = $state(false);
  
  // Consolidated timer state
  let timer = $state({
    playing: false,
    duration: 30, // seconds
    remaining: 30,
    editing: false,
    inputValue: '30'
  });
  let timerInterval = null;
  let isFullscreen = $state(false);
  
  // Consolidated UI visibility state
  let uiVisibility = $state({
    mouseActive: true,
    showDuringDraw: false
  });
 
  // Computed: show timer warning in last 3 seconds
  let showTimerWarning = $derived(timer.remaining <= 3 && timer.playing);
  
  // Computed: timer progress (0 to 1)
  let timerProgress = $derived(timer.duration > 0 ? timer.remaining / timer.duration : 0);
  
  // Computed: show timer bar when UI is hidden and timer is playing (or always in drawing mode)
  let showTimerBar = $derived(timer.playing && currentImage !== null && (!uiVisibility.mouseActive || appMode === 'drawing'));
  
  // Computed: filtered images based on checked folders (always includes root images)
  let filteredImages = $derived.by(() => {
    if (!images || !images.images || images.images.length === 0) return [];
    
    return images.images.filter(img => {
      // Always include root images (no parent folder)
      const pathParts = (img.path || img.relative_path || '').split('/');
      if (pathParts.length <= 1) {
        return true; // Root image, always include
      }
      
      // Get immediate parent folder
      const parentFolder = pathParts[pathParts.length - 2];
      return checkedFolders.has(parentFolder);
    });
  });

  // Drawing mode state
  const DRAW_COLOR = '#FF69B4';
  const DRAW_WIDTH = 3;
  let fabricCanvas = null;
  let drawingCanvasEl = null;
  
  // Drawing storage: Map of image URL -> drawing snapshot (data URL)
  let imageDrawings = $state(new Map());
  let showDrawingsInGallery = $state(true);

  function initFabricIfNeeded() {
    if (!drawingCanvasEl) return;
    if (!fabricCanvas) {
      fabricCanvas = new fabric.Canvas(drawingCanvasEl, {
        isDrawingMode: true,
        selection: false
      });
    }
    fabricCanvas.isDrawingMode = true;
    if (fabricCanvas.freeDrawingBrush) {
      fabricCanvas.freeDrawingBrush.color = DRAW_COLOR;
      fabricCanvas.freeDrawingBrush.width = DRAW_WIDTH;
    }
    // Ensure canvas matches viewport
    fabricCanvas.setWidth(window.innerWidth);
    fabricCanvas.setHeight(window.innerHeight);
    fabricCanvas.renderAll();
  }

  function enterDrawingMode() {
    resetMouseTimeout();
    appMode = 'drawing';
    uiVisibility.showDuringDraw = false;
    // Show overlay, then init
    queueMicrotask(() => {
      initFabricIfNeeded();
    });
  }

  function saveCurrentDrawing() {
    if (!fabricCanvas || !currentImage) return;
    
    // Check if canvas has any drawing objects
    const objects = fabricCanvas.getObjects();
    if (objects.length === 0) {
      // No drawing, remove from storage if exists
      imageDrawings.delete(currentImage.url);
      return;
    }
    
    // Save the canvas as a data URL
    // The canvas is fullscreen, but we'll overlay it on thumbnails in gallery
    // The browser will scale it appropriately when displayed
    try {
      const dataUrl = fabricCanvas.toDataURL('image/png');
      imageDrawings.set(currentImage.url, dataUrl);
    } catch (e) {
      console.error('Error saving drawing:', e);
      // If CORS error, try without crossOrigin
      try {
        const dataUrl = fabricCanvas.toDataURL('image/png');
        imageDrawings.set(currentImage.url, dataUrl);
      } catch (e2) {
        console.error('Error saving drawing (retry):', e2);
      }
    }
  }

  function exitDrawingMode() {
    // Save drawing before exiting
    saveCurrentDrawing();
    
    appMode = 'viewing';
    uiVisibility.showDuringDraw = false;
    if (fabricCanvas) {
      fabricCanvas.isDrawingMode = false;
    }
    // Reset mouse timeout to show top and bottom bars
    resetMouseTimeout();
  }

  function clearDrawingCanvas() {
    if (fabricCanvas) {
      fabricCanvas.clear();
      // Reapply brush after clear (clear removes background/objects but brush persists)
      fabricCanvas.isDrawingMode = true;
      if (fabricCanvas.freeDrawingBrush) {
        fabricCanvas.freeDrawingBrush.color = DRAW_COLOR;
        fabricCanvas.freeDrawingBrush.width = DRAW_WIDTH;
      }
      fabricCanvas.renderAll();
    }
    // Remove drawing from storage for current image
    if (currentImage) {
      imageDrawings.delete(currentImage.url);
    }
  }

  // Fullscreen functionality
  function toggleFullscreen() {
    const doc = document;
    const docEl = doc.documentElement;
    
    const isFullscreenActive = 
      doc.fullscreenElement || 
      doc.webkitFullscreenElement || 
      doc.mozFullScreenElement || 
      doc.msFullscreenElement;
    
    if (!isFullscreenActive) {
      if (docEl.requestFullscreen) {
        docEl.requestFullscreen().catch(err => {
          console.error('Error attempting to enable fullscreen:', err);
        });
      } else if (docEl.webkitRequestFullscreen) {
        docEl.webkitRequestFullscreen();
      } else if (docEl.mozRequestFullScreen) {
        docEl.mozRequestFullScreen();
      } else if (docEl.msRequestFullscreen) {
        docEl.msRequestFullscreen();
      }
    } else {
      if (doc.exitFullscreen) {
        doc.exitFullscreen().catch(err => {
          console.error('Error attempting to exit fullscreen:', err);
        });
      } else if (doc.webkitExitFullscreen) {
        doc.webkitExitFullscreen();
      } else if (doc.mozCancelFullScreen) {
        doc.mozCancelFullScreen();
      } else if (doc.msExitFullscreen) {
        doc.msExitFullscreen();
      }
    }
  }

  function handleFullscreenChange() {
    isFullscreen = !!(
      document.fullscreenElement || 
      document.webkitFullscreenElement || 
      document.mozFullScreenElement || 
      document.msFullscreenElement
    );
  }

  // Simple router
  async function checkRoute() {
    currentPath = window.location.pathname;
    
    // Check authentication status
    appMode = 'loading';
    const authStatus = await isAuthenticated();
    
    // If not authenticated and not on login page, redirect to login
    if (!authStatus && currentPath !== '/login') {
      window.history.pushState({}, '', '/login');
      currentPath = '/login';
      appMode = 'login';
      return;
    }

    // If authenticated and on login page, redirect to home
    if (authStatus && currentPath === '/login') {
      window.history.pushState({}, '', '/');
      currentPath = '/';
      // Load images after authentication
      await loadImages();
      return;
    }
    
    // If authenticated and not on login page, load images
    if (authStatus && currentPath !== '/login') {
      await loadImages();
    } else {
      appMode = 'login';
    }
  }

  async function loadImages() {
    appMode = 'loading';
    // Check localStorage first
    const stored = localStorage.getItem(IMAGES_STORAGE_KEY);
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        images = parsed;
        // Extract parent folders and initialize checked folders
        extractFolders();
        appMode = 'start';
        return;
      } catch (e) {
        console.error('Error parsing stored images:', e);
        localStorage.removeItem(IMAGES_STORAGE_KEY);
      }
    }

    // Fetch from API
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
      
      // Extract parent folders and initialize checked folders
      extractFolders();
      appMode = 'start';
    } catch (err) {
      console.error('Error loading images:', err);
      imageError = err.message || 'Failed to load images';
      appMode = 'error';
    }
  }

  function extractFolders() {
    if (!images || !images.images || images.images.length === 0) {
      availableFolders = [];
      checkedFolders = new Set();
      return;
    }
    
    const folders = new Set();
    
    images.images.forEach(img => {
      const pathParts = (img.path || img.relative_path || '').split('/');
      // If path has more than 1 part, it has a parent folder
      if (pathParts.length > 1) {
        const parentFolder = pathParts[pathParts.length - 2];
        folders.add(parentFolder);
      }
    });
    
    availableFolders = Array.from(folders).sort();
    
    // Try to load saved checked folders from localStorage
    const stored = localStorage.getItem(CHECKED_FOLDERS_STORAGE_KEY);
    if (stored) {
      try {
        const savedFolders = JSON.parse(stored);
        // Only restore folders that still exist
        const validSavedFolders = savedFolders.filter(f => folders.has(f));
        if (validSavedFolders.length > 0) {
          checkedFolders = new Set(validSavedFolders);
          return;
        }
      } catch (e) {
        console.error('Error parsing stored checked folders:', e);
      }
    }
    
    // Initialize all folders as checked if no saved preferences
    checkedFolders = new Set(availableFolders);
  }
  
  function saveCheckedFolders() {
    try {
      const foldersArray = Array.from(checkedFolders);
      localStorage.setItem(CHECKED_FOLDERS_STORAGE_KEY, JSON.stringify(foldersArray));
    } catch (e) {
      console.error('Error saving checked folders:', e);
    }
  }

  function toggleFolder(folder) {
    const newChecked = new Set(checkedFolders);
    if (newChecked.has(folder)) {
      newChecked.delete(folder);
    } else {
      newChecked.add(folder);
    }
    checkedFolders = newChecked;
    saveCheckedFolders();
    // Clear preloaded random images buffer when folder selection changes
    nextRandomImages = [];
  }
  
  function toggleAllFolders() {
    if (checkedFolders.size === availableFolders.length) {
      // Uncheck all
      checkedFolders = new Set();
    } else {
      // Check all
      checkedFolders = new Set(availableFolders);
    }
    saveCheckedFolders();
    // Clear preloaded random images buffer when folder selection changes
    nextRandomImages = [];
  }
  
  function getFirstImageForFolder(folder) {
    if (!images || !images.images || images.images.length === 0) {
      return null;
    }
    
    // Find the first image that belongs to this folder
    for (const img of images.images) {
      const pathParts = (img.path || img.relative_path || '').split('/');
      if (pathParts.length > 1) {
        const parentFolder = pathParts[pathParts.length - 2];
        if (parentFolder === folder) {
          return img.url;
        }
      }
    }
    
    return null;
  }
  
  function startSession() {
    appMode = 'viewing';
    pickRandomImage();
    // Preload a batch of images for smoother navigation
    preloadBatch(5);
    // Start the timer
    timer.playing = true;
    timer.remaining = timer.duration;
    startTimer();
  }

  function pickRandomImage() {
    const filtered = filteredImages;
    if (!filtered || filtered.length === 0) {
      currentImage = null;
      return;
    }

    let newImage;

    // Use preloaded random image from buffer if available, otherwise pick a new one
    if (nextRandomImages && nextRandomImages.length > 0) {
      newImage = nextRandomImages.shift();
    } else {
      const randomIndex = Math.floor(Math.random() * filtered.length);
      newImage = filtered[randomIndex];
    }
    
    // Add new image to history
    imageHistory = [...imageHistory, newImage];
    historyIndex = imageHistory.length - 1;
    
    // Keep history bounded
    if (imageHistory.length > MAX_HISTORY_SIZE) {
      imageHistory = imageHistory.slice(-MAX_HISTORY_SIZE);
      historyIndex = imageHistory.length - 1;
    }
    
    currentImage = newImage;
    
    // Preload adjacent images after setting current image
    preloadAdjacentImages();
    
    // Top up the next random images buffer
    preloadNextRandomImages(2);
  }

  function preloadNextRandomImages(count = 2) {
    const filtered = filteredImages;
    if (!filtered || filtered.length === 0) return;

    if (!nextRandomImages) nextRandomImages = [];

    const totalImages = filtered.length;
    const currentUrl = currentImage?.url;

    // Fill the buffer up to 'count' items
    while (nextRandomImages.length < count) {
      const randomIndex = Math.floor(Math.random() * totalImages);
      const candidate = filtered[randomIndex];

      // Avoid immediate duplicates with current or already buffered URLs
      const alreadyBuffered = nextRandomImages.some(img => img.url === candidate.url);
      if (candidate.url !== currentUrl && !alreadyBuffered) {
        nextRandomImages.push(candidate);
        preloadImage(candidate.url);
      }
      // If duplicate encountered, loop continues until filled (or best effort if all same)
      if (totalImages <= 1) break;
    }
  }

  function goToNextImage() {
    if (appMode === 'start') {
      appMode = 'viewing';
    }
    // Save current drawing before moving to next image
    if (fabricCanvas && currentImage) {
      saveCurrentDrawing();
    }
    // Clear drawing canvas for next image
    if (fabricCanvas) {
      fabricCanvas.clear();
      if (fabricCanvas.isDrawingMode) {
        if (fabricCanvas.freeDrawingBrush) {
          fabricCanvas.freeDrawingBrush.color = DRAW_COLOR;
          fabricCanvas.freeDrawingBrush.width = DRAW_WIDTH;
        }
      }
    }
    // If we're not at the end of history, go forward
    if (historyIndex < imageHistory.length - 1) {
      historyIndex++;
      currentImage = imageHistory[historyIndex];
    } else {
      // Otherwise, pick a new random image
      pickRandomImage();
    }
    // Reset timer when image changes if playing
    if (timer.playing) {
      timer.remaining = timer.duration;
    }
  }

  function goToPreviousImage() {
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
    if (!images || !images.images || images.images.length === 0) {
      return;
    }
    // Save current drawing before moving to next image
    if (fabricCanvas && currentImage) {
      saveCurrentDrawing();
    }
    const currentIndex = getCurrentImageIndex();
    if (currentIndex === -1) {
      // If current image not found, go to first image
      currentImage = images.images[0];
      preloadAdjacentImages();
      return;
    }
    const nextIndex = (currentIndex + 1) % images.images.length;
    currentImage = images.images[nextIndex];
    // Clear drawing canvas for next image
    if (fabricCanvas) {
      fabricCanvas.clear();
      if (fabricCanvas.isDrawingMode) {
        if (fabricCanvas.freeDrawingBrush) {
          fabricCanvas.freeDrawingBrush.color = DRAW_COLOR;
          fabricCanvas.freeDrawingBrush.width = DRAW_WIDTH;
        }
      }
    }
    preloadAdjacentImages();
  }

  function goToPreviousSequential() {
    if (!images || !images.images || images.images.length === 0) {
      return;
    }
    const currentIndex = getCurrentImageIndex();
    if (currentIndex === -1) {
      // If current image not found, go to last image
      currentImage = images.images[images.images.length - 1];
      preloadAdjacentImages();
      return;
    }
    const prevIndex = (currentIndex - 1 + images.images.length) % images.images.length;
    currentImage = images.images[prevIndex];
    preloadAdjacentImages();
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
    localStorage.removeItem(CHECKED_FOLDERS_STORAGE_KEY);
    images = null;
    currentImage = null;
    imageHistory = [];
    historyIndex = -1;
    appMode = 'login';
    
    // Redirect to login
    window.history.pushState({}, '', '/login');
    currentPath = '/login';
  }

  function stopSession() {
    // Save current drawing before stopping
    if (fabricCanvas && currentImage) {
      saveCurrentDrawing();
    }
    
    // Clear the drawing canvas
    if (fabricCanvas) {
      fabricCanvas.clear();
      if (fabricCanvas.isDrawingMode) {
        if (fabricCanvas.freeDrawingBrush) {
          fabricCanvas.freeDrawingBrush.color = DRAW_COLOR;
          fabricCanvas.freeDrawingBrush.width = DRAW_WIDTH;
        }
      }
    }
    
    appMode = 'stopped';
    // Stop the timer
    timer.playing = false;
    stopTimer();
  }

  function resumeSession() {
    appMode = 'viewing';
    // Resume the timer
    timer.playing = true;
    startTimer();
  }

  function newSession() {
    appMode = 'start';
    // Stop the timer
    timer.playing = false;
    stopTimer();
    // Clear current image and history
    currentImage = null;
    imageHistory = [];
    historyIndex = -1;
    nextRandomImages = [];
  }

  function resetMouseTimeout() {
    uiVisibility.mouseActive = true;
    if (mouseTimeout) {
      clearTimeout(mouseTimeout);
    }
    mouseTimeout = setTimeout(() => {
      uiVisibility.mouseActive = false;
    }, MOUSE_INACTIVITY_TIMEOUT);
  }

  function startTimer() {
    if (timerInterval) {
      clearInterval(timerInterval);
    }
    timerInterval = setInterval(() => {
      if (timer.remaining > 0) {
        timer.remaining--;
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
    timer.playing = !timer.playing;
    if (timer.playing) {
      startTimer();
    } else {
      stopTimer();
    }
  }

  function handleTimerInputChange(e) {
    const value = e.target.value;
    timer.inputValue = value;
    const numValue = parseInt(value, 10);
    if (!isNaN(numValue) && numValue > 0) {
      timer.duration = numValue;
      if (!timer.playing) {
        timer.remaining = numValue;
      }
    }
  }

  function handleTimerInputBlur() {
    timer.editing = false;
    const numValue = parseInt(timer.inputValue, 10);
    if (isNaN(numValue) || numValue <= 0) {
      // Reset to previous valid value
      timer.inputValue = timer.duration.toString();
      timer.remaining = timer.duration;
    } else {
      timer.duration = numValue;
      timer.remaining = numValue;
    }
  }

  function handleTimerInputFocus() {
    if (!timer.playing) {
      timer.editing = true;
    }
  }

  function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  // Image preloading functions
  function preloadImage(url) {
    const img = new Image();
    img.src = url;
  }

  function preloadAdjacentImages() {
    if (!images?.images || images.images.length === 0) return;

    const currentIndex = getCurrentImageIndex();
    if (currentIndex === -1) return;

    const totalImages = images.images.length;
    const bufferSize = 2; // preload 2 before and 2 after

    // Preload a symmetric buffer around the current index
    for (let offset = 1; offset <= bufferSize; offset++) {
      const nextIndex = (currentIndex + offset) % totalImages;
      const prevIndex = (currentIndex - offset + totalImages) % totalImages;
      preloadImage(images.images[nextIndex].url);
      preloadImage(images.images[prevIndex].url);
    }
  }

  function preloadBatch(count = 3) {
    if (!images?.images || images.images.length === 0) return;

    const currentIndex = getCurrentImageIndex();
    if (currentIndex === -1) return;

    const totalImages = images.images.length;
    
    // Preload 'count' images ahead
    for (let i = 1; i <= count; i++) {
      const nextIndex = (currentIndex + i) % totalImages;
      preloadImage(images.images[nextIndex].url);
    }
  }

  // Keyboard controls
  function handleKeydown(event) {
    // Only handle keyboard shortcuts when not on login page
    if (appMode === 'login' || currentPath === '/login') return;
    
    // Don't handle keyboard shortcuts when editing timer
    if (timer.editing) return;
    
    switch (event.key) {
      case 'Escape':
        if (appMode === 'drawing') {
          event.preventDefault();
          exitDrawingMode();
        }
        break;
      case ' ':
        event.preventDefault();
        togglePlayPause();
        break;
      case 'ArrowRight':
        event.preventDefault();
        goToNextSequential();
        break;
      case 'ArrowLeft':
        event.preventDefault();
        goToPreviousSequential();
        break;
      case 'Enter':
        event.preventDefault();
        goToNextImage();
        break;
    }
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

    // Listen for fullscreen changes
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    document.addEventListener('webkitfullscreenchange', handleFullscreenChange);
    document.addEventListener('mozfullscreenchange', handleFullscreenChange);
    document.addEventListener('MSFullscreenChange', handleFullscreenChange);
    
    // Listen for keyboard events
    document.addEventListener('keydown', handleKeydown);
    
    // Check initial fullscreen state
    handleFullscreenChange();

    return () => {
      window.removeEventListener('popstate', checkRoute);
      window.removeEventListener('mousemove', resetMouseTimeout);
      window.removeEventListener('mouseenter', resetMouseTimeout);
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      document.removeEventListener('webkitfullscreenchange', handleFullscreenChange);
      document.removeEventListener('mozfullscreenchange', handleFullscreenChange);
      document.removeEventListener('MSFullscreenChange', handleFullscreenChange);
      document.removeEventListener('keydown', handleKeydown);
      if (mouseTimeout) {
        clearTimeout(mouseTimeout);
      }
      stopTimer();
    };
  });
</script>

{#if appMode === 'login' || currentPath === '/login'}
  <Login />
{:else}
  <main onmouseenter={resetMouseTimeout} onmousemove={resetMouseTimeout}>
    <header class:inactive={!uiVisibility.mouseActive || (appMode === 'drawing' && !uiVisibility.showDuringDraw)}>
      <h1 class="header-title">ViewMaster</h1>
      <div class="header-center">
        <div class="playback-controls">
          <button 
            class="prev-btn" 
            onclick={goToPreviousImage}
            disabled={historyIndex <= 0}
            aria-label="Previous"
          >
            <span style="display: flex; align-items: center; justify-content: center; height: 100%">&laquo;</span>
          </button>
          <button 
            class="play-pause-btn" 
            onclick={togglePlayPause}
            disabled={!images || !images.images || images.images.length === 0}
            aria-label={timer.playing ? 'Pause' : 'Play'}
          >
            {timer.playing ? '⏸' : '▶'}
          </button>
          <div class="timer-container" class:show-warning={showTimerWarning}>
            {#if timer.editing && !timer.playing}
              <input
                type="number"
                class="timer-input"
                value={timer.inputValue}
                min="1"
                max="600"
                oninput={handleTimerInputChange}
                onblur={handleTimerInputBlur}
                onkeydown={(e) => {
                  if (e.key === 'Enter') {
                    e.target.blur();
                  } else if (e.key === 'Escape') {
                    timer.inputValue = timer.duration.toString();
                    e.target.blur();
                  }
                }}
              />
              <span class="timer-label">s</span>
            {:else}
              <button
                class="timer-display"
                onclick={handleTimerInputFocus}
                disabled={timer.playing}
                aria-label="Edit timer duration"
              >
                {formatTime(timer.remaining)}
              </button>
            {/if}
          </div>
          <button 
            class="next-btn" 
            onclick={goToNextImage}
            disabled={!images || !images.images || images.images.length === 0}
            aria-label="Next"
          >
            <span style="display: flex; align-items: center; justify-content: center; height: 100%">&raquo;</span>
          </button>
        </div>
      </div>
      <div class="header-actions">
        {#if appMode === 'stopped'}
          <button class="resume-btn" onclick={resumeSession} aria-label="Resume">
            Resume
          </button>
          <button class="new-session-btn" onclick={newSession} aria-label="New Session">
            New Session
          </button>
        {:else}
          <button 
            class="fullscreen-btn" 
            onclick={toggleFullscreen}
            aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
            title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
          >
            {isFullscreen ? '⤓' : '⤢'}
          </button>
          {#if appMode === 'viewing'}
            <button class="stop-btn" onclick={stopSession} aria-label="Stop">⏹</button>
          {:else}
            <button class="logout-btn" onclick={handleLogout} aria-label="Logout">⎋</button>
          {/if}
        {/if}
      </div>
    </header>
    <div class="content">
      {#if appMode === 'loading'}
        <p>{currentPath === '/login' ? 'Checking authentication...' : 'Loading images...'}</p>
      {:else if appMode === 'error'}
        <div class="error-message">
          <p>Error: {imageError}</p>
          <button onclick={loadImages}>Retry</button>
        </div>
      {:else if appMode === 'start'}
        <div class="start-container">
          <div class="start-content">
            <button class="start-btn" onclick={startSession}>
              Start
            </button>
            {#if availableFolders.length > 0}
              <div class="folder-filter">
                <button 
                  class="folder-filter-toggle"
                  onclick={() => folderDropdownOpen = !folderDropdownOpen}
                  aria-label="Toggle folder filter"
                  aria-expanded={folderDropdownOpen}
                >
                  <span>Filter Folders</span>
                  <span class="folder-filter-icon">{folderDropdownOpen ? '▼' : '▶'}</span>
                </button>
                {#if folderDropdownOpen}
                  <div class="folder-checkboxes">
                    <label class="folder-checkbox-item folder-checkbox-select-all">
                      <input
                        type="checkbox"
                        checked={checkedFolders.size === availableFolders.length}
                        onchange={toggleAllFolders}
                      />
                      <span>Select All</span>
                    </label>
                    {#each availableFolders as folder}
                      {@const thumbnailUrl = getFirstImageForFolder(folder)}
                      <label class="folder-checkbox-item">
                        {#if thumbnailUrl}
                          <img 
                            src={thumbnailUrl} 
                            alt=""
                            class="folder-thumbnail"
                            loading="lazy"
                          />
                        {/if}
                        <input
                          type="checkbox"
                          checked={checkedFolders.has(folder)}
                          onchange={() => toggleFolder(folder)}
                        />
                        <span>{folder}</span>
                      </label>
                    {/each}
                  </div>
                {/if}
              </div>
            {/if}
          </div>
        </div>
      {:else if appMode === 'stopped'}
        <div class="gallery-container">
          <div class="gallery-grid">
            {#each imageHistory as image}
              {@const hasDrawing = imageDrawings.has(image.url) && showDrawingsInGallery}
              <div class="gallery-item">
                <img 
                  src={image.url} 
                  alt={image.filename}
                  class="gallery-thumbnail"
                  loading="lazy"
                />
                {#if hasDrawing}
                  <img 
                    src={imageDrawings.get(image.url)} 
                    alt="Drawing overlay"
                    class="gallery-drawing-overlay"
                  />
                {/if}
              </div>
            {/each}
          </div>
        </div>
      {:else if (appMode === 'viewing' || appMode === 'drawing') && currentImage}
        <div class="image-container">
          {#if showTimerBar}
            <div class="timer-bar" style="width: {timerProgress * 100}%"></div>
          {/if}
          <button 
            class="arrow-btn left-arrow" 
            class:inactive={!uiVisibility.mouseActive || (appMode === 'drawing' && !uiVisibility.showDuringDraw)}
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
            class:inactive={!uiVisibility.mouseActive || (appMode === 'drawing' && !uiVisibility.showDuringDraw)}
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
<!-- Drawing overlay covers entire viewport; only active during drawing mode -->
<div class="drawing-overlay" class:active={appMode === 'drawing'} role="presentation" aria-hidden="true" onmousemove={resetMouseTimeout} onmouseenter={resetMouseTimeout}
  ontouchstart={(e) => {
    if (appMode !== 'drawing') return;
    // Two-finger tap exits draw mode (do not clear)
    if (e.touches && e.touches.length === 2) {
      e.preventDefault();
      exitDrawingMode();
      uiVisibility.showDuringDraw = false;
    } else if (e.touches && e.touches.length === 1) {
      // Resume drawing: hide UI again
      uiVisibility.showDuringDraw = false;
    }
  }}
  onpointerdown={(e) => {
    if (appMode !== 'drawing') return;
    // Any pen press resumes drawing; hide UI
    if (e.pointerType === 'pen' || e.pointerType === 'mouse' || e.pointerType === 'touch') {
      uiVisibility.showDuringDraw = false;
    }
  }}>
  <canvas bind:this={drawingCanvasEl} id="drawing-canvas"></canvas>
  <!-- no controls while drawing; exit with Escape -->
  <!-- pointer events are enabled only when active via CSS -->
</div>

{#if appMode !== 'login' && currentPath !== '/login' && appMode !== 'stopped' && (appMode !== 'drawing' || uiVisibility.showDuringDraw)}
  <footer class:inactive={!uiVisibility.mouseActive} class="bottom-bar">
    <div class="bottom-actions">
      <button 
        class="draw-toggle-btn"
        onclick={enterDrawingMode}
        disabled={!images || !images.images || images.images.length === 0}
        aria-label="Enter drawing mode"
        title="Enter drawing mode (Esc to exit)"
      >✎ Draw</button>
      <button 
        class="clear-draw-btn"
        onclick={clearDrawingCanvas}
        aria-label="Clear drawing"
        disabled={!images || !images.images || images.images.length === 0}
      >Clear</button>
    </div>
  </footer>
{:else if appMode === 'stopped'}
  <footer class="bottom-bar">
    <div class="bottom-actions">
      <button 
        class="toggle-drawings-btn"
        onclick={() => showDrawingsInGallery = !showDrawingsInGallery}
        aria-label={showDrawingsInGallery ? 'Hide drawings' : 'Show drawings'}
        title={showDrawingsInGallery ? 'Hide drawings' : 'Show drawings'}
      >
        {showDrawingsInGallery ? '👁️ Hide Drawings' : '👁️‍🗨️ Show Drawings'}
      </button>
    </div>
  </footer>
{/if}
