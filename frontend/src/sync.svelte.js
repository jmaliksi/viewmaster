export const syncState = $state({
  wsState: 'disconnected',
  role: null,
  sessionActive: false,
  connectedClients: 0,
  waitingForHost: false,
  sessionEnded: false,
  currentImage: null,
})

let ws = null
let reconnectTimer = null
let currentRole = null
let pendingRegister = false
let pendingAttach = false

function getWsUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api/ws/sync`
}

export function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
  syncState.wsState = 'connecting'
  ws = new WebSocket(getWsUrl())
  ws.onopen = () => {
    syncState.wsState = 'connected'
    if (currentRole === 'host' || pendingRegister) {
      pendingRegister = false
      ws.send(JSON.stringify({ type: 'register_host' }))
    } else if (currentRole === 'client' || pendingAttach) {
      pendingAttach = false
      ws.send(JSON.stringify({ type: 'attach_client' }))
    }
  }
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      handleMessage(msg)
    } catch (e) {
      console.error('Invalid sync message:', e)
    }
  }
  ws.onclose = () => {
    const wasRole = currentRole
    syncState.wsState = 'disconnected'
    syncState.sessionActive = false
    syncState.waitingForHost = false
    syncState.role = null
    ws = null
    if (wasRole === 'host') {
      scheduleReconnect()
    }
  }
  ws.onerror = () => {
    ws?.close()
  }
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer)
  reconnectTimer = setTimeout(() => {
    connect()
  }, 3000)
}

function handleMessage(msg) {
  switch (msg.type) {
    case 'host_registered':
      currentRole = 'host'
      syncState.role = 'host'
      syncState.sessionActive = true
      syncState.connectedClients = 0
      break
    case 'client_joined':
      syncState.connectedClients++
      break
    case 'client_left':
      if (syncState.connectedClients > 0) syncState.connectedClients--
      break
    case 'session_joined':
      currentRole = 'client'
      syncState.role = 'client'
      syncState.sessionActive = true
      syncState.waitingForHost = false
      if (msg.state) applyState(msg.state)
      break
    case 'waiting_for_host':
      syncState.waitingForHost = true
      break
    case 'state_update':
      if (msg.state) applyState(msg.state)
      break
    case 'session_ended':
      syncState.sessionActive = false
      syncState.waitingForHost = false
      syncState.sessionEnded = true
      syncState.currentImage = null
      if (syncState.role === 'client') {
        ws?.close()
      }
      break
    case 'error':
      console.error('Sync error:', msg.message)
      break
  }
}

function applyState(state) {
  if (state.currentImage) {
    syncState.currentImage = state.currentImage
  }
}

export function registerHost() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'register_host' }))
  } else {
    pendingRegister = true
    connect()
  }
}

export function attachClient() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'attach_client' }))
  } else {
    pendingAttach = true
    connect()
  }
}

export function sendState(state) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'state_update', state }))
  }
}

export function disconnect() {
  clearTimeout(reconnectTimer)
  pendingRegister = false
  pendingAttach = false
  currentRole = null
  syncState.role = null
  syncState.sessionActive = false
  syncState.waitingForHost = false
  syncState.sessionEnded = false
  syncState.currentImage = null
  syncState.connectedClients = 0
  if (ws) {
    ws.onclose = null
    ws.close()
    ws = null
  }
  syncState.wsState = 'disconnected'
}
