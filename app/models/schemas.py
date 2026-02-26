import re
import logging
from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, field_validator, model_validator

logger = logging.getLogger(__name__)

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class Location(BaseModel):
    lat: float
    lng: float

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError(f"lat must be between -90 and 90, got {v}")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError(f"lng must be between -180 and 180, got {v}")
        return v


class Stop(BaseModel):
    stop_id: str
    location: Location
    earliest_pickup: str
    latest_pickup: str
    service_time_minutes: int

    @field_validator("earliest_pickup", "latest_pickup")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError(f"Time must be in HH:MM format, got '{v}'")
        hour, minute = int(v[:2]), int(v[3:])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Invalid time value '{v}'")
        return v

    @field_validator("service_time_minutes")
    @classmethod
    def validate_service_time(cls, v: int) -> int:
        if not 1 <= v <= 60:
            raise ValueError(f"service_time_minutes must be between 1 and 60, got {v}")
        return v

    @model_validator(mode="after")
    def validate_time_window(self) -> "Stop":
        # Convert HH:MM to minutes for comparison
        def to_minutes(t: str) -> int:
            h, m = t.split(":")
            return int(h) * 60 + int(m)

        if to_minutes(self.earliest_pickup) >= to_minutes(self.latest_pickup):
            raise ValueError(
                f"earliest_pickup ({self.earliest_pickup}) must be "
                f"before latest_pickup ({self.latest_pickup})"
            )
        return self


class OptimizeRouteRequest(BaseModel):
    driver_id: str
    driver_location: Location
    departure_time: datetime
    stops: List[Stop]

    @field_validator("stops")
    @classmethod
    def validate_stops_count(cls, v: List[Stop]) -> List[Stop]:
        if not 2 <= len(v) <= 25:
            raise ValueError(
                f"stops must contain between 2 and 25 items, got {len(v)}"
            )
        return v

    @field_validator("departure_time")
    @classmethod
    def validate_departure_not_in_past(cls, v: datetime) -> datetime:
        # Ensure timezone-aware for comparison
        now = datetime.now(timezone.utc)
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v < now:
            raise ValueError("departure_time must not be in the past")
        return v


class OptimizedStop(BaseModel):
    stop_id: str
    sequence: int
    location: Location
    arrival_time: str
    departure_time: str


class OptimizeRouteResponse(BaseModel):
    driver_id: str
    optimized_stops: List[OptimizedStop]
    total_distance_km: float
    total_duration_minutes: float
    google_maps_url: str
    optimization_score: float
