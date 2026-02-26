import logging
from typing import List

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.config import settings
from app.models.schemas import Stop
from app.utils.time_utils import time_str_to_minutes

logger = logging.getLogger(__name__)


def solve_vrp(
    time_matrix: List[List[int]],
    stops: List[Stop],
    service_times: List[int],
    departure_time_minutes: int = 0,
    num_vehicles: int = 1,
) -> List[int]:
    """Solve the Vehicle Routing Problem with Time Windows (VRPTW).

    Args:
        time_matrix: (n+1) × (n+1) travel-time matrix in **seconds**.
                     Index 0 = driver/depot; indices 1..n = stops in input order.
        stops:       List of Stop objects in input order (length n).
        service_times: Service duration in **minutes** at each stop (length n).
                       Indexed to match `stops`.
        departure_time_minutes: Departure time as minutes since midnight (e.g. 540
                                for 09:00).  Used to anchor the time-window solver.
        num_vehicles: Number of vehicles (currently always 1 for Phase 1).

    Returns:
        Ordered list of 0-based stop indices representing the optimal visit sequence
        (depot excluded).

    Raises:
        ValueError: If no feasible route exists for the given time windows /
                    travel times.  The caller should return HTTP 422.
    """
    n_nodes = len(time_matrix)  # depot + n stops

    # OR-Tools requires integer costs — convert seconds → minutes
    time_mins = [[v // 60 for v in row] for row in time_matrix]

    manager = pywrapcp.RoutingIndexManager(n_nodes, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    # ------------------------------------------------------------------
    # Transit callback: travel time (min) + service time at origin node
    # ------------------------------------------------------------------
    def transit_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel = time_mins[from_node][to_node]
        # Service time is incurred when *leaving* a stop (not at depot)
        service = service_times[from_node - 1] if from_node > 0 else 0
        return travel + service

    transit_idx = routing.RegisterTransitCallback(transit_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    # ------------------------------------------------------------------
    # Time dimension
    # Using absolute minutes-since-midnight so stop windows map directly.
    # capacity = 1440 (full day); slack_max = 30 min early-arrival buffer.
    # ------------------------------------------------------------------
    routing.AddDimension(
        transit_idx,
        30,    # slack_max: vehicle may wait up to 30 min before a window opens
        1440,  # capacity: upper bound on cumulative time (full 24-hour day)
        False, # fix_start_cumul_to_zero: False → use absolute time-of-day values
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    # Fix the driver's departure time at the start node
    time_dim.CumulVar(routing.Start(0)).SetRange(
        departure_time_minutes, departure_time_minutes
    )

    # Apply per-stop time windows
    for i, stop in enumerate(stops):
        node_idx = manager.NodeToIndex(i + 1)
        earliest = time_str_to_minutes(stop.earliest_pickup)
        latest = time_str_to_minutes(stop.latest_pickup)
        time_dim.CumulVar(node_idx).SetRange(earliest, latest)

    # ------------------------------------------------------------------
    # Search parameters
    # ------------------------------------------------------------------
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = settings.MAX_OPTIMIZATION_SECONDS

    logger.info(
        "VRP solve: %d stops, departure=%d min, time_limit=%ds",
        len(stops),
        departure_time_minutes,
        settings.MAX_OPTIMIZATION_SECONDS,
    )

    solution = routing.SolveWithParameters(search_params)

    if not solution:
        raise ValueError(
            f"No feasible route found for {len(stops)} stops with the given "
            "time windows and travel times. Verify that all stops can be reached "
            "within their pickup windows from the specified departure time."
        )

    # ------------------------------------------------------------------
    # Extract ordered stop indices (0-based, depot excluded)
    # ------------------------------------------------------------------
    route: List[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node != 0:  # skip depot
            route.append(node - 1)
        index = solution.Value(routing.NextVar(index))

    logger.info("VRP solution: %s (objective=%d)", route, solution.ObjectiveValue())
    return route
