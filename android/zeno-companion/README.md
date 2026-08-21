# ZENO Android Companion

This is the optional native layer for the existing ZENO Anywhere service.
It does not replace the PWA. The PWA remains the full phone interface; this
small application supplies the Android features a web page cannot provide:

- an owner-enabled `TYPE_APPLICATION_OVERLAY` mini-orb;
- a visible foreground-service notification while the orb is active;
- Android Keystore-backed storage for the one-time device credential;
- an explicitly enabled Accessibility Service for a deliberately small action
  allowlist.

## Safety boundary

The app can perform only Back, Home, Recents, open notifications/quick
settings, scroll a visible scroll container, and open a normal launchable app.
It has no arbitrary tap, typing, gesture injection, purchase, message-send,
delete, settings, permission, package-install, credential, or lock-screen
operation. Android can hide overlays on sensitive screens and remains the
authority for every permission.

## Pair and run

1. In the trusted ZENO Anywhere PWA open **Devices → Pair Android overlay**.
2. In this app scan the temporary QR (or enter its HTTPS gateway and six-digit
   code). The permanent device token is returned only after the one-time code
   is consumed and is encrypted with Android Keystore.
3. Approve the new Android device in the PWA.
4. Enable **Display over other apps** and, if phone actions are wanted,
   **ZENO basic phone controls** in Android Accessibility Settings.
5. Press **Start ZENO orb**. Android displays a persistent notification while
   it is active.

The project targets API 35, requires JDK 17 and Android SDK 35, and opens
directly in Android Studio. No Android SDK is bundled into the ZENO repository.

## Command-line verification

From this directory, run the unit tests and build a debug APK with Gradle 8.9:

```powershell
gradle --no-daemon :app:testDebugUnitTest :app:assembleDebug
```

The generated APK is `app/build/outputs/apk/debug/app-debug.apk`. Installation
is an explicit owner action; ZENO does not install packages or grant its own
permissions. After installation, pair it from the trusted PWA before enabling
the overlay or Accessibility service.

## Android limits

Most ordinary apps can be covered by the owner-enabled overlay. Android or an
individual app may suppress overlays on lock, permission, payment, DRM or other
sensitive screens. Some games also prohibit overlays or Accessibility services.
ZENO treats those restrictions as authoritative and does not attempt to bypass
them. The basic action bridge does not claim game-specific play or unrestricted
phone control.
