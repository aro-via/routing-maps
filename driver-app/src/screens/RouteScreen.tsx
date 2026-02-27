/**
 * driver-app/src/screens/RouteScreen.tsx — Main shift screen for the driver.
 *
 * Layout (vertical split):
 *   ┌──────────────────────────────────┐
 *   │  UpdateBanner (dismissible)      │  ← only when route was re-optimized
 *   ├──────────────────────────────────┤
 *   │                                  │
 *   │         MapView (50 %)           │  ← driver dot + stop markers + polyline
 *   │                                  │
 *   ├──────────────────────────────────┤
 *   │  Stop list (scrollable, 50 %)    │  ← all stops, current highlighted
 *   └──────────────────────────────────┘
 *
 * Tapping a stop row navigates to StopDetailScreen.
 * The "Navigate" button deep-links to Google Maps for the current stop.
 *
 * No PHI is displayed — only stop sequence number and arrival ETA.
 */

import React, {useCallback, useEffect, useRef} from 'react';
import {
  Linking,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import MapView, {Marker, Polyline, Region} from 'react-native-maps';
import {useNavigation} from '@react-navigation/native';
import type {NativeStackNavigationProp} from '@react-navigation/native-stack';

import {
  useRouteStore,
  selectCurrentStop,
  selectStopsRemaining,
} from '../store/routeStore';
import {OptimizedStop, RootStackParamList} from '../types';

type NavigationProp = NativeStackNavigationProp<RootStackParamList, 'Route'>;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function RouteScreen(): React.JSX.Element {
  const navigation = useNavigation<NavigationProp>();
  const mapRef = useRef<MapView>(null);

  const route = useRouteStore(state => state.currentRoute);
  const stopIndex = useRouteStore(state => state.currentStopIndex);
  const updateReason = useRouteStore(state => state.routeUpdateReason);
  const dismissBanner = useRouteStore(state => state.dismissUpdateBanner);
  const currentStop = useRouteStore(selectCurrentStop);
  const remaining = useRouteStore(selectStopsRemaining);

  // Pan map to current stop whenever the route updates
  useEffect(() => {
    if (currentStop && mapRef.current) {
      mapRef.current.animateToRegion(
        {
          latitude: currentStop.location.lat,
          longitude: currentStop.location.lng,
          latitudeDelta: 0.05,
          longitudeDelta: 0.05,
        },
        500, // animation duration ms
      );
    }
  }, [currentStop]);

  const openGoogleMaps = useCallback(() => {
    if (!currentStop) {
      return;
    }
    const {lat, lng} = currentStop.location;
    // Try Google Maps deep link first, fall back to browser URL
    const gmapsDeep = `comgooglemaps://?daddr=${lat},${lng}&directionsmode=driving`;
    const gmapsWeb = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;

    Linking.canOpenURL(gmapsDeep)
      .then(supported =>
        Linking.openURL(supported ? gmapsDeep : gmapsWeb),
      )
      .catch(() => Linking.openURL(gmapsWeb));
  }, [currentStop]);

  const goToStopDetail = useCallback(
    (stop: OptimizedStop, index: number) => {
      navigation.navigate('StopDetail', {stop, stopIndex: index});
    },
    [navigation],
  );

  // Build polyline coordinates from all stops
  const polylineCoords = route.map(s => ({
    latitude: s.location.lat,
    longitude: s.location.lng,
  }));

  const initialRegion: Region | undefined =
    route.length > 0
      ? {
          latitude: route[0].location.lat,
          longitude: route[0].location.lng,
          latitudeDelta: 0.1,
          longitudeDelta: 0.1,
        }
      : undefined;

  return (
    <View style={styles.container}>
      {/* ---- Route update banner ---- */}
      {updateReason != null && (
        <View style={styles.banner}>
          <Text style={styles.bannerText}>
            {updateReason === 'traffic_delay'
              ? '🚦 Route updated due to traffic'
              : '📍 Route updated — stop list changed'}
          </Text>
          <TouchableOpacity onPress={dismissBanner} testID="dismiss-banner">
            <Text style={styles.bannerDismiss}>✕</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* ---- Map ---- */}
      <MapView
        ref={mapRef}
        style={styles.map}
        initialRegion={initialRegion}
        showsUserLocation
        showsMyLocationButton={false}>
        {/* Stop markers */}
        {route.map((stop, idx) => (
          <Marker
            key={stop.stop_id}
            coordinate={{
              latitude: stop.location.lat,
              longitude: stop.location.lng,
            }}
            title={`Stop ${stop.sequence}`}
            description={`ETA ${stop.arrival_time}`}
            pinColor={idx === stopIndex ? '#2196F3' : idx < stopIndex ? '#9E9E9E' : '#F44336'}
            testID={`marker-${stop.stop_id}`}
          />
        ))}
        {/* Route polyline */}
        {polylineCoords.length > 1 && (
          <Polyline
            coordinates={polylineCoords}
            strokeColor="#2196F3"
            strokeWidth={3}
          />
        )}
      </MapView>

      {/* ---- Stop list ---- */}
      <View style={styles.listContainer}>
        <View style={styles.listHeader}>
          <Text style={styles.listTitle}>
            {remaining} stop{remaining !== 1 ? 's' : ''} remaining
          </Text>
          {currentStop && (
            <TouchableOpacity
              style={styles.navigateButton}
              onPress={openGoogleMaps}
              testID="navigate-button">
              <Text style={styles.navigateText}>Navigate</Text>
            </TouchableOpacity>
          )}
        </View>

        <ScrollView>
          {route.length === 0 ? (
            <Text style={styles.emptyText}>No stops assigned yet.</Text>
          ) : (
            route.map((stop, idx) => (
              <TouchableOpacity
                key={stop.stop_id}
                style={[
                  styles.stopRow,
                  idx === stopIndex && styles.stopRowCurrent,
                  idx < stopIndex && styles.stopRowCompleted,
                ]}
                onPress={() => goToStopDetail(stop, idx)}
                testID={`stop-row-${stop.stop_id}`}>
                <View style={styles.stopBadge}>
                  <Text style={styles.stopBadgeText}>{stop.sequence}</Text>
                </View>
                <View style={styles.stopInfo}>
                  <Text
                    style={[
                      styles.stopTitle,
                      idx < stopIndex && styles.stopTitleCompleted,
                    ]}>
                    Stop {stop.sequence}
                    {idx === stopIndex ? '  ← Current' : ''}
                  </Text>
                  <Text style={styles.stopEta}>ETA {stop.arrival_time}</Text>
                </View>
              </TouchableOpacity>
            ))
          )}
        </ScrollView>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#fff'},

  // Banner
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#FFF3CD',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#FFECB5',
  },
  bannerText: {fontSize: 14, color: '#856404', flex: 1},
  bannerDismiss: {fontSize: 16, color: '#856404', paddingLeft: 12},

  // Map (top 50 %)
  map: {flex: 1},

  // Stop list (bottom 50 %)
  listContainer: {
    flex: 1,
    borderTopWidth: 1,
    borderTopColor: '#E0E0E0',
    backgroundColor: '#FAFAFA',
  },
  listHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#E0E0E0',
    backgroundColor: '#fff',
  },
  listTitle: {fontSize: 15, fontWeight: '600', color: '#333'},

  navigateButton: {
    backgroundColor: '#2196F3',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  navigateText: {color: '#fff', fontWeight: '600', fontSize: 13},

  emptyText: {
    textAlign: 'center',
    color: '#9E9E9E',
    marginTop: 32,
    fontSize: 15,
  },

  // Stop row
  stopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#E0E0E0',
    backgroundColor: '#fff',
  },
  stopRowCurrent: {backgroundColor: '#E3F2FD'},
  stopRowCompleted: {opacity: 0.5},

  stopBadge: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#2196F3',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  stopBadgeText: {color: '#fff', fontWeight: '700', fontSize: 13},

  stopInfo: {flex: 1},
  stopTitle: {fontSize: 15, fontWeight: '500', color: '#333'},
  stopTitleCompleted: {textDecorationLine: 'line-through', color: '#9E9E9E'},
  stopEta: {fontSize: 13, color: '#757575', marginTop: 2},
});
