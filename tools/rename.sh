#!/usr/bin/env bash
# Rebrand the editor:  tools/rename.sh "Zenith"
# Changes the display name, command, app id, theme names, icon and desktop file names. Run it once, before you release.
set -euo pipefail
cd "$(dirname "$0")/.."
NEW="${1:?usage: tools/rename.sh NewName}"
new="$(echo "$NEW" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9')"
[ -n "$new" ] || { echo "name needs letters/digits"; exit 1; }
FILES=$(grep -rIl --exclude-dir=dist --exclude-dir=__pycache__ --exclude-dir=.git -e Aether -e aether . || true)
for f in $FILES; do
  sed -i -e "s/Aether/$NEW/g" -e "s/aether/$new/g" "$f"
done
# rename files and directories (deepest first)
find . -depth \( -name '*aether*' -o -name '*Aether*' \) -not -path './dist/*' -not -path './.git/*' | while read -r p; do
  d="$(dirname "$p")"; b="$(basename "$p")"
  mv "$p" "$d/$(echo "$b" | sed -e "s/Aether/$NEW/g" -e "s/aether/$new/g")"
done
rm -rf dist; find . -name __pycache__ -prune -exec rm -rf {} +
echo "Renamed to $NEW (command: $new). Check LICENSE, packaging/ and the icon, then 'make deb'."
