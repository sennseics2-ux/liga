# Liga SX-AAC

This repository contains the **v81 league website** and the **1.1.0 mobile apps** for https://liga.sx-aac.com.

## Club landing page

The centered black-and-white page for **www.sx-aac.com** is in [`website/landing/`](website/landing/). Its League button links to https://liga.sx-aac.com/. The website proxy serves both domains; point `www.sx-aac.com` and `sx-aac.com` DNS records to the League VM before deployment.

[Desktop preview](docs/previews/sx-aac-landing-desktop.png) · [Mobile preview](docs/previews/sx-aac-landing-mobile.png)

## Website — v81

The website source is in [`website/`](website/). V35 adds round filtering, explicit home-versus-away fixture headings, and season league standings using 3/1/0 match points; fantasy-point displays and adjustment controls are removed. V34 adds current team affiliation and join dates to profile headers, final match winner/draw highlights, a round schedule in Results, and corrected responsive dark backgrounds. V33 introduces captain terminology, compact profile-header career results, clearer seasonal squad cards with join/leave dates, simpler team sorting and stronger dark-mode section contrast. V32 permits shared FIDE IDs, adds all-season player wins/draws/losses, introduces persistent site-wide dark mode, renames the season calendar Results, and shows each archived squad member’s chess score/games played. V31 adds direct invitation cancellation in team management, a red remove-manager icon, and automatic availability after an administrator removes a manager, allowing reinvitation to the same team. Before kickoff, lineups are visible only within their own team; board pairings and associated game/PGN pages remain hidden from every viewer until kickoff. V30 adds team profile pictures uploaded, replaced and removed by the currently assigned manager. Pictures also appear in the directory, standings, fixtures and match scoreboards, and are included in SQLite backups. V29 adds a redesigned administration dashboard with dedicated management workspaces, the ♔ transfer-currency symbol, and green/red/grey results on player profiles. V28 adds gold, silver and bronze team-profile medals engraved with the season year. Completed seasons use 3/1/0 team-match points and head-to-head tiebreaks. V27 opens Seasons on the current season even before publication, adds a season dropdown, and redesigns round results and match scoreboards for desktop and mobile. V26 requires both username and email for password recovery, improves the recovery page, explains deactivated-account login failures, and renders Criar conta on Portuguese registration. A private VM generator adds two completed six-round demonstration seasons using current teams and rosters while retaining accounts. Account settings, automatic FIDE standard ratings, season scheduling, lineups, auctions, scoring, backups and public PGN replay remain available. Keep SMTP credentials private on the VM; the default public FIDE lookup needs no API key. See the hosting guide for upgrades and database generation.

**PGN replay and downloads are available without signing in for visible games.** Pre-match pairings keep their existing privacy restrictions.

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

The app requires internet access. Website login cookies are retained in the WebView but are separate from browser cookies. PGN downloads open in the device browser. Push notifications and offline league-data storage are not included.

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
