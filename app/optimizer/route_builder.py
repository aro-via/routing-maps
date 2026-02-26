import logging
from datetime import datetime
from typing import List

from app.models.schemas import Location, OptimizedStop, OptimizeRouteResponse, Stop
from app.utils.time_utils import add_minutes_to_time, minutes_to_time_str, time_str_to_minutes

logger = logging.getLogger(__name__)


def _build_maps_url(driver_location: Location, ordered_stops: List[Stop]) -> str:
    """Build a Google Maps directions URL using coordinates only (no PHI).

    Format: https://www.google.com/maps/dir/lat,lng/lat,lng/...
    """
    parts = [f"{driver_location.lat},{driver_location.lng}"]
    parts += [f"{s.location.lat},{s.location.lng}" for s in ordered_stops]
    return "https://www.google.com/maps/dir/" + "/".join(parts)


def build_final_route(
    driver_id: str,
    driver_location: Location,
    ordered_stops: List[Stop],
    time_matrix: List[List[int]],
    distance_matrix: List[List[int]],
    departure_time: datetime,
) -> OptimizeRouteResponse:
    """Assemble the final optimised route with per-stop ETAs and summary stats.

    The caller is responsible for pre-ordering `ordered_stops` and for
    providing `time_matrix` / `distance_matrix` whose indices are aligned to
    that order:
        index 0  → driver location
        index 1  → ordered_stops[0]
        index 2  → ordered_stops[1]
        ...

    Args:
        driver_id:        Identifies the driver in the response payload.
        driver_location:  Starting (lat, lng) of the driver.
        ordered_stops:    Stops in the optimised visit sequence.
        time_matrix:      Travel times in **seconds** (index-aligned as above).
        distance_matrix:  Distances in **metres** (index-aligned as above).
        departure_time:   Scheduled departure (used to anchor absolute ETAs).

    Returns:
        A fully populated OptimizeRouteResponse.
    """
    departure_minutes = departure_time.hour * 60 + departure_time.minute
    current_minutes = departure_minutes
    prev_node = 0  # driver location = matrix index 0
    total_distance_m = 0

    optimized_stops: List[OptimizedStop] = []

    for seq, stop in enumerate(ordered_stops):
        curr_node = seq + 1  # matrix index for this stop

        travel_secs = time_matrix[prev_node][curr_node]
        travel_mins = travel_secs // 60

        arrival_minutes = current_minutes + travel_mins
        departure_minutes_stop = arrival_minutes + stop.service_time_minutes

        total_distance_m += distance_matrix[prev_node][curr_node]

        optimized_stops.append(
            OptimizedStop(
                stop_id=stop.stop_id,
                sequence=seq + 1,
                location=stop.location,
                arrival_time=minutes_to_time_str(arrival_minutes),
                departure_time=minutes_to_time_str(departure_minutes_stop),
            )
        )

        logger.debug(
            "Stop %d (%s): arrive=%s depart=%s travel=%d min",
            seq + 1,
            stop.stop_id,
            minutes_to_time_str(arrival_minutes),
            minutes_to_time_str(departure_minutes_stop),
            travel_mins,
        )

        current_minutes = departure_minutes_stop
        prev_node = curr_node

    total_distance_km = round(total_distance_m / 1000, 2)
    total_duration_minutes = round(current_minutes - departure_minutes, 2)
    maps_url = _build_maps_url(driver_location, ordered_stops)

    logger.info(
        "Route built: %d stops, %.1f km, %.0f min",
        len(ordered_stops),
        total_distance_km,
        total_duration_minutes,
    )

    return OptimizeRouteResponse(
        driver_id=driver_id,
        optimized_stops=optimized_stops,
        total_distance_km=total_distance_km,
        total_duration_minutes=total_duration_minutes,
        google_maps_url=maps_url,
        optimization_score=0.0,  # computed by the pipeline (Task 9)
    )
