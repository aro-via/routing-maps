# Route Optimizer — NEMT Route Optimization API

A HIPAA-compliant Route Optimization API for Non-Emergency Medical Transportation (NEMT). Given a driver's start location and patient pickup stops, it returns the most time-efficient route considering real-time traffic using Google Maps and Google OR-Tools.

---

## Prerequisites

- **Python 3.11+**
- **Docker** and **Docker Compose** (for containerized setup)
- **Google Maps API key** with Distance Matrix API enabled
- **Redis** (via Docker or local install)

---

## Setup

```bash
# 1. Clone the repository
git clone https://github.com/aro-via/routing-maps.git
cd routing-maps

# 2. Copy environment file and fill in your API key
cp .env.example .env
# Edit .env and set GOOGLE_MAPS_API_KEY=your_actual_key

# 3. Install dependencies (local development)
pip install -r requirements.txt
```

---

## Running Locally

### Without Docker

```bash
# Start Redis (required)
docker-compose up redis -d

# Start the API server
uvicorn app.main:app --reload --port 8000
```

### With Docker (recommended)

```bash
docker-compose up --build
```

The API will be available at `http://localhost:8000`.

---

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_vrp_solver.py -v

# Run a specific test by name
pytest tests/test_schemas.py::test_invalid_coordinates -v
```

---

## API Usage

### Optimize Route

```
POST /api/v1/optimize-route
Content-Type: application/json
```

**Request:**
```json
{
  "driver_id": "driver-001",
  "driver_location": { "lat": 40.7128, "lng": -74.0060 },
  "departure_time": "2030-06-15T08:00:00Z",
  "stops": [
    {
      "stop_id": "550e8400-e29b-41d4-a716-446655440001",
      "location": { "lat": 40.7580, "lng": -73.9855 },
      "earliest_pickup": "08:30",
      "latest_pickup": "09:00",
      "service_time_minutes": 5
    },
    {
      "stop_id": "550e8400-e29b-41d4-a716-446655440002",
      "location": { "lat": 40.6892, "lng": -74.0445 },
      "earliest_pickup": "09:00",
      "latest_pickup": "09:30",
      "service_time_minutes": 10
    }
  ]
}
```

**Response:**
```json
{
  "driver_id": "driver-001",
  "optimized_stops": [
    {
      "stop_id": "550e8400-e29b-41d4-a716-446655440001",
      "sequence": 1,
      "location": { "lat": 40.7580, "lng": -73.9855 },
      "arrival_time": "08:22",
      "departure_time": "08:27"
    },
    {
      "stop_id": "550e8400-e29b-41d4-a716-446655440002",
      "sequence": 2,
      "location": { "lat": 40.6892, "lng": -74.0445 },
      "arrival_time": "09:01",
      "departure_time": "09:11"
    }
  ],
  "total_distance_km": 18.4,
  "total_duration_minutes": 71.0,
  "google_maps_url": "https://www.google.com/maps/dir/40.7128,-74.006/40.758,-73.9855/40.6892,-74.0445",
  "optimization_score": 0.87
}
```

### Health Check

```
GET /api/v1/health
```

**Response:**
```json
{
  "status": "healthy",
  "redis": "ok",
  "maps_api": "configured"
}
```

---

## Interactive API Explorer

Visit `http://localhost:8000/docs` for the Swagger UI with full request/response documentation.

---

## HIPAA Data Handling

This service is designed to never expose Protected Health Information (PHI) to external APIs:

- **Google Distance Matrix API** receives only `(lat, lng)` coordinate pairs — never patient names, addresses, or identifiers
- **Redis cache** stores only hashed keys and coordinate-based matrices — no readable location names or patient data
- `stop_id` is a UUID managed by your system — the mapping to patient identity stays in your system only
- Log messages contain no PHI

The HIPAA boundary is enforced at the code level. See `ARCHITECTURE.md` Section 4 for full details.
