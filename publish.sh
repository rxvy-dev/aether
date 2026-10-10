#!/usr/bin/env bash
# Publish this folder to GitHub — repo, push, topics and a release with the .deb + source tarball.
#
#   ./publish.sh                    public repo named "aether" on your account
#   ./publish.sh --name myide       different repo name
#   ./publish.sh --private          private repo
#   ./publish.sh --no-release       just push, no GitHub release
#
# Uses the GitHub CLI (gh). If it isn't installed, the script offers to install it,
# or falls back to plain git (you create the empty repo on github.com yourself).
set -euo pipefail
cd "$(dirname "$0")"

NAME="aether"; VIS="--public"; RELEASE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="$2"; shift ;;
    --private) VIS="--private" ;;
    --no-release) RELEASE=0 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
  shift
done

R=$'\e[38;5;197m'; G=$'\e[32m'; D=$'\e[2m'; B=$'\e[1m'; X=$'\e[0m'
[ -t 1 ] || { R=; G=; D=; B=; X=; }
say()  { printf '%s==>%s %s%s%s\n' "$R" "$X" "$B" "$*" "$X"; }
ok()   { printf '  %s✔%s %s\n' "$G" "$X" "$*"; }
info() { printf '  %s%s%s\n' "$D" "$*" "$X"; }
die()  { printf '  %s✖ %s%s\n' "$R" "$*" "$X"; exit 1; }
ask()  { local a; printf '  %s?%s %s ' "$R" "$X" "$1" >&2; read -r a < /dev/tty || a=""; echo "$a"; }

VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' aether/__init__.py)
CUR_SLUG=$(sed -n 's/^REPO = "\([^"]*\)".*/\1/p' aether/__init__.py)

# ---------------------------------------------------------------- git
command -v git >/dev/null || die "git is not installed (Void: sudo xbps-install -S git · Arch: sudo pacman -S git · Debian/Ubuntu: sudo apt install git)"
if [ -z "$(git config --global user.name || true)" ]; then
  n=$(ask "Your name for git commits:"); git config --global user.name "$n"
fi
if [ -z "$(git config --global user.email || true)" ]; then
  e=$(ask "Your email for git commits (GitHub's no-reply address works):"); git config --global user.email "$e"
fi

# ---------------------------------------------------------------- gh
install_gh() {
  local cmd=""
  if   command -v xbps-install >/dev/null; then cmd="sudo xbps-install -Sy github-cli"
  elif command -v pacman >/dev/null; then cmd="sudo pacman -S --needed --noconfirm github-cli"
  elif command -v apt-get >/dev/null; then cmd="sudo apt-get install -y gh"
  elif command -v dnf >/dev/null; then cmd="sudo dnf install -y gh"
  elif command -v zypper >/dev/null; then cmd="sudo zypper --non-interactive install gh"
  elif command -v apk >/dev/null; then cmd="sudo apk add github-cli"
  elif command -v emerge >/dev/null; then cmd="sudo emerge dev-util/github-cli"
  fi
  [ -z "$cmd" ] && return 1
  info "$cmd"
  a=$(ask "Install the GitHub CLI (gh) now? [Y/n]")
  case "$a" in n|N|no) return 1 ;; esac
  eval "$cmd"
}

USE_GH=1
if ! command -v gh >/dev/null; then
  say "The GitHub CLI (gh) makes this one step"
  install_gh || USE_GH=0
  command -v gh >/dev/null || USE_GH=0
fi
if [ "$USE_GH" = 1 ] && ! gh auth status >/dev/null 2>&1; then
  say "Log in to GitHub (a browser link + code will appear)"
  gh auth login --hostname github.com --git-protocol https --web || USE_GH=0
fi

if [ "$USE_GH" = 1 ]; then
  OWNER=$(gh api user --jq .login)
else
  OWNER=$(ask "Your GitHub username:")
  [ -n "$OWNER" ] || die "need a username"
fi
SLUG="$OWNER/$NAME"

# ---------------------------------------------------------------- point every link at YOUR repo
if [ "$SLUG" != "$CUR_SLUG" ]; then
  say "Pointing links at github.com/$SLUG (was $CUR_SLUG)"
  grep -rIl --exclude-dir=.git --exclude-dir=dist --exclude=publish.sh -e "$CUR_SLUG" . | while read -r f; do
    sed -i "s#$CUR_SLUG#$SLUG#g" "$f"
  done
  ok "updated README, get.sh, packaging and the app's update URL"
fi

# ---------------------------------------------------------------- commit
say "Committing"
[ -d .git ] || git init -q -b main
git symbolic-ref -q HEAD >/dev/null || true
git checkout -q -B main 2>/dev/null || true
git add -A
if git diff --cached --quiet; then
  ok "nothing new to commit"
else
  if git rev-parse -q --verify HEAD >/dev/null; then git commit -qm "Aether $VERSION"; else git commit -qm "Aether $VERSION — initial commit"; fi
  ok "committed"
fi

# ---------------------------------------------------------------- push
say "Pushing to github.com/$SLUG"
if [ "$USE_GH" = 1 ]; then
  if gh repo view "$SLUG" >/dev/null 2>&1; then
    git remote get-url origin >/dev/null 2>&1 && git remote set-url origin "https://github.com/$SLUG.git" || git remote add origin "https://github.com/$SLUG.git"
    gh auth setup-git >/dev/null 2>&1 || true
    git push -u origin main
  else
    gh repo create "$SLUG" $VIS --source . --remote origin --push \
      --description "A fast IDE for Linux: projects & builds, gdb debugger, LSP, git, folding, multiple cursors" \
      --homepage "https://github.com/$SLUG"
  fi
  gh repo edit "$SLUG" --add-topic ide,linux,gtk4,code-editor,debugger,gdb,python,c,cpp,lsp >/dev/null 2>&1 || true
  ok "pushed"
else
  echo
  info "1. Open https://github.com/new"
  info "2. Repository name: $NAME   ·   leave 'Add a README' UNCHECKED   ·   Create repository"
  ask "Press Enter when the empty repo exists…" >/dev/null
  git remote get-url origin >/dev/null 2>&1 && git remote set-url origin "https://github.com/$SLUG.git" || git remote add origin "https://github.com/$SLUG.git"
  info "git will ask for your username and a password — use a Personal Access Token as the password"
  info "(github.com → Settings → Developer settings → Personal access tokens → Generate, with 'repo' scope)"
  git push -u origin main
  ok "pushed"
  RELEASE=0
  info "releases need gh — install it later and run ./publish.sh again to add one"
fi

# ---------------------------------------------------------------- release
if [ "$RELEASE" = 1 ]; then
  say "Release v$VERSION"
  if gh release view "v$VERSION" -R "$SLUG" >/dev/null 2>&1; then
    ok "v$VERSION already released — bump VERSION in aether/__init__.py and Makefile for a new one"
  else
    rm -rf dist
    make -s dist >/dev/null
    ASSETS=(dist/aether-"$VERSION".tar.gz)
    if command -v dpkg-deb >/dev/null; then sh packaging/build-deb.sh >/dev/null && ASSETS+=(dist/aether_"$VERSION"_all.deb); fi
    NOTES=$(awk -v v="## $VERSION" '$0==v{f=1;next} /^## /{f=0} f' CHANGELOG.md)
    NOTES="$NOTES

### Install
\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/$SLUG/main/get.sh | bash
\`\`\`"
    gh release create "v$VERSION" "${ASSETS[@]}" -R "$SLUG" --title "Aether $VERSION" --notes "$NOTES"
    ok "released with: ${ASSETS[*]##*/}"
  fi
fi

echo
printf '  %s%sDone!%s  https://github.com/%s\n\n' "$G" "$B" "$X" "$SLUG"
printf '  Anyone can now install it with:\n    %scurl -fsSL https://raw.githubusercontent.com/%s/main/get.sh | bash%s\n\n' "$B" "$SLUG" "$X"
