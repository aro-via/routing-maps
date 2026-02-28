/**
 * driver-app/src/services/gps.ts — Background GPS tracking service.
 *
 * Uses react-native-geolocation-service to provide:
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

import Geolocation from 'react-native-geolocation-service';
import {Platform, PermissionsAndroid} from 'react-native';

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
  private _watchId: number | null = null;
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
   * Requests location permission before starting.
   * Safe to call multiple times — subsequent calls update the callback.
   */
  async start(callback: GpsCallback): Promise<void> {
    this._callback = callback;
    await this._subscribe();
  }

  /** Stop GPS tracking and release the callback. */
  async stop(): Promise<void> {
    if (this._watchId !== null) {
      Geolocation.clearWatch(this._watchId);
      this._watchId = null;
    }
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
      if (this._watchId !== null) {
        Geolocation.clearWatch(this._watchId);
        this._watchId = null;
      }
      await this._subscribe();
    }
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private async _requestPermission(): Promise<boolean> {
    if (Platform.OS === 'ios') {
      const result = await Geolocation.requestAuthorization('whenInUse');
      return result === 'granted';
    }
    if (Platform.OS === 'android') {
      const result = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
        {
          title: 'Location Permission',
          message: 'NEMT Driver needs your location for route guidance.',
          buttonPositive: 'Grant',
        },
      );
      return result === PermissionsAndroid.RESULTS.GRANTED;
    }
    return false;
  }

  private async _subscribe(): Promise<void> {
    const hasPermission = await this._requestPermission();
    if (!hasPermission) {
      console.warn('[GpsService] location permission denied');
      return;
    }

    this._watchId = Geolocation.watchPosition(
      pos => {
        if (this._callback) {
          this._callback({
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            timestamp: new Date(pos.timestamp).toISOString(),
            speed: pos.coords.speed ?? -1,
          });
        }
      },
      err => {
        console.warn('[GpsService] watchPosition error:', err.message);
      },
      {
        enableHighAccuracy: true,
        distanceFilter: 10,
        interval: this._timeIntervalMs,
        fastestInterval: this._timeIntervalMs,
        accuracy: {
          android: 'high',
          ios: 'best',
        },
      },
    );
  }
}

// Shared singleton exported to App.tsx and WS client
export const gpsService = new GpsService();
