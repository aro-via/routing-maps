/**
 * driver-app/src/store/routeStore.ts — Zustand state store for the active route.
 *
 * State:
 *   currentRoute       — ordered list of remaining optimized stops
 *   currentStopIndex   — index into currentRoute of the next stop to service
 *   driverStatus       — 'idle' | 'active' | 'completed'
 *   lastUpdated        — ISO timestamp of the last route update (or null)
 *   routeUpdateReason  — why the route was last updated (or null if not updated)
 *
 * Actions:
 *   setRoute(stops)         — replace the route (called on initial load + re-route)
 *   completeCurrentStop()   — mark current stop done, advance to next
 *   resetRoute()            — end-of-shift cleanup
 *
 * The WebSocket client calls setRoute() on every route_updated message.
 * No PHI is stored here — stop_id is an internal UUID; names and addresses
 * are never included in route data sent to the driver app.
 */

import {create} from 'zustand';
import {OptimizedStop, DriverStatus, RouteUpdateReason} from '../types';

// ---------------------------------------------------------------------------
// State shape
// ---------------------------------------------------------------------------

interface RouteState {
  currentRoute: OptimizedStop[];
  currentStopIndex: number;
  driverStatus: DriverStatus;
  lastUpdated: string | null;
  routeUpdateReason: RouteUpdateReason | null;
}

// ---------------------------------------------------------------------------
// Actions shape
// ---------------------------------------------------------------------------

interface RouteActions {
  /**
   * Set the full route.  Called on initial route load and on every re-route
   * pushed from the server.
   *
   * @param stops   Ordered list of optimized stops (server schema).
   * @param reason  Why the route changed (undefined on first load).
   */
  setRoute: (stops: OptimizedStop[], reason?: RouteUpdateReason) => void;

  /**
   * Mark the current stop as completed and advance to the next one.
   * If no more stops remain, transitions status to 'completed'.
   */
  completeCurrentStop: () => void;

  /**
   * Reset all route state — called at end-of-shift or on logout.
   */
  resetRoute: () => void;

  /**
   * Dismiss the route update banner (clear routeUpdateReason).
   */
  dismissUpdateBanner: () => void;
}

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

const INITIAL_STATE: RouteState = {
  currentRoute: [],
  currentStopIndex: 0,
  driverStatus: 'idle',
  lastUpdated: null,
  routeUpdateReason: null,
};

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useRouteStore = create<RouteState & RouteActions>(set => ({
  ...INITIAL_STATE,

  setRoute: (stops: OptimizedStop[], reason?: RouteUpdateReason) =>
    set({
      currentRoute: stops,
      currentStopIndex: 0,
      driverStatus: stops.length > 0 ? 'active' : 'completed',
      lastUpdated: new Date().toISOString(),
      routeUpdateReason: reason ?? null,
    }),

  completeCurrentStop: () =>
    set(state => {
      const nextIndex = state.currentStopIndex + 1;
      const completed = nextIndex >= state.currentRoute.length;
      return {
        currentStopIndex: nextIndex,
        driverStatus: completed ? 'completed' : 'active',
      };
    }),

  resetRoute: () => set(INITIAL_STATE),

  dismissUpdateBanner: () => set({routeUpdateReason: null}),
}));

// ---------------------------------------------------------------------------
// Selectors (pure functions — no re-render cost for derived values)
// ---------------------------------------------------------------------------

/** The stop the driver should service next. */
export const selectCurrentStop = (
  state: RouteState,
): OptimizedStop | undefined => state.currentRoute[state.currentStopIndex];

/** All stops after the current one (i.e., not yet serviced). */
export const selectRemainingStops = (state: RouteState): OptimizedStop[] =>
  state.currentRoute.slice(state.currentStopIndex + 1);

/** Number of stops still to complete (including the current one). */
export const selectStopsRemaining = (state: RouteState): number =>
  Math.max(0, state.currentRoute.length - state.currentStopIndex);
