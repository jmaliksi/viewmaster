<script>
  import { onMount } from 'svelte'
  import { fabric } from 'fabric'
  import { syncState, connect, attachClient, disconnect } from './sync.svelte.js'

  const DRAW_COLOR = '#FF69B4'
  const DRAW_WIDTH = 1
  const CACHE_BUST_VERSION = '1'

  let appMode = $state('connecting')
  let myImage = $state(null)
  let imageOpacity = $state(100)
  let imageFitMode = $state('fit')
  let prevImageUrl = $state(null)
  let currentImageDimensions = $state({ width: 0, height: 0 })
  let imageDrawings = $state({})
  let isDrawing = $state(false)
  let userDisconnected = $state(false)

  let fabricCanvas = null
  let drawingCanvasEl = null
  let drawingOverlayEl = null
  let uiVisible = $state(true)
  let mouseTimeout = null

  function cacheBust(url) {
    if (!url) return url
    const separator = url.includes('?') ? '&' : '?'
    return `${url}${separator}cb=${CACHE_BUST_VERSION}`
  }

  function loadImageDimensions(url) {
    return new Promise((resolve) => {
      const img = new Image()
      img.onload = () => {
        currentImageDimensions = { width: img.naturalWidth, height: img.naturalHeight }
        resolve()
      }
      img.onerror = () => {
        currentImageDimensions = { width: 0, height: 0 }
        resolve()
      }
      img.src = cacheBust(url)
    })
  }

  function initFabricIfNeeded() {
    if (!drawingCanvasEl) return
    if (!fabricCanvas) {
      fabricCanvas = new fabric.Canvas(drawingCanvasEl, {
        isDrawingMode: true,
        selection: false,
        allowTouchScrolling: false,
      })
    }
    fabricCanvas.isDrawingMode = true
    if (fabricCanvas.freeDrawingBrush) {
      fabricCanvas.freeDrawingBrush.color = DRAW_COLOR
      fabricCanvas.freeDrawingBrush.width = DRAW_WIDTH
    }
    fabricCanvas.setWidth(window.innerWidth)
    fabricCanvas.setHeight(window.innerHeight)
    fabricCanvas.renderAll()
  }

  function enterDrawingMode() {
    isDrawing = true
    queueMicrotask(() => initFabricIfNeeded())
  }

  function saveCurrentDrawing() {
    if (!fabricCanvas || !myImage) return
    const objects = fabricCanvas.getObjects()
    if (objects.length === 0) {
      delete imageDrawings[myImage.url]
      imageDrawings = imageDrawings
      return
    }
    const viewportWidth = fabricCanvas.getWidth()
    const viewportHeight = fabricCanvas.getHeight()
    const imgWidth = currentImageDimensions.width
    const imgHeight = currentImageDimensions.height
    if (imgWidth === 0 || imgHeight === 0) return
    const STROKE_SCALE = 5
    objects.forEach(obj => {
      if (obj.strokeWidth) obj.set('strokeWidth', obj.strokeWidth * STROKE_SCALE)
    })
    fabricCanvas.renderAll()
    const viewportRatio = viewportWidth / viewportHeight
    const imgRatio = imgWidth / imgHeight
    let displayWidth, displayHeight, offsetX, offsetY
    if (imgRatio > viewportRatio) {
      displayWidth = viewportWidth
      displayHeight = viewportWidth / imgRatio
      offsetX = 0
      offsetY = (viewportHeight - displayHeight) / 2
    } else {
      displayHeight = viewportHeight
      displayWidth = viewportHeight * imgRatio
      offsetX = (viewportWidth - displayWidth) / 2
      offsetY = 0
    }
    try {
      const dataUrl = fabricCanvas.toDataURL('image/png', {
        left: offsetX,
        top: offsetY,
        width: displayWidth,
        height: displayHeight,
      })
      imageDrawings[myImage.url] = { dataUrl, width: imgWidth, height: imgHeight, fitMode: imageFitMode }
      imageDrawings = imageDrawings
    } catch (e) {
      console.error('Error saving drawing:', e)
    } finally {
      objects.forEach(obj => {
        if (obj.strokeWidth) obj.set('strokeWidth', obj.strokeWidth / STROKE_SCALE)
      })
      fabricCanvas.renderAll()
    }
  }

  function exitDrawingMode() {
    saveCurrentDrawing()
    isDrawing = false
    if (fabricCanvas) fabricCanvas.isDrawingMode = false
  }

  function clearDrawingCanvas() {
    if (fabricCanvas) {
      fabricCanvas.clear()
      fabricCanvas.isDrawingMode = true
      if (fabricCanvas.freeDrawingBrush) {
        fabricCanvas.freeDrawingBrush.color = DRAW_COLOR
        fabricCanvas.freeDrawingBrush.width = DRAW_WIDTH
      }
      fabricCanvas.renderAll()
    }
    if (myImage) {
      delete imageDrawings[myImage.url]
      imageDrawings = imageDrawings
    }
  }

  function resetMouse() {
    uiVisible = true
    clearTimeout(mouseTimeout)
    mouseTimeout = setTimeout(() => { uiVisible = false }, 2000)
  }

  function handleDisconnect() {
    exitDrawingMode()
    disconnect()
    userDisconnected = true
    myImage = null
    prevImageUrl = null
    isDrawing = false
    if (fabricCanvas) { fabricCanvas.clear(); fabricCanvas = null }
  }

  function handleReconnect() {
    userDisconnected = false
    connect()
    attachClient()
  }

  $effect(() => {
    const newImg = syncState.currentImage
    if (!newImg) return
    if (prevImageUrl && prevImageUrl !== newImg.url) {
      saveCurrentDrawing()
      if (fabricCanvas) {
        fabricCanvas.clear()
        if (fabricCanvas.isDrawingMode && fabricCanvas.freeDrawingBrush) {
          fabricCanvas.freeDrawingBrush.color = DRAW_COLOR
          fabricCanvas.freeDrawingBrush.width = DRAW_WIDTH
        }
        fabricCanvas.renderAll()
      }
    }
    prevImageUrl = newImg.url
    myImage = newImg
    isDrawing = false
    loadImageDimensions(newImg.url)
  })

  $effect(() => {
    if (userDisconnected) { appMode = 'disconnected'; return }
    const state = syncState.wsState
    const waiting = syncState.waitingForHost
    const active = syncState.sessionActive
    const ended = syncState.sessionEnded
    if (ended) { appMode = 'ended'; return }
    if (state === 'connecting') { appMode = 'connecting'; return }
    if (state === 'connected' && waiting) { appMode = 'waiting'; return }
    if (state === 'connected' && active) { appMode = 'connected'; return }
    appMode = 'connecting'
  })

  function handleDrawingTouchStart(e) {
    if (!isDrawing) return
    if (e.touches && e.touches.length === 1) uiVisible = false
  }
  function handleDrawingTouchMove(e) {
    if (!isDrawing) return
    if (e.touches && e.touches.length === 1) e.preventDefault()
  }
  function handleDrawingTouchEnd(e) {
    if (!isDrawing) return
    if (e.touches && e.touches.length === 2) {
      const midY = (e.changedTouches[0].clientY + e.changedTouches[1].clientY) / 2
      const height = window.innerHeight
      if (midY < height * 0.2 || midY > height * 0.8) exitDrawingMode()
    }
  }
  function handleDrawingPointerDown(e) {
    if (!isDrawing) return
    if (e.pointerType === 'pen' || e.pointerType === 'mouse' || e.pointerType === 'touch') uiVisible = false
  }

  onMount(() => {
    attachClient()
    return () => { clearTimeout(mouseTimeout); handleDisconnect() }
  })

  $effect(() => {
    if (!drawingOverlayEl) return
    drawingOverlayEl.addEventListener('touchstart', handleDrawingTouchStart, { passive: false })
    drawingOverlayEl.addEventListener('touchmove', handleDrawingTouchMove, { passive: false })
    drawingOverlayEl.addEventListener('touchend', handleDrawingTouchEnd, { passive: false })
    drawingOverlayEl.addEventListener('pointerdown', handleDrawingPointerDown)
    return () => {
      drawingOverlayEl.removeEventListener('touchstart', handleDrawingTouchStart)
      drawingOverlayEl.removeEventListener('touchmove', handleDrawingTouchMove)
      drawingOverlayEl.removeEventListener('touchend', handleDrawingTouchEnd)
      drawingOverlayEl.removeEventListener('pointerdown', handleDrawingPointerDown)
    }
  })
</script>

{#if appMode === 'connecting'}
  <div class="sync-status">
    <p>Connecting to host session...</p>
  </div>
{:else if appMode === 'waiting'}
  <div class="sync-status">
    <p>Connected. Waiting for host to start a sync session...</p>
    <button class="disconnect-btn" onclick={handleDisconnect}>Disconnect</button>
  </div>
{:else if appMode === 'ended'}
  <div class="sync-status">
    <p>Session ended. The host has disconnected.</p>
    <button class="disconnect-btn" onclick={handleDisconnect}>Disconnect</button>
  </div>
{:else if appMode === 'disconnected'}
  <div class="sync-status">
    <p>Disconnected from sync session.</p>
    <button class="reconnect-btn" onclick={handleReconnect}>Reconnect</button>
  </div>
{:else if appMode === 'connected' && myImage}
  <div class="sync-client-layout">
    <header class="sync-header" class:hidden={!uiVisible && isDrawing}>
      <span class="sync-indicator">Connected</span>
      <span class="sync-image-info">{myImage.filename}</span>
      <button class="disconnect-btn" onclick={handleDisconnect}>Disconnect</button>
    </header>
    <div class="sync-content">
      <figure class="image-container">
        <img
          src={cacheBust(myImage.url)}
          alt={myImage.filename}
          class="display-image"
          style="opacity: {imageOpacity / 100}; object-fit: {imageFitMode === 'fill' ? 'cover' : 'contain'};"
        />
        {#if imageDrawings[myImage.url]}
          <img
            src={imageDrawings[myImage.url].dataUrl}
            alt="Drawing overlay"
            class="drawing-overlay-img"
            style="object-fit: {imageDrawings[myImage.url].fitMode === 'fill' ? 'cover' : 'contain'};"
          />
        {/if}
      </figure>
    </div>
    <footer class="sync-footer" class:hidden={!uiVisible && isDrawing}>
      <label class="opacity-slider-label">
        <span>Opacity:</span>
        <input type="range" min="0" max="100" value={imageOpacity} oninput={(e) => imageOpacity = parseInt(e.target.value, 10)} />
        <span>{imageOpacity}%</span>
      </label>
      {#if !isDrawing}
        <button class="draw-btn" onclick={enterDrawingMode}>✎ Draw</button>
      {:else}
        <button class="draw-btn active" onclick={exitDrawingMode}>✎ Done</button>
      {/if}
      <button class="clear-btn" onclick={clearDrawingCanvas} disabled={!isDrawing}>Clear</button>
    </footer>
  </div>
{/if}

<div
  bind:this={drawingOverlayEl}
  class="drawing-overlay"
  class:active={isDrawing}
  role="presentation"
  aria-hidden="true"
>
  <canvas bind:this={drawingCanvasEl}></canvas>
</div>

<style>
  .sync-status {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    gap: 1rem;
    color: #ccc;
    font-size: 1.2rem;
  }
  .sync-client-layout {
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }
  .sync-header {
    display: flex;
    align-items: center;
    padding: 0.5rem 1rem;
    background: rgba(0,0,0,0.85);
    z-index: 10;
    gap: 1rem;
    transition: opacity 0.3s;
  }
  .sync-header.hidden {
    opacity: 0;
    pointer-events: none;
  }
  .sync-indicator {
    color: #4caf50;
    font-size: 0.8rem;
    font-weight: bold;
  }
  .sync-image-info {
    flex: 1;
    color: #aaa;
    font-family: monospace;
    font-size: 0.9rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .disconnect-btn {
    background: #c0392b;
    color: #fff;
    border: none;
    padding: 0.3rem 0.8rem;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.8rem;
  }
  .sync-content {
    flex: 1;
    position: relative;
    overflow: hidden;
  }
  .image-container {
    display: flex;
    justify-content: center;
    align-items: center;
    width: 100%;
    height: 100%;
    margin: 0;
    position: relative;
  }
  .display-image {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .drawing-overlay-img {
    position: absolute;
    top: 0; left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }
  .sync-footer {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    padding: 0.5rem 1rem;
    background: rgba(0,0,0,0.85);
    z-index: 10;
    transition: opacity 0.3s;
  }
  .sync-footer.hidden {
    opacity: 0;
    pointer-events: none;
  }
  .opacity-slider-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: #ccc;
    font-size: 0.85rem;
  }
  .opacity-slider-label input[type="range"] {
    width: 100px;
  }
  .draw-btn, .clear-btn {
    padding: 0.3rem 0.8rem;
    border-radius: 4px;
    border: none;
    cursor: pointer;
    font-size: 0.85rem;
  }
  .draw-btn { background: #FF69B4; color: #fff; }
  .draw-btn.active { background: #e55a9e; }
  .clear-btn { background: #555; color: #ccc; }
  .clear-btn:disabled { opacity: 0.4; cursor: default; }
  .drawing-overlay {
    position: fixed;
    top: 0; left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    z-index: 20;
  }
  .drawing-overlay.active {
    pointer-events: auto;
  }
</style>
