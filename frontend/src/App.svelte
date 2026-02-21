<script>
  import { onMount } from 'svelte';
  import Login from './Login.svelte';
  import { isAuthenticated, authenticatedFetch, clearAuthCache } from './auth.js';
  import { fabric } from 'fabric';
  import Masonry from 'svelte-bricks';

  const SETTINGS_STORAGE_KEY = 'viewmaster_settings';
  const MAX_HISTORY_SIZE = 50;
  const MOUSE_INACTIVITY_TIMEOUT = 2000; // 2 seconds

  /**
   * Shuffles an array in-place using the Fisher-Yates algorithm.
   * @param {Array} array The array to shuffle.
   * @returns {Array} The shuffled array.
   */
  function shuffleArray(array) {
    let currentIndex = array.length, randomIndex;

    // While there remain elements to shuffle.
    while (currentIndex !== 0) {
      // Pick a remaining element.
      randomIndex = Math.floor(Math.random() * currentIndex);
      currentIndex--;

      // And swap it with the current element.
      [array[currentIndex], array[randomIndex]] = [array[randomIndex], array[currentIndex]];
    }

    return array;
  }

  function saveSettings() {
    const settings = {
      checkedFolders: Array.from(checkedFolders),
      checkedAspectRatios: Array.from(checkedAspectRatios),
      timerDuration: timer.duration,
      imageFitMode: imageFitMode,
      imageOpacity: imageOpacity,
      gallerySizePercent: gallerySizePercent
    };
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
  }

  function loadSettings() {
    try {
      const stored = localStorage.getItem(SETTINGS_STORAGE_KEY);
      if (!stored) return null;
      return JSON.parse(stored);
    } catch (e) {
      console.error('Error loading settings:', e);
      return null;
    }
  }

  // Main app mode state machine
  let appMode = $state('loading'); // 'login' | 'loading' | 'start' | 'viewing' | 'drawing' | 'stopped' | 'error'

  let currentPath = $state('/');
  let images = $state(null);
  let currentImage = $state(null);
  let imageError = $state(null);
  let imageHistory = $state([]);
  let historyIndex = $state(-1);
  let mouseTimeout = null;

  let imagePlaylist = $state([]);
  let playlistIndex = $state(0);
  let shuffledFolders = $state([]);

  // Folder filtering state
  let availableFolders = $state([]);
  let checkedFolders = $state(new Set());
  let folderDropdownOpen = $state(false);
  let folderThumbnails = $state(new Map());
  let folderFilterText = $state('');

  // Aspect ratio filtering state
  let availableAspectRatios = $state([]);
  let checkedAspectRatios = $state(new Set());
  let aspectRatioDropdownOpen = $state(false);

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

  // Computed: filtered images based on checked folders and aspect ratios
  // Only calculated once when user presses Start, not on every checkbox toggle
  let filteredImages = $state(null);

  // Computed: aspect ratio image counts from full image list
  let aspectRatioImageCounts = $derived.by(() => {
    if (!images || !images.aspect_ratios) return {};
    return images.aspect_ratios;
  });

  let filteredAvailableFolders = $derived.by(() => {
    if (!folderFilterText) return availableFolders;
    return availableFolders.filter(folder =>
      folder.toLowerCase().includes(folderFilterText.toLowerCase())
    );
  });

  // Drawing mode state
  const DRAW_COLOR = '#FF69B4';
  const DRAW_WIDTH = 1;
  let fabricCanvas = null;
  let drawingCanvasEl = null;
  let drawingOverlayEl = null;

  // Current image dimensions for drawing export
  let currentImageDimensions = $state({ width: 0, height: 0 });

  // Drawing storage: object of image URL -> { dataUrl, width, height }
  let imageDrawings = $state({});
  let showDrawingsInGallery = $state(true);

  // Gallery size control (percentage of smaller viewport dimension)
  let gallerySizePercent = $state(25); // Default 25%, min 15%

  // Window dimensions for reactive calculations
  let windowWidth = $state(typeof window !== 'undefined' ? window.innerWidth : 1200);
  let windowHeight = $state(typeof window !== 'undefined' ? window.innerHeight : 800);

  // Computed: min column width for masonry based on slider (100-500px range)
  let galleryMinColWidth = $derived(100 + Math.floor((gallerySizePercent - 15) * 400 / 85));

  // Image opacity control (0-100%)
  let imageOpacity = $state(100); // Default 100% opacity

  // Image fit mode: 'fit' = contain (fit inside), 'fill' = cover (fill viewport)
  let imageFitMode = $state('fit');

  let currentImageInfo = $derived.by(() => {
    if (!currentImage) return '';

    const path = currentImage.path || currentImage.relative_path || '';
    const filename = currentImage.filename;

    if (!path || !filename) {
        return filename || path || '';
    }

    const parts = path.split('/');
    if (parts.length > 1) {
      const parentDir = parts[parts.length - 2];
      if (parentDir) {
        return `${parentDir}/${filename}`;
      }
    }

    return filename;
  });

  function initFabricIfNeeded() {
    if (!drawingCanvasEl) return;
    if (!fabricCanvas) {
      fabricCanvas = new fabric.Canvas(drawingCanvasEl, {
        isDrawingMode: true,
        selection: false,
        allowTouchScrolling: false
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

  // Track two-finger tap for zone-based actions
  let twoFingerTouches = null;
  let twoFingerTapStart = 0;

  function handleDrawingTouchStart(e) {
    if (appMode !== 'drawing') return;
    
    // Single finger: hide UI
    if (e.touches && e.touches.length === 1) {
      uiVisibility.showDuringDraw = false;
      twoFingerTouches = null;
    }
    
    // Two-finger: track positions for zone detection
    if (e.touches && e.touches.length === 2) {
      twoFingerTouches = [
        { x: e.touches[0].clientX, y: e.touches[0].clientY },
        { x: e.touches[1].clientX, y: e.touches[1].clientY }
      ];
      twoFingerTapStart = Date.now();
    }
  }

  function handleDrawingTouchEnd(e) {
    if (appMode !== 'drawing') return;
    
    // Check for two-finger tap (quick tap with 2 fingers)
    if (twoFingerTouches && e.changedTouches && e.changedTouches.length === 2) {
      const tapDuration = Date.now() - twoFingerTapStart;
      
      // Quick tap (< 400ms) triggers zone action
      if (tapDuration < 400) {
        const width = window.innerWidth;
        const height = window.innerHeight;
        
        // Use midpoint of the two touches
        const midX = (twoFingerTouches[0].x + twoFingerTouches[1].x) / 2;
        const midY = (twoFingerTouches[0].y + twoFingerTouches[1].y) / 2;

        // Top 20% or Bottom 20% = exit draw mode
        if (midY < height * 0.2 || midY > height * 0.8) {
          exitDrawingMode();
          uiVisibility.showDuringDraw = false;
        }
        // Left 20% = previous image
        else if (midX < width * 0.2) {
          goToPreviousImage();
        }
        // Right 20% = next image
        else if (midX > width * 0.8) {
          goToNextImage();
        }
      }
      
      twoFingerTouches = null;
    }
  }

  function handleDrawingTouchMove(e) {
    if (appMode !== 'drawing') return;
    // Prevent pull-to-refresh / pull-to-exit-fullscreen on iOS
    // Only prevent default for single touch (drawing), allow two-finger gestures
    if (e.touches && e.touches.length === 1) {
      e.preventDefault();
    }
  }

  function handleDrawingPointerDown(e) {
    if (appMode !== 'drawing') return;
    // Any pen/mouse/touch press resumes drawing; hide UI
    // Using pointer events to avoid virtual keyboard warning on iOS
    if (e.pointerType === 'pen' || e.pointerType === 'mouse' || e.pointerType === 'touch') {
      uiVisibility.showDuringDraw = false;
    }
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
      delete imageDrawings[currentImage.url];
      return;
    }

    // Calculate how the image is displayed within the viewport (object-fit: contain)
    const viewportWidth = fabricCanvas.getWidth();
    const viewportHeight = fabricCanvas.getHeight();
    const imgWidth = currentImageDimensions.width;
    const imgHeight = currentImageDimensions.height;

    if (imgWidth === 0 || imgHeight === 0) {
      console.error('Cannot save drawing: image dimensions unknown');
      return;
    }

    // Scale up stroke widths for visibility at thumbnail sizes
    const STROKE_SCALE = 5;
    objects.forEach(obj => {
      if (obj.strokeWidth) {
        obj.set('strokeWidth', obj.strokeWidth * STROKE_SCALE);
      }
    });
    fabricCanvas.renderAll();

    // Calculate display dimensions maintaining aspect ratio (same as object-fit: contain)
    const viewportRatio = viewportWidth / viewportHeight;
    const imgRatio = imgWidth / imgHeight;

    let displayWidth, displayHeight, offsetX, offsetY;
    if (imgRatio > viewportRatio) {
      // Image is wider - constrained by width
      displayWidth = viewportWidth;
      displayHeight = viewportWidth / imgRatio;
      offsetX = 0;
      offsetY = (viewportHeight - displayHeight) / 2;
    } else {
      // Image is taller - constrained by height
      displayHeight = viewportHeight;
      displayWidth = viewportHeight * imgRatio;
      offsetX = (viewportWidth - displayWidth) / 2;
      offsetY = 0;
    }

    // Crop the drawing to the actual image dimensions
    try {
      const dataUrl = fabricCanvas.toDataURL('image/png', {
        left: offsetX,
        top: offsetY,
        width: displayWidth,
        height: displayHeight
      });
      imageDrawings[currentImage.url] = { 
        dataUrl, 
        width: imgWidth, 
        height: imgHeight,
        fitMode: imageFitMode
      };
      imageDrawings = imageDrawings; // trigger reactivity
    } catch (e) {
      console.error('Error saving drawing:', e);
    } finally {
      // Restore original stroke widths after saving
      objects.forEach(obj => {
        if (obj.strokeWidth) {
          obj.set('strokeWidth', obj.strokeWidth / STROKE_SCALE);
        }
      });
      fabricCanvas.renderAll();
    }
  }

  async function loadImageDimensions(url) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        currentImageDimensions = { width: img.naturalWidth, height: img.naturalHeight };
        resolve();
      };
      img.onerror = () => {
        currentImageDimensions = { width: 0, height: 0 };
        resolve();
      };
      img.src = url;
    });
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
      delete imageDrawings[currentImage.url];
      imageDrawings = imageDrawings; // trigger reactivity
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
    // Always fetch from API (no localStorage caching)
    imageError = null;

    try {
      const response = await fetch('/api/load', {
        credentials: 'include', // Include cookies for authentication
      });

      if (!response.ok) {
        throw new Error(`Failed to load images: ${response.statusText}`);
      }

      const data = await response.json();

      // Keep in memory only
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
      folderThumbnails = new Map();
      availableAspectRatios = [];
      checkedAspectRatios = new Set();
      return;
    }

    const folders = new Set();
    const thumbnails = new Map();
    const aspectRatios = new Set();

    images.images.forEach(img => {
      const pathParts = (img.path || img.relative_path || '').split('/');
      // If path has more than 1 part, it has a parent folder
      if (pathParts.length > 1) {
        const parentFolder = pathParts[pathParts.length - 2];
        folders.add(parentFolder);
        if (!thumbnails.has(parentFolder)) {
          thumbnails.set(parentFolder, img.url);
        }
      }

      // Extract aspect ratio
      const aspectRatio = img.aspect_ratio || 'unknown';
      aspectRatios.add(aspectRatio);
    });

    availableFolders = Array.from(folders).sort();
    folderThumbnails = thumbnails;

    // Initialize all folders as checked
    checkedFolders = new Set(availableFolders);

    // Extract available aspect ratios from the data
    availableAspectRatios = Array.from(aspectRatios).sort();
    checkedAspectRatios = new Set(availableAspectRatios);

    // Load and apply saved settings
    const saved = loadSettings();
    if (saved) {
      // Apply saved folders that still exist
      if (saved.checkedFolders && Array.isArray(saved.checkedFolders)) {
        const validSavedFolders = saved.checkedFolders.filter(f => availableFolders.includes(f));
        if (validSavedFolders.length > 0) {
          checkedFolders = new Set(validSavedFolders);
        }
      }
      // Apply saved aspect ratios that still exist
      if (saved.checkedAspectRatios && Array.isArray(saved.checkedAspectRatios)) {
        const validSavedRatios = saved.checkedAspectRatios.filter(r => availableAspectRatios.includes(r));
        if (validSavedRatios.length > 0) {
          checkedAspectRatios = new Set(validSavedRatios);
        }
      }
      if (saved.timerDuration && saved.timerDuration > 0) {
        timer.duration = saved.timerDuration;
        timer.remaining = saved.timerDuration;
        timer.inputValue = saved.timerDuration.toString();
      }
      if (saved.imageFitMode) {
        imageFitMode = saved.imageFitMode;
      }
      if (saved.imageOpacity !== undefined) {
        imageOpacity = saved.imageOpacity;
      }
      if (saved.gallerySizePercent !== undefined) {
        gallerySizePercent = saved.gallerySizePercent;
      }
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
  }

  function toggleAllFolders() {
    // These are the folders currently visible in the dropdown
    const visibleFolders = filteredAvailableFolders;

    // Are all visible folders already checked?
    const allVisibleChecked = visibleFolders.length > 0 && visibleFolders.every(f => checkedFolders.has(f));

    const newChecked = new Set(checkedFolders);
    if (allVisibleChecked) {
      // If all are checked, uncheck them
      visibleFolders.forEach(folder => newChecked.delete(folder));
    } else {
      // Otherwise, check all of them
      visibleFolders.forEach(folder => newChecked.add(folder));
    }
    checkedFolders = newChecked;
  }

  function toggleAspectRatio(ratio) {
    const newChecked = new Set(checkedAspectRatios);
    if (newChecked.has(ratio)) {
      newChecked.delete(ratio);
    } else {
      newChecked.add(ratio);
    }
    checkedAspectRatios = newChecked;
  }

  function toggleAllAspectRatios() {
    const visibleRatios = availableAspectRatios;

    const allVisibleChecked = visibleRatios.length > 0 && visibleRatios.every(r => checkedAspectRatios.has(r));

    const newChecked = new Set(checkedAspectRatios);
    if (allVisibleChecked) {
      visibleRatios.forEach(ratio => newChecked.delete(ratio));
    } else {
      visibleRatios.forEach(ratio => newChecked.add(ratio));
    }
    checkedAspectRatios = newChecked;
  }

  function getAspectRatioIcon(ratio) {
    const icons = {
      '1:1': { w: 16, h: 16 },
      '4:3': { w: 16, h: 12 },
      '3:2': { w: 16, h: 10.67 },
      '16:9': { w: 16, h: 9 },
      '2:3': { w: 10.67, h: 16 },
      '9:16': { w: 9, h: 16 },
      'unknown': { w: 16, h: 16 },
    };
    return icons[ratio] || icons['unknown'];
  }

  function getFirstImageForFolder(folderName) {
    return folderThumbnails.get(folderName) || null;
  }

  function getAlbumFromImage(image) {
    if (!image) return null;
    const path = image.path || image.relative_path || '';
    const pathParts = path.split('/');
    // An image in the root has one path part (its name), or zero if path is empty.
    // A path like 'album/image.jpg' has two parts.
    if (pathParts.length <= 1) {
      return '__root__'; // Special identifier for root-level images
    }
    return pathParts[pathParts.length - 2];
  }

  function initializeImagePlaylist() {
    // Filter images based on current checked folders and aspect ratios
    // This only runs once when user presses Start, not on every checkbox toggle
    const filtered = images.images.filter(img => {
      // Always include root images (no parent folder)
      const pathParts = (img.path || img.relative_path || '').split('/');
      if (pathParts.length <= 1) {
        return true;
      }

      // Get immediate parent folder
      const parentFolder = pathParts[pathParts.length - 2];
      if (!checkedFolders.has(parentFolder)) return false;

      // Aspect ratio filter
      const aspectRatio = img.aspect_ratio || 'unknown';
      if (!checkedAspectRatios.has(aspectRatio)) return false;

      return true;
    });

    shuffledFolders = [];
    if (!filtered || filtered.length === 0) {
      imagePlaylist = [];
      playlistIndex = 0;
      return;
    }

    if (shuffledFolders.length === 0) {
      const folders = new Set(filtered.map(getAlbumFromImage));
      shuffledFolders = shuffleArray(Array.from(folders));
    }

    const imagesByFolder = shuffledFolders.map(folder => {
      const imagesInFolder = filtered.filter(img => getAlbumFromImage(img) === folder);
      return shuffleArray(imagesInFolder); // Shuffle images within the folder
    });

    let finalPlaylist = [];
    let maxLength = 0;
    imagesByFolder.forEach(group => {
      if (group.length > maxLength) {
        maxLength = group.length;
      }
    });

    for (let i = 0; i < maxLength; i++) {
      for (const group of imagesByFolder) {
        if (group[i]) {
          finalPlaylist.push(group[i]);
        }
      }
    }

    imagePlaylist = finalPlaylist;
    playlistIndex = 0;
  }

  function getNextImageFromPlaylist() {
    if (playlistIndex >= imagePlaylist.length) {
      shuffledFolders = [];
      initializeImagePlaylist();

      if (imagePlaylist.length === 0) return null; // No images found even after reset
    }

    const newImage = imagePlaylist[playlistIndex];
    playlistIndex++;
    return newImage;
  }

  function pickRandomImage() {
    const newImage = getNextImageFromPlaylist();
    if (!newImage) {
      currentImage = null;
      return;
    }

    imageHistory = [...imageHistory, newImage];
    historyIndex = imageHistory.length - 1;

    if (imageHistory.length > MAX_HISTORY_SIZE) {
      imageHistory = imageHistory.slice(-MAX_HISTORY_SIZE);
      historyIndex = imageHistory.length - 1;
    }

    currentImage = newImage;
    preloadNextImages();
  }

  function preloadNextImages(count = 2) {
    if (!imagePlaylist || imagePlaylist.length === 0) return;

    for (let i = 0; i < count; i++) {
      const nextPlaylistIndex = playlistIndex + i;
      if (nextPlaylistIndex < imagePlaylist.length) {
        preloadImage(imagePlaylist[nextPlaylistIndex].url);
      }
    }
  }

  function goToNextImage() {
    if (appMode === 'start') {
      appMode = 'viewing';
      initializeImagePlaylist();
      timer.playing = true;
      startTimer();
    }
    if (fabricCanvas && currentImage) {
      saveCurrentDrawing();
    }
    if (fabricCanvas) {
      fabricCanvas.clear();
      if (fabricCanvas.isDrawingMode) {
        if (fabricCanvas.freeDrawingBrush) {
          fabricCanvas.freeDrawingBrush.color = DRAW_COLOR;
          fabricCanvas.freeDrawingBrush.width = DRAW_WIDTH;
        }
      }
    }
    if (historyIndex < imageHistory.length - 1) {
      historyIndex++;
      currentImage = imageHistory[historyIndex];
    } else {
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

  function openFromGallery(image) {
    const imageFromList = images?.images?.find(img => img.url === image.url) || image;
    const historyPosition = imageHistory.findIndex(img => img.url === imageFromList.url);
    
    if (historyPosition !== -1) {
      imagePlaylist = [...imageHistory];
      playlistIndex = historyPosition;
      historyIndex = historyPosition;
    }
    currentImage = imageFromList;
    appMode = 'viewing';
    timer.playing = false;
    stopTimer();
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
    localStorage.removeItem(SETTINGS_STORAGE_KEY);
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
    imagePlaylist = [];
    playlistIndex = 0;
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
    if (appMode === 'drawing') return;
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

    // Track window resize
    const handleResize = () => {
      windowWidth = window.innerWidth;
      windowHeight = window.innerHeight;
    };
    window.addEventListener('resize', handleResize);

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
      window.removeEventListener('resize', handleResize);
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

  // Load image dimensions when current image changes
  $effect(() => {
    if (currentImage?.url) {
      loadImageDimensions(currentImage.url);
    }
  });

  // Auto-save settings when any of these change
  $effect(() => {
    // Track these specific values
    const _folders = Array.from(checkedFolders);
    const _ratios = Array.from(checkedAspectRatios);
    const _timer = timer.duration;
    const _fit = imageFitMode;
    const _opacity = imageOpacity;
    const _gallery = gallerySizePercent;

    // Only save after initial load
    if (availableFolders.length > 0 || availableAspectRatios.length > 0) {
      saveSettings();
    }
  });

  // Set up native touch/pointer event listeners on drawing overlay
  // Using { passive: false } to allow preventDefault() to block pull-to-refresh
  $effect(() => {
    if (!drawingOverlayEl) return;

    drawingOverlayEl.addEventListener('touchstart', handleDrawingTouchStart, { passive: false });
    drawingOverlayEl.addEventListener('touchmove', handleDrawingTouchMove, { passive: false });
    drawingOverlayEl.addEventListener('touchend', handleDrawingTouchEnd, { passive: false });
    drawingOverlayEl.addEventListener('pointerdown', handleDrawingPointerDown);

    return () => {
      drawingOverlayEl.removeEventListener('touchstart', handleDrawingTouchStart);
      drawingOverlayEl.removeEventListener('touchmove', handleDrawingTouchMove);
      drawingOverlayEl.removeEventListener('touchend', handleDrawingTouchEnd);
      drawingOverlayEl.removeEventListener('pointerdown', handleDrawingPointerDown);
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
                inputmode="numeric"
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
          <button
            class="fit-mode-btn"
            onclick={() => imageFitMode = imageFitMode === 'fit' ? 'fill' : 'fit'}
            aria-label={imageFitMode === 'fit' ? 'Fill viewport' : 'Fit in viewport'}
            title={imageFitMode === 'fit' ? 'Fill viewport' : 'Fit in viewport'}
          >
            {imageFitMode === 'fit' ? '⊡' : '⊞'}
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
            <button class="start-btn" onclick={goToNextImage}>
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
                    <input
                      type="text"
                      placeholder="Filter by name..."
                      bind:value={folderFilterText}
                      class="folder-filter-input"
                      onclick={(e) => e.stopPropagation()}
                    />
                    <label class="folder-checkbox-item folder-checkbox-select-all">
                      <input
                        type="checkbox"
                        checked={
                          filteredAvailableFolders.length > 0 &&
                          filteredAvailableFolders.every(f => checkedFolders.has(f))
                        }
                        indeterminate={
                          filteredAvailableFolders.some(f => checkedFolders.has(f)) &&
                          !filteredAvailableFolders.every(f => checkedFolders.has(f))
                        }
                        onchange={toggleAllFolders}
                      />
                      <span>Select All (filtered)</span>
                    </label>
                    {#each filteredAvailableFolders as folder}
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
            {#if availableAspectRatios.length > 0}
              <div class="folder-filter">
                <button
                  class="folder-filter-toggle"
                  onclick={() => aspectRatioDropdownOpen = !aspectRatioDropdownOpen}
                  aria-label="Toggle aspect ratio filter"
                  aria-expanded={aspectRatioDropdownOpen}
                >
                  <span>Filter Aspect Ratios</span>
                  <span class="folder-filter-icon">{aspectRatioDropdownOpen ? '▼' : '▶'}</span>
                </button>
                {#if aspectRatioDropdownOpen}
                  <div class="folder-checkboxes">
                    <label class="folder-checkbox-item folder-checkbox-select-all">
                      <input
                        type="checkbox"
                        checked={
                          availableAspectRatios.length > 0 &&
                          availableAspectRatios.every(r => checkedAspectRatios.has(r))
                        }
                        indeterminate={
                          availableAspectRatios.some(r => checkedAspectRatios.has(r)) &&
                          !availableAspectRatios.every(r => checkedAspectRatios.has(r))
                        }
                        onchange={toggleAllAspectRatios}
                      />
                      <span>Select All</span>
                    </label>
                    {#each availableAspectRatios as ratio}
                      {@const icon = getAspectRatioIcon(ratio)}
                      {@const count = aspectRatioImageCounts[ratio] || 0}
                      <label class="folder-checkbox-item">
                        <svg width="24" height="24" viewBox="0 0 24 24" style="margin-right: 8px; flex-shrink: 0;">
                          <rect
                            x={(24 - icon.w) / 2}
                            y={(24 - icon.h) / 2}
                            width={icon.w}
                            height={icon.h}
                            fill="none"
                            stroke="#888"
                            stroke-width="1.5"
                          />
                        </svg>
                        <input
                          type="checkbox"
                          checked={checkedAspectRatios.has(ratio)}
                          onchange={() => toggleAspectRatio(ratio)}
                        />
                        <span>{ratio} ({count})</span>
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
          <Masonry 
            items={imageHistory} 
            idKey="url"
            minColWidth={galleryMinColWidth}
            gap={16}
          >
            {#snippet children({ item })}
              <div 
                class="gallery-item" 
                onclick={() => openFromGallery(item)}
                onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') openFromGallery(item); }}
                role="button"
                tabindex="0"
              >
                <img
                  src={item.url}
                  alt={item.filename}
                  class="gallery-thumbnail"
                  loading="lazy"
                  style="opacity: {imageOpacity / 100};"
                />
                {#if imageDrawings[item.url] && showDrawingsInGallery}
                  {@const drawing = imageDrawings[item.url]}
                  <img
                    src={drawing.dataUrl}
                    alt="Drawing overlay"
                    class="gallery-drawing-overlay"
                    style="object-fit: {drawing.fitMode === 'fill' ? 'contain' : 'cover'};"
                  />
                {/if}
              </div>
            {/snippet}
          </Masonry>
        </div>
      {:else if (appMode === 'viewing' || appMode === 'drawing') && currentImage}
        <figure class="image-container">
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
            class:fill-mode={imageFitMode === 'fill'}
            style="opacity: {imageOpacity / 100}; object-fit: {imageFitMode === 'fill' ? 'cover' : 'contain'};"
          />
          {#if imageDrawings[currentImage.url]}
            {@const drawing = imageDrawings[currentImage.url]}
            <img
              src={drawing.dataUrl}
              alt="Drawing overlay"
              class="drawing-view-overlay"
              style="object-fit: {drawing.fitMode === 'fill' ? 'cover' : 'contain'};"
            />
          {/if}
          <button
            class="arrow-btn right-arrow"
            class:inactive={!uiVisibility.mouseActive || (appMode === 'drawing' && !uiVisibility.showDuringDraw)}
            onclick={goToNextSequential}
            disabled={!images || !images.images || images.images.length === 0}
            aria-label="Next image"
          >
            →
          </button>
        </figure>
      {:else if images && images.images && images.images.length === 0}
        <p>No images available.</p>
      {:else}
        <p>Loading...</p>
      {/if}
    </div>
  </main>
{/if}
<!-- Drawing overlay covers entire viewport; only active during drawing mode -->
<div bind:this={drawingOverlayEl} class="drawing-overlay" class:active={appMode === 'drawing'} role="presentation" aria-hidden="true" onmousemove={resetMouseTimeout} onmouseenter={resetMouseTimeout}>
  <canvas bind:this={drawingCanvasEl} id="drawing-canvas"></canvas>
  <!-- no controls while drawing; exit with Escape -->
  <!-- native touch/pointer event listeners added via $effect -->
</div>

{#if appMode !== 'login' && currentPath !== '/login' && appMode !== 'stopped' && (appMode !== 'drawing' || uiVisibility.showDuringDraw)}
  <footer class:inactive={!uiVisibility.mouseActive} class="bottom-bar">
    <div class="bottom-actions" style="display: flex; width: 100%; align-items: center;">
      <div class="image-info" style="margin-right: auto; padding-left: 1rem; font-family: monospace; color: #ccc; word-break: break-all;">
        {currentImageInfo}
      </div>
      <label class="opacity-slider-label">
        <span>Opacity:</span>
        <input
          type="range"
          class="opacity-slider"
          min="0"
          max="100"
          value={imageOpacity}
          oninput={(e) => imageOpacity = parseInt(e.target.value, 10)}
          aria-label="Image opacity"
        />
        <span class="opacity-percent">{imageOpacity}%</span>
      </label>
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
      <label class="opacity-slider-label">
        <span>Opacity:</span>
        <input
          type="range"
          class="opacity-slider"
          min="0"
          max="100"
          value={imageOpacity}
          oninput={(e) => imageOpacity = parseInt(e.target.value, 10)}
          aria-label="Image opacity"
        />
        <span class="opacity-percent">{imageOpacity}%</span>
      </label>
      <label class="gallery-size-slider-label">
        <span>Size:</span>
        <input
          type="range"
          class="gallery-size-slider"
          min="15"
          max="100"
          value={gallerySizePercent}
          oninput={(e) => gallerySizePercent = parseInt(e.target.value, 10)}
          aria-label="Gallery image size"
        />
        <span class="gallery-size-percent">{gallerySizePercent}%</span>
      </label>
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

<style>
  :global(html), :global(body) {
    overscroll-behavior-y: none;
  }

  .image-container {
    display: flex;
    justify-content: center;
    align-items: center;
    width: 100%;
    height: 100%;
    margin: 0; /* for figure */
    position: relative;
  }

  .display-image {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }

  .drawing-view-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }

  .gallery-item {
    position: relative;
  }

  .gallery-drawing-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }

  .folder-filter-input {
    width: calc(100% - 20px);
    padding: 8px;
    margin: 5px 10px;
    border: 1px solid #444;
    border-radius: 4px;
    background-color: #222;
    color: #eee;
    box-sizing: border-box;
  }

  .folder-filter-input:focus {
    outline: none;
    border-color: #666;
  }
</style>
