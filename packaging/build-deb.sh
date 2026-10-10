#!/bin/sh
# Build dist/aether_<ver>_all.deb (Debian 12+, Ubuntu 23.04+, Mint 22+, Pop!_OS 24+…). Needs dpkg-deb.
set -e
cd "$(dirname "$0")/.."
VER=$(sed -n 's/^VERSION := //p' Makefile)
ROOT=$(mktemp -d)
make -s install PREFIX=/usr DESTDIR="$ROOT"
mkdir -p "$ROOT/DEBIAN" dist
cat > "$ROOT/DEBIAN/control" <<CTL
Package: aether
Version: $VER
Section: devel
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0 (>= 4.8), gir1.2-gtksource-5
Recommends: gir1.2-vte-3.91, gdb, build-essential, git
Suggests: clangd, shellcheck, clang-format
Maintainer: rxvy <https://github.com/rxvy-dev>
Homepage: https://github.com/rxvy-dev/aether
Description: Fast IDE for Linux
 Projects and builds (Make, CMake, Meson, Cargo, Go, Zig, npm), a gdb debugger
 with breakpoints, variables and call stack, language servers, git, code
 folding, multiple cursors, an outline, 39 themes and a built-in terminal.
CTL
find "$ROOT/usr" -type d -exec chmod 755 {} +
dpkg-deb --root-owner-group --build "$ROOT" "dist/aether_${VER}_all.deb" >/dev/null
rm -rf "$ROOT"
echo "dist/aether_${VER}_all.deb"
