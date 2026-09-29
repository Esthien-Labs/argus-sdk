#!/bin/bash
# Build a .deb package for Argus SDK on Debian/Ubuntu.
#
# Usage:
#   ./packaging/linux/build_deb.sh <payload_executable> <version> <arch>
#
# Arguments:
#   payload_executable  Path to the PyInstaller-built argus binary
#   version             Package version (e.g., 0.7.3)
#   arch                amd64 or arm64
#
# Output:
#   argus-sdk_<version>_<arch>.deb in the current directory

set -euo pipefail

PAYLOAD="${1:?payload executable path required}"
VERSION="${2:?version required}"
ARCH="${3:?arch required (amd64 or arm64)}"
PACKAGE="argus-sdk"

if [ ! -f "$PAYLOAD" ]; then
    echo "ERROR: payload not found: $PAYLOAD" >&2
    exit 1
fi

# Create package structure
PKG_ROOT=$(mktemp -d)
trap "rm -rf $PKG_ROOT" EXIT

mkdir -p "$PKG_ROOT/usr/local/bin"
mkdir -p "$PKG_ROOT/usr/share/doc/$PACKAGE"
mkdir -p "$PKG_ROOT/DEBIAN"

cp "$PAYLOAD" "$PKG_ROOT/usr/local/bin/argus"
chmod +x "$PKG_ROOT/usr/local/bin/argus"

# Control file
cat > "$PKG_ROOT/DEBIAN/control" << EOF
Package: $PACKAGE
Version: $VERSION
Architecture: $ARCH
Maintainer: Esthien Labs <engineering@esthien.com>
Description: Argus SDK - safety-supervised inference for physical systems
 Argus SDK provides profile-bound controller regression evaluation with
 evidence records and explicit boundaries. It includes the argus CLI and
 Python API for safety-supervised inference workloads.
Section: devel
Priority: optional
EOF

# Post-install script
cat > "$PKG_ROOT/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e
# Ensure /usr/local/bin is in PATH for all users
if ! grep -q "/usr/local/bin" /etc/environment 2>/dev/null; then
    echo 'PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"' > /etc/environment
fi
EOF
chmod 755 "$PKG_ROOT/DEBIAN/postinst"

# Build the package
dpkg-deb --build "$PKG_ROOT" "${PACKAGE}_${VERSION}_${ARCH}.deb"

echo "Built: ${PACKAGE}_${VERSION}_${ARCH}.deb"
