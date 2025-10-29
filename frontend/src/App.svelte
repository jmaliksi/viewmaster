<script>
  import { onMount } from 'svelte';
  import Login from './Login.svelte';
  import { isAuthenticated, authenticatedFetch, clearAuthCache } from './auth.js';

  let authenticated = false;
  let currentPath = '/';
  let checkingAuth = true;

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
      return;
    }

    authenticated = authStatus;
    checkingAuth = false;
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
    
    // Clear auth cache
    clearAuthCache();
    authenticated = false;
    
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
      <button class="logout-btn" on:click={handleLogout}>Logout</button>
    </header>
    <div class="content">
      <p class="read-the-docs">
        FastAPI + Svelte integration
      </p>
      <p>You are authenticated and can access protected endpoints.</p>
    </div>
  </main>
{/if}
