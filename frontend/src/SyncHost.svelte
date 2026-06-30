<script>
  import { syncState, connect, registerHost, disconnect } from './sync.svelte.js'

  let active = $state(false)

  function toggle() {
    if (active) {
      active = false
      disconnect()
    } else {
      active = true
      registerHost()
    }
  }

  function stop() {
    active = false
    disconnect()
  }

  $effect(() => {
    if (!active && syncState.role === 'host') {
      active = true
    }
  })
</script>

{#if active}
  <div class="sync-host-widget">
    <span class="sync-host-dot">●</span>
    <span class="sync-host-label">Sync</span>
    {#if syncState.connectedClients > 0}
      <span class="sync-host-count">{syncState.connectedClients} client{syncState.connectedClients !== 1 ? 's' : ''}</span>
    {/if}
    <button class="sync-host-stop" onclick={stop} title="Stop sync">⏹</button>
  </div>
{:else}
  <button class="sync-host-start" onclick={toggle} title="Host a sync session">
    Sync
  </button>
{/if}

<style>
  .sync-host-widget {
    display: inline-flex;
    align-items: center;
    gap: 0.5em;
    background: #1e3a1e;
    border: 1px solid rgba(255, 255, 255, 0.3);
    border-radius: var(--border-radius);
    padding: var(--spacing-sm) 0.9em;
    font-size: 0.9em;
    font-weight: 500;
    font-family: inherit;
    color: white;
  }
  .sync-host-dot {
    color: #4caf50;
    font-size: 0.7em;
  }
  .sync-host-label {
  }
  .sync-host-count {
    font-size: 0.8em;
    color: #aed9ae;
  }
  .sync-host-stop {
    background: none;
    border: none;
    color: #ccc;
    cursor: pointer;
    padding: 0;
    font-size: 0.9em;
    line-height: 1;
    transition: color 0.2s;
  }
  .sync-host-stop:hover {
    color: #fff;
  }
  .sync-host-start {
    border-radius: var(--border-radius);
    border: 1px solid rgba(255, 255, 255, 0.3);
    padding: var(--spacing-sm) 1.2em;
    font-size: 0.9em;
    font-weight: 500;
    font-family: inherit;
    background-color: transparent;
    color: white;
    cursor: pointer;
    transition: background-color 0.25s, border-color 0.25s;
  }
  .sync-host-start:hover {
    background-color: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.5);
  }
</style>
