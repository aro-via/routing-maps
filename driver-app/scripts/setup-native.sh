#!/usr/bin/env bash
# =============================================================================
# setup-native.sh — Generate React Native 0.76.5 native project infrastructure
#
# Run this ONCE after cloning the repo (or after switching from Expo to pure RN).
# It generates the android/ and ios/ build files using the official RN template,
# then overlays our custom source files on top.
#
# Usage:
#   cd driver-app
#   bash scripts/setup-native.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
APP_NAME="DriverApp"
RN_VERSION="0.76.5"
TMP_DIR="$(mktemp -d)"

echo "============================================="
echo "  NEMT Driver App — Native Setup"
echo "  React Native $RN_VERSION"
echo "============================================="
echo ""

cleanup() {
  echo "Cleaning up temp directory..."
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# 1. Generate a fresh RN project in a temp location
echo "[1/5] Generating RN $RN_VERSION template..."
cd "$TMP_DIR"
npx @react-native-community/cli@15 init "$APP_NAME" \
  --version "$RN_VERSION" \
  --skip-install \
  --skip-git-init \
  --pm npm

echo "[2/5] Copying Android build infrastructure..."
# Copy gradle wrapper + top-level build files
# Do NOT overwrite AndroidManifest.xml, gradle.properties (we keep newArchEnabled=false)
cp    "$TMP_DIR/$APP_NAME/android/build.gradle"              "$APP_DIR/android/"
cp    "$TMP_DIR/$APP_NAME/android/settings.gradle"          "$APP_DIR/android/"
cp    "$TMP_DIR/$APP_NAME/android/app/build.gradle"         "$APP_DIR/android/app/"
cp    "$TMP_DIR/$APP_NAME/android/app/proguard-rules.pro"   "$APP_DIR/android/app/"
cp -r "$TMP_DIR/$APP_NAME/android/gradle"                   "$APP_DIR/android/"
cp    "$TMP_DIR/$APP_NAME/android/gradlew"                  "$APP_DIR/android/"
cp    "$TMP_DIR/$APP_NAME/android/gradlew.bat"              "$APP_DIR/android/"
chmod +x "$APP_DIR/android/gradlew"

# Copy resource directories (strings, styles, launcher icons, etc.)
cp -r "$TMP_DIR/$APP_NAME/android/app/src/main/res"         "$APP_DIR/android/app/src/main/"

echo "[3/5] Copying iOS project structure..."
# Copy Podfile + Xcode project (do NOT overwrite AppDelegate.swift)
cp    "$TMP_DIR/$APP_NAME/ios/Podfile"                                   "$APP_DIR/ios/"
cp -r "$TMP_DIR/$APP_NAME/ios/$APP_NAME.xcodeproj"                       "$APP_DIR/ios/"
# Info.plist and LaunchScreen if not already present
[ ! -f "$APP_DIR/ios/$APP_NAME/Info.plist" ] && \
  cp "$TMP_DIR/$APP_NAME/ios/$APP_NAME/Info.plist"                       "$APP_DIR/ios/$APP_NAME/"
[ ! -f "$APP_DIR/ios/$APP_NAME/LaunchScreen.storyboard" ] && \
  cp "$TMP_DIR/$APP_NAME/ios/$APP_NAME/LaunchScreen.storyboard"          "$APP_DIR/ios/$APP_NAME/"
[ ! -f "$APP_DIR/ios/$APP_NAME/PrivacyInfo.xcprivacy" ] && \
  cp "$TMP_DIR/$APP_NAME/ios/$APP_NAME/PrivacyInfo.xcprivacy"            "$APP_DIR/ios/$APP_NAME/"

echo "[4/5] Installing JS dependencies..."
cd "$APP_DIR"
npm install

echo "[5/5] Installing iOS CocoaPods..."
cd "$APP_DIR/ios"
pod install
cd "$APP_DIR"

echo ""
echo "============================================="
echo "  Setup complete!"
echo "============================================="
echo ""
echo "To run on Android:"
echo "  cd driver-app && npx react-native run-android"
echo ""
echo "To run on iOS simulator:"
echo "  cd driver-app && npx react-native run-ios"
echo ""
echo "To run on iOS device (Xcode):"
echo "  Open driver-app/ios/DriverApp.xcworkspace in Xcode"
echo "  Select your device and press Run (▶)"
echo ""
