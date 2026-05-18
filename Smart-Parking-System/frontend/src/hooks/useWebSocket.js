/**
 * useWebSocket.js — Auto-reconnecting WebSocket Client
 *
 * Connects to /ws/state and calls onMessage(parsedFrame) for every
 * JSON message received. Reconnects automatically after 1 second if
 * the connection is lost (server restart, network blip, etc.).
 *
 * Sends a keep-alive 'ping' text message every 20 seconds to prevent
 * the connection from being closed by idle-timeout proxies.
 *
 * Usage
 * -----
 * useWebSocket(useCallback((frame) => {
 *   // handle frame.vehicles, frame.spots_delta, etc.
 * }, []))
 *
 * The onMessage callback is stored in a ref so it never needs to be
 * listed as a dependency — the hook only connects/disconnects once.
 *
 * URL is derived from window.location so the same build works on any
 * host (localhost dev server, production server, etc.).
 */
import { useEffect, useRef, useCallback } from 'react'

const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/state`

export function useWebSocket(onMessage) {
  const wsRef = useRef(null)
  const onMsgRef = useRef(onMessage)
  onMsgRef.current = onMessage

  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        onMsgRef.current(data)
      } catch {}
    }

    ws.onclose = () => {
      // Reconnect after 1s
      setTimeout(connect, 1000)
    }

    ws.onerror = () => {
      ws.close()
    }

    // Keep-alive ping every 20s
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping')
    }, 20000)

    ws.addEventListener('close', () => clearInterval(ping))
  }, [])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
    }
  }, [connect])
}
