/**
 * driver-app/src/services/websocket.ts — WebSocket client for real-time
 * communication with the Route Optimizer backend.
 *
 * Features:
 *   - Connects to ws://{serverUrl}/ws/driver/{driverId}
 *   - Sends GPS updates as { type: "gps_update", lat, lng, timestamp }
 *   - Sends stop completion as { type: "gps_update", ..., completed_stop_id }
 *   - Receives and dispatches { type: "route_updated" } messages
 *   - Responds to server { type: "ping" } with { type: "pong" }
 *   - Auto-reconnects on disconnect with exponential backoff (max 5 retries)
 *
 * No PHI is included in any WebSocket message.
 */

import {GpsLocation} from './gps';
import {
  GpsUpdate,
  OptimizedStop,
  RouteUpdatedMessage,
  ServerMessage,
} from '../types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WsClientCallbacks {
  /** Called when the server pushes a new optimized route. */
  onRouteUpdated: (stops: OptimizedStop[]) => void;
  /** Optional: called on each connection open. */
  onConnected?: () => void;
  /** Optional: called when all reconnect attempts are exhausted. */
  onFailed?: () => void;
}

// ---------------------------------------------------------------------------
// Reconnect configuration
// ---------------------------------------------------------------------------

const MAX_RETRIES = 5;
const BASE_BACKOFF_MS = 1_000; // 1 s, doubles each retry
const MAX_BACKOFF_MS = 30_000; // cap at 30 s

// ---------------------------------------------------------------------------
// WebSocketClient
// ---------------------------------------------------------------------------

export class WebSocketClient {
  private _socket: WebSocket | null = null;
  private _serverUrl = '';
  private _driverId = '';
  private _callbacks: WsClientCallbacks | null = null;
  private _retryCount = 0;
  private _retryTimer: ReturnType<typeof setTimeout> | null = null;
  private _intentionalClose = false;

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /** Open a WebSocket connection and register callbacks. */
  connect(
    serverUrl: string,
    driverId: string,
    callbacks: WsClientCallbacks,
  ): void {
    this._serverUrl = serverUrl;
    this._driverId = driverId;
    this._callbacks = callbacks;
    this._intentionalClose = false;
    this._retryCount = 0;
    this._openSocket();
  }

  /** Close the connection permanently (no reconnect). */
  disconnect(): void {
    this._intentionalClose = true;
    this._clearRetryTimer();
    if (this._socket) {
      this._socket.close();
      this._socket = null;
    }
  }

  /**
   * Send a GPS position fix to the server.
   * Optionally marks a stop as completed in the same message.
   */
  sendGpsUpdate(
    location: GpsLocation,
    completedStopId?: string,
  ): void {
    const message: GpsUpdate = {
      type: 'gps_update',
      lat: location.lat,
      lng: location.lng,
      timestamp: location.timestamp,
      ...(completedStopId ? {completed_stop_id: completedStopId} : {}),
    };
    this._send(message);
  }

  /** True when the WebSocket is in the OPEN state. */
  get isConnected(): boolean {
    return this._socket?.readyState === WebSocket.OPEN;
  }

  /**
   * Compute the next reconnect delay using exponential backoff with jitter.
   * Exported for unit testing.
   */
  backoffDelayMs(retryCount: number): number {
    const base = Math.min(BASE_BACKOFF_MS * 2 ** retryCount, MAX_BACKOFF_MS);
    // Add up to 20 % jitter to avoid thundering-herd reconnections
    const jitter = base * 0.2 * Math.random();
    return Math.round(base + jitter);
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private _openSocket(): void {
    const url = `${this._serverUrl}/ws/driver/${this._driverId}`;
    const socket = new WebSocket(url);

    socket.onopen = () => {
      console.log('[WsClient] connected to', url);
      this._retryCount = 0;
      this._callbacks?.onConnected?.();
    };

    socket.onmessage = (event: MessageEvent) => {
      this._handleMessage(event.data as string);
    };

    socket.onerror = (event: Event) => {
      console.warn('[WsClient] error', event);
    };

    socket.onclose = (event: CloseEvent) => {
      console.log('[WsClient] closed', event.code, event.reason);
      this._socket = null;
      if (!this._intentionalClose) {
        this._scheduleReconnect();
      }
    };

    this._socket = socket;
  }

  private _handleMessage(raw: string): void {
    let message: ServerMessage;
    try {
      message = JSON.parse(raw) as ServerMessage;
    } catch {
      console.warn('[WsClient] invalid JSON:', raw);
      return;
    }

    switch (message.type) {
      case 'route_updated':
        this._callbacks?.onRouteUpdated(
          (message as RouteUpdatedMessage).optimized_stops,
        );
        break;

      case 'ping':
        this._send({type: 'pong', client_time: new Date().toISOString()});
        break;

      default:
        console.warn('[WsClient] unknown message type:', (message as ServerMessage).type);
    }
  }

  private _send(payload: object): void {
    if (!this.isConnected) {
      console.warn('[WsClient] send skipped — not connected');
      return;
    }
    this._socket!.send(JSON.stringify(payload));
  }

  private _scheduleReconnect(): void {
    if (this._retryCount >= MAX_RETRIES) {
      console.error('[WsClient] max retries reached — giving up');
      this._callbacks?.onFailed?.();
      return;
    }

    const delay = this.backoffDelayMs(this._retryCount);
    this._retryCount += 1;
    console.log(
      `[WsClient] reconnecting in ${delay} ms (attempt ${this._retryCount}/${MAX_RETRIES})`,
    );

    this._retryTimer = setTimeout(() => {
      this._retryTimer = null;
      if (!this._intentionalClose) {
        this._openSocket();
      }
    }, delay);
  }

  private _clearRetryTimer(): void {
    if (this._retryTimer !== null) {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
    }
  }
}

// Shared singleton exported to App.tsx
export const wsClient = new WebSocketClient();
