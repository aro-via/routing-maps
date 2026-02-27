# HIPAA PHI Boundary Check — Phase 2

**Date:** 2026-02-27
**Scope:** Phase 2 source files (WebSocket, Celery, Redis state, React Native driver app)
**Result: PASS** — No PHI found in any data path.

---

## Findings by Category

### 1. WebSocket Messages — PASS

**Inbound (driver → server):**
```
{type, lat, lng, timestamp, completed_stop_id?}
```
- `completed_stop_id` is a UUID assigned by the dispatcher's back-office.
  The Route Optimization system never learns the patient identity behind it.

**Outbound (server → driver):**
```
{type: "route_updated", reason, optimized_stops[], total_distance_km,
 total_duration_minutes, google_maps_url}
```
Each `OptimizedStop` contains: `stop_id` (UUID), `sequence`, `location: {lat, lng}`,
`arrival_time`, `departure_time`. No names, addresses, or clinical data.

### 2. Celery Task Arguments — PASS

`process_gps_update` signature:
```python
def process_gps_update(driver_id, lat, lng, timestamp, completed_stop_id=None)
```
Return value: `{"rerouted": bool, "reason": str}` where `reason` is one of a fixed
set of operational strings (`traffic_delay`, `stop_modified`, …).

Celery Flower dashboard shows only these PHI-free arguments.

### 3. Redis Keys and Values — PASS

| Key pattern | Content |
|---|---|
| `driver:{driver_id}:state` | DriverState: UUIDs, coordinates, numeric durations |
| `distance_matrix:{hash}` | Serialised time/distance matrix (numbers only) |
| Pub/Sub channel: `reroute:{driver_id}` | Route update payload (see §1 outbound) |

No patient names, addresses, phone numbers, DOBs, SSNs, diagnoses, or
insurance identifiers appear in any Redis key or value.

### 4. Driver App Local Storage — PASS

The Zustand store (`routeStore.ts`) is in-memory only.
No `AsyncStorage`, `MMKV`, or SQLite persistence layer is used.

| Screen | Displays |
|---|---|
| `RouteScreen` | Stop sequence number, ETA — no PHI |
| `StopDetailScreen` | Sequence, coordinates, UUID, ETA — no PHI |

Cancellation reasons ("Patient not home", "Patient declined transport", …) are
predefined operational strings; they are not stored, and the corresponding
WebSocket message carries only `cancel:{stop_id}` — a UUID, not a name.

### 5. Firebase Push Notifications — N/A (not yet implemented)

`FIREBASE_SERVER_KEY` is defined in `app/config.py` but no FCM payload
construction code exists. When implemented, payloads must contain only
`driver_id` and operational reason strings — never stop details or patient info.

### 6. Flower Dashboard Access — PASS (with fix applied)

HTTP basic authentication added via `--basic_auth` flag in `docker-compose.yml`.
Set the `FLOWER_BASIC_AUTH=user:password` environment variable for production;
default `admin:changeme` applies locally.
Celery task arguments visible in Flower contain only PHI-free values (see §2).

---

## Data Flow Summary

```
Dispatcher back-office               Route Optimization System
────────────────────────             ─────────────────────────────────────────
patient_id  ──►  stop_id (UUID)  ──► all internal processing uses stop_id only
patient_name     NOT TRANSMITTED     Google API receives: [(lat, lng), ...]
address                              Redis stores: lat/lng, UUIDs, numbers
phone                                Driver app shows: seq#, ETA, lat/lng
diagnosis
```

The PHI boundary is enforced at the API input layer (`schemas.py`): the
`OptimizeRouteRequest` schema accepts `stop_id` (string), `location` (lat/lng),
time windows, and service duration. No PHI field exists in any schema.
