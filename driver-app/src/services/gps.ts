/**
 * driver-app/src/services/gps.ts — Background GPS tracking service.
 *
 * Uses expo-location (Expo Go compatible) to provide:
 *   - Start/stop tracking with a single call
 *   - Adaptive update intervals based on driver speed (ARCHITECTURE.md §10.7):
 *       speed < 5 km/h (stationary)  → 60 s interval
 *       normal driving               → 15 s interval
 *       approaching stop  (< 500 m)  → 5 s interval
 *   - Callback fires with { lat, lng, timestamp, speed } on each fix
 *
 * No PHI passes through this module.  Location data is sent to the server
 * as raw coordinates only.
 */

import * as Location from 'expo-location';

export interface GpsLocation {
  lat: number;
  lng: number;
  timestamp: string; // ISO-8601 UTC
  speed: number;     // m/s; -1 if unavailable
}

export type GpsCallback = (location: GpsLocation) => void;

// ---------------------------------------------------------------------------
// Adaptive interval thresholds
// ---------------------------------------------------------------------------

const SPEED_STATIONARY_KMH = 5;

const INTERVAL_STATIONARY_MS = 60_000;
const INTERVAL_NORMAL_MS = 15_000;
const INTERVAL_APPROACHING_MS = 5_000;

// Distance threshold (metres) for "approaching a stop"
export const APPROACHING_DISTANCE_M = 500;

// ---------------------------------------------------------------------------
// GpsService
// ---------------------------------------------------------------------------

class GpsService {
  private _callback: GpsCallback | null = null;
  private _subscription: Location.LocationSubscription | null = null;
  private _timeIntervalMs = INTERVAL_NORMAL_MS;

  /**
   * Compute the desired location interval based on current speed.
   *
   * Used internally and exported for unit testing.
   */
  adaptiveIntervalMs(speedMs: number, nearestStopDistM = Infinity): number {
    if (nearestStopDistM < APPROACHING_DISTANCE_M) {
      return INTERVAL_APPROACHING_MS;
    }
    const speedKmh = speedMs * 3.6;
    if (speedKmh < SPEED_STATIONARY_KMH) {
      return INTERVAL_STATIONARY_MS;
    }
    return INTERVAL_NORMAL_MS;
  }

  /**
   * Start GPS tracking.  The callback is called on every fix.
   *
   * Requests foreground location permission before starting.
   * Safe to call multiple times — subsequent calls update the callback.
   */
  async start(callback: GpsCallback): Promise<void> {
    this._callback = callback;
    await this._subscribe();
  }

  /** Stop GPS tracking and release the callback. */
  async stop(): Promise<void> {
    this._subscription?.remove();
    this._subscription = null;
    this._callback = null;
  }

  /**
   * Dynamically update the location interval — called after each fix
   * when stop-proximity information is available from the route store.
   * Re-creates the watcher only when the interval actually changes.
   */
  async updateInterval(speedMs: number, nearestStopDistM?: number): Promise<void> {
    const interval = this.adaptiveIntervalMs(speedMs, nearestStopDistM);
    if (interval !== this._timeIntervalMs && this._callback) {
      this._timeIntervalMs = interval;
      this._subscription?.remove();
      this._subscription = null;
      await this._subscribe();
    }
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private async _subscribe(): Promise<void> {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') {
      console.warn('[GpsService] location permission denied');
      return;
    }

    this._subscription = await Location.watchPositionAsync(
      {
        accuracy: Location.Accuracy.High,
        distanceInterval: 10,       // metres — minimum movement between updates
        timeInterval: this._timeIntervalMs,
      },
      (loc) => {
        if (this._callback) {
          this._callback({
            lat: loc.coords.latitude,
            lng: loc.coords.longitude,
            timestamp: new Date(loc.timestamp).toISOString(),
            speed: loc.coords.speed ?? -1,
          });
        }
      },
    );
  }
}

// Shared singleton exported to App.tsx and WS client
export const gpsService = new GpsService();
