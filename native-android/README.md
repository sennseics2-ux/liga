# Liga SX-AAC Android app

This framework-only Android implementation opens the Liga website at `https://liga.sx-aac.com/`. The React Native/Expo source remains in the parent project. Both implement the same improved app controls and branding. This Android project has no React Native, AndroidX, or other third-party runtime dependencies.

## Features

- Original Liga logo, white/black interface and restrained red highlights.
- Portuguese and English app controls, with the language choice remembered.
- Back, Home, Refresh/Stop and the Android share sheet. Hardware Back handles website history before leaving the app, including the modern Android back API.
- Persistent first-party cookies and website storage. Activity recreation preserves browser history and the current page.
- Branded startup/loading screen, navigation progress and scrollable offline, 404 and server-error recovery screens.
- Website file uploads through the Android document picker, including multiple-file selection when requested by the website.
- External browser, email and telephone links pass a strict URL guard. PGN downloads open in the phone's browser, matching the original app. The browser maintains its own login session and may require signing in for protected downloads.
- Edge-to-edge system-bar insets, keyboard handling, system font scaling and accessible native controls.

The website continues to own login, accounts, chess games, standings and form validation. Website authentication/validation responses such as 401, 403 and 422 are displayed by the website. An internet connection is required; the app does not provide an offline copy of live League data.

Only the `INTERNET` permission is requested. The native shell exposes no JavaScript interfaces or injected authentication, blocks mixed content and local file/content navigation, rejects unsafe intent schemes and retains normal TLS verification. The release build disables Android backup of website sessions.

## Build

Use JDK 17, Android SDK platform 36 and Gradle 9.3.1. The Gradle wrapper includes the official distribution SHA-256 checksum. Android Gradle Plugin is pinned to 8.12.0. The app requires Android 7.0 or newer (`minSdk 24`) and targets SDK 36.

From the parent project:

```sh
scripts/build-native-apk.sh
```

That helper signs release builds using private key material kept outside the source checkout. Preserve the signing directory for future updates; Android requires the same key to install an update over an existing installation. Never commit the key, password or signing directory. APK signing by an existing different key requires uninstalling the earlier app first, which removes its local website session.

For an unsigned build without the parent helper:

```sh
cd native-android
./gradlew :app:assembleRelease
```

To use an existing signing key with the parent project's signing initializer:

```sh
export LIGA_SIGNING_DIR=/private/path/to/signing-material
./gradlew :app:assembleRelease --init-script ../scripts/signing.gradle
```

The signed APK is generated at `app/build/outputs/apk/release/app-release.apk`. The distribution build uses package `com.sxaac.liga`, version `1.1.0` and version code `2`.

## Validate

```sh
tests/test-urls.sh
./gradlew :app:lintRelease
```

The pure Java URL tests do not need Android SDK, Gradle or downloaded testing dependencies. On a phone or emulator, exercise launch, the PT/EN toggle, site navigation, Back/Home/Refresh/Stop, sharing and browser links. Switch off connectivity to verify Retry and browser recovery. File uploads and protected account workflows need a real website session.

For cloud work, use the existing checkout: each task already runs in an isolated environment, so a Git worktree is unnecessary unless explicitly requested.
