#!/usr/bin/env bash
set -euo pipefail
native_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_output=$(mktemp -d)
trap 'rm -rf -- "$test_output"' EXIT
javac -encoding UTF-8 -d "$test_output" \
  "$native_root/app/src/main/java/com/sxaac/liga/UrlGuard.java" \
  "$native_root/tests/UrlGuardTest.java"
java -cp "$test_output" com.sxaac.liga.UrlGuardTest
