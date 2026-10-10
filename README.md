# Liga SX-AAC

This repository contains the **v25 league website** and the **1.1.0 mobile apps** for https://liga.sx-aac.com.

## Website — v25

The website source is in [`website/`](website/). This release adds email-based password recovery, editable identities and locked FIDE IDs, account deactivation, season scheduling, four-player match lineups, admin navigation, and security fixes. It retains the auction, scoring, localization, backup, and login-only replay improvements from v24. SMTP and the documented FIDE API contract require private deployment configuration; see the hosting guide.

**PGN replay and PGN downloads require a signed-in account.** Fixtures and results remain public. Login returns members to the selected game.

- [Website setup, features, and tests](website/README.md)
- [Production deployment, upgrades, backups, and restoration](website/HOSTING.md)
- [Automated website checks](.github/workflows/website.yml)

Publishing this repository does not deploy the live website. Follow the hosting instructions to update the server while preserving its database and uploads. Off-server backups require privately configured storage credentials.

## Mobile apps — 1.1.0

Mobile apps for **https://liga.sx-aac.com**. League data, accounts, results, and the website's language selector continue to come from the existing server. No backend deployment or database changes are required.

The delivered Android APK is built from the lightweight framework-only project in `native-android/`. The improved Expo implementation is retained in `src/` for optional cross-platform development. Both implementations use the same website and native controls.

## Improvements in this version

- Branded launch screen, header, and accessible native navigation.
- Back, Home, Refresh/Stop, and native sharing of the current league page.
- Portuguese/English native controls and notices. This switch does not change the website's own language setting.
- Clear connection, missing-page, and server-error screens with retry and browser actions.
- Progress resets on each navigation; intentional cancellation does not look like a connection failure.
- Exact HTTPS origin checks for the authenticated WebView, with guarded external links and visible link-opening failures.
- Compatible Expo/React Native dependencies and a reproducible npm lockfile.

The app requires internet access. Website login cookies are retained in the WebView but are separate from browser cookies. PGN downloads open in the device browser, which may require a separate website login. Push notifications and offline league-data storage are not included.

## Install the APK

Download `liga-sx-aac-1.1.0.apk` to an Android phone running Android 7.0 or newer, open the file, and allow installation from the browser or Files app if Android asks. It runs as a standalone Android app using the device's System WebView, across Android CPU architectures.

The APK is signed with a dedicated local signing key. If an existing `com.sxaac.liga` app was signed with another key, Android will not accept this as an update. Uninstalling the previous app removes its local session data. Future updates to this build must use the same signing key and a higher Android version code.

## Develop and validate

For the Expo implementation, use Node.js 24 or newer and npm:

```sh
npm ci
npm run check
npm test
npm run bundle:android
npm start
```

The nine URL-policy tests execute the production TypeScript using Node's built-in type stripping. `bundle:android` creates an Android JavaScript bundle; it does not create an APK. Expo Go can run this app for development, or `npm run android` builds a local development app when the Android toolchain and a device/emulator are available.

In the prepared cloud environment, use writable caches and disable optional Expo telemetry:

```sh
export npm_config_cache=/workspace/.cache/npm
export EXPO_NO_TELEMETRY=1
export EXPO_OFFLINE=1
```

Offline Expo commands use the compatibility metadata shipped with the installed Expo SDK. Online Expo account services are optional for this local build workflow.

## Build a signed APK locally

For the delivered native Android version, use Python 3, JDK 17, and an Android SDK containing platform 36 and build-tools 36.0.0. Set `JAVA_HOME`, `ANDROID_HOME`, and your executable `PATH`; accept the SDK licenses through Android's supported installer. The project uses Gradle 9.3.1. Its framework-only build does not require npm or an Expo account.

```sh
bash scripts/build-native-apk.sh
```

The output is `dist/liga.apk`. The helper builds a native release APK, applies the private signing key, and verifies the APK signature and alignment when Android build-tools are available. It uses up to four Gradle workers by default; set `LIGA_BUILD_WORKERS` for a different limit. See `native-android/README.md` for native URL-policy tests. `npm run build:apk` invokes this same helper when npm is available.

The separate `scripts/build-apk.sh` builds the Expo Android implementation. That route additionally needs NDK 27.1.12297006 and CMake 3.22.1, `npm ci`, and `npx --no-install expo prebuild --platform android --no-install`. React Native's Android artifact is served from `repo.reactnative.dev`; this environment currently blocks that domain. The domain addition is saved in the environment draft. Native Android builds are already independent of that artifact.

Signing material is kept **outside the source directory**, in the sibling `liga-signing` directory by default. Set `LIGA_SIGNING_DIR` to choose another location. The helper creates a key only when none exists and retains it for updates. Back up both `liga-release.jks` and `keystore-password.txt` privately; the source ZIP excludes them. The separate signing-backup download contains those files and must not be shared publicly.

The prepared cloud machine already contains the verified toolchain at `/workspace/toolchains`; the helper activates it automatically there. Retained dependencies and tools survive an environment snapshot, but emulator and Metro processes must be restarted.

## Optional Expo cloud/store builds

`eas.json` retains the `preview` APK and `production` Android App Bundle profiles. An Expo account and its signing configuration are required for EAS cloud builds. Store publication and iOS distribution are separate from this Android installation build.

## Project layout

- `src/App.tsx`: native shell, navigation, loading, and recovery UI.
- `native-android/`: Android framework implementation used for the delivered APK.
- `src/urls.ts`: first-party and external-link policy.
- `tests/urls.test.cjs`: production URL-policy regression tests.
- `app.json`: branding, app IDs, native version, and permissions.
- `scripts/`: local APK build and signing configuration without embedded credentials.

Use the existing checkout for cloud tasks; a Git worktree is unnecessary unless explicitly requested.
