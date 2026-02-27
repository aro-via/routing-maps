/**
 * Tests for Zustand route store actions and selectors.
 *
 * Zustand stores are tested by calling actions directly and asserting on
 * the resulting state — no React rendering required.
 */

import {useRouteStore, selectCurrentStop, selectRemainingStops, selectStopsRemaining} from '../store/routeStore';
import {OptimizedStop} from '../types';

// ---------------------------------------------------------------------------
// Test data helpers
// ---------------------------------------------------------------------------

function makeStop(id: string, seq: number): OptimizedStop {
  return {
    stop_id: id,
    sequence: seq,
    location: {lat: 37.77 + seq * 0.01, lng: -122.41},
    arrival_time: `09:${10 + seq * 10}`,
    departure_time: `09:${20 + seq * 10}`,
  };
}

const STOP_1 = makeStop('s1', 1);
const STOP_2 = makeStop('s2', 2);
const STOP_3 = makeStop('s3', 3);

// ---------------------------------------------------------------------------
// Reset store between tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  useRouteStore.getState().resetRoute();
});

// ---------------------------------------------------------------------------
// setRoute
// ---------------------------------------------------------------------------

describe('setRoute', () => {
  test('sets the route and resets stop index to 0', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2, STOP_3]);
    const state = useRouteStore.getState();
    expect(state.currentRoute).toEqual([STOP_1, STOP_2, STOP_3]);
    expect(state.currentStopIndex).toBe(0);
  });

  test('sets driverStatus to "active" when stops are provided', () => {
    useRouteStore.getState().setRoute([STOP_1]);
    expect(useRouteStore.getState().driverStatus).toBe('active');
  });

  test('sets driverStatus to "completed" when empty route provided', () => {
    useRouteStore.getState().setRoute([]);
    expect(useRouteStore.getState().driverStatus).toBe('completed');
  });

  test('sets routeUpdateReason when provided', () => {
    useRouteStore.getState().setRoute([STOP_1], 'traffic_delay');
    expect(useRouteStore.getState().routeUpdateReason).toBe('traffic_delay');
  });

  test('routeUpdateReason is null when not provided', () => {
    useRouteStore.getState().setRoute([STOP_1]);
    expect(useRouteStore.getState().routeUpdateReason).toBeNull();
  });

  test('sets lastUpdated to a recent ISO timestamp', () => {
    const before = Date.now();
    useRouteStore.getState().setRoute([STOP_1]);
    const after = Date.now();
    const ts = Date.parse(useRouteStore.getState().lastUpdated!);
    expect(ts).toBeGreaterThanOrEqual(before);
    expect(ts).toBeLessThanOrEqual(after);
  });

  test('replaces previous route completely', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2]);
    useRouteStore.getState().setRoute([STOP_3]);
    expect(useRouteStore.getState().currentRoute).toEqual([STOP_3]);
  });
});

// ---------------------------------------------------------------------------
// completeCurrentStop
// ---------------------------------------------------------------------------

describe('completeCurrentStop', () => {
  test('advances currentStopIndex by 1', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2, STOP_3]);
    useRouteStore.getState().completeCurrentStop();
    expect(useRouteStore.getState().currentStopIndex).toBe(1);
  });

  test('status remains "active" if more stops remain', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2]);
    useRouteStore.getState().completeCurrentStop();
    expect(useRouteStore.getState().driverStatus).toBe('active');
  });

  test('status becomes "completed" after the last stop is done', () => {
    useRouteStore.getState().setRoute([STOP_1]);
    useRouteStore.getState().completeCurrentStop();
    expect(useRouteStore.getState().driverStatus).toBe('completed');
  });

  test('completing all stops advances index past the route length', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2]);
    useRouteStore.getState().completeCurrentStop(); // stop 0 done
    useRouteStore.getState().completeCurrentStop(); // stop 1 done
    expect(useRouteStore.getState().driverStatus).toBe('completed');
  });
});

// ---------------------------------------------------------------------------
// resetRoute
// ---------------------------------------------------------------------------

describe('resetRoute', () => {
  test('clears the route and resets all state', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2, STOP_3], 'traffic_delay');
    useRouteStore.getState().completeCurrentStop();
    useRouteStore.getState().resetRoute();

    const state = useRouteStore.getState();
    expect(state.currentRoute).toEqual([]);
    expect(state.currentStopIndex).toBe(0);
    expect(state.driverStatus).toBe('idle');
    expect(state.lastUpdated).toBeNull();
    expect(state.routeUpdateReason).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// dismissUpdateBanner
// ---------------------------------------------------------------------------

describe('dismissUpdateBanner', () => {
  test('clears routeUpdateReason', () => {
    useRouteStore.getState().setRoute([STOP_1], 'stop_modified');
    useRouteStore.getState().dismissUpdateBanner();
    expect(useRouteStore.getState().routeUpdateReason).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

describe('selectCurrentStop', () => {
  test('returns the stop at currentStopIndex', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2, STOP_3]);
    expect(selectCurrentStop(useRouteStore.getState())).toEqual(STOP_1);
  });

  test('advances after completeCurrentStop', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2]);
    useRouteStore.getState().completeCurrentStop();
    expect(selectCurrentStop(useRouteStore.getState())).toEqual(STOP_2);
  });

  test('returns undefined when route is empty', () => {
    expect(selectCurrentStop(useRouteStore.getState())).toBeUndefined();
  });
});

describe('selectRemainingStops', () => {
  test('excludes the current stop and all previous stops', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2, STOP_3]);
    expect(selectRemainingStops(useRouteStore.getState())).toEqual([STOP_2, STOP_3]);
  });

  test('returns empty array when on last stop', () => {
    useRouteStore.getState().setRoute([STOP_1]);
    expect(selectRemainingStops(useRouteStore.getState())).toEqual([]);
  });
});

describe('selectStopsRemaining', () => {
  test('returns total stops for a fresh route', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2, STOP_3]);
    expect(selectStopsRemaining(useRouteStore.getState())).toBe(3);
  });

  test('decrements after each stop completion', () => {
    useRouteStore.getState().setRoute([STOP_1, STOP_2]);
    useRouteStore.getState().completeCurrentStop();
    expect(selectStopsRemaining(useRouteStore.getState())).toBe(1);
  });

  test('returns 0 after all stops completed', () => {
    useRouteStore.getState().setRoute([STOP_1]);
    useRouteStore.getState().completeCurrentStop();
    expect(selectStopsRemaining(useRouteStore.getState())).toBe(0);
  });

  test('returns 0 for empty route', () => {
    expect(selectStopsRemaining(useRouteStore.getState())).toBe(0);
  });
});
