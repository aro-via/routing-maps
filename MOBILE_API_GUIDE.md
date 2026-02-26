# MOBILE_API_GUIDE.md — Route Optimizer API
**Audience:** React Native (Driver App) Developer
**Version:** 2.0 (Phase 1 REST + Phase 2 WebSocket)
**Last Updated:** February 2026

> This document is your single reference for integrating the Route Optimizer API
> into the driver mobile app. It covers every endpoint, every message format,
> every error code, and includes ready-to-use TypeScript code for each integration point.

---

## Table of Contents

1. [What This API Does](#1-what-this-api-does)
2. [Base URLs & Environments](#2-base-urls--environments)
3. [HIPAA Rules for the Mobile App](#3-hipaa-rules-for-the-mobile-app)
4. [Phase 1 — REST API](#4-phase-1--rest-api)
   - [POST /api/v1/optimize-route](#41-post-apiv1optimize-route)
   - [GET /api/v1/health](#42-get-apiv1health)
5. [Phase 2 — WebSocket API](#5-phase-2--websocket-api)
   - [Connecting](#51-connecting)
   - [Messages: App → Server](#52-messages-app--server)
   - [Messages: Server → App](#53-messages-server--app)
   - [Disconnection & Reconnection](#54-disconnection--reconnection)
6. [Data Models Reference](#6-data-models-reference)
7. [Error Handling](#7-error-handling)
8. [TypeScript Service Layer](#8-typescript-service-layer)
   - [API Service](#81-api-service-ts)
   - [WebSocket Service](#82-websocket-service-ts)
   - [GPS Service](#83-gps-service-ts)
9. [End-to-End Flow Diagrams](#9-end-to-end-flow-diagrams)
10. [Integration Checklist](#10-integration-checklist)

---

## 1. What This API Does

The Route Optimizer API solves one problem: **given a driver's starting location and a list
of patient pickup stops, return the most time-efficient pickup order accounting for real-time
traffic.**

The mobile app uses this API in two ways:

**Phase 1 — At the start of a shift (REST)**
The dispatcher (or the app itself) calls `POST /api/v1/optimize-route` once before the
driver departs. The API returns an ordered list of stops with estimated arrival times and
a Google Maps URL the driver can tap to start navigation.

**Phase 2 — During the shift (WebSocket)**
The driver app maintains a live WebSocket connection throughout the shift. It streams the
driver's GPS location to the server every 15 seconds. If the server detects the driver is
significantly delayed, it automatically re-optimizes the route and pushes the updated stop
order back to the app in real-time — no action needed from the driver.

```
SHIFT START                    DURING SHIFT                    SHIFT END
──────────────                 ──────────────────────          ──────────
POST /optimize-route   →       WebSocket connected      →      WS disconnect
Receive ordered stops          Stream GPS every 15s            Clear local state
Tap Google Maps link           Receive route updates
Start driving                  if traffic detected
```

---

## 2. Base URLs & Environments

```typescript
// config/api.config.ts

const API_CONFIG = {
  development: {
    REST_BASE_URL:  'http://localhost:8000',
    WS_BASE_URL:    'ws://localhost:8000',
  },
  staging: {
    REST_BASE_URL:  'https://api-staging.yourcompany.com',
    WS_BASE_URL:    'wss://api-staging.yourcompany.com',
  },
  production: {
    REST_BASE_URL:  'https://api.yourcompany.com',
    WS_BASE_URL:    'wss://api.yourcompany.com',
  },
};

export const ENV = 'development'; // change per build
export const { REST_BASE_URL, WS_BASE_URL } = API_CONFIG[ENV];
```

> ⚠️ **Important:** Always use `wss://` (secure WebSocket) in staging and production,
> never `ws://`. Use `https://` for REST, never `http://` outside local development.

---

## 3. HIPAA Rules for the Mobile App

This API is designed for HIPAA-compliant medical transportation. As the mobile developer,
you must follow these rules — they are not optional.

### What the API Accepts
The API only accepts GPS **coordinates** (latitude/longitude) and internal **stop IDs** (UUIDs).
It never accepts patient names, dates of birth, addresses as text, or any other PHI.

### What the App Must Never Send
```typescript
// ❌ NEVER send this — PHI in API call
{
  stop_id: "stop_001",
  patient_name: "John Smith",       // VIOLATION
  address: "123 Main Street",       // VIOLATION
  dob: "1955-04-12"                 // VIOLATION
}

// ✅ ALWAYS send this — coordinates only
{
  stop_id: "stop_001",              // internal UUID only
  location: { lat: 40.7128, lng: -74.0060 },
  earliest_pickup: "08:00",
  latest_pickup: "08:30",
  service_time_minutes: 3
}
```

### What the App Must Never Store
- Do not store patient names, DOB, or full addresses in `AsyncStorage` or any local device storage
- The app may cache the current route (stop IDs + coordinates) locally for offline resilience
- Patient identity is resolved by your **dispatcher system** — the driver app only needs
  `stop_id` to cross-reference locally if needed

### What Appears on Screen
- Driver sees: stop sequence number, ETA, mobility requirement icon, pickup instructions
- Driver does **not** see: full patient name (first name only is acceptable), medical details,
  insurance info, or any data beyond what is needed to complete the pickup

---

## 4. Phase 1 — REST API

### 4.1 POST /api/v1/optimize-route

**Purpose:** Request an optimized pickup route for a driver's shift. Call this once at the
start of the shift before the driver departs.

**Method:** `POST`
**URL:** `{REST_BASE_URL}/api/v1/optimize-route`
**Content-Type:** `application/json`

---

#### Request Body

```typescript
interface OptimizeRouteRequest {
  driver_id: string;           // Your internal driver UUID
  driver_location: Location;   // Driver's current GPS position
  departure_time: string;      // ISO 8601 format — used to fetch live traffic
  stops: Stop[];               // 2–25 pickup stops (order doesn't matter)
}

interface Location {
  lat: number;   // Latitude  (-90 to 90)
  lng: number;   // Longitude (-180 to 180)
}

interface Stop {
  stop_id: string;                // Your internal stop/trip UUID — no PHI
  location: Location;             // Pickup coordinates
  earliest_pickup: string;        // "HH:MM" — earliest acceptable pickup time
  latest_pickup: string;          // "HH:MM" — latest acceptable pickup time
  service_time_minutes: number;   // Minutes spent at stop (typically 2–5)
}
```

#### Request Example

```json
{
  "driver_id": "drv_f3a2c1b4",
  "driver_location": {
    "lat": 40.7128,
    "lng": -74.0060
  },
  "departure_time": "2024-01-15T07:30:00Z",
  "stops": [
    {
      "stop_id": "trip_001_uuid",
      "location": { "lat": 40.7282, "lng": -73.7949 },
      "earliest_pickup": "08:00",
      "latest_pickup": "08:30",
      "service_time_minutes": 3
    },
    {
      "stop_id": "trip_002_uuid",
      "location": { "lat": 40.6892, "lng": -74.0445 },
      "earliest_pickup": "08:15",
      "latest_pickup": "08:45",
      "service_time_minutes": 3
    },
    {
      "stop_id": "trip_003_uuid",
      "location": { "lat": 40.7489, "lng": -73.9680 },
      "earliest_pickup": "08:30",
      "latest_pickup": "09:00",
      "service_time_minutes": 3
    },
    {
      "stop_id": "trip_004_uuid",
      "location": { "lat": 40.7614, "lng": -73.9776 },
      "earliest_pickup": "08:00",
      "latest_pickup": "09:00",
      "service_time_minutes": 5
    }
  ]
}
```

---

#### Response Body

```typescript
interface OptimizeRouteResponse {
  driver_id: string;
  optimized_stops: OptimizedStop[];   // Stops in optimal pickup order
  total_distance_km: number;          // Total route distance
  total_duration_minutes: number;     // Total estimated driving + service time
  google_maps_url: string;            // Deep-link for turn-by-turn navigation
  optimization_score: number;         // 0.0–1.0 (1.0 = maximum possible efficiency)
}

interface OptimizedStop {
  stop_id: string;          // Matches your input stop_id
  sequence: number;         // 1-based pickup order (1 = first stop)
  location: Location;       // Pickup coordinates (echoed back)
  arrival_time: string;     // "HH:MM" — estimated driver arrival
  departure_time: string;   // "HH:MM" — estimated departure (after service time)
}
```

#### Response Example

```json
{
  "driver_id": "drv_f3a2c1b4",
  "optimized_stops": [
    {
      "stop_id": "trip_002_uuid",
      "sequence": 1,
      "location": { "lat": 40.6892, "lng": -74.0445 },
      "arrival_time": "07:52",
      "departure_time": "07:55"
    },
    {
      "stop_id": "trip_004_uuid",
      "sequence": 2,
      "location": { "lat": 40.7614, "lng": -73.9776 },
      "arrival_time": "08:18",
      "departure_time": "08:23"
    },
    {
      "stop_id": "trip_001_uuid",
      "sequence": 3,
      "location": { "lat": 40.7282, "lng": -73.7949 },
      "arrival_time": "08:41",
      "departure_time": "08:44"
    },
    {
      "stop_id": "trip_003_uuid",
      "sequence": 4,
      "location": { "lat": 40.7489, "lng": -73.9680 },
      "arrival_time": "09:02",
      "departure_time": "09:05"
    }
  ],
  "total_distance_km": 28.4,
  "total_duration_minutes": 95,
  "google_maps_url": "https://www.google.com/maps/dir/40.7128,-74.0060/40.6892,-74.0445/40.7614,-73.9776/40.7282,-73.7949/40.7489,-73.9680",
  "optimization_score": 0.94
}
```

---

#### Key Notes for the App

**Stop order in response will differ from input.**
The whole point of this API is reordering. `trip_002_uuid` may come back as sequence 1 even if
it was the second item in your request. Always use the `sequence` field to order your display,
not the array index.

**`google_maps_url` is ready to use directly.**
Pass it to `Linking.openURL()`. It opens Google Maps with all stops pre-loaded in the
optimized order. The driver can tap once and start navigating.

```typescript
// Open optimized route in Google Maps
await Linking.openURL(response.google_maps_url);
```

**`arrival_time` and `departure_time` are in `HH:MM` local time.**
They are calculated relative to the `departure_time` you sent. If you send `07:30:00` as
departure, all times in the response are offset from that.

**Response time:** Expect 2–8 seconds depending on number of stops and traffic data freshness.
Show a loading spinner and do not allow the user to tap "Start Route" until the response arrives.

---

### 4.2 GET /api/v1/health

**Purpose:** Check if the API service is reachable and healthy. Call this on app launch
before making any optimization requests.

**Method:** `GET`
**URL:** `{REST_BASE_URL}/api/v1/health`

#### Response

```json
{
  "status": "healthy",
  "redis": "ok",
  "maps_api": "configured"
}
```

If `status` is not `"healthy"`, show an error state and prevent the driver from starting
their shift until connectivity is restored.

---

## 5. Phase 2 — WebSocket API

The WebSocket connection is the live channel between the driver app and the server during
an active shift. It has two purposes: sending GPS updates and receiving route changes.

### 5.1 Connecting

**URL:** `{WS_BASE_URL}/ws/driver/{driver_id}`

```typescript
const driverId = 'drv_f3a2c1b4';
const ws = new WebSocket(`${WS_BASE_URL}/ws/driver/${driverId}`);
```

**When to connect:** After the driver taps "Start Shift" and the initial route has been
received from `POST /api/v1/optimize-route`.

**When to disconnect:** When the driver taps "End Shift" or all stops are completed.

**Connection lifecycle:**
```
App launches
    ↓
GET /health → confirm server is up
    ↓
POST /optimize-route → get initial route
    ↓
Display route to driver
    ↓
Driver taps "Start Shift"
    ↓
Open WebSocket connection ← YOU ARE HERE
    ↓
Stream GPS every 15 seconds
    ↓
Receive route updates as needed
    ↓
Driver taps "End Shift" OR all stops completed
    ↓
Close WebSocket
```

---

### 5.2 Messages: App → Server

The app sends two types of messages to the server.

---

#### GPS Update (required, every 15 seconds)

Send the driver's current location on a regular interval throughout the shift.
The server uses these to detect delays and trigger re-optimization.

```typescript
interface GpsUpdateMessage {
  type: 'gps_update';
  lat: number;
  lng: number;
  timestamp: string;           // ISO 8601 UTC
  completed_stop_id?: string;  // Include ONLY when marking a stop as completed
}
```

**Example — regular GPS update:**
```json
{
  "type": "gps_update",
  "lat": 40.7214,
  "lng": -74.0052,
  "timestamp": "2024-01-15T08:14:30Z"
}
```

**Example — GPS update when marking stop as completed:**
```json
{
  "type": "gps_update",
  "lat": 40.6892,
  "lng": -74.0445,
  "timestamp": "2024-01-15T07:55:10Z",
  "completed_stop_id": "trip_002_uuid"
}
```

> Include `completed_stop_id` in the very next GPS update after the driver taps
> "Picked Up" on the Stop Detail screen. The server will remove that stop from
> the remaining route and recalculate ETAs for the remaining stops.

---

#### Pong (required, in response to server ping)

The server sends a `ping` every 60 seconds to verify the connection is alive.
The app must respond with a `pong`.

```typescript
interface PongMessage {
  type: 'pong';
}
```

```json
{ "type": "pong" }
```

> If the server does not receive a `pong` within 30 seconds of sending a `ping`,
> it will close the connection. Your reconnect logic (see Section 5.4) will handle this.

---

### 5.3 Messages: Server → App

The server sends three types of messages to the app.

---

#### Route Updated

Sent when the server has re-optimized the route due to a detected delay or stop change.
This is the most important message the app receives. When you get this, replace the
current route display entirely with the new stop order.

```typescript
interface RouteUpdatedMessage {
  type: 'route_updated';
  reason: 'traffic_delay' | 'stop_added' | 'stop_cancelled';
  optimized_stops: OptimizedStop[];    // Full new stop list (remaining stops only)
  total_duration_minutes: number;      // Updated total remaining time
  google_maps_url: string;             // New Maps URL reflecting updated order
}
```

**Example:**
```json
{
  "type": "route_updated",
  "reason": "traffic_delay",
  "optimized_stops": [
    {
      "stop_id": "trip_004_uuid",
      "sequence": 1,
      "location": { "lat": 40.7614, "lng": -73.9776 },
      "arrival_time": "08:35",
      "departure_time": "08:40"
    },
    {
      "stop_id": "trip_001_uuid",
      "sequence": 2,
      "location": { "lat": 40.7282, "lng": -73.7949 },
      "arrival_time": "08:58",
      "departure_time": "09:01"
    },
    {
      "stop_id": "trip_003_uuid",
      "sequence": 3,
      "location": { "lat": 40.7489, "lng": -73.9680 },
      "arrival_time": "09:19",
      "departure_time": "09:22"
    }
  ],
  "total_duration_minutes": 47,
  "google_maps_url": "https://www.google.com/maps/dir/..."
}
```

**What the app should do when this arrives:**
1. Update the route store with the new `optimized_stops`
2. Show a dismissible banner: *"Route updated due to traffic"*
3. Update the Google Maps URL in state (driver may need to re-open Maps)
4. Do NOT interrupt the driver if they are currently navigating — show the banner and let them dismiss it

---

#### Ping

Sent every 60 seconds by the server to verify the connection is alive.

```typescript
interface PingMessage {
  type: 'ping';
  server_time: string;   // ISO 8601 UTC
}
```

```json
{
  "type": "ping",
  "server_time": "2024-01-15T08:15:00Z"
}
```

**What the app should do:** Immediately respond with `{ "type": "pong" }`.

---

#### Error

Sent when the server encounters a problem processing a message from the app.

```typescript
interface ErrorMessage {
  type: 'error';
  code: string;
  message: string;
}
```

```json
{
  "type": "error",
  "code": "INVALID_STOP_ID",
  "message": "completed_stop_id trip_999_uuid not found in current route"
}
```

**Error codes:**

| Code | Meaning | App Action |
|---|---|---|
| `INVALID_GPS` | Coordinates out of valid range | Log error, skip this GPS update |
| `INVALID_STOP_ID` | `completed_stop_id` not in current route | Log error, resync route from server |
| `DRIVER_NOT_FOUND` | Driver ID not recognized / session expired | Re-authenticate driver, reconnect |
| `OPTIMIZATION_FAILED` | Re-optimization could not find a valid route | Show alert, contact dispatcher |
| `RATE_LIMITED` | Too many messages sent too quickly | Back off for 30 seconds |

---

### 5.4 Disconnection & Reconnection

Network drops are common on mobile. The app must handle them gracefully with
automatic reconnection using exponential backoff.

```typescript
// Reconnection strategy
const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16000]; // max 5 retries
// After 5 retries, show "Connection lost" alert and require driver to manually retry
```

**Reconnection behavior:**
- On unexpected disconnect → wait 1s → reconnect → if fails → wait 2s → reconnect → etc.
- On successful reconnect → resume GPS streaming immediately
- If reconnect fails after all retries → show persistent alert: *"Connection to server lost. Please contact dispatch."*
- GPS updates sent during disconnection → buffer last 3 updates → send on reconnect

---

## 6. Data Models Reference

Complete TypeScript type definitions for all data used in the app.

```typescript
// types/api.types.ts

// ─── Shared ───────────────────────────────────────────────────────────────────

export interface Location {
  lat: number;
  lng: number;
}

// ─── REST API ─────────────────────────────────────────────────────────────────

export interface Stop {
  stop_id: string;
  location: Location;
  earliest_pickup: string;       // "HH:MM"
  latest_pickup: string;         // "HH:MM"
  service_time_minutes: number;
}

export interface OptimizedStop {
  stop_id: string;
  sequence: number;
  location: Location;
  arrival_time: string;          // "HH:MM"
  departure_time: string;        // "HH:MM"
}

export interface OptimizeRouteRequest {
  driver_id: string;
  driver_location: Location;
  departure_time: string;        // ISO 8601
  stops: Stop[];
}

export interface OptimizeRouteResponse {
  driver_id: string;
  optimized_stops: OptimizedStop[];
  total_distance_km: number;
  total_duration_minutes: number;
  google_maps_url: string;
  optimization_score: number;
}

export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  redis: 'ok' | 'error';
  maps_api: 'configured' | 'missing';
}

// ─── WebSocket Messages (App → Server) ────────────────────────────────────────

export interface GpsUpdateMessage {
  type: 'gps_update';
  lat: number;
  lng: number;
  timestamp: string;
  completed_stop_id?: string;
}

export interface PongMessage {
  type: 'pong';
}

export type OutgoingWsMessage = GpsUpdateMessage | PongMessage;

// ─── WebSocket Messages (Server → App) ────────────────────────────────────────

export interface RouteUpdatedMessage {
  type: 'route_updated';
  reason: 'traffic_delay' | 'stop_added' | 'stop_cancelled';
  optimized_stops: OptimizedStop[];
  total_duration_minutes: number;
  google_maps_url: string;
}

export interface PingMessage {
  type: 'ping';
  server_time: string;
}

export interface WsErrorMessage {
  type: 'error';
  code: string;
  message: string;
}

export type IncomingWsMessage = RouteUpdatedMessage | PingMessage | WsErrorMessage;

// ─── API Error ────────────────────────────────────────────────────────────────

export interface ApiError {
  status: number;
  detail: string | ValidationError[];
}

export interface ValidationError {
  loc: string[];
  msg: string;
  type: string;
}
```

---

## 7. Error Handling

### REST API Errors

| HTTP Status | Meaning | When It Happens | App Action |
|---|---|---|---|
| `200 OK` | Success | Request processed successfully | Use response data |
| `422 Unprocessable Entity` | Validation error | Bad coords, past time, wrong stop count | Show error to dispatcher, do not start shift |
| `500 Internal Server Error` | Server error | Unexpected failure in optimization | Retry once after 3s, then show error |
| `502 Bad Gateway` | Upstream error | Google Maps API is unavailable | Show "Service temporarily unavailable", retry in 60s |

**Validation Error Response (422):**
```json
{
  "detail": [
    {
      "loc": ["body", "stops", 0, "earliest_pickup"],
      "msg": "invalid time format, expected HH:MM",
      "type": "value_error"
    }
  ]
}
```

**Handling in TypeScript:**
```typescript
async function optimizeRoute(request: OptimizeRouteRequest): Promise<OptimizeRouteResponse> {
  const response = await fetch(`${REST_BASE_URL}/api/v1/optimize-route`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json();

    switch (response.status) {
      case 422:
        throw new Error(`Invalid request: ${JSON.stringify(error.detail)}`);
      case 502:
        throw new Error('Navigation service temporarily unavailable. Please try again shortly.');
      default:
        throw new Error('Unable to optimize route. Please contact dispatch.');
    }
  }

  return response.json();
}
```

---

## 8. TypeScript Service Layer

Drop-in service files for the driver app. Place these in `src/services/`.

### 8.1 api.service.ts

```typescript
// src/services/api.service.ts
import { REST_BASE_URL } from '../config/api.config';
import {
  OptimizeRouteRequest,
  OptimizeRouteResponse,
  HealthResponse,
} from '../types/api.types';

class ApiService {

  async checkHealth(): Promise<HealthResponse> {
    const response = await fetch(`${REST_BASE_URL}/api/v1/health`);
    if (!response.ok) throw new Error('Server is unreachable');
    return response.json();
  }

  async optimizeRoute(request: OptimizeRouteRequest): Promise<OptimizeRouteResponse> {
    const response = await fetch(`${REST_BASE_URL}/api/v1/optimize-route`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const error = await response.json();
      switch (response.status) {
        case 422:
          throw new Error(`Route request invalid: ${JSON.stringify(error.detail)}`);
        case 502:
          throw new Error('Traffic service unavailable. Please try again.');
        default:
          throw new Error('Failed to optimize route. Contact dispatch.');
      }
    }

    return response.json();
  }
}

export const apiService = new ApiService();
```

---

### 8.2 websocket.service.ts

```typescript
// src/services/websocket.service.ts
import { WS_BASE_URL } from '../config/api.config';
import {
  OutgoingWsMessage,
  IncomingWsMessage,
  RouteUpdatedMessage,
} from '../types/api.types';

const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16000];
const MAX_RETRIES = RECONNECT_DELAYS_MS.length;

type RouteUpdateHandler = (message: RouteUpdatedMessage) => void;
type ConnectionStateHandler = (state: 'connected' | 'disconnected' | 'failed') => void;

class WebSocketService {
  private ws: WebSocket | null = null;
  private driverId: string | null = null;
  private retryCount = 0;
  private retryTimeout: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  private onRouteUpdate: RouteUpdateHandler | null = null;
  private onConnectionStateChange: ConnectionStateHandler | null = null;

  // Pending GPS buffer for reconnect scenarios
  private pendingGpsBuffer: OutgoingWsMessage[] = [];

  connect(driverId: string): void {
    this.driverId = driverId;
    this.intentionalClose = false;
    this._openConnection();
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.retryCount = 0;
    if (this.retryTimeout) clearTimeout(this.retryTimeout);
    this.ws?.close(1000, 'Shift ended');
    this.ws = null;
  }

  send(message: OutgoingWsMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    } else {
      // Buffer last 3 GPS updates for when connection restores
      if (message.type === 'gps_update') {
        this.pendingGpsBuffer.push(message);
        if (this.pendingGpsBuffer.length > 3) {
          this.pendingGpsBuffer.shift(); // keep only latest 3
        }
      }
    }
  }

  onRouteUpdated(handler: RouteUpdateHandler): void {
    this.onRouteUpdate = handler;
  }

  onConnectionState(handler: ConnectionStateHandler): void {
    this.onConnectionStateChange = handler;
  }

  private _openConnection(): void {
    if (!this.driverId) return;

    const url = `${WS_BASE_URL}/ws/driver/${this.driverId}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.retryCount = 0;
      this.onConnectionStateChange?.('connected');

      // Flush buffered GPS updates
      this.pendingGpsBuffer.forEach(msg => this.send(msg));
      this.pendingGpsBuffer = [];
    };

    this.ws.onmessage = (event: MessageEvent) => {
      this._handleMessage(JSON.parse(event.data) as IncomingWsMessage);
    };

    this.ws.onclose = (event: CloseEvent) => {
      if (!this.intentionalClose) {
        this.onConnectionStateChange?.('disconnected');
        this._scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      // onerror is always followed by onclose — handle reconnect there
    };
  }

  private _handleMessage(message: IncomingWsMessage): void {
    switch (message.type) {
      case 'ping':
        this.send({ type: 'pong' });
        break;

      case 'route_updated':
        this.onRouteUpdate?.(message);
        break;

      case 'error':
        console.warn(`[WS] Server error: ${message.code} — ${message.message}`);
        break;
    }
  }

  private _scheduleReconnect(): void {
    if (this.retryCount >= MAX_RETRIES) {
      this.onConnectionStateChange?.('failed');
      return;
    }

    const delay = RECONNECT_DELAYS_MS[this.retryCount];
    this.retryCount++;

    this.retryTimeout = setTimeout(() => {
      this._openConnection();
    }, delay);
  }
}

export const wsService = new WebSocketService();
```

---

### 8.3 gps.service.ts

```typescript
// src/services/gps.service.ts
import BackgroundGeolocation from 'react-native-background-geolocation';
import { wsService } from './websocket.service';

// Adaptive GPS update intervals (milliseconds)
const GPS_INTERVALS = {
  STATIONARY:   60_000,   // barely moving
  NORMAL:       15_000,   // regular driving
  APPROACHING:   5_000,   // within 500m of next stop
};

let currentInterval = GPS_INTERVALS.NORMAL;
let gpsTimer: ReturnType<typeof setInterval> | null = null;

export function startGpsTracking(nextStopLocation: { lat: number; lng: number }): void {
  BackgroundGeolocation.start();

  gpsTimer = setInterval(async () => {
    const location = await BackgroundGeolocation.getCurrentPosition({
      timeout: 10,
      maximumAge: 5000,
      desiredAccuracy: BackgroundGeolocation.DESIRED_ACCURACY_HIGH,
    });

    // Adjust interval based on proximity to next stop
    const distanceToStop = _haversineDistance(
      { lat: location.coords.latitude, lng: location.coords.longitude },
      nextStopLocation
    );
    _adjustInterval(distanceToStop, location.coords.speed ?? 0);

    wsService.send({
      type: 'gps_update',
      lat: location.coords.latitude,
      lng: location.coords.longitude,
      timestamp: new Date().toISOString(),
    });

  }, currentInterval);
}

export function stopGpsTracking(): void {
  if (gpsTimer) clearInterval(gpsTimer);
  BackgroundGeolocation.stop();
}

export function markStopCompleted(stopId: string, lat: number, lng: number): void {
  // Send completed_stop_id with the very next GPS update
  wsService.send({
    type: 'gps_update',
    lat,
    lng,
    timestamp: new Date().toISOString(),
    completed_stop_id: stopId,
  });
}

function _adjustInterval(distanceMeters: number, speedKph: number): void {
  if (speedKph < 5) {
    currentInterval = GPS_INTERVALS.STATIONARY;
  } else if (distanceMeters < 500) {
    currentInterval = GPS_INTERVALS.APPROACHING;
  } else {
    currentInterval = GPS_INTERVALS.NORMAL;
  }
}

function _haversineDistance(
  a: { lat: number; lng: number },
  b: { lat: number; lng: number }
): number {
  const R = 6371000; // Earth radius in meters
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const x =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((a.lat * Math.PI) / 180) *
      Math.cos((b.lat * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}
```

---

## 9. End-to-End Flow Diagrams

### Phase 1 — Shift Start Flow

```
Driver opens app
      │
      ▼
GET /api/v1/health
      │
      ├─ unhealthy ──▶ Show "Service Unavailable" screen
      │
      └─ healthy ────▶ Show route request form
                             │
                             ▼
                  Dispatcher enters shift details
                  (driver location + stop list)
                             │
                             ▼
                  POST /api/v1/optimize-route
                  (show loading spinner, 2–8 seconds)
                             │
                  ┌──────────┴──────────────┐
                  │                         │
               200 OK                    422/500
                  │                         │
                  ▼                         ▼
        Display ordered stops          Show error message
        with ETAs                      Ask dispatcher to retry
                  │
                  ▼
        Driver taps "Start Shift"
                  │
                  ▼
        Open WebSocket connection
        Begin GPS tracking
```

---

### Phase 2 — Active Shift Flow

```
WebSocket connected + GPS streaming
            │
            │  every 15 seconds
            ▼
  App sends gps_update ──────────────────────────────▶ Server
                                                          │
                                                   Checks for delay
                                                          │
                                          ┌───────────────┴──────────────┐
                                          │                              │
                                     No delay                       Delay detected
                                          │                              │
                                   Nothing sent                 Re-optimizes route
                                                                         │
                                                               Server sends route_updated
                                                                         │
  App receives route_updated ◀────────────────────────────────────────┘
            │
            ▼
  Update route store (new stop order)
  Show "Route updated" banner
  Update Google Maps URL
            │
            ▼
  Driver acknowledges banner
  Continues to next stop
```

---

### Stop Completion Flow

```
Driver arrives at stop
          │
          ▼
  Driver taps "Arrived" button
  (records arrival, starts service timer)
          │
          ▼
  Driver taps "Picked Up" button
          │
          ▼
  markStopCompleted(stopId, lat, lng)
          │
          ▼
  GPS update sent with completed_stop_id
          │
          ▼
  Server removes stop from remaining route
  Recalculates ETAs for remaining stops
          │
          ▼
  Server sends route_updated message
  (with remaining stops and new ETAs)
          │
          ▼
  App advances to next stop in list
```

---

## 10. Integration Checklist

Work through this before submitting for review.

### Phase 1 (REST)
- [ ] `GET /health` called on app launch — blocks shift start if unhealthy
- [ ] `POST /optimize-route` called with correct data types (coordinates as numbers, not strings)
- [ ] `departure_time` sent as ISO 8601 UTC string
- [ ] Response `optimized_stops` sorted by `sequence` field before displaying
- [ ] `google_maps_url` opens correctly via `Linking.openURL()`
- [ ] Loading state shown during API call (2–8 seconds expected)
- [ ] 422 errors displayed clearly to dispatcher with specific field errors
- [ ] 500/502 errors show generic "try again" message without technical details

### Phase 2 (WebSocket)
- [ ] WebSocket connects after `POST /optimize-route` succeeds, not before
- [ ] GPS updates sent every 15 seconds (adaptive interval based on speed/proximity)
- [ ] `pong` sent immediately on every `ping` received
- [ ] `completed_stop_id` included in GPS update when driver marks stop done (not in a separate message)
- [ ] `route_updated` message replaces entire stop list (not merged/patched)
- [ ] Route update banner shown to driver on `route_updated` — dismissible, non-blocking
- [ ] Reconnect logic tested: kill server mid-shift, confirm app reconnects automatically
- [ ] Intentional disconnect on "End Shift" — no reconnect attempts after deliberate close
- [ ] GPS tracking stopped on disconnect and on "End Shift"

### HIPAA
- [ ] No patient names in any API request payload
- [ ] No patient names in any WebSocket message
- [ ] No PHI stored in `AsyncStorage` or device local storage
- [ ] Only `stop_id` (UUID), coordinates, and times appear in network traffic
- [ ] Verified with a network inspector (e.g. Proxyman, Charles) that no PHI is transmitted

### General
- [ ] Works on iOS simulator and Android emulator
- [ ] Works with the app backgrounded (GPS continues, WebSocket stays alive)
- [ ] Tested on slow network (3G simulation) — timeouts and loading states handle gracefully
- [ ] All TypeScript types imported from `types/api.types.ts` — no `any` types in API layer
