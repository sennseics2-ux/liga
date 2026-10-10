#!/usr/bin/env bash
set -euo pipefail
app_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ -f /workspace/toolchains/android-env.sh ]]; then
  source /workspace/toolchains/android-env.sh
fi
export LIGA_SIGNING_DIR="${LIGA_SIGNING_DIR:-$(dirname -- "$app_dir")/liga-signing}"
mkdir -p -- "$LIGA_SIGNING_DIR"
chmod 700 -- "$LIGA_SIGNING_DIR"
if [[ ! -f "$LIGA_SIGNING_DIR/liga-release.jks" ]]; then
  if [[ ! -f "$LIGA_SIGNING_DIR/keystore-password.txt" ]]; then
    python3 - "$LIGA_SIGNING_DIR/keystore-password.txt" <<'PYTHON'
import os, secrets, sys
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as file:
    file.write(secrets.token_urlsafe(36) + '\n')
PYTHON
  fi
  keytool -genkeypair -keystore "$LIGA_SIGNING_DIR/liga-release.jks" -storetype JKS \
    -storepass:file "$LIGA_SIGNING_DIR/keystore-password.txt" \
    -keypass:file "$LIGA_SIGNING_DIR/keystore-password.txt" \
    -alias liga-release -keyalg RSA -keysize 4096 -validity 10000 \
    -dname 'CN=LIGA, OU=Mobile, O=SX AAC, C=PT'
fi
chmod 600 -- "$LIGA_SIGNING_DIR/liga-release.jks" "$LIGA_SIGNING_DIR/keystore-password.txt"
android_gradle=(gradle)
if [[ -x "$app_dir/native-android/gradlew" ]]; then
  android_gradle=("$app_dir/native-android/gradlew")
fi
if [[ -x /workspace/toolchains/gradle-9.3.1/bin/gradle ]]; then
  android_gradle=(/workspace/toolchains/gradle-9.3.1/bin/gradle)
fi
"${android_gradle[@]}" -p "$app_dir/native-android" :app:assembleRelease \
  --init-script "$app_dir/scripts/signing.gradle" --no-daemon --console=plain \
  --max-workers="${LIGA_BUILD_WORKERS:-4}" \
  -Dorg.gradle.jvmargs='-Xmx2048m -XX:MaxMetaspaceSize=512m' "$@"
output_dir="${LIGA_APK_OUTPUT_DIR:-$app_dir/dist}"
mkdir -p -- "$output_dir"
cp -- "$app_dir/native-android/app/build/outputs/apk/release/app-release.apk" "$output_dir/liga.apk"
if [[ -n "${ANDROID_HOME:-}" && -x "$ANDROID_HOME/build-tools/36.0.0/apksigner" ]]; then
  "$ANDROID_HOME/build-tools/36.0.0/apksigner" verify --verbose --print-certs "$output_dir/liga.apk"
  "$ANDROID_HOME/build-tools/36.0.0/zipalign" -c -P 16 4 "$output_dir/liga.apk"
fi
printf 'Installable APK: %s\n' "$output_dir/liga.apk"
