#!/usr/bin/env bash
# ┌──────────────────────────────────────────────────────────────────────────┐
# │  Aether installer — any Linux distro                                      │
# │                                                                          │
# │    ./install.sh               install everything (asks once)              │
# │    ./install.sh -y            same, no questions                          │
# │    ./install.sh --user        install to ~/.local (no sudo for Aether)    │
# │    ./install.sh --no-deps     skip the package manager step               │
# │    ./install.sh --minimal     only what's needed to start                 │
# │    ./install.sh --check       show what's installed / missing             │
# │    ./install.sh --print-deps  show the package command, don't run it      │
# │    ./install.sh --uninstall   remove Aether (add --user if needed)        │
# └──────────────────────────────────────────────────────────────────────────┘
set -euo pipefail
cd "$(dirname "$0")"

MODE=auto; DEPS=1; MINIMAL=0; ACTION=install; YES=0
for a in "$@"; do
  case "$a" in
    --user) MODE=user ;;
    --system) MODE=system ;;
    --deps) DEPS=1 ;;                      # kept for old instructions (deps are the default now)
    --no-deps) DEPS=0 ;;
    --minimal) MINIMAL=1 ;;
    -y|--yes) YES=1 ;;
    --check|--doctor) ACTION=check ;;
    --uninstall) ACTION=uninstall ;;
    --print-deps) ACTION=print ;;
    -h|--help) sed -n '3,13p' "$0" | sed 's/^# //'; exit 0 ;;
    *) echo "unknown option: $a (try --help)"; exit 2 ;;
  esac
done

# ---------------------------------------------------------------- pretty output
if [ -t 1 ]; then
  R=$'\e[38;5;197m'; D=$'\e[2m'; B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; X=$'\e[0m'
else
  R=; D=; B=; G=; Y=; X=
fi
STEP=0; STEPS=4
banner() {
  printf '%s' "$R"
  cat <<'ART'
     ___       __  __
    / _ | ___ / /_/ /  ___ ____
   / __ |/ -_) __/ _ \/ -_) __/
  /_/ |_|\__/\__/_//_/\__/_/
ART
  printf '%s   a fast IDE for Linux%s\n\n' "$D" "$X"
}
step() { STEP=$((STEP+1)); printf '\n%s[%d/%d]%s %s%s%s\n' "$R" "$STEP" "$STEPS" "$X" "$B" "$*" "$X"; }
ok()   { printf '  %s✔%s %s\n' "$G" "$X" "$*"; }
info() { printf '  %s•%s %s\n' "$D" "$X" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$X" "$*"; }
die()  { printf '  %s✖ %s%s\n' "$R" "$*" "$X"; exit 1; }
ask() {   # ask "question" -> 0 for yes (default yes); reads the real terminal even under curl | bash
  [ "$YES" = 1 ] && return 0
  local ans=""
  if [ -r /dev/tty ]; then
    printf '  %s?%s %s %s[Y/n]%s ' "$R" "$X" "$1" "$D" "$X"
    read -r ans < /dev/tty || ans=""
  fi
  case "$ans" in n|N|no|NO) return 1 ;; *) return 0 ;; esac
}
spin() {  # spin "label" cmd...  — run quietly with a spinner, show the log if it fails
  local label=$1; shift
  local log; log=$(mktemp)
  ( "$@" ) >"$log" 2>&1 &
  local pid=$! i=0 frames='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  if [ -t 1 ]; then
    while kill -0 "$pid" 2>/dev/null; do
      printf '\r  %s%s%s %s' "$R" "${frames:i++%10:1}" "$X" "$label"; sleep 0.1
    done
    printf '\r\033[K'
  fi
  if wait "$pid"; then ok "$label"; rm -f "$log"; return 0; fi
  warn "$label failed — last lines:"; tail -n 15 "$log" | sed 's/^/      /'; rm -f "$log"; return 1
}

# ---------------------------------------------------------------- privileges
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null; then SUDO=sudo
  elif command -v doas >/dev/null; then SUDO=doas
  fi
fi
if [ "$MODE" = auto ]; then
  if [ "$(id -u)" -eq 0 ] || [ -n "$SUDO" ]; then MODE=system; else MODE=user; fi
fi
[ -n "$SUDO" ] && [ "$(id -u)" -ne 0 ] && SUDO_PROMPT="  password for %u (to install packages): " && export SUDO_PROMPT

# ---------------------------------------------------------------- distro detection
. /etc/os-release 2>/dev/null || true
IDS=" ${ID:-} ${ID_LIKE:-} "
detect_pm() {
  case "$IDS" in *" nixos "*) echo nix; return ;; esac
  if [ -e /run/ostree-booted ] && command -v rpm-ostree >/dev/null; then echo rpm-ostree; return; fi
  for pm in xbps-install pacman apt-get dnf zypper apk emerge eopkg urpmi swupd yum; do
    if command -v "$pm" >/dev/null; then echo "$pm"; return; fi
  done
  echo unknown
}
PM=$(detect_pm)

deps_for() {
  case "$1" in
    pacman)       CORE="python python-gobject python-cairo gtk4 gtksourceview5 make"
                  EXTRA="vte4 gdb base-devel git" ;;
    apt-get)      CORE="python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-gtksource-5 make"
                  EXTRA="gir1.2-vte-3.91 gdb build-essential git" ;;
    dnf|yum)      CORE="python3 python3-gobject python3-cairo gtk4 gtksourceview5 make"
                  EXTRA="vte291-gtk4 gdb gcc gcc-c++ make git" ;;
    rpm-ostree)   CORE="python3-gobject python3-cairo gtk4 gtksourceview5"
                  EXTRA="vte291-gtk4 gdb gcc gcc-c++ make git" ;;
    zypper)       CORE="python3 python3-gobject python3-gobject-cairo python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-GtkSource-5 make"
                  EXTRA="typelib-1_0-Vte-3_91 gdb gcc gcc-c++ make git" ;;
    apk)          CORE="python3 py3-gobject3 py3-cairo gtk4.0 gtksourceview5 make"
                  EXTRA="vte3-gtk4 gdb build-base git" ;;
    xbps-install) CORE="python3 python3-gobject python3-cairo gtk4 gtksourceview5 make"
                  EXTRA="vte3-gtk4 gdb base-devel git" ;;
    emerge)       CORE="dev-python/pygobject dev-python/pycairo gui-libs/gtk gui-libs/gtksourceview:5"
                  EXTRA="x11-libs/vte dev-debug/gdb dev-vcs/git" ;;
    eopkg)        CORE="python3 python-gobject python-cairo libgtk-4 gtksourceview5 make"
                  EXTRA="vte-gtk4 gdb gcc make git" ;;
    urpmi)        CORE="python3-gobject3 python3-cairo gtk4 gtksourceview5 make"
                  EXTRA="gdb gcc make git" ;;
    swupd)        CORE="desktop-dev python3-basic"
                  EXTRA="dev-utils" ;;
    *)            CORE=""; EXTRA="" ;;
  esac
  PKGS="$CORE"
  [ "$MINIMAL" = 1 ] || PKGS="$CORE $EXTRA"
}

install_cmd() {
  deps_for "$PM"
  case "$PM" in
    pacman)       echo "$SUDO pacman -S --needed --noconfirm $PKGS" ;;
    apt-get)      echo "$SUDO apt-get update -qq && $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y $PKGS" ;;
    dnf)          echo "$SUDO dnf install -y $PKGS" ;;
    yum)          echo "$SUDO yum install -y $PKGS" ;;
    rpm-ostree)   echo "$SUDO rpm-ostree install --idempotent $PKGS" ;;
    zypper)       echo "$SUDO zypper --non-interactive install $PKGS" ;;
    apk)          echo "$SUDO apk add $PKGS" ;;
    xbps-install) echo "$SUDO xbps-install -Sy $PKGS" ;;
    emerge)       echo "$SUDO emerge --ask=n --noreplace $PKGS" ;;
    eopkg)        echo "$SUDO eopkg install -y $PKGS" ;;
    urpmi)        echo "$SUDO urpmi --auto $PKGS" ;;
    swupd)        echo "$SUDO swupd bundle-add $PKGS" ;;
    *)            echo "" ;;
  esac
}

pick_python() {
  for py in /usr/bin/python3 "$(command -v python3 2>/dev/null)" /usr/bin/python3.1[0-9] /usr/bin/python3.9; do
    [ -x "$py" ] && "$py" -c 'import gi' 2>/dev/null && { echo "$py"; return; }
  done
  command -v python3 2>/dev/null || echo python3
}
doctor() { PYTHONPATH="$PWD" "$(pick_python)" -c 'import sys; from aether.doctor import main; sys.exit(main())'; }
has_core() {
  "$(pick_python)" - <<'PY' 2>/dev/null
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("GtkSource", "5"); gi.require_foreign("cairo")
from gi.repository import Gtk, GtkSource
assert (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4, 8)
PY
}

# ---------------------------------------------------------------- simple actions
case "$ACTION" in
  print)
    echo "${PRETTY_NAME:-unknown distro} · $PM"
    c=$(install_cmd); echo "  ${c:-(no automatic command for this system — see README)}"; exit 0 ;;
  check) doctor; exit $? ;;
  uninstall)
    for p in "$HOME/.local" /usr/local /usr; do
      if [ -e "$p/bin/aether" ] && [ -d "$p/share/aether" ]; then
        if [ -w "$p/bin" ]; then make -s uninstall PREFIX="$p"; else $SUDO make -s uninstall PREFIX="$p"; fi
        ok "removed from $p"
      fi
    done
    info "settings kept in ~/.config/aether (delete it to reset)"; exit 0 ;;
esac

# ---------------------------------------------------------------- install
banner
step "Checking your system"
ok "${PRETTY_NAME:-Linux} · package manager: $PM · install to: $([ "$MODE" = user ] && echo '~/.local' || echo /usr/local)"
[ "$MODE" = user ] && [ -z "$SUDO" ] && [ "$(id -u)" -ne 0 ] && info "no sudo/doas — Aether goes to ~/.local; system packages must already be installed"

step "Dependencies"
if [ "$DEPS" = 0 ]; then
  info "skipped (--no-deps)"
elif [ "$PM" = nix ]; then
  info "NixOS: run it with the bundled shell —  nix-shell --run ./bin/aether"
  DEPS=0
elif [ "$PM" = unknown ]; then
  warn "unknown package manager — install: Python 3.9+, PyGObject + cairo, GTK 4.8+, GtkSourceView 5.6+ (and VTE-gtk4, gdb, gcc, make, git)"
elif [ "$MODE" = user ] && [ -z "$SUDO" ] && [ "$(id -u)" -ne 0 ]; then
  has_core && ok "GTK 4 and GtkSourceView are already installed" || warn "needs root to install packages — ask your admin, or run:  $(install_cmd)"
else
  CMD=$(install_cmd)
  case "$PM" in
    emerge) info "Gentoo: x11-libs/vte needs USE=\"gtk4 introspection\"; GTK & GtkSourceView need USE=\"introspection\"" ;;
    rpm-ostree) info "immutable system: packages are layered and need a reboot (or use: toolbox create && toolbox enter)" ;;
    urpmi|eopkg|swupd) info "package names for $PM are best-effort" ;;
  esac
  info "$D$CMD$X"
  if ask "Install these packages?"; then
    # get the password now, so it isn't hidden behind the spinner
    if [ "$SUDO" = sudo ]; then sudo -v < /dev/tty || die "sudo failed"; fi
    run_pkgs() { if [ "$SUDO" = doas ]; then bash -c "$1"; else spin "$2" bash -c "$1"; fi; }
    if ! run_pkgs "$CMD" "installing packages"; then
      MINIMAL=1
      run_pkgs "$(install_cmd)" "retrying with only the required packages" || warn "package install failed — continuing; see the check below"
    fi
  else
    info "skipped"
  fi
fi

step "Installing Aether"
command -v make >/dev/null || die "'make' is missing — install it with your package manager and run this again"
if [ "$MODE" = user ]; then
  spin "copying files to ~/.local" make -s install PREFIX="$HOME/.local"
  LINE='export PATH="$HOME/.local/bin:$PATH"'
  for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
    [ -f "$rc" ] && ! grep -qs '\.local/bin' "$rc" && echo "$LINE" >> "$rc"
  done
  if [ -d "$HOME/.config/fish" ] && command -v fish >/dev/null; then fish -c 'fish_add_path -U $HOME/.local/bin' 2>/dev/null || true; fi
  case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) info "open a new terminal so ~/.local/bin is on your PATH" ;; esac
else
  [ "$SUDO" = sudo ] && { sudo -v < /dev/tty || die "sudo failed"; }
  if [ "$SUDO" = doas ]; then doas make -s install PREFIX=/usr/local && ok "copied files to /usr/local"
  else spin "copying files to /usr/local" $SUDO make -s install PREFIX=/usr/local; fi
fi
ok "app launcher entry + icon installed"

step "Final check"
if doctor >/tmp/aether-doctor.$$ 2>&1; then
  grep -E "✔|•" /tmp/aether-doctor.$$ | grep -E "GTK|GtkSource|gdb|VTE|git" | sed 's/^ */  /'
  rm -f /tmp/aether-doctor.$$
  printf '\n  %s%sAether is installed.%s  Start it from your app menu, or run:  %saether%s  (aether . opens this folder)\n\n' "$G" "$B" "$X" "$B" "$X"
else
  cat /tmp/aether-doctor.$$; rm -f /tmp/aether-doctor.$$
  printf '\n  %sSomething required is missing.%s Re-run ./install.sh, or install the ✖ items with your package manager.\n\n' "$R" "$X"
  exit 1
fi
