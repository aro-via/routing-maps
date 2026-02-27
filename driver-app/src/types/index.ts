/**
 * Shared TypeScript types for the Driver App.
 * Mirror the server-side Pydantic schemas (see app/models/schemas.py).
 *
 * No PHI is stored in these types — stop_id is a UUID managed by the
 * dispatcher's back-office system.  The driver app never receives or
 * stores patient names or medical information.
 */

// ---------------------------------------------------------------------------
// Location
// ---------------------------------------------------------------------------

export interface Location {
  lat: number;
  lng: number;
}

// ---------------------------------------------------------------------------
// GPS update (sent from app to server over WebSocket)
// ---------------------------------------------------------------------------

export interface GpsUpdate {
  type: 'gps_update';
  lat: number;
  lng: number;
  timestamp: string; // ISO-8601 UTC
  completed_stop_id?: string; // present only when driver marks stop done
}

// ---------------------------------------------------------------------------
// Optimized stop (received from server)
// ---------------------------------------------------------------------------

export interface OptimizedStop {
  stop_id: string;       // internal UUID — no PHI
  sequence: number;
  location: Location;
  arrival_time: string;   // "HH:MM"
  departure_time: string; // "HH:MM"
}

// ---------------------------------------------------------------------------
// Route update (pushed from server → app via WebSocket)
// ---------------------------------------------------------------------------

export type RouteUpdateReason = 'traffic_delay' | 'stop_modified';

export interface RouteUpdatedMessage {
  type: 'route_updated';
  reason: RouteUpdateReason;
  optimized_stops: OptimizedStop[];
  total_duration_minutes: number;
  google_maps_url: string;
}

// ---------------------------------------------------------------------------
// Ping / pong (server heartbeat)
// ---------------------------------------------------------------------------

export interface PingMessage {
  type: 'ping';
  server_time: string;
}

export interface PongMessage {
  type: 'pong';
  client_time: string;
}

// ---------------------------------------------------------------------------
// All inbound WebSocket messages
// ---------------------------------------------------------------------------

export type ServerMessage = RouteUpdatedMessage | PingMessage;

// ---------------------------------------------------------------------------
// Driver status
// ---------------------------------------------------------------------------

export type DriverStatus = 'idle' | 'active' | 'completed';

// ---------------------------------------------------------------------------
// React Navigation param list
// ---------------------------------------------------------------------------

export type RootStackParamList = {
  Route: undefined;
  StopDetail: { stop: OptimizedStop; stopIndex: number };
};
