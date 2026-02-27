"""app/workers/delay_detector.py — Re-routing trigger logic.

should_reroute() is called by the Celery GPS-update task after every
position fix.  It returns (True, reason) when a fresh optimisation run
should be triggered, (False, "") otherwise.

Rules are evaluated in order:
  0. Cooldown — never re-route more than once per MIN_REROUTE_INTERVAL_SECONDS.
  1. Schedule delay > DELAY_THRESHOLD_MINUTES.
  2. Remaining route time grew by more than TRAFFIC_INCREASE_RATIO.
  3. Dispatcher added or cancelled a stop (stops_changed flag).

All thresholds are loaded from settings (no hardcoded values).
"""
import logging
import time

from app.config import settings
from app.state.driver_state import DriverState

logger = logging.getLogger(__name__)


def should_reroute(driver_state: DriverState) -> tuple[bool, str]:
    """Decide whether the driver's route should be re-optimised.

    Args:
        driver_state: Current state snapshot for the active driver.

    Returns:
        (True, reason_string)  — re-route should be triggered.
        (False, "")            — no re-route needed at this time.

    Reason strings match the WebSocket contract:
        "traffic_delay"  — driver is behind schedule or traffic worsened.
        "stop_modified"  — dispatcher changed the stop list.
    """
    driver_id = driver_state.driver_id

    # ------------------------------------------------------------------
    # Rule 0 (checked first): cooldown — don't re-route too frequently.
    # If the last re-route was less than MIN_REROUTE_INTERVAL_SECONDS ago,
    # suppress all rules to avoid rapid-fire disruption to the driver.
    # ------------------------------------------------------------------
    if driver_state.last_reroute_timestamp is not None:
        seconds_since = time.time() - driver_state.last_reroute_timestamp
        if seconds_since < settings.MIN_REROUTE_INTERVAL_SECONDS:
            logger.debug(
                "Reroute suppressed (cooldown): driver=%s %.0fs < %ds",
                driver_id,
                seconds_since,
                settings.MIN_REROUTE_INTERVAL_SECONDS,
            )
            return False, ""

    # ------------------------------------------------------------------
    # Rule 1: Driver is behind schedule.
    # ------------------------------------------------------------------
    if driver_state.schedule_delay_minutes > settings.DELAY_THRESHOLD_MINUTES:
        logger.info(
            "Reroute triggered (schedule delay): driver=%s delay=%.1f min",
            driver_id,
            driver_state.schedule_delay_minutes,
        )
        return True, "traffic_delay"

    # ------------------------------------------------------------------
    # Rule 2: Remaining route time has grown significantly vs. baseline.
    # ------------------------------------------------------------------
    if (
        driver_state.original_remaining_duration > 0
        and driver_state.remaining_duration
        > driver_state.original_remaining_duration * settings.TRAFFIC_INCREASE_RATIO
    ):
        logger.info(
            "Reroute triggered (traffic increase): driver=%s remaining=%.1f original=%.1f ratio=%.2f",
            driver_id,
            driver_state.remaining_duration,
            driver_state.original_remaining_duration,
            settings.TRAFFIC_INCREASE_RATIO,
        )
        return True, "traffic_delay"

    # ------------------------------------------------------------------
    # Rule 3: Dispatcher added or cancelled a stop.
    # ------------------------------------------------------------------
    if driver_state.stops_changed:
        logger.info("Reroute triggered (stop modified): driver=%s", driver_id)
        return True, "stop_modified"

    return False, ""
