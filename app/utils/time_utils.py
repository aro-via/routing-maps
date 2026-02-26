import logging

logger = logging.getLogger(__name__)


def time_str_to_minutes(time_str: str) -> int:
    """Convert 'HH:MM' string to total minutes since midnight. E.g. '08:30' -> 510."""
    h, m = time_str.split(":")
    return int(h) * 60 + int(m)


def minutes_to_time_str(minutes: int) -> str:
    """Convert total minutes since midnight to 'HH:MM'. Wraps at 24 h. E.g. 510 -> '08:30'."""
    minutes = minutes % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def add_minutes_to_time(time_str: str, minutes: int) -> str:
    """Add *minutes* to a 'HH:MM' string and return a new 'HH:MM'. Wraps at 24 h."""
    return minutes_to_time_str(time_str_to_minutes(time_str) + minutes)
