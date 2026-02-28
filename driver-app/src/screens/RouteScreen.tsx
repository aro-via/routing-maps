/**
 * driver-app/src/screens/RouteScreen.tsx — Main shift screen for the driver.
 *
 * Layout:
 *   ┌──────────────────────────────────┐
 *   │  UpdateBanner (dismissible)      │  ← only when route was re-optimised
 *   ├──────────────────────────────────┤
 *   │  Route Summary Card              │  ← current stop + Navigate button
 *   ├──────────────────────────────────┤
 *   │  Stop list (scrollable)          │  ← all stops, current highlighted
 *   └──────────────────────────────────┘
 *
 * react-native-maps removed for Expo Go compatibility.
 * The Navigate button deep-links to Google Maps for turn-by-turn directions.
 *
 * No PHI is displayed — only stop sequence number and arrival ETA.
 */

import React, {useCallback} from 'react';
import {
  Linking,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
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

  const route = useRouteStore(state => state.currentRoute);
  const stopIndex = useRouteStore(state => state.currentStopIndex);
  const updateReason = useRouteStore(state => state.routeUpdateReason);
  const dismissBanner = useRouteStore(state => state.dismissUpdateBanner);
  const currentStop = useRouteStore(selectCurrentStop);
  const remaining = useRouteStore(selectStopsRemaining);

  const openGoogleMaps = useCallback(() => {
    if (!currentStop) {return;}
    const {lat, lng} = currentStop.location;
    const gmapsDeep = `comgooglemaps://?daddr=${lat},${lng}&directionsmode=driving`;
    const gmapsWeb = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;
    Linking.canOpenURL(gmapsDeep)
      .then(supported => Linking.openURL(supported ? gmapsDeep : gmapsWeb))
      .catch(() => Linking.openURL(gmapsWeb));
  }, [currentStop]);

  const goToStopDetail = useCallback(
    (stop: OptimizedStop, index: number) => {
      navigation.navigate('StopDetail', {stop, stopIndex: index});
    },
    [navigation],
  );

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

      {/* ---- Current stop summary card ---- */}
      <View style={styles.card}>
        {currentStop ? (
          <>
            <View style={styles.cardRow}>
              <View style={styles.cardBadge}>
                <Text style={styles.cardBadgeText}>{currentStop.sequence}</Text>
              </View>
              <View style={styles.cardInfo}>
                <Text style={styles.cardTitle}>
                  Next Stop · Arrive {currentStop.arrival_time}
                </Text>
                <Text style={styles.cardCoords}>
                  {currentStop.location.lat.toFixed(5)}, {currentStop.location.lng.toFixed(5)}
                </Text>
                <Text style={styles.cardDepart}>
                  Depart by {currentStop.departure_time}
                </Text>
              </View>
            </View>
            <TouchableOpacity
              style={styles.navButton}
              onPress={openGoogleMaps}
              testID="navigate-button">
              <Text style={styles.navButtonText}>▶  Open in Google Maps</Text>
            </TouchableOpacity>
          </>
        ) : (
          <Text style={styles.cardEmpty}>
            {route.length === 0 ? 'Waiting for route assignment…' : 'All stops completed ✓'}
          </Text>
        )}
      </View>

      {/* ---- Stop list ---- */}
      <View style={styles.listContainer}>
        <View style={styles.listHeader}>
          <Text style={styles.listTitle}>
            {remaining} stop{remaining !== 1 ? 's' : ''} remaining
          </Text>
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
                <View style={[
                  styles.stopBadge,
                  idx < stopIndex && styles.stopBadgeDone,
                ]}>
                  <Text style={styles.stopBadgeText}>
                    {idx < stopIndex ? '✓' : stop.sequence}
                  </Text>
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
                <Text style={styles.stopChevron}>›</Text>
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
  container: {flex: 1, backgroundColor: '#F5F6FA'},

  // Update banner
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

  // Current stop card
  card: {
    backgroundColor: '#fff',
    margin: 12,
    borderRadius: 12,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 2},
    shadowOpacity: 0.08,
    shadowRadius: 6,
    elevation: 3,
  },
  cardRow: {flexDirection: 'row', alignItems: 'flex-start'},
  cardBadge: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#2196F3',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  cardBadgeText: {color: '#fff', fontWeight: '700', fontSize: 18},
  cardInfo: {flex: 1},
  cardTitle: {fontSize: 16, fontWeight: '700', color: '#1A1A2E'},
  cardCoords: {fontSize: 12, color: '#757575', marginTop: 2, fontFamily: 'monospace'},
  cardDepart: {fontSize: 12, color: '#F57C00', marginTop: 4},
  cardEmpty: {fontSize: 15, color: '#9E9E9E', textAlign: 'center', paddingVertical: 8},
  navButton: {
    marginTop: 14,
    backgroundColor: '#2196F3',
    paddingVertical: 11,
    borderRadius: 8,
    alignItems: 'center',
  },
  navButtonText: {color: '#fff', fontWeight: '700', fontSize: 14},

  // Stop list
  listContainer: {
    flex: 1,
    backgroundColor: '#fff',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    overflow: 'hidden',
  },
  listHeader: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#F0F0F0',
  },
  listTitle: {fontSize: 15, fontWeight: '600', color: '#333'},
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
    paddingVertical: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#E8E8E8',
    backgroundColor: '#fff',
  },
  stopRowCurrent: {backgroundColor: '#E3F2FD'},
  stopRowCompleted: {opacity: 0.45},

  stopBadge: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#2196F3',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  stopBadgeDone: {backgroundColor: '#4CAF50'},
  stopBadgeText: {color: '#fff', fontWeight: '700', fontSize: 13},

  stopInfo: {flex: 1},
  stopTitle: {fontSize: 15, fontWeight: '500', color: '#222'},
  stopTitleCompleted: {textDecorationLine: 'line-through', color: '#AAAAAA'},
  stopEta: {fontSize: 13, color: '#757575', marginTop: 2},
  stopChevron: {fontSize: 20, color: '#CCCCCC', marginLeft: 8},
});
