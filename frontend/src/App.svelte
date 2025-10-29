<script>
  import { onMount } from 'svelte';

  let count = 0;

  async function fetchHealth() {
    try {
      const response = await fetch('/api/health');
      const data = await response.json();
      console.log('Health check:', data);
    } catch (error) {
      console.error('Error fetching health:', error);
    }
  }

  // Fetch health on mount
  onMount(() => {
    fetchHealth();
  });
</script>

<main>
  <h1>ViewMaster</h1>
  <div class="card">
    <button on:click={() => count++}>
      count is {count}
    </button>
  </div>
  <p class="read-the-docs">
    FastAPI + Svelte integration
  </p>
</main>

<style>
  :global(body) {
    margin: 0;
    display: flex;
    place-items: center;
    min-width: 320px;
    min-height: 100vh;
  }

  :global(#app) {
    max-width: 1280px;
    margin: 0 auto;
    padding: 2rem;
    text-align: center;
  }

  h1 {
    font-size: 3.2em;
    line-height: 1.1;
  }

  .card {
    padding: 2em;
  }

  button {
    border-radius: 8px;
    border: 1px solid transparent;
    padding: 0.6em 1.2em;
    font-size: 1em;
    font-weight: 500;
    font-family: inherit;
    background-color: #1a1a1a;
    color: white;
    cursor: pointer;
    transition: border-color 0.25s;
  }

  button:hover {
    border-color: #646cff;
  }

  button:focus,
  button:focus-visible {
    outline: 4px auto -webkit-focus-ring-color;
  }

  .read-the-docs {
    color: #888;
  }
</style>

