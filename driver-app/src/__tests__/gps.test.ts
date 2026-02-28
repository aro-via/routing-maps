/**
 * Tests for GPS service adaptive interval logic.
 *
 * expo-location is mocked so these tests run in a plain Node environment
 * with no native modules.
 */

import {gpsService, APPROACHING_DISTANCE_M} from '../services/gps';

// ---------------------------------------------------------------------------
// Mock expo-location
// ---------------------------------------------------------------------------

jest.mock('expo-location', () => ({
  Accuracy: {High: 6},
  requestForegroundPermissionsAsync: jest.fn().mockResolvedValue({status: 'granted'}),
  watchPositionAsync: jest.fn().mockResolvedValue({remove: jest.fn()}),
}));

// ---------------------------------------------------------------------------
// adaptiveIntervalMs
// ---------------------------------------------------------------------------

describe('GpsService.adaptiveIntervalMs', () => {
  test('returns 5 s interval when approaching a stop (< 500 m)', () => {
    // speed doesn't matter — proximity takes priority
    expect(gpsService.adaptiveIntervalMs(20, 400)).toBe(5_000);
  });

  test('returns 60 s interval when stationary (speed < 5 km/h)', () => {
    const speedMs = 4 / 3.6; // 4 km/h in m/s
    expect(gpsService.adaptiveIntervalMs(speedMs)).toBe(60_000);
  });

  test('returns 60 s interval when speed is exactly 0', () => {
    expect(gpsService.adaptiveIntervalMs(0)).toBe(60_000);
  });

  test('returns 15 s interval for normal driving (≥ 5 km/h, not approaching)', () => {
    const speedMs = 50 / 3.6; // 50 km/h in m/s
    expect(gpsService.adaptiveIntervalMs(speedMs, 1000)).toBe(15_000);
  });

  test('approaching threshold is 500 m', () => {
    expect(APPROACHING_DISTANCE_M).toBe(500);
  });

  test('exactly at approaching distance boundary — uses normal interval', () => {
    const speedMs = 30 / 3.6;
    // exactly 500 m → NOT < 500, so normal interval
    expect(gpsService.adaptiveIntervalMs(speedMs, 500)).toBe(15_000);
  });

  test('stationary override does not apply when approaching', () => {
    // Even a stationary driver very close to a stop gets the 5 s interval
    expect(gpsService.adaptiveIntervalMs(0, 100)).toBe(5_000);
  });
});
