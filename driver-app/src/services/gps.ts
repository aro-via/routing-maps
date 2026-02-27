/**
 * driver-app/src/services/gps.ts — Background GPS tracking service.
 *
 * Wraps react-native-background-geolocation to provide:
 *   - Start/stop tracking with a single call
 *   - Adaptive update intervals based on driver speed (ARCHITECTURE.md §10.7):
 *       speed < 5 km/h (stationary)  → 60 s interval
 *       normal driving               → 15 s interval
 *       approaching stop  (< 500 m)  → 5 s interval
 *       (speed-based heuristic — stop proximity requires stop list from store)
 *   - Callback fires with { lat, lng, timestamp, speed } on each fix
 *
 * No PHI passes through this module.  Location data is sent to the server
 * as raw coordinates only.
 */

import BackgroundGeolocation, {
  Location as BGLocation,
  State as BGState,
} from 'react-native-background-geolocation';

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
const SPEED_TO_MS = 1 / 3.6; // km/h → m/s

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
  private _configured = false;

  /**
   * Start background GPS tracking.  The callback is called on every fix.
   *
   * Safe to call multiple times — subsequent calls update the callback and
   * re-start if the service was stopped.
   */
  async start(callback: GpsCallback): Promise<void> {
    this._callback = callback;

    if (!this._configured) {
      await this._configure();
      this._configured = true;
    }

    await BackgroundGeolocation.start();
  }

  /** Stop GPS tracking and release the callback. */
  async stop(): Promise<void> {
    this._callback = null;
    await BackgroundGeolocation.stop();
  }

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

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private async _configure(): Promise<BGState> {
    // Event listener — fired on every location fix
    BackgroundGeolocation.onLocation(
      (location: BGLocation) => {
        if (this._callback) {
          this._callback({
            lat: location.coords.latitude,
            lng: location.coords.longitude,
            timestamp: location.timestamp,
            speed: location.coords.speed ?? -1,
          });
        }
      },
      (error: number) => {
        // Location error (permissions denied, GPS off, etc.) — log only
        console.warn('[GpsService] location error code:', error);
      },
    );

    return BackgroundGeolocation.ready({
      // --- Accuracy ---
      desiredAccuracy: BackgroundGeolocation.DESIRED_ACCURACY_HIGH,
      distanceFilter: 10, // metres — minimum movement to fire an update

      // --- Battery / intervals (overridden adaptively at runtime) ---
      locationUpdateInterval: INTERVAL_NORMAL_MS,
      fastestLocationUpdateInterval: INTERVAL_APPROACHING_MS,

      // --- Background behaviour ---
      stopOnTerminate: false,
      startOnBoot: true,
      foregroundService: true, // Android: keeps tracking when app is backgrounded
      notification: {
        title: 'NEMT Driver App',
        text: 'GPS tracking active',
        smallIcon: 'mipmap/ic_launcher',
      },

      // --- Debug (disable in production) ---
      debug: false,
      logLevel: BackgroundGeolocation.LOG_LEVEL_WARNING,
    });
  }

  /**
   * Dynamically update the location interval — called after each fix
   * when stop-proximity information is available from the route store.
   */
  async updateInterval(speedMs: number, nearestStopDistM?: number): Promise<void> {
    const interval = this.adaptiveIntervalMs(speedMs, nearestStopDistM);
    await BackgroundGeolocation.setConfig({
      locationUpdateInterval: interval,
      fastestLocationUpdateInterval: Math.min(interval, INTERVAL_APPROACHING_MS),
    });
  }
}

// Shared singleton exported to App.tsx and WS client
export const gpsService = new GpsService();
