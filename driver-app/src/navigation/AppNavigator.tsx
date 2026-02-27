/**
 * AppNavigator — root React Navigation stack for the Driver App.
 *
 * Screens:
 *   Route       — full-shift map + stop list (default screen)
 *   StopDetail  — individual stop actions ("Arrived", "Picked Up", etc.)
 */
import React from 'react';
import {NavigationContainer} from '@react-navigation/native';
import {createNativeStackNavigator} from '@react-navigation/native-stack';

import RouteScreen from '../screens/RouteScreen';
import StopDetailScreen from '../screens/StopDetailScreen';
import {RootStackParamList} from '../types';

const Stack = createNativeStackNavigator<RootStackParamList>();

export default function AppNavigator(): React.JSX.Element {
  return (
    <NavigationContainer>
      <Stack.Navigator initialRouteName="Route">
        <Stack.Screen
          name="Route"
          component={RouteScreen}
          options={{title: 'Today\'s Route'}}
        />
        <Stack.Screen
          name="StopDetail"
          component={StopDetailScreen}
          options={{title: 'Stop Detail'}}
        />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
