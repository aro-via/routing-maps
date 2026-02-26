# PRD — Route Optimizer Service
**Version:** 1.0 (MVP)
**Status:** Ready for Development
**Last Updated:** February 2026

---

## 1. Problem Statement

Medical transportation drivers (NEMT) need to pick up multiple patients during peak hours.
Without route optimization, drivers often follow an inefficient order — leading to late pickups,
missed appointment windows, and wasted fuel. Manual dispatching cannot account for real-time
traffic conditions.

---

## 2. Goal

Build a single API service that accepts a driver's starting location and a list of patient
pickup stops, and returns the **optimal pickup order** that minimizes total travel time
while respecting each patient's pickup time window and accounting for live traffic.

---

## 3. Users

| User | How They Interact |
|---|---|
| **Dispatcher** | Calls the API to generate an optimized route before each driver's shift |
| **Developer / Integration** | Integrates the API into a dispatch management system or driver app |
| **Driver** | Receives the optimized stop list (via the calling application, not directly) |

---

## 4. Functional Requirements

### FR-01 — Accept Route Optimization Request
The API must accept a POST request containing:
- Driver's current GPS coordinates (latitude, longitude)
- A list of 2–25 pickup stops, each with:
  - A unique stop identifier (internal ID, no PHI)
  - GPS coordinates of the pickup location
  - Earliest acceptable pickup time (e.g. `"08:00"`)
  - Latest acceptable pickup time (e.g. `"08:30"`)
  - Estimated service time at the stop in minutes (e.g. `3`)
- Requested departure time (used to pull accurate traffic data)

### FR-02 — Fetch Traffic-Aware Travel Times
The service must call the Google Distance Matrix API using the departure time to retrieve
real traffic-based travel durations between all location pairs. It must use
`duration_in_traffic` (not `duration`) wherever available.

### FR-03 — Optimize Stop Order
The service must use Google OR-Tools to solve the Vehicle Routing Problem (VRP) and
determine the stop sequence that:
- Minimizes total travel time
- Respects each stop's time window (earliest and latest pickup time)
- Accounts for service time spent at each stop

### FR-04 — Return Enriched Response
The API must return:
- The optimized list of stops in sequence order
- Estimated arrival and departure time at each stop
- Total route distance in kilometers
- Total estimated route duration in minutes
- A Google Maps URL the driver can open for turn-by-turn navigation
- An optimization score (time saved vs. naive ordering)

### FR-05 — Cache Distance Matrix Results
To reduce Google API costs and latency, distance matrix results for the same set of
locations within the same hour must be cached in Redis with a 30-minute TTL.

### FR-06 — Input Validation
The API must validate:
- Coordinates are valid lat/lng ranges
- At least 2 stops are provided
- No more than 25 stops are provided (Google Maps API limit)
- Time windows are valid (earliest < latest, valid HH:MM format)
- Departure time is not in the past

### FR-07 — HIPAA-Safe External Calls
No patient names, identifiers, or any PHI must appear in any call made to Google APIs.
Only GPS coordinates and timestamps are permitted in external API requests.

### FR-08 — Health Check Endpoint
A `GET /api/v1/health` endpoint must return service status, Redis connectivity, and
Google Maps API key validity.

---

## 5. Non-Functional Requirements

### NFR-01 — Performance
- API response time must be under **5 seconds** for up to 15 stops
- API response time must be under **10 seconds** for 15–25 stops
- OR-Tools solver must have a hard time limit of 10 seconds

### NFR-02 — Reliability
- The service must return HTTP 200 for valid requests
- If Google Distance Matrix API is unavailable, return HTTP 502 with a clear error message
- If no feasible route exists (time windows too tight), return HTTP 422 with explanation

### NFR-03 — HIPAA Compliance
- No PHI in any external API call (Google Maps, Redis keys, logs)
- Use stop_id (internal UUID) as the only identifier in all processing
- Logs must never contain patient-identifying information

### NFR-04 — Scalability
- The service must be stateless — any instance can handle any request
- Redis is the only shared state (cache only, not session)
- Must support horizontal scaling behind a load balancer

### NFR-05 — Security
- API key must be provided via environment variable, never hardcoded
- All inter-service communication over HTTPS/TLS in production
- Docker container must not run as root

---

## 6. Out of Scope (MVP)

The following are explicitly excluded from this version:

- Authentication / API key management (handled by API Gateway layer)
- Patient record storage or management
- Multi-driver / fleet optimization
- Real-time re-optimization mid-route
- Driver mobile app
- Dispatcher web dashboard
- Notifications (SMS/push)
- Billing and invoicing
- Broker integrations (Modivcare, MTM, etc.)

---

## 7. Constraints

| Constraint | Detail |
|---|---|
| Google Maps `optimizeWaypoints` limit | Max 25 stops per request |
| OR-Tools solver timeout | 10 seconds max |
| Distance Matrix API pricing | ~$5 per 1,000 elements — cache aggressively |
| HIPAA requirement | No PHI in external API calls |
| Time window granularity | Minutes only (no seconds) |

---

## 8. Success Metrics

| Metric | Target |
|---|---|
| Route optimization accuracy | Optimized route ≤ 110% of theoretical minimum time |
| API response time (≤15 stops) | < 5 seconds (p95) |
| API response time (≤25 stops) | < 10 seconds (p95) |
| Cache hit rate | > 60% during active dispatch hours |
| Time window violation rate | 0% — all returned routes must honor time windows |

---

## 9. Sample Use Case

**Scenario:** A driver starts their shift at 7:30 AM from the depot. They have 5 patients
to pick up before 9:00 AM. Peak traffic is heavy. The dispatcher calls the API before
the driver leaves.

**Input:** Driver depot coordinates + 5 stop objects with pickup windows.

**Output:** Reordered stop list (e.g., stop 3 → stop 1 → stop 5 → stop 2 → stop 4)
with ETAs at each stop and a Google Maps link the driver taps to start navigation.

**Value Delivered:** Driver avoids backtracking, arrives at all stops within their time
windows, and completes the route 18 minutes faster than the original order.

---

## 10. Future Phases

| Phase | Feature |
|---|---|
| Phase 2 | Multi-driver optimization (fleet VRP) |
| Phase 3 | Real-time re-routing when driver is delayed |
| Phase 4 | Driver mobile app consuming this API |
| Phase 5 | Dispatcher dashboard with live map view |
| Phase 6 | Predictive traffic using historical patterns |
