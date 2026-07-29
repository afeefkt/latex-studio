#!/bin/bash
# ── LaTeX Studio macOS DMG creator ──
# Usage: bash installer/macos.sh
# Requires: create-dmg (brew install create-dmg)

set -euo pipefail

VERSION="${1:-0.1.0}"
APP_NAME="LaTeXStudio"
ARCH=$(uname -m)
DMG_NAME="${APP_NAME}-${VERSION}-macos-${ARCH}.dmg"

echo "Creating DMG: ${DMG_NAME}"

# Prepare the .app bundle structure if not already done by PyInstaller
APP_DIR="dist/${APP_NAME}.app"
if [ ! -d "${APP_DIR}" ]; then
    # PyInstaller produces a folder; wrap it as .app
    mkdir -p "${APP_DIR}/Contents/MacOS"
    cp -R "dist/${APP_NAME}/"* "${APP_DIR}/Contents/MacOS/"
    cat > "${APP_DIR}/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>LaTeXStudio</string>
    <key>CFBundleIdentifier</key>
    <string>com.latexstudio.app</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
</dict>
</plist>
EOF
fi

# Ad-hoc sign (avoids "damaged app" Gatekeeper error without paid Developer ID)
echo "Signing bundle (ad-hoc)..."
codesign --force --deep --sign - "${APP_DIR}" 2>/dev/null || true

# Create DMG
echo "Creating disk image..."
test -f "dist/${DMG_NAME}" && rm "dist/${DMG_NAME}"

create-dmg \
    --volname "${APP_NAME}" \
    --volicon "" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "${APP_NAME}.app" 150 190 \
    --hide-extension "${APP_NAME}.app" \
    --app-drop-link 400 190 \
    "dist/${DMG_NAME}" \
    "dist/" 2>/dev/null || \
    hdiutil create -volname "${APP_NAME}" -srcfolder "dist/" -ov -format UDZO "dist/${DMG_NAME}"

echo "Done: dist/${DMG_NAME}"
