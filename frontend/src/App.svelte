<script>
  import { onMount } from 'svelte';
  import Login from './Login.svelte';
  import { isAuthenticated, authenticatedFetch, removeAuthToken } from './auth.js';

  let authenticated = false;
  let currentPath = '/';

  // Simple router
  function checkRoute() {
    currentPath = window.location.pathname;
    
    // If not authenticated and not on login page, redirect to login
    if (!isAuthenticated() && currentPath !== '/login') {
      window.history.pushState({}, '', '/login');
      currentPath = '/login';
      authenticated = false;
      return;
    }

    // If authenticated and on login page, redirect to home
    if (isAuthenticated() && currentPath === '/login') {
      window.history.pushState({}, '', '/');
      currentPath = '/';
      authenticated = true;
      return;
    }

    authenticated = isAuthenticated();
  }

  async function handleLogout() {
    removeAuthToken();
    window.history.pushState({}, '', '/login');
    checkRoute();
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
