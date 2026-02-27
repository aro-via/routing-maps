# NEMT Driver App

React Native mobile app for Non-Emergency Medical Transportation drivers.

## Prerequisites

| Tool | Version |
|------|---------|
| Node | 18+ |
| React Native CLI | Latest |
| Xcode | 15+ (iOS) |
| Android Studio | Flamingo+ (Android) |
| CocoaPods | 1.15+ |

## Setup

```bash
# Install dependencies
npm install

# iOS — install CocoaPods
cd ios && pod install && cd ..

# Android — no extra steps
```

## API Keys (required before running)

### Google Maps

**Android** — set in `android/app/src/main/AndroidManifest.xml`:
```xml
<meta-data android:name="com.google.android.geo.API_KEY"
           android:value="YOUR_API_KEY_HERE" />
```

**iOS** — set in `ios/Info.plist`:
```xml
<key>GMSApiKey</key>
<string>YOUR_API_KEY_HERE</string>
```

### Firebase

1. Create a Firebase project at [console.firebase.google.com](https://console.firebase.google.com)
2. Download `google-services.json` → place in `android/app/`
3. Download `GoogleService-Info.plist` → place in `ios/`

> **HIPAA note:** These files contain project credentials — never commit them.
> They are excluded via `.gitignore`.

## Running

```bash
# Start Metro bundler
npm start

# Run on iOS simulator (requires Xcode)
npm run ios

# Run on Android emulator
npm run android
```

## Server configuration

Set the WebSocket server URL in `App.tsx`:
```typescript
const SERVER_URL = 'ws://localhost:8000'; // development
// const SERVER_URL = 'wss://your-production-host.com'; // production
```

## Architecture

```
src/
├── types/         — Shared TypeScript interfaces (mirror server schemas)
├── services/
│   ├── gps.ts     — Background GPS tracking (adaptive intervals)
│   └── websocket.ts — WS client with auto-reconnect
├── store/
│   └── routeStore.ts — Zustand state for current route
├── navigation/
│   └── AppNavigator.tsx — React Navigation stack
├── screens/
│   ├── RouteScreen.tsx      — Map + stop list
│   └── StopDetailScreen.tsx — Per-stop actions
└── components/    — Shared UI components
```
