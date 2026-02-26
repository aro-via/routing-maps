# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project

A HIPAA-compliant Route Optimization API for Non-Emergency Medical Transportation (NEMT). Given a driver's start location and patient pickup stops, it returns the most time-efficient route considering real-time traffic.

- **Phase 1** — REST API (this repo's MVP)
- **Phase 2** — Real-time re-routing via WebSocket + Celery + React Native driver app

Full requirements: `PRD.md` | Architecture: `ARCHITECTURE.md` | Task checklist: `TASKS.md` | Mobile API: `MOBILE_API_GUIDE.md`

---

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server
uvicorn app.main:app --reload --port 8000

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_vrp_solver.py -v

# Run a single test by name
pytest tests/test_schemas.py::test_invalid_coordinates -v

# Start Redis only
docker-compose up redis -d

# Full stack (API + Redis)
docker-compose up --build

# Phase 2: start Celery worker
celery -A app.workers.celery_app worker --loglevel=info

# Phase 2: start Flower dashboard (localhost:5555)
celery -A app.workers.celery_app flower
```

---

## Project Structure

Phase 1 layout (create these when building from scratch):

```
app/
├── main.py                      # FastAPI app + logging setup
├── config.py                    # pydantic-settings singleton
├── models/
│   └── schemas.py               # All Pydantic request/response models
├── api/
│   └── routes.py                # HTTP endpoints (no business logic)
├── optimizer/
│   ├── distance_matrix.py       # Redis cache + Google Distance Matrix API
│   ├── vrp_solver.py            # OR-Tools VRP solver
│   ├── route_builder.py         # ETA calculation + Maps URL builder
│   └── pipeline.py              # Phase 2: run_optimization() shared entry point
├── utils/
│   └── time_utils.py            # HH:MM ↔ minutes conversions
├── state/
│   └── driver_state.py          # Phase 2: Redis-backed driver session
├── workers/
│   ├── celery_app.py            # Phase 2: Celery instance + config
│   ├── tasks.py                 # Phase 2: process_gps_update task
│   └── delay_detector.py        # Phase 2: should_reroute() logic
└── websocket/
    ├── manager.py               # Phase 2: ConnectionManager + Pub/Sub listener
    └── handlers.py              # Phase 2: WebSocket endpoint logic
tests/
driver-app/                      # Phase 2: React Native app
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in values. All loaded via `app/config.py`.

```bash
# Required
GOOGLE_MAPS_API_KEY=your_key_here

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_TTL_SECONDS=1800           # Distance matrix cache TTL (30 min)

# Solver
MAX_OPTIMIZATION_SECONDS=10
MAX_STOPS_PER_ROUTE=25

# App
ENV=development
LOG_LEVEL=INFO

# Phase 2 — Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Phase 2 — Re-routing thresholds
DELAY_THRESHOLD_MINUTES=5
TRAFFIC_INCREASE_RATIO=1.20
MIN_REROUTE_INTERVAL_SECONDS=300
DRIVER_STATE_TTL_SECONDS=43200   # 12 hours

# Phase 2 — Push notifications
FIREBASE_SERVER_KEY=your_firebase_key_here
```

---

## Architecture

### Request Pipeline (Phase 1)

Every `POST /api/v1/optimize-route` flows through these components in order:

```
routes.py → distance_matrix.py → vrp_solver.py → route_builder.py → response
```

1. **`app/models/schemas.py`** — Pydantic validates input; rejects bad coords, >25 stops, past departure time, invalid time windows
2. **`app/optimizer/distance_matrix.py`** — checks Redis cache (key = MD5 of sorted coords + departure hour); on miss, calls Google Distance Matrix API with `departure_time` for traffic-aware `duration_in_traffic`; stores result for 30 min
3. **`app/optimizer/vrp_solver.py`** — feeds `time_matrix` + time windows + service times into OR-Tools `RoutingModel`; single vehicle; 10-second solver time limit; returns ordered stop indices
4. **`app/optimizer/route_builder.py`** — maps indices back to stops, calculates cumulative ETAs, builds Google Maps URL (coordinates only), computes totals

### Phase 2 Additions

```
WebSocket /ws/driver/{id}  →  ConnectionManager  →  Celery task  →  delay_detector  →  run_optimization()  →  Redis Pub/Sub  →  WebSocket push
```

- **`app/optimizer/pipeline.py`** — `run_optimization()` extracted from the HTTP handler so both the REST endpoint and Celery workers call it identically
- **`app/state/driver_state.py`** — Redis-backed driver session (GPS, completed stops, reroute timestamps); 12-hour TTL; no PHI
- **`app/workers/delay_detector.py`** — `should_reroute()` checks: schedule delay >5 min, remaining time grew >20%, or stops changed; cooldown of 5 min between reroutes
- **`app/websocket/manager.py`** — in-memory `dict[driver_id → WebSocket]`; subscribes to `reroute:{driver_id}` Redis Pub/Sub channel per connected driver

---

## Critical Rules

### HIPAA Boundary
Google APIs and Redis must never receive PHI. Only `(lat, lng)` pairs and timestamps cross the boundary. `stop_id` is a UUID — the caller's system owns the mapping to patient identity.

```python
# Correct
origins = [(s.location.lat, s.location.lng) for s in stops]

# Violation — never do this
origins = [f"{s.patient_name}, {s.address}" for s in stops]
```

This applies to: Google API calls, Redis keys, Redis values, log messages, Celery task arguments.

### Redis Failure is Non-Fatal
If Redis is unavailable, log a warning and call Google directly. Never raise an exception for a cache miss or connection error — the service must degrade gracefully.

### OR-Tools No-Solution = Loud Failure
If the VRP solver finds no feasible route, raise a clear exception (HTTP 422). Never return a partial or empty route silently.

---

## Conventions

- Files: `snake_case.py` | Classes: `PascalCase` | Constants: `UPPER_SNAKE_CASE`
- API endpoints: `/api/v1/resource-name` (kebab-case, versioned)
- All settings loaded via `app/config.py` (pydantic-settings); never hardcode values
- Use `logger = logging.getLogger(__name__)` — no `print()` statements
- Specific exceptions only — no bare `except:`
- Comments only on complex logic

## Testing

Always mock external dependencies — never make real API calls in tests:

```python
# Mock Google Maps client
with patch("app.optimizer.distance_matrix.googlemaps.Client") as mock_client:
    ...

# Mock Redis
with patch("app.optimizer.distance_matrix.redis.Redis") as mock_redis:
    ...
```

- VRP solver tests use synthetic `time_matrix` arrays (no Google API needed)
- Redis tests use `fakeredis` or `unittest.mock` — never a real Redis connection
- FastAPI endpoint tests use `TestClient` from `fastapi.testclient`

## Git Workflow

When completing tasks from TASKS.md:
- Create new branch named `feature/<task-number>-<brief-description>` before starting work
- Make atomic commits with conventional commit messages:
    - feat: for new features
    - fix: for bug fixes
    - docs: for documentation
    - test: for tests
    - refactor: for refactoring
- After completing a task, create a pull request with:
    - A descriptive title matching the task
    - A summary of changes made
    - Any testing notes or considerations
- Update the task checkbox in TASKS.md to mark it complete