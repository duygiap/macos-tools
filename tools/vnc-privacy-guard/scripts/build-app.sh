#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ARCH="${ARCH:-x86_64}"
CONFIG="${CONFIG:-release}"
DIST="$ROOT/dist"
APP="$DIST/VNC Privacy Guard.app"
CONTENTS="$APP/Contents"

rm -rf "$DIST"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources" "$CONTENTS/Helpers"

swift build -c "$CONFIG" --arch "$ARCH"
BIN_DIR="$(swift build -c "$CONFIG" --arch "$ARCH" --show-bin-path)"

cp "$BIN_DIR/VNCPrivacyGuard" "$CONTENTS/MacOS/VNCPrivacyGuard"
cp "$BIN_DIR/vncprivacy" "$CONTENTS/Helpers/vncprivacy"
cp "$BIN_DIR/VNCPrivacyRecoveryAgent" "$CONTENTS/Helpers/VNCPrivacyRecoveryAgent"
cp "$ROOT/Resources/Info.plist" "$CONTENTS/Info.plist"

chmod 755 "$CONTENTS/MacOS/VNCPrivacyGuard" "$CONTENTS/Helpers/vncprivacy" "$CONTENTS/Helpers/VNCPrivacyRecoveryAgent"
plutil -lint "$CONTENTS/Info.plist"

# Ad-hoc signing keeps local/test builds self-contained. Developer ID signing
# and notarization require the repository owner's Apple Developer credentials.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

file "$CONTENTS/MacOS/VNCPrivacyGuard"
lipo -info "$CONTENTS/MacOS/VNCPrivacyGuard"

mkdir -p "$DIST/packages"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$DIST/packages/VNC-Privacy-Guard-macOS-Intel-x86_64.zip"
hdiutil create \
  -volname "VNC Privacy Guard" \
  -srcfolder "$APP" \
  -ov \
  -format UDZO \
  "$DIST/packages/VNC-Privacy-Guard-macOS-Intel-x86_64.dmg"

printf '\nBuilt artifacts:\n'
ls -lh "$DIST/packages"
