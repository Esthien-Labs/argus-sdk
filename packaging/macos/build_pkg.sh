#!/bin/bash
# Build a signed macOS .pkg installer for Argus SDK.
#
# Usage:
#   ./packaging/macos/build_pkg.sh <payload_executable> <version> <arch>
#
# Arguments:
#   payload_executable  Path to the PyInstaller-built argus binary
#   version             Package version (e.g., 0.7.3)
#   arch                x86_64 or arm64
#
# Output:
#   argus-sdk-<version>-macos-<arch>.pkg in the current directory

set -euo pipefail

PAYLOAD="${1:?payload executable path required}"
VERSION="${2:?version required}"
ARCH="${3:?arch required (x86_64 or arm64)}"
IDENTIFIER="com.esthien.argus-sdk"
INSTALL_LOCATION="/usr/local/esthien/argus-sdk"

if [ ! -f "$PAYLOAD" ]; then
    echo "ERROR: payload not found: $PAYLOAD" >&2
    exit 1
fi

# Create package root
PKG_ROOT=$(mktemp -d)
trap "rm -rf $PKG_ROOT" EXIT

mkdir -p "$PKG_ROOT$INSTALL_LOCATION/bin"
cp "$PAYLOAD" "$PKG_ROOT$INSTALL_LOCATION/bin/argus"
chmod +x "$PKG_ROOT$INSTALL_LOCATION/bin/argus"

# Create symlink in /usr/local/bin
mkdir -p "$PKG_ROOT/usr/local/bin"
ln -sf "$INSTALL_LOCATION/bin/argus" "$PKG_ROOT/usr/local/bin/argus"

# Build the package
pkgbuild \
    --root "$PKG_ROOT" \
    --identifier "$IDENTIFIER" \
    --version "$VERSION" \
    --install-location "/" \
    "argus-sdk-$VERSION-$ARCH.pkg"

echo "Built: argus-sdk-$VERSION-$ARCH.pkg"
