# TASKS.md — Implementation Checklist
**Purpose:** Step-by-step guide for Claude Code to build the Route Optimizer (Phase 1 MVP + Phase 2 Real-Time Re-Routing).
Work through tasks in order. Do not skip ahead. Complete and validate each phase before starting the next.

---

## Repository

**Remote:** `https://github.com/aro-via/routing-maps.git`

```bash
git remote add origin https://github.com/aro-via/routing-maps.git
```

---

## Git Workflow Per Task

For every task:
1. Sync with remote `main` first:
    ```bash
    git fetch origin
    git checkout main
    git pull origin main
    ```
2. Create a new branch from `main`:
    ```bash
    git checkout -b feature/<task-number>-<description>
    ```
3. Implement changes and commit
4. Push the branch to remote:
    ```bash
    git push -u origin feature/<task-number>-<description>
    ```
5. `gh pr create` targeting `main` — **always create a PR, never push directly to main**
6. Check off task boxes in this file
7. **Do NOT merge the PR** — the user merges manually via github.com

---

## How to Use This File

1. Start Claude Code in the project directory: `claude`
2. Tell Claude Code: *"Read CLAUDE.md and TASKS.md, then start with Task 1"*
3. Claude Code will implement each task, run tests, and check items off
4. After each task, verify tests pass before moving on

---

## Phase 1 — Project Foundation

### Task 1: Initialize Project Structure
- [x] Create Readme.md file with prerequisites
- [x] Create all directories: `app/`, `app/models/`, `app/optimizer/`, `app/api/`, `app/utils/`, `tests/`
- [x] Create all `__init__.py` files
- [x] Create `requirements.txt` with exact pinned versions
- [x] Create `.env.example` with all required environment variables
- [x] Create `.gitignore` (ignore `.env`, `__pycache__`, `.pytest_cache`, `*.pyc`)
- [x] Verify project structure matches the layout defined in `CLAUDE.md`
- [x] Commit and push the changes

**Validation:** Run `find . -name "*.py" | head -20` and confirm structure looks correct.

---

### Task 2: Configuration & Settings
- [x] Create `app/config.py` using `pydantic-settings`
- [x] Load all settings from environment variables (no hardcoded values)
- [x] Settings to include:
  - `GOOGLE_MAPS_API_KEY: str`
  - `REDIS_HOST: str = "localhost"`
  - `REDIS_PORT: int = 6379`
  - `REDIS_TTL_SECONDS: int = 1800`
  - `MAX_OPTIMIZATION_SECONDS: int = 10`
  - `MAX_STOPS_PER_ROUTE: int = 25`
  - `ENV: str = "development"`
  - `LOG_LEVEL: str = "INFO"`
- [x] Settings class uses `model_config = SettingsConfigDict(env_file=".env")`
- [x] Export a single `settings` singleton instance

**Validation:** Write a quick test that loads settings and confirms `MAX_STOPS_PER_ROUTE == 25`.

---

### Task 3: Pydantic Schemas
- [x] Create `app/models/schemas.py`
- [x] Implement `Location` model with `lat: float` and `lng: float`
  - Add validator: lat must be between -90 and 90
  - Add validator: lng must be between -180 and 180
- [x] Implement `Stop` model with all fields from ARCHITECTURE.md
  - Add validator: `earliest_pickup` < `latest_pickup`
  - Add validator: time format is `HH:MM`
  - Add validator: `service_time_minutes` between 1 and 60
- [x] Implement `OptimizeRouteRequest` model
  - Add validator: stops list has between 2 and 25 items
  - Add validator: `departure_time` is not in the past
- [x] Implement `OptimizedStop` model
- [x] Implement `OptimizeRouteResponse` model
- [x] Write `tests/test_schemas.py` with tests for:
  - Valid request passes validation
  - Invalid coordinates rejected
  - Too many stops rejected
  - Invalid time window (earliest > latest) rejected
  - Past departure time rejected

**Validation:** `pytest tests/test_schemas.py -v` — all tests pass.

---

### Task 4: FastAPI App Entry Point
- [x] Create `app/main.py` with FastAPI app instance
- [x] Configure logging into database table based on `settings.LOG_LEVEL`
- [x] Include router from `app/api/routes.py`
- [x] Add startup event that logs app is ready
- [x] Create `app/api/routes.py` with placeholder endpoints:
  - `POST /api/v1/optimize-route` → returns `{"status": "not implemented"}` for now
  - `GET /api/v1/health` → returns `{"status": "healthy"}`
- [x] Confirm app starts: `uvicorn app.main:app --reload`
- [x] Confirm `/docs` Swagger UI loads in browser
- [x] Confirm `GET /api/v1/health` returns 200

**Validation:** App starts without errors. `/docs` loads. `/api/v1/health` returns 200.

---

## Phase 2 — Core Optimizer

### Task 5: Time Utilities
- [x] Create `app/utils/time_utils.py`
- [x] Implement `time_str_to_minutes(time_str: str) -> int`
  - Input: `"08:30"` → Output: `510`
- [x] Implement `minutes_to_time_str(minutes: int) -> str`
  - Input: `510` → Output: `"08:30"`
- [x] Implement `add_minutes_to_time(time_str: str, minutes: int) -> str`
  - Input: `"08:30"`, `45` → Output: `"09:15"`
  - Handle day overflow (should not happen in practice but handle gracefully)
- [x] Write `tests/test_time_utils.py` with edge cases:
  - Midnight (0 minutes → `"00:00"`)
  - End of day (1439 minutes → `"23:59"`)
  - Overflow protection

**Validation:** `pytest tests/test_time_utils.py -v` — all tests pass.

---

### Task 6: Distance Matrix Module
- [x] Create `app/optimizer/distance_matrix.py`
- [x] Implement Redis connection using settings
- [x] Implement `_build_cache_key(locations, departure_time) -> str`
  - Use MD5 of sorted coordinates + departure hour
- [x] Implement `build_distance_matrix(locations, departure_time) -> dict`
  - Check Redis cache first
  - On miss: call `googlemaps.distance_matrix()` with:
    - `mode="driving"`
    - `departure_time=departure_time`
    - `traffic_model="best_guess"`
    - `units="metric"`
  - Parse response into `time_matrix` (seconds) and `distance_matrix` (meters)
  - Use `duration_in_traffic` if available, fallback to `duration`
  - Handle `element['status'] != 'OK'` gracefully (set to 999999)
  - Cache result in Redis with TTL
  - Return `{"time_matrix": [...], "distance_matrix": [...]}`
- [x] Write `tests/test_distance_matrix.py` using mocked Google client:
  - Test cache hit returns cached value
  - Test cache miss calls Google API
  - Test response parsing extracts `duration_in_traffic` correctly
  - Test handles Google API error gracefully

**Validation:** `pytest tests/test_distance_matrix.py -v` — all tests pass.

---

### Task 7: VRP Solver (OR-Tools)
- [x] Create `app/optimizer/vrp_solver.py`
- [x] Implement `solve_vrp(time_matrix, stops, service_times, num_vehicles=1) -> List[int]`
  - Set up `RoutingIndexManager` with depot at index 0
  - Register transit callback (travel time + service time)
  - Set arc cost evaluator
  - Add `Time` dimension with:
    - slack_max = 30 minutes
    - capacity = 1440 minutes (full day, absolute time-of-day values)
    - fix_start_cumul_to_zero = False
  - Apply time window constraints for each stop
  - Set search parameters:
    - `PATH_CHEAPEST_ARC` first solution strategy
    - `GUIDED_LOCAL_SEARCH` metaheuristic
    - Time limit = `settings.MAX_OPTIMIZATION_SECONDS`
  - Solve and extract ordered route
  - Raise clear exception if no solution found
  - Return list of stop indices in optimal order (0-based, depot excluded)
- [x] Write `tests/test_vrp_solver.py`:
  - Test 3-stop problem with known optimal solution
  - Test that time windows are respected in output
  - Test raises exception when windows are impossible
  - Test single stop (edge case)
  - Test returns stops in different order than input when optimization warrants it

**Validation:** `pytest tests/test_vrp_solver.py -v` — all tests pass.

---

### Task 8: Route Builder
- [x] Create `app/optimizer/route_builder.py`
- [x] Implement `build_final_route(driver_location, ordered_stops, time_matrix, departure_time) -> dict`
  - Calculate cumulative arrival time at each stop
  - Calculate departure time (arrival + service_time_minutes)
  - Build list of `OptimizedStop` objects with sequence numbers
  - Build Google Maps URL with coordinates only (no PHI)
  - Calculate total distance from distance_matrix
  - Calculate total duration in minutes
  - Return full result dict
- [x] Implement `_build_maps_url(origin, stops) -> str`
  - Format: `https://www.google.com/maps/dir/lat,lng/lat,lng/...`
  - Coordinates only — never include names or IDs
- [x] Write `tests/test_route_builder.py`:
  - Test arrival times calculated correctly
  - Test departure times include service time
  - Test Google Maps URL format is correct
  - Test URL contains only coordinates (no stop IDs or names)
  - Test sequence numbers start at 1

**Validation:** `pytest tests/test_route_builder.py -v` — all tests pass.

---

## Phase 3 — API Integration

### Task 9: Wire Up the Full Pipeline
- [x] Update `app/api/routes.py` to implement the full `/api/v1/optimize-route` endpoint:
  - Call `build_distance_matrix()`
  - Call `solve_vrp()`
  - Call `build_final_route()`
  - Return `OptimizeRouteResponse`
- [x] Add proper error handling for each step (see ARCHITECTURE.md Section 6)
- [x] Update `/api/v1/health` to check:
  - Redis connectivity (ping)
  - Google Maps API key presence (not validity — don't make API calls on health check)
  - Return `{"status": "healthy", "redis": "ok", "maps_api": "configured"}`
- [x] Write `tests/test_api.py` using FastAPI `TestClient`:
  - Test valid request returns 200 with correct response shape
  - Test invalid coordinates return 422
  - Test too many stops returns 422
  - Test health endpoint returns 200
  - Test missing required fields return 422
  - Use mocked Google Maps client (don't make real API calls in tests)

**Validation:** `pytest tests/test_api.py -v` — all tests pass.

---

### Task 10: End-to-End Test
- [x] Create `tests/test_e2e.py` with a realistic scenario:
  - 5 stops with varying time windows
  - Assert optimized route is different from input order
  - Assert all time windows are respected
  - Assert total duration is less than naive (input order) duration
  - Assert Google Maps URL is valid format
  - Assert no stop_id or PHI appears in the maps URL
- [x] Run full test suite: `pytest tests/ -v`
- [x] Fix any failures

**Validation:** `pytest tests/ -v` — ALL tests pass. Zero failures.

---

## Phase 4 — Docker & Deployment Prep

### Task 11: Dockerfile
- [ ] Create `Dockerfile`:
  - Base image: `python:3.11-slim`
  - Create non-root user (`appuser`) — HIPAA / security requirement
  - Copy and install requirements
  - Copy app code
  - Expose port 8000
  - Run as non-root user
  - CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- [ ] Create `docker-compose.yml`:
  - `api` service (build from Dockerfile)
  - `redis` service (redis:7-alpine)
  - Proper `depends_on` and `env_file`
  - Volume mount for development hot reload
- [ ] Build and run: `docker-compose up --build`
- [ ] Confirm service is reachable at `http://localhost:8000/api/v1/health`

**Validation:** `curl http://localhost:8000/api/v1/health` returns `{"status": "healthy"}`.

---

### Task 12: README.md
- [ ] Create `README.md` with:
  - Project description (one paragraph)
  - Prerequisites (Python 3.11+, Docker, Google Maps API key)
  - Setup instructions (clone, copy .env.example, add API key, run)
  - How to run locally (with and without Docker)
  - How to run tests
  - Sample API request and response (copy from ARCHITECTURE.md)
  - Link to `/docs` for interactive API explorer
  - HIPAA note: what data is and is not sent to Google

**Validation:** A new developer can follow README.md and get the service running from scratch.

---

## Phase 5 — Final Review

### Task 13: Code Quality Pass
- [ ] Run through every file and confirm:
  - No hardcoded API keys or secrets
  - No PHI or patient names in any variable, log message, or comment
  - Every public function has a docstring
  - All imports are used
  - No `print()` statements (use `logger` instead)
  - No bare `except:` clauses
- [ ] Confirm `pytest tests/ -v` still passes after cleanup

---

### Task 14: HIPAA Final Check
- [ ] Search entire codebase for any of these strings (should find ZERO occurrences in actual data):
  - `patient_name`
  - `first_name` / `last_name`
  - `dob` / `date_of_birth`
  - Any hardcoded personal data
- [ ] Confirm Google Maps URL in response contains ONLY coordinates
- [ ] Confirm Redis cache keys contain ONLY hashes (no readable location names)
- [ ] Confirm no PHI appears in log output

---

### Task 15: Smoke Test in Docker
- [ ] Start full stack: `docker-compose up --build`
- [ ] Send a test request with 4–5 mock stops
- [ ] Confirm response includes reordered stops, ETAs, and Maps URL
- [ ] Confirm Maps URL opens correctly in a browser
- [ ] Run `docker-compose down`

---

## Phase 1 Complete ✅

When all checkboxes above (Tasks 1–15) are ticked:
- The Route Optimizer MVP is production-ready
- All tests pass
- HIPAA data handling is verified
- Service runs cleanly in Docker
- A new developer can onboard from the README alone

**→ Proceed to Phase 2 below.**

---
---

## Phase 2 — Real-Time Re-Routing

> Before starting Phase 2, read Section 10 of `ARCHITECTURE.md` in full.
> Tell Claude Code: *"Phase 1 is complete. Read ARCHITECTURE.md Section 10, then start Phase 2 from Task 16."*

---

## Phase 6 — Backend Re-Routing Infrastructure

### Task 16: Extract Optimizer Pipeline
- [ ] Create `app/optimizer/pipeline.py`
- [ ] Move the core optimization logic out of the HTTP endpoint into a standalone async function:
  ```python
  async def run_optimization(driver_location, stops, departure_time) -> OptimizeRouteResponse
  ```
- [ ] Update `app/api/routes.py` POST endpoint to call `run_optimization()` — no logic change, just delegation
- [ ] Confirm all Phase 1 tests still pass after refactor: `pytest tests/ -v`
- [ ] This function will be called identically from both the HTTP handler and the Celery worker

**Validation:** `pytest tests/ -v` — zero regressions. Function is importable from `app.optimizer.pipeline`.

---

### Task 17: Active Driver State (Redis)
- [ ] Create `app/state/driver_state.py`
- [ ] Implement `DriverState` dataclass with fields:
  - `driver_id`, `current_route`, `last_gps`, `completed_stop_ids`
  - `original_remaining_duration`, `schedule_delay_minutes`
  - `last_reroute_timestamp`, `stops_changed`, `status`
- [ ] Implement `save_driver_state(state: DriverState)` — serialize to Redis with 12-hour TTL
- [ ] Implement `get_driver_state(driver_id: str) -> DriverState | None`
- [ ] Implement `update_driver_gps(driver_id, lat, lng, timestamp)`
- [ ] Implement `mark_stop_completed(driver_id, stop_id)`
- [ ] Implement `clear_driver_state(driver_id)` — called at end of shift
- [ ] Confirm no PHI stored — only stop IDs (UUIDs) and coordinates
- [ ] Write `tests/test_driver_state.py`:
  - Test save and retrieve round-trip
  - Test GPS update modifies only last_gps
  - Test completed stops accumulate correctly
  - Test expired state returns None

**Validation:** `pytest tests/test_driver_state.py -v` — all pass.

---

### Task 18: Celery Setup
- [ ] Add to `requirements.txt`: `celery==5.3+`, `flower==2.0+`
- [ ] Create `app/workers/celery_app.py`:
  - Celery instance using Redis as broker (`CELERY_BROKER_URL`)
  - Redis as result backend (`CELERY_RESULT_BACKEND`)
  - Configure serializer as JSON
  - Set task time limits (soft: 15s, hard: 30s)
- [ ] Add new environment variables to `.env.example`:
  - `CELERY_BROKER_URL=redis://localhost:6379/1`
  - `CELERY_RESULT_BACKEND=redis://localhost:6379/2`
- [ ] Confirm Celery worker starts: `celery -A app.workers.celery_app worker --loglevel=info`
- [ ] Confirm Flower dashboard starts: `celery -A app.workers.celery_app flower`

**Validation:** Flower UI visible at `http://localhost:5555`. Worker shows as online.

---

### Task 19: Delay Detection Logic
- [ ] Create `app/workers/delay_detector.py`
- [ ] Implement `should_reroute(driver_state: DriverState) -> tuple[bool, str]`
  - Rule 1: `schedule_delay_minutes > DELAY_THRESHOLD_MINUTES` → `(True, "traffic_delay")`
  - Rule 2: remaining duration > original × `TRAFFIC_INCREASE_RATIO` → `(True, "traffic_delay")`
  - Rule 3: `stops_changed == True` → `(True, "stop_modified")`
  - Rule 4: cooldown — if last re-route was < `MIN_REROUTE_INTERVAL_SECONDS` ago → `(False, "")`
  - Default → `(False, "")`
- [ ] Load all thresholds from `settings` (not hardcoded)
- [ ] Add to `.env.example`:
  - `DELAY_THRESHOLD_MINUTES=5`
  - `TRAFFIC_INCREASE_RATIO=1.20`
  - `MIN_REROUTE_INTERVAL_SECONDS=300`
- [ ] Write `tests/test_delay_detector.py`:
  - Test each rule triggers independently
  - Test cooldown prevents back-to-back re-routing
  - Test no false positives on normal on-time driver

**Validation:** `pytest tests/test_delay_detector.py -v` — all pass.

---

### Task 20: Celery Re-Routing Task
- [ ] Create `app/workers/tasks.py`
- [ ] Implement `@celery_app.task process_gps_update(driver_id, lat, lng, timestamp, completed_stop_id=None)`:
  - Load driver state from Redis
  - Update GPS in driver state
  - Mark stop completed if `completed_stop_id` provided
  - Call `should_reroute()` — if False, save state and return
  - If True: call `run_optimization()` with remaining stops + current driver GPS
  - Save new route to driver state
  - Publish new route to Redis Pub/Sub channel `reroute:{driver_id}`
  - Update `last_reroute_timestamp`
  - Log the re-routing event (no PHI in log)
- [ ] Write `tests/test_tasks.py` with mocked Redis and optimizer:
  - Test GPS update stored correctly
  - Test re-routing triggered when delay detected
  - Test re-routing NOT triggered when on schedule
  - Test completed stop removed from remaining stops

**Validation:** `pytest tests/test_tasks.py -v` — all pass.

---

## Phase 7 — WebSocket Layer

### Task 21: WebSocket Connection Manager
- [ ] Create `app/websocket/manager.py`
- [ ] Implement `ConnectionManager` class:
  - `connect(driver_id, websocket)` — store active connection
  - `disconnect(driver_id)` — remove connection, clear driver state
  - `send_route_update(driver_id, route_data)` — push JSON to driver
  - `active_connections: dict[str, WebSocket]` — in-memory connection registry
- [ ] Implement Redis Pub/Sub listener:
  - Subscribe to `reroute:{driver_id}` channel
  - On message received → call `send_route_update()`
  - Run as async background task per connected driver
- [ ] Write `tests/test_websocket_manager.py`:
  - Test connect adds to registry
  - Test disconnect removes from registry
  - Test send_route_update calls websocket.send_json

**Validation:** `pytest tests/test_websocket_manager.py -v` — all pass.

---

### Task 22: WebSocket Endpoint
- [ ] Create `app/websocket/handlers.py`
- [ ] Add to `app/api/routes.py`:
  ```python
  @app.websocket("/ws/driver/{driver_id}")
  async def driver_route_stream(websocket: WebSocket, driver_id: str)
  ```
- [ ] Implement handler:
  - Accept WebSocket connection
  - Register with `ConnectionManager`
  - Start Redis Pub/Sub listener as background task
  - Loop: receive GPS JSON → validate → dispatch `process_gps_update` Celery task
  - Handle `completed_stop_id` field if present in message
  - On disconnect: clean up connection + cancel background task
- [ ] Handle connection errors and unexpected disconnects gracefully
- [ ] Message format must match contract in `ARCHITECTURE.md` Section 10.4
- [ ] Write `tests/test_websocket_endpoint.py` using FastAPI `TestClient` WebSocket support:
  - Test connection accepted
  - Test GPS message dispatches Celery task
  - Test disconnection cleans up properly

**Validation:** `pytest tests/test_websocket_endpoint.py -v` — all pass.

---

### Task 23: Update Docker Compose for Phase 2
- [ ] Update `docker-compose.yml` to add:
  - `celery-worker` service
  - `celery-beat` service
  - `flower` service (port 5555)
- [ ] Ensure all services share the same Redis instance
- [ ] Test full stack starts cleanly: `docker-compose up --build`
- [ ] Confirm Flower at `http://localhost:5555`
- [ ] Confirm WebSocket endpoint reachable at `ws://localhost:8000/ws/driver/test`

**Validation:** All 5 services start without errors (`api`, `celery-worker`, `celery-beat`, `flower`, `redis`).

---

## Phase 8 — React Native Driver App

### Task 24: React Native Project Setup
- [ ] Initialize React Native project in `driver-app/` directory:
  ```bash
  npx react-native@latest init DriverApp --directory driver-app
  ```
- [ ] Install required libraries:
  - `react-native-maps` — map display
  - `react-native-background-geolocation` — GPS tracking
  - `@react-native-firebase/messaging` — push notifications
  - `react-navigation` + `@react-navigation/native-stack` — screen navigation
  - `zustand` — state management
  - `@react-native-async-storage/async-storage` — local storage
- [ ] Configure Google Maps SDK (add API key to `AndroidManifest.xml` and `AppDelegate`)
- [ ] Configure Firebase project and add `google-services.json` / `GoogleService-Info.plist`
- [ ] Confirm app builds and runs on simulator: `npx react-native run-ios` or `run-android`

**Validation:** App launches on simulator showing a blank screen with no errors.

---

### Task 25: GPS Service & WebSocket Client
- [ ] Create `driver-app/src/services/gps.ts`
  - Start/stop background GPS tracking
  - Adaptive update intervals (see `ARCHITECTURE.md` Section 10.7)
  - Callback fires with `{ lat, lng, timestamp, speed }`
- [ ] Create `driver-app/src/services/websocket.ts`
  - Connect to `ws://{SERVER_URL}/ws/driver/{driver_id}`
  - Send GPS update on each location callback
  - Listen for incoming `route_updated` messages
  - Auto-reconnect on disconnect (exponential backoff, max 5 retries)
  - Handle `ping` messages (respond with `pong`)
- [ ] Write unit tests for reconnect logic and message parsing

**Validation:** GPS service fires callbacks. WebSocket connects to local server and sends/receives messages.

---

### Task 26: Zustand Route Store
- [ ] Create `driver-app/src/store/routeStore.ts`
- [ ] State to manage:
  - `currentRoute: OptimizedStop[]`
  - `currentStopIndex: number`
  - `driverStatus: 'idle' | 'active' | 'completed'`
  - `lastUpdated: string`
  - `routeUpdateReason: string | null`
- [ ] Actions:
  - `setRoute(stops)` — set initial or updated route
  - `completeCurrentStop()` — advance to next stop
  - `resetRoute()` — end of shift cleanup
- [ ] Route updates from WebSocket call `setRoute()` automatically

**Validation:** Store updates correctly when `setRoute()` and `completeCurrentStop()` are called in isolation.

---

### Task 27: Route Screen
- [ ] Create `driver-app/src/screens/RouteScreen.tsx`
- [ ] Map view (full screen top half):
  - Show current driver location (blue dot)
  - Show all remaining stops as numbered markers
  - Draw route polyline between stops
  - Auto-pan to current stop when route updates
- [ ] Stop list (scrollable bottom half):
  - Each stop shows: sequence number, estimated arrival time
  - Current stop highlighted
  - Completed stops shown with strikethrough
- [ ] "Navigate" button:
  - Deep-links to Google Maps: `comgooglemaps://?daddr={lat},{lng}`
  - Fallback to browser Google Maps URL on non-Google-Maps devices
- [ ] Route update banner:
  - When `routeUpdateReason` is set, show a dismissible banner: "Route updated due to traffic"

**Validation:** Screen renders with mock route data. Navigate button opens Google Maps.

---

### Task 28: Stop Detail Screen
- [ ] Create `driver-app/src/screens/StopDetailScreen.tsx`
- [ ] Display (minimum PHI — first name only):
  - Stop sequence number and ETA
  - Mobility requirement icon (wheelchair, stretcher, ambulatory)
  - Special pickup instructions (free text)
- [ ] Action buttons:
  - **"Arrived"** — records arrival, starts service timer
  - **"Picked Up"** — sends `completed_stop_id` via WebSocket, advances route
  - **"Unable to Pick Up"** — sends cancellation flag, opens reason selector
- [ ] Confirm "Picked Up" action sends correct WebSocket message

**Validation:** All three buttons trigger correct WebSocket messages visible in server logs.

---

## Phase 9 — End-to-End Testing & Phase 2 Sign-Off

### Task 29: End-to-End Re-Routing Test
- [ ] Create `tests/test_rerouting_e2e.py`
- [ ] Simulate a full re-routing scenario:
  1. POST `/api/v1/optimize-route` → get initial route
  2. Connect WebSocket for driver
  3. Send 5 GPS updates simulating driver moving normally → confirm no re-route triggered
  4. Send GPS update simulating driver 6 minutes behind schedule → confirm re-route triggered
  5. Confirm new route received on WebSocket
  6. Confirm new route is different from original (optimizer ran)
  7. Confirm all time windows still respected in new route
  8. Confirm no PHI in any WebSocket message or log

**Validation:** `pytest tests/test_rerouting_e2e.py -v` — all pass.

---

### Task 30: Phase 2 HIPAA Check
- [ ] Confirm no PHI in WebSocket messages (stop IDs only, no names)
- [ ] Confirm no PHI in Celery task arguments or result payloads
- [ ] Confirm no PHI in Redis keys or values
- [ ] Confirm driver app stores no PHI in local device storage
- [ ] Confirm Firebase push notification payloads contain no PHI
- [ ] Confirm Flower dashboard accessible only on internal network (not public)

---

### Task 31: Full Stack Smoke Test
- [ ] Start full Phase 2 stack: `docker-compose up --build`
- [ ] Build and run driver app on simulator
- [ ] Connect driver app WebSocket to local server
- [ ] Manually simulate delay scenario → confirm route update received on app
- [ ] Confirm Flower shows Celery tasks executed
- [ ] Confirm route update banner appears on Route Screen
- [ ] Run `docker-compose down`

---

## All Phases Complete ✅

When all checkboxes in Tasks 1–31 are ticked:

**Phase 1 delivered:**
- Traffic-aware route optimization API
- Full test coverage
- HIPAA-safe data handling
- Dockerized and production-ready

**Phase 2 delivered:**
- Real-time GPS tracking via WebSocket
- Automated delay detection
- Live route re-optimization via Celery
- React Native driver app (iOS + Android)
- Full end-to-end re-routing flow verified

**Phase 3 options (future):**
- Multi-driver fleet optimization
- Dispatcher web dashboard (React.js)
- Predictive re-routing using historical traffic
- Auth layer (API Gateway + JWT)
- Prometheus metrics + alerting
