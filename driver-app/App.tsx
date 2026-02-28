/**
 * App.tsx — Root component for the NEMT Driver App.
 *
 * Bootstraps:
 *   - React Navigation (AppNavigator)
 *   - GPS service (started/stopped via useEffect)
 *   - WebSocket client (connect on mount, disconnect on unmount)
 */
import React, {useEffect} from 'react';
import {StatusBar} from 'react-native';

import AppNavigator from './src/navigation/AppNavigator';
import {gpsService} from './src/services/gps';
import {wsClient} from './src/services/websocket';
import {useRouteStore} from './src/store/routeStore';

// Driver ID supplied by the dispatcher system at shift start.
// In production this comes from a secure login / session token.
const DRIVER_ID = 'driver-001';
const SERVER_URL = 'ws://localhost:8000';

export default function App(): React.JSX.Element {
  const setRoute = useRouteStore(state => state.setRoute);
  const setDriverLocation = useRouteStore(state => state.setDriverLocation);

  useEffect(() => {
    // Connect WebSocket and wire route updates into the store
    wsClient.connect(SERVER_URL, DRIVER_ID, {
      onRouteUpdated: stops => setRoute(stops),
    });

    // Start background GPS — each fix is forwarded to the WS client and map store
    gpsService.start(location => {
      wsClient.sendGpsUpdate(location);
      setDriverLocation(location);
    });

    return () => {
      gpsService.stop();
      wsClient.disconnect();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <StatusBar barStyle="dark-content" />
      <AppNavigator />
    </>
  );
}
