#!/bin/sh
# Rebuilds the squelchbreak .deb package from the deb-pkg/ packaging
# skeleton plus the application source one directory up (run.py and
# the squelchbreak/ package). Run this script from inside deb-pkg/
# after bumping the version in ../squelchbreak/constants.py and
# updating deb-pkg/squelchbreak/DEBIAN/control and
# deb-pkg/squelchbreak/usr/share/doc/squelchbreak/changelog accordingly.
#
# Expected layout:
#   squelchbreak/            <- project root
#   ├── run.py
#   ├── squelchbreak/         <- Python package
#   └── deb-pkg/              <- this packaging skeleton (run build.sh from here)
#
# Usage:
#   cd deb-pkg
#   ./build.sh
#
# Requires: dpkg-deb (already present on any Debian/Ubuntu system)

set -e

PKG_ROOT="squelchbreak"
SRC_DIR=".."                       # project root: contains run.py and squelchbreak/
LIB_DIR="$PKG_ROOT/usr/lib/squelchbreak"

if [ ! -d "$PKG_ROOT/DEBIAN" ]; then
    echo "Error: run this script from inside the deb-pkg/ directory." >&2
    exit 1
fi

VERSION=$(grep -oP '(?<=^Version: ).*' "$PKG_ROOT/DEBIAN/control")
if [ -z "$VERSION" ]; then
    echo "Error: could not read Version from $PKG_ROOT/DEBIAN/control" >&2
    exit 1
fi

echo "Refreshing application source from $SRC_DIR ..."
rm -rf "$LIB_DIR"
mkdir -p "$LIB_DIR"
cp "$SRC_DIR/run.py" "$LIB_DIR/"
cp -r "$SRC_DIR/squelchbreak" "$LIB_DIR/squelchbreak"

# Clean any bytecode that might have come along for the ride
find "$LIB_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$LIB_DIR" -name "*.pyc" -delete 2>/dev/null || true

# Permissions
find "$PKG_ROOT" -type f -name "*.py" -exec chmod 644 {} \;
find "$PKG_ROOT" -type d -exec chmod 755 {} \;
chmod 755 "$PKG_ROOT/usr/bin/squelchbreak"
chmod 755 "$PKG_ROOT/DEBIAN/postinst" "$PKG_ROOT/DEBIAN/postrm"
chmod 644 "$PKG_ROOT/DEBIAN/control"

OUT="squelchbreak_${VERSION}_all.deb"
echo "Building $OUT ..."
dpkg-deb --build --root-owner-group "$PKG_ROOT" "$OUT"

echo ""
echo "Done: $OUT"
echo "Install with:   sudo dpkg -i $OUT"
echo "Then fix deps:  sudo apt -f install   (if dpkg reports missing dependencies)"
