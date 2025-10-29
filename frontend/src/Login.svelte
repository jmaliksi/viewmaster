<script>
  import { onMount } from 'svelte';
  import { clearAuthCache } from './auth.js';
  
  let username = '';
  let password = '';
  let error = '';
  let loading = false;

  // Add login-page class to body for styling
  onMount(() => {
    document.body.classList.add('login-page');
    
    return () => {
      document.body.classList.remove('login-page');
    };
  });

  async function handleLogin() {
    error = '';
    loading = true;

    try {
      const response = await fetch('/api/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include', // Include cookies in request (important!)
        body: JSON.stringify({ username, password }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Login failed');
      }

      const data = await response.json();
      
      // Token is now set as an HTTP-only cookie by the backend
      // No need to manually store it in localStorage
      // Clear any cached auth status to force re-check
      clearAuthCache();
      
      // Use pushState instead of location.href to avoid full page reload
      window.history.pushState({}, '', '/');
      // Trigger popstate to notify App.svelte of route change
      window.dispatchEvent(new PopStateEvent('popstate'));
    } catch (err) {
      error = err.message || 'Login failed. Please check your credentials.';
    } finally {
      loading = false;
    }
  }

  function handleKeyPress(event) {
    if (event.key === 'Enter') {
      handleLogin();
    }
  }
</script>

<div class="login-container">
  <div class="login-card">
    <h1>ViewMaster</h1>
    <h2>Login</h2>
    
    {#if error}
      <div class="error-message">{error}</div>
    {/if}

    <form on:submit|preventDefault={handleLogin}>
      <div class="form-group">
        <label for="username">Username</label>
        <input
          id="username"
          type="text"
          bind:value={username}
          on:keypress={handleKeyPress}
          disabled={loading}
          required
          autocomplete="username"
        />
      </div>

      <div class="form-group">
        <label for="password">Password</label>
        <input
          id="password"
          type="password"
          bind:value={password}
          on:keypress={handleKeyPress}
          disabled={loading}
          required
          autocomplete="current-password"
        />
      </div>

      <button type="submit" disabled={loading || !username || !password}>
        {loading ? 'Logging in...' : 'Login'}
      </button>
    </form>
  </div>
</div>

