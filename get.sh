#!/usr/bin/env bash
# One-line install / update for Aether:
#   curl -fsSL https://raw.githubusercontent.com/rxvy-dev/aether/main/get.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/rxvy-dev/aether/main/get.sh | bash -s -- --user     (options go to install.sh)
set -euo pipefail
REPO="${AETHER_REPO:-rxvy-dev/aether}"
BRANCH="${AETHER_BRANCH:-main}"
SRC="${XDG_DATA_HOME:-$HOME/.local/share}/aether-src"
R=$'\e[38;5;197m'; X=$'\e[0m'; [ -t 1 ] || { R=; X=; }

echo "${R}==>${X} Getting Aether from github.com/$REPO"
mkdir -p "$(dirname "$SRC")"
if command -v git >/dev/null; then
  if [ -d "$SRC/.git" ]; then
    git -C "$SRC" fetch -q --depth 1 origin "$BRANCH" && git -C "$SRC" reset -q --hard "origin/$BRANCH"
  else
    rm -rf "$SRC"
    git clone -q --depth 1 -b "$BRANCH" "${AETHER_URL:-https://github.com/$REPO.git}" "$SRC"
  fi
else
  TMP=$(mktemp -d)
  if command -v curl >/dev/null; then curl -fsSL "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz" -o "$TMP/a.tgz"
  else wget -qO "$TMP/a.tgz" "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz"; fi
  rm -rf "$SRC"; mkdir -p "$SRC"
  tar xzf "$TMP/a.tgz" -C "$SRC" --strip-components=1
  rm -rf "$TMP"
fi
cd "$SRC"
exec ./install.sh "$@"
