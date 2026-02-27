/**
 * AppDelegate.swift — iOS entry point for the NEMT Driver App.
 *
 * Configures:
 *   - Google Maps SDK (API key loaded from Info.plist)
 *   - Firebase (FCM push notifications)
 *   - React Native bridge
 *
 * SETUP:
 *   1. Add your Google Maps API key to Info.plist under GMSApiKey.
 *   2. Download GoogleService-Info.plist from Firebase Console and place it
 *      in the ios/ directory (do NOT commit this file — add to .gitignore).
 */
import UIKit
import GoogleMaps
import FirebaseCore

@main
class AppDelegate: UIResponder, UIApplicationDelegate {

  var window: UIWindow?

  func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {

    // Google Maps SDK — key stored in Info.plist (never hardcoded)
    if let mapsApiKey = Bundle.main.object(forInfoDictionaryKey: "GMSApiKey") as? String {
      GMSServices.provideAPIKey(mapsApiKey)
    }

    // Firebase (FCM push notifications)
    FirebaseApp.configure()

    return true
  }
}
