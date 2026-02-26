# ARCHITECTURE.md — Route Optimizer Service
**Version:** 2.0 (Phase 1 + Phase 2)
**Status:** Approved for Implementation

---

## 1. System Overview

The Route Optimizer is a **single-responsibility microservice**. It receives pickup stop data,
computes the optimal route using traffic-aware travel times, and returns an ordered stop list
with ETAs. It has no database, no auth layer, and no UI — it is a pure optimization API.

```
                        ┌──────────────────────────────────────────┐
                        │         ROUTE OPTIMIZER SERVICE          │
                        │                                          │
 Caller (Dispatcher     │  ┌────────────┐    ┌─────────────────┐  │
 System or Driver App)  │  │  FastAPI   │    │   Redis Cache   │  │
         │              │  │  REST API  │    │ (Distance Matrix│  │
         │ POST         │  └─────┬──────┘    │   Results)      │  │
         │ /optimize    │        │            └────────▲────────┘  │
         │─────────────▶│        ▼                     │           │
         │              │  ┌─────────────┐             │           │
         │◀─────────────│  │ Optimizer   │─────────────┘           │
         │  Ordered     │  │  Pipeline   │                         │
         │  Stops +     │  └──────┬──────┘                         │
         │  ETAs +      │         │                                 │
         │  Maps URL    │    ┌────┴─────────────────┐              │
                        │    │                       │              │
                        │    ▼                       ▼              │
                        │ ┌──────────────┐  ┌──────────────────┐  │
                        │ │ Google       │  │  Google OR-Tools  │  │
                        │ │ Distance     │  │  VRP Solver       │  │
                        │ │ Matrix API   │  │  (local, no API)  │  │
                        │ └──────────────┘  └──────────────────┘  │
                        └──────────────────────────────────────────┘
```

---

## 2. Request Lifecycle

Every call to `POST /api/v1/optimize-route` follows this exact pipeline:

```
Step 1 — INPUT VALIDATION
  Pydantic validates all fields.
  Rejects invalid coords, bad time formats, >25 stops, past departure times.
  Returns HTTP 422 immediately on validation failure.

Step 2 — BUILD LOCATION LIST
  Prepend driver's starting location to the stops list.
  Result: [driver_location, stop_1, stop_2, ..., stop_n]
  All as (lat, lng) tuples — no names, no PHI.

Step 3 — DISTANCE MATRIX (with traffic)
  Check Redis cache first (key = hash of coords + departure hour).
  Cache HIT  → use cached time_matrix and distance_matrix.
  Cache MISS → call Google Distance Matrix API with departure_time.
               Parse duration_in_traffic for each pair.
               Store result in Redis (TTL = 30 minutes).

Step 4 — VRP SOLVE (OR-Tools)
  Feed time_matrix + time_windows + service_times into OR-Tools.
  Apply constraints: time windows, single vehicle (MVP), max 600 min route.
  Set solver time limit to 10 seconds.
  Returns: ordered list of stop indices (optimal sequence).

Step 5 — BUILD FINAL ROUTE
  Reorder stops based on OR-Tools output.
  Calculate ETA and departure time at each stop.
  Build Google Maps directions URL (coordinates only).
  Calculate total distance and duration.

Step 6 — RETURN RESPONSE
  Return HTTP 200 with optimized stop list, ETAs, maps URL.
```

---

## 3. Component Design

### 3.1 API Layer (`app/api/routes.py`)
- Single POST endpoint: `/api/v1/optimize-route`
- GET endpoint: `/api/v1/health`
- Handles HTTP concerns only — no business logic
- Delegates entirely to the optimizer pipeline

### 3.2 Schemas (`app/models/schemas.py`)
- `Location` — lat/lng pair
- `Stop` — stop_id, location, time_window, service_time
- `OptimizeRouteRequest` — driver_location, stops[], departure_time
- `OptimizedStop` — stop_id, sequence, arrival_time, departure_time
- `OptimizeRouteResponse` — full result with maps URL and totals

### 3.3 Distance Matrix (`app/optimizer/distance_matrix.py`)
- Accepts list of Location objects + departure_time
- Checks Redis for cached result
- If miss: calls `googlemaps.distance_matrix()` with traffic parameters
- Parses response into `time_matrix[n][n]` (seconds) and `distance_matrix[n][n]` (meters)
- Stores result in Redis with 30-min TTL
- Returns both matrices

**Google API parameters used:**
```python
{
  "mode": "driving",
  "departure_time": departure_time,     # enables traffic data
  "traffic_model": "best_guess",        # realistic estimate
  "units": "metric"
}
```

### 3.4 VRP Solver (`app/optimizer/vrp_solver.py`)
- Wraps Google OR-Tools `pywrapcp.RoutingModel`
- Single vehicle (MVP)
- Index 0 = depot (driver start location)
- Constraints applied:
  - **Time windows** per stop (earliest/latest pickup in minutes from midnight)
  - **Service time** added to transit time at each node
  - **Slack** of 30 minutes (driver can wait up to 30 min at a stop if early)
  - **Route capacity** of 600 minutes (10-hour shift max)
- Search strategy: `PATH_CHEAPEST_ARC` + `GUIDED_LOCAL_SEARCH` metaheuristic
- Time limit: 10 seconds
- Returns ordered list of stop indices (0-based, excluding depot)

### 3.5 Route Builder (`app/optimizer/route_builder.py`)
- Accepts ordered stops + time_matrix + departure_time
- Calculates arrival time at each stop (cumulative travel time)
- Calculates departure time (arrival + service_time)
- Builds Google Maps URL: `https://www.google.com/maps/dir/lat,lng/lat,lng/...`
- Returns enriched stop list + totals

### 3.6 Config (`app/config.py`)
- Uses `pydantic-settings` to load from `.env`
- All sensitive values (API key) loaded from environment only
- Config object is a singleton (loaded once at startup)

---

## 4. Data Flow — HIPAA Boundary

This is the most critical design element. The HIPAA boundary must be respected at all times.

```
YOUR SYSTEM (caller)                    THIS SERVICE                    GOOGLE APIs
─────────────────────────────────────────────────────────────────────────────────

Patient Record:                         Receives:                       Receives:
{                                       {                               [
  name: "John Smith",                     stop_id: "uuid-001",   →       (40.71, -74.00),
  dob: "1955-04-12",         ──────▶      location: {            ──────▶ (40.73, -73.98),
  address: "123 Main St",                   lat: 40.71,                  (40.75, -73.97)
  appointment: "9:00 AM"                    lng: -74.00                ]
}                                         },                           
                                          ...                           NO NAMES.
PHI stays in caller's system.           }                               NO IDs.
                                                                        COORDS ONLY.
                                        stop_id is YOUR reference.
                                        Maps never see who it is.
```

**Rule:** The only data that ever crosses the boundary to Google is `(lat, lng)` coordinate pairs and a `departure_time` timestamp.

---

## 5. Caching Strategy

```
Cache Key:   MD5( sorted_coords_string + departure_hour )
Cache Value: { time_matrix: [[...]], distance_matrix: [[...]] }
TTL:         1800 seconds (30 minutes)

Why 30 minutes:
  - Traffic conditions change but not minute-by-minute
  - Same dispatch run often calls the API multiple times (retries, re-checks)
  - Balances freshness vs. API cost savings
```

Cache is **read-through** — the calling code never manages cache directly. The `build_distance_matrix()` function handles cache transparently.

---

## 6. Error Handling Strategy

| Scenario | HTTP Code | Behavior |
|---|---|---|
| Invalid input (bad coords, missing fields) | 422 | Pydantic auto-response with field details |
| Too many stops (>25) | 422 | Validation error with clear message |
| Past departure time | 422 | Validation error |
| Google API error | 502 | Log error, return upstream error message |
| OR-Tools no solution found | 422 | Return explanation (likely time windows too tight) |
| OR-Tools timeout | 200 | Return best solution found within 10 seconds |
| Redis unavailable | 200 | Log warning, skip cache, call Google directly |

Redis failure is **non-fatal** — the service degrades gracefully (more Google API calls, but still works).

---

## 7. Infrastructure

### Development
```yaml
# docker-compose.yml (dev)
services:
  api:
    build: .
    ports: ["8000:8000"]
    volumes: [".:/app"]          # hot reload
    env_file: .env
    depends_on: [redis]
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

### Production
```
Cloud:          AWS ECS (Fargate) or GCP Cloud Run
Container:      Docker (non-root user)
Load Balancer:  AWS ALB or GCP Load Balancer
Cache:          AWS ElastiCache (Redis) or GCP Memorystore
Secrets:        AWS Secrets Manager or GCP Secret Manager
Monitoring:     CloudWatch or GCP Cloud Monitoring
Logging:        CloudWatch Logs or GCP Cloud Logging
```

### HIPAA-Eligible Infrastructure
Both AWS and GCP will sign a Business Associate Agreement (BAA) for HIPAA workloads.
Ensure your account has BAA coverage before storing any PHI (not needed for this service
alone, but required for the broader system this feeds into).

---

## 8. OR-Tools Algorithm Details

The optimization problem is modeled as a **Capacitated Vehicle Routing Problem with Time Windows (CVRPTW)**:

- **Nodes:** 0 = depot (driver start), 1..n = pickup stops
- **Vehicle:** 1 (single driver, MVP)
- **Objective:** Minimize total travel time
- **Constraints:**
  - Each stop visited exactly once
  - Arrival at stop i must be within [earliest_i, latest_i]
  - Driver can wait if arriving early (slack ≤ 30 min)
  - Total route time ≤ 600 minutes

**Why OR-Tools over Google's `optimizeWaypoints`:**
- `optimizeWaypoints` does not support time windows
- OR-Tools gives us full constraint control
- OR-Tools is free (no API cost per call)
- OR-Tools runs locally (no latency, no rate limits)

---

## 9. API Contract

### Request
```
POST /api/v1/optimize-route
Content-Type: application/json

{
  "driver_id": "string",
  "driver_location": { "lat": float, "lng": float },
  "departure_time": "ISO8601 datetime string",
  "stops": [
    {
      "stop_id": "string (UUID, no PHI)",
      "location": { "lat": float, "lng": float },
      "earliest_pickup": "HH:MM",
      "latest_pickup": "HH:MM",
      "service_time_minutes": integer
    }
  ]
}
```

### Response
```
HTTP 200 OK
{
  "driver_id": "string",
  "optimized_stops": [
    {
      "stop_id": "string",
      "sequence": integer,
      "location": { "lat": float, "lng": float },
      "arrival_time": "HH:MM",
      "departure_time": "HH:MM"
    }
  ],
  "total_distance_km": float,
  "total_duration_minutes": float,
  "google_maps_url": "string",
  "optimization_score": float
}
```

---

## 10. Phase 2 — Real-Time Re-Routing Architecture

### 10.1 Overview

Real-time re-routing builds *on top of* the Phase 1 optimizer without replacing anything.
The core `run_optimization()` function is reused as-is — Phase 2 adds a trigger mechanism
around it: a WebSocket layer to receive live GPS from the driver, a Celery background worker
to detect delays and re-run optimization, and a React Native driver app to display updates.

```
┌──────────────────────────────────────────────────────────────────────┐
│                        DRIVER MOBILE APP                              │
│  React Native                                                         │
│  ┌─────────────┐  GPS every 15s   ┌─────────────────────────────┐   │
│  │  Map View   │ ────────────────▶ │   WebSocket Client          │   │
│  │  Stop List  │ ◀──────────────── │   Receives updated route    │   │
│  │  Navigation │   Updated Route   └─────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────┘
         │ WebSocket /ws/driver/{id}                    ▲
         ▼                                              │ Push updated route
┌──────────────────────────────────────────────────────────────────────┐
│                          FASTAPI BACKEND                              │
│                                                                       │
│  ┌──────────────────────┐   Publish GPS    ┌──────────────────────┐  │
│  │  WebSocket Handler   │ ───────────────▶ │  Redis               │  │
│  │  Receive GPS         │                  │  (Celery Broker      │  │
│  │  Store in Redis      │                  │  + Active State)     │  │
│  │  Check for alerts    │                  └──────────┬───────────┘  │
│  └──────────────────────┘                             │ Task queued  │
│                                                        ▼              │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                     CELERY WORKER                                │ │
│  │  1. Pull GPS update from queue                                   │ │
│  │  2. Run delay detection logic                                    │ │
│  │  3. If re-route needed → call run_optimization()  ✅ (reused)   │ │
│  │  4. Store new route in Redis                                     │ │
│  │  5. Publish to Redis Pub/Sub → WebSocket pushes to driver        │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

### 10.2 Phase 2 Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| **Real-Time Communication** | FastAPI WebSockets (built-in) | No new framework needed; async-native |
| **Background Tasks** | Celery + Redis broker | Off-thread optimization; retry logic; scales independently |
| **Active Driver State** | Redis (extended use) | Reuse existing Redis; fast R/W for GPS frequency; auto-TTL cleanup |
| **Driver Mobile App** | React Native | Single codebase iOS + Android; Google Maps SDK; background GPS support |
| **Push Notifications** | Firebase Cloud Messaging (FCM) | Route change alerts when app is backgrounded |
| **GPS Strategy** | Adaptive polling | Reduces battery drain and server load |
| **Celery Monitoring** | Flower dashboard | Visual task queue monitor |

---

### 10.3 New Project Structure (Phase 2 Additions)

```
route-optimizer/
├── app/
│   ├── websocket/                       ← NEW
│   │   ├── __init__.py
│   │   ├── manager.py                   # WebSocket connection manager
│   │   └── handlers.py                  # GPS receive + route push logic
│   │
│   ├── workers/                         ← NEW
│   │   ├── __init__.py
│   │   ├── celery_app.py                # Celery app instance + config
│   │   ├── tasks.py                     # detect_delay, trigger_reroute tasks
│   │   └── delay_detector.py            # shouldReroute() logic
│   │
│   ├── state/                           ← NEW
│   │   ├── __init__.py
│   │   └── driver_state.py              # Redis-backed active driver state
│   │
│   └── optimizer/
│       └── pipeline.py                  ← NEW — extracted run_optimization()
│
├── driver-app/                          ← NEW (React Native)
│   ├── src/
│   │   ├── screens/
│   │   │   ├── RouteScreen.tsx          # Map + ordered stop list
│   │   │   └── StopDetailScreen.tsx     # Individual stop info
│   │   ├── services/
│   │   │   ├── websocket.ts             # WebSocket connection manager
│   │   │   └── gps.ts                   # Background GPS tracker
│   │   └── store/
│   │       └── routeStore.ts            # Zustand state management
│   ├── package.json
│   └── app.json
```

---

### 10.4 WebSocket Endpoint Contract

```
WS /ws/driver/{driver_id}

Driver → Server (GPS update, every 15s):
{
  "type": "gps_update",
  "lat": 40.7128,
  "lng": -74.0060,
  "timestamp": "2024-01-15T08:14:30Z",
  "completed_stop_id": "stop_002"      // optional — when driver marks stop done
}

Server → Driver (route update, only when re-optimization triggered):
{
  "type": "route_updated",
  "reason": "traffic_delay",           // traffic_delay | stop_added | stop_cancelled
  "optimized_stops": [ ...stops ],
  "total_duration_minutes": 72,
  "google_maps_url": "https://..."
}

Server → Driver (status ping, every 60s):
{
  "type": "ping",
  "server_time": "2024-01-15T08:15:00Z"
}
```

---

### 10.5 Active Driver State in Redis

```python
# Keys stored per active driver shift (auto-expire after 12 hours)
{
  "driver:{id}:current_route":      { ...ordered_stops },         # TTL: 12h
  "driver:{id}:last_gps":           { lat, lng, timestamp },      # TTL: 5min
  "driver:{id}:completed_stops":    ["stop_001", "stop_003"],     # TTL: 12h
  "driver:{id}:original_duration":  78,                           # minutes, TTL: 12h
  "driver:{id}:status":             "active"                      # TTL: 12h
}
```

No PHI is stored in Redis — only stop IDs (internal UUIDs) and coordinates.

---

### 10.6 Delay Detection Logic

```python
# app/workers/delay_detector.py

DELAY_THRESHOLD_MINUTES   = 5     # re-route if >5 min behind schedule
TRAFFIC_INCREASE_RATIO    = 1.20  # re-route if remaining time grows >20%
MIN_REROUTE_INTERVAL_SEC  = 300   # never re-route more than once per 5 min

def should_reroute(driver_state: DriverState) -> tuple[bool, str]:

    # Rule 1: Driver is behind schedule
    if driver_state.schedule_delay_minutes > DELAY_THRESHOLD_MINUTES:
        return True, "traffic_delay"

    # Rule 2: Remaining route time has grown significantly
    if driver_state.remaining_duration > \
       driver_state.original_remaining_duration * TRAFFIC_INCREASE_RATIO:
        return True, "traffic_delay"

    # Rule 3: Dispatcher added or cancelled a stop
    if driver_state.stops_changed:
        return True, "stop_modified"

    # Rule 4: Cooldown — don't re-route too frequently
    if driver_state.seconds_since_last_reroute < MIN_REROUTE_INTERVAL_SEC:
        return False, ""

    return False, ""
```

---

### 10.7 Adaptive GPS Update Strategy

The driver app adjusts how frequently it sends GPS based on context — balancing
battery life, data usage, and server load:

```
Driver Status              Update Interval    Reason
─────────────────────────  ────────────────   ────────────────────────────
Stationary (speed < 5kph)  Every 60 seconds   No meaningful position change
Normal driving             Every 15 seconds   Standard tracking resolution
Approaching stop (<500m)   Every 5 seconds    Precise arrival detection
App backgrounded           Every 30 seconds   OS-managed background mode
```

---

### 10.8 React Native Driver App — Key Screens

**Route Screen (main screen)**
- Google Maps with route polyline drawn
- Ordered stop list below map (scroll view)
- Current stop highlighted with ETA countdown
- "Navigate" button → deep-links to Google Maps turn-by-turn
- Real-time badge when route is updated by server

**Stop Detail Screen**
- Patient first name only (minimal PHI)
- Mobility requirement icon (wheelchair, stretcher, etc.)
- Special pickup instructions
- "Arrived", "Picked Up", "Unable to Pick Up" action buttons
- Sends completed_stop_id back via WebSocket on confirmation

---

### 10.9 Updated Environment Variables (Phase 2 Additions)

```bash
# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Re-routing thresholds
DELAY_THRESHOLD_MINUTES=5
TRAFFIC_INCREASE_RATIO=1.20
MIN_REROUTE_INTERVAL_SECONDS=300

# Firebase (push notifications)
FIREBASE_SERVER_KEY=your_firebase_key_here

# Driver state TTL
DRIVER_STATE_TTL_SECONDS=43200    # 12 hours
```

---

### 10.10 Updated Docker Compose (Phase 2)

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [redis]

  celery-worker:
    build: .
    command: celery -A app.workers.celery_app worker --loglevel=info
    env_file: .env
    depends_on: [redis]

  celery-beat:
    build: .
    command: celery -A app.workers.celery_app beat --loglevel=info
    env_file: .env
    depends_on: [redis]

  flower:
    build: .
    command: celery -A app.workers.celery_app flower --port=5555
    ports: ["5555:5555"]
    depends_on: [redis]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

---

### 10.11 Complete Tech Stack — Phase 1 + Phase 2

| Layer | Phase 1 (MVP) | Phase 2 Addition |
|---|---|---|
| **API Framework** | FastAPI | + WebSocket support (built-in) |
| **Optimization Engine** | OR-Tools | Same — reused as-is ✅ |
| **Maps / Traffic** | Google Maps API | Same ✅ |
| **Cache** | Redis | + Celery broker + active driver state store |
| **Background Jobs** | None | + Celery workers + Celery Beat scheduler |
| **Driver App** | None | + React Native (iOS + Android) |
| **Push Notifications** | None | + Firebase Cloud Messaging |
| **Task Monitoring** | None | + Flower dashboard |
| **Backend Language** | Python 3.11 | Same ✅ |
| **App Language** | None | + TypeScript (React Native) |

---

### 10.12 Future Additions (Phase 3+)

- **Multi-driver fleet optimization:** Extend OR-Tools VRP to multiple vehicles
- **Auth layer:** API Gateway with JWT or API key validation
- **Dispatcher dashboard:** React.js web app with live map view of all drivers
- **Metrics:** Prometheus endpoint for response times, cache hit rates, re-routing frequency
- **Predictive re-routing:** Use historical traffic patterns to proactively re-optimize before delays hit
