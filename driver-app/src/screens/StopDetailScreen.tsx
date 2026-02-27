/**
 * driver-app/src/screens/StopDetailScreen.tsx — Per-stop action screen.
 *
 * Displays minimal information about the current stop (no PHI beyond stop_id
 * UUID and sequence number — patient names/addresses are never sent to the app).
 *
 * Action buttons:
 *   "Arrived"      — records arrival time locally; starts a service timer
 *   "Picked Up"    — sends completed_stop_id via WebSocket; advances route
 *   "Unable to Pick Up" — opens reason selector; sends cancellation flag
 *
 * The screen is navigated to from RouteScreen when the driver taps a stop row.
 */

import React, {useCallback, useEffect, useState} from 'react';
import {
  Alert,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import {useNavigation, useRoute, RouteProp} from '@react-navigation/native';
import type {NativeStackNavigationProp} from '@react-navigation/native-stack';

import {useRouteStore} from '../store/routeStore';
import {wsClient} from '../services/websocket';
import {gpsService} from '../services/gps';
import {RootStackParamList} from '../types';

type StopDetailRouteProp = RouteProp<RootStackParamList, 'StopDetail'>;
type NavigationProp = NativeStackNavigationProp<RootStackParamList, 'StopDetail'>;

// ---------------------------------------------------------------------------
// Cancellation reasons (no PHI — operational reasons only)
// ---------------------------------------------------------------------------

const CANCELLATION_REASONS = [
  'Patient not home',
  'Patient declined transport',
  'Wrong address',
  'Safety concern',
  'Other',
] as const;

type CancellationReason = (typeof CANCELLATION_REASONS)[number];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function StopDetailScreen(): React.JSX.Element {
  const navigation = useNavigation<NavigationProp>();
  const {params} = useRoute<StopDetailRouteProp>();
  const {stop, stopIndex} = params;

  const completeCurrentStop = useRouteStore(state => state.completeCurrentStop);
  const currentStopIndex = useRouteStore(state => state.currentStopIndex);

  const [arrivedAt, setArrivedAt] = useState<string | null>(null);
  const [serviceSeconds, setServiceSeconds] = useState(0);

  // Service timer — starts when driver taps "Arrived"
  useEffect(() => {
    if (!arrivedAt) {
      return;
    }
    const interval = setInterval(
      () => setServiceSeconds(s => s + 1),
      1000,
    );
    return () => clearInterval(interval);
  }, [arrivedAt]);

  const isCurrentStop = stopIndex === currentStopIndex;

  // ---- Handlers ----

  const handleArrived = useCallback(() => {
    const now = new Date().toISOString();
    setArrivedAt(now);
  }, []);

  const handlePickedUp = useCallback(() => {
    // Send completed_stop_id via WebSocket (GPS location will be in the
    // next regular GPS update — we piggyback on that message)
    gpsService.stop().then(() =>
      gpsService.start(location =>
        wsClient.sendGpsUpdate(location, stop.stop_id),
      ),
    );

    // Advance local state immediately so the UI responds without waiting
    // for the server round-trip
    completeCurrentStop();
    navigation.goBack();
  }, [stop.stop_id, completeCurrentStop, navigation]);

  const handleUnableToPickUp = useCallback(() => {
    Alert.alert(
      'Unable to Pick Up',
      'Select a reason:',
      [
        ...CANCELLATION_REASONS.map(reason => ({
          text: reason,
          onPress: () => _sendCancellation(reason),
        })),
        {text: 'Cancel', style: 'cancel'},
      ],
    );
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function _sendCancellation(reason: CancellationReason): void {
    // Send cancellation via WebSocket (mark stop with a cancellation flag
    // embedded in the stop_id convention: "cancel:{stop_id}:{reason}")
    // No PHI in the reason strings — all predefined operational values.
    const cancelStopId = `cancel:${stop.stop_id}`;
    gpsService.stop().then(() =>
      gpsService.start(location =>
        wsClient.sendGpsUpdate(location, cancelStopId),
      ),
    );

    completeCurrentStop();
    navigation.goBack();
  }

  // ---- Render ----

  const formattedServiceTime = arrivedAt
    ? `${Math.floor(serviceSeconds / 60)}m ${serviceSeconds % 60}s`
    : null;

  return (
    <View style={styles.container}>
      {/* ---- Stop header ---- */}
      <View style={styles.header}>
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{stop.sequence}</Text>
        </View>
        <View style={styles.headerInfo}>
          <Text style={styles.headerTitle}>Stop {stop.sequence}</Text>
          <Text style={styles.headerEta}>
            ETA {stop.arrival_time} — Dep {stop.departure_time}
          </Text>
        </View>
      </View>

      {/* ---- Arrived status ---- */}
      {arrivedAt && (
        <View style={styles.arrivedBanner}>
          <Text style={styles.arrivedText}>
            Arrived — Service time: {formattedServiceTime}
          </Text>
        </View>
      )}

      {/* ---- Action buttons (only for current stop) ---- */}
      {isCurrentStop ? (
        <View style={styles.actions}>
          {!arrivedAt && (
            <TouchableOpacity
              style={[styles.button, styles.buttonArrived]}
              onPress={handleArrived}
              testID="btn-arrived">
              <Text style={styles.buttonText}>Arrived</Text>
            </TouchableOpacity>
          )}

          <TouchableOpacity
            style={[styles.button, styles.buttonPickedUp]}
            onPress={handlePickedUp}
            testID="btn-picked-up">
            <Text style={styles.buttonText}>Picked Up</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.button, styles.buttonUnable]}
            onPress={handleUnableToPickUp}
            testID="btn-unable">
            <Text style={styles.buttonText}>Unable to Pick Up</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <View style={styles.infoBox}>
          <Text style={styles.infoText}>
            {stopIndex < currentStopIndex
              ? 'This stop has been completed.'
              : 'Complete the current stop first.'}
          </Text>
        </View>
      )}

      {/* ---- Stop coordinates (operational, no PHI) ---- */}
      <View style={styles.detailsBox}>
        <Text style={styles.detailsLabel}>Location</Text>
        <Text style={styles.detailsValue}>
          {stop.location.lat.toFixed(5)}, {stop.location.lng.toFixed(5)}
        </Text>
        <Text style={styles.detailsLabel}>Stop ID</Text>
        <Text style={styles.detailsValue}>{stop.stop_id}</Text>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#fff'},

  // Header
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#E0E0E0',
  },
  badge: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#2196F3',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 16,
  },
  badgeText: {color: '#fff', fontWeight: '700', fontSize: 20},
  headerInfo: {flex: 1},
  headerTitle: {fontSize: 20, fontWeight: '700', color: '#212121'},
  headerEta: {fontSize: 14, color: '#757575', marginTop: 2},

  // Arrived banner
  arrivedBanner: {
    backgroundColor: '#E8F5E9',
    padding: 12,
    marginHorizontal: 16,
    marginTop: 12,
    borderRadius: 8,
  },
  arrivedText: {color: '#2E7D32', fontWeight: '600', textAlign: 'center'},

  // Action buttons
  actions: {padding: 20, gap: 12},
  button: {
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  buttonArrived: {backgroundColor: '#4CAF50'},
  buttonPickedUp: {backgroundColor: '#2196F3'},
  buttonUnable: {backgroundColor: '#FF5722'},
  buttonText: {color: '#fff', fontWeight: '700', fontSize: 16},

  // Info box (non-current stop)
  infoBox: {
    margin: 20,
    padding: 16,
    backgroundColor: '#F5F5F5',
    borderRadius: 8,
  },
  infoText: {color: '#757575', textAlign: 'center', fontSize: 15},

  // Details
  detailsBox: {
    margin: 20,
    padding: 16,
    backgroundColor: '#F9F9F9',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E0E0E0',
  },
  detailsLabel: {
    fontSize: 11,
    color: '#9E9E9E',
    fontWeight: '600',
    marginTop: 8,
    textTransform: 'uppercase',
  },
  detailsValue: {fontSize: 14, color: '#333', marginTop: 2},
});
