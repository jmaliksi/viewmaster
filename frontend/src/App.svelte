<script>
  import { onMount } from 'svelte';
  import Login from './Login.svelte';
  import { isAuthenticated, authenticatedFetch, clearAuthCache } from './auth.js';

  const IMAGES_STORAGE_KEY = 'viewmaster_images';
  const MAX_HISTORY_SIZE = 50;

  let authenticated = $state(false);
  let currentPath = $state('/');
  let checkingAuth = $state(true);
  let images = $state(null);
  let currentImage = $state(null);
  let loadingImages = $state(false);
  let imageError = $state(null);
  let imageHistory = $state([]);
  let historyIndex = $state(-1);

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
    // If we're not at the end of history, go forward
    if (historyIndex < imageHistory.length - 1) {
      historyIndex++;
      currentImage = imageHistory[historyIndex];
    } else {
      // Otherwise, pick a new random image
      pickRandomImage();
    }
  }

  function goToPreviousImage() {
    if (historyIndex > 0) {
      historyIndex--;
      currentImage = imageHistory[historyIndex];
    }
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

  // Check route on mount and when path changes
  onMount(() => {
    checkRoute();
    
    // Listen for popstate events (back/forward navigation)
    window.addEventListener('popstate', checkRoute);

    return () => {
      window.removeEventListener('popstate', checkRoute);
    };
  });
</script>

{#if !authenticated || currentPath === '/login'}
  <Login />
{:else}
  <main>
    <header>
      <h1>ViewMaster</h1>
      <div class="header-actions">
        <button 
          class="prev-btn" 
          onclick={goToPreviousImage}
          disabled={historyIndex <= 0}
        >
          Prev
        </button>
        <button 
          class="next-btn" 
          onclick={goToNextImage}
          disabled={!images || !images.images || images.images.length === 0}
        >
          Next
        </button>
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
          <img 
            src={currentImage.url} 
            alt={currentImage.filename}
            class="display-image"
          />
        </div>
      {:else if images && images.images && images.images.length === 0}
        <p>No images available.</p>
      {:else}
        <p>Loading...</p>
      {/if}
    </div>
  </main>
{/if}
