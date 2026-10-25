# Changelog

## 3.1.0
**Boards: Arduino, ESP32 and friends.**

- **Board projects are detected automatically:** Arduino sketches (`.ino`, `sketch.yaml`), PlatformIO (`platformio.ini`), ESP-IDF and MicroPython.
- **Board picker and port picker** in the status bar and the new *Device* sidebar page. The choice is saved in `sketch.yaml` or `platformio.ini`. 23 boards built in (Uno, Nano, Mega, Leonardo, Micro, Uno R4, ESP32 variants, XIAO, ESP8266, Pico, Pico W, Pico 2); custom FQBNs work too.
- **Build and Upload** (`Ctrl+Shift+B`, `Ctrl+Alt+U`) through arduino-cli, PlatformIO, `idf.py` or mpremote, with clickable compiler errors. F5 on a sketch uploads and opens the monitor. Missing Arduino cores are installed automatically.
- **Serial monitor** (`Ctrl+Alt+M`): no extra dependencies, any baud rate, ANSI colours, timestamps, autoscroll, send with line-ending choice and history, reset button, auto-reconnect for USB boards that re-enumerate, and it lets go of the port during uploads. Baud is guessed from your project.
- **Libraries and board support:** install or search Arduino libraries and cores from the Device page.
- **New project templates:** Arduino, ESP32 (Arduino and PlatformIO), Uno (PlatformIO), Pico (PlatformIO), ESP-IDF and MicroPython.
- Arduino and ESP32 code snippets (`inosetup`, `inowifi`, `inoserver`, `esplog`, …).
- `aether --doctor` checks the board tools and serial-port permissions.
- ANSI colour codes are stripped from build output.
- Not included yet: language-server support for `.ino` and on-chip debugging.

## 3.0.0
**Aether becomes an IDE.**

- **Projects & builds:** auto-detects Cargo, CMake, Meson, Makefile, Go, Zig, npm and Python projects. Adds Build (`Ctrl+Shift+B`), a task list (`Ctrl+Alt+B`), and a Build panel with clickable gcc/clang/rustc/go/zig/python errors that jumps to the first error. Per-project overrides go in `.aether/project.json`.
- **Debugger (gdb):** breakpoints in the gutter (`F9`, saved between sessions), start/continue `F6`, step over/into/out, pause, restart and stop. Shows variables with expandable structs and arrays, watch expressions, a clickable call stack, a breakpoint list, a *Program* terminal for your program's I/O and a *Debug console* for raw gdb commands.
- **New project** templates (C/Makefile, C/Meson, C++/CMake, Python, Rust, Go, web, Bash) and **Clone repository**.
- **New welcome screen** with quick actions, recent projects as cards (build system + git branch) and recent files.
- **Code folding** for braces, indentation, Markdown headings and comments, with new line numbers that skip folded lines.
- **Multiple cursors:** `Ctrl+D`, `Ctrl+Shift+L`, `Ctrl+Alt+↑/↓`, `Alt+Click`.
- **Outline** sidebar (LSP document symbols with a regex fallback; follows the cursor; filter).
- **Works on all distros:** `install.sh --deps` supports pacman, apt, dnf, zypper, xbps, apk, emerge, eopkg, urpmi, swupd, rpm-ostree and NixOS (`shell.nix`). New `--check`, `--print-deps`, `--minimal` and `--uninstall` options, plus `aether --doctor`.
- **Packages:** .deb, .rpm spec, PKGBUILD, Void template, Alpine APKBUILD and a Gentoo ebuild.
- The launcher finds a Python that has the GTK bindings (fixes pyenv/conda setups).
- Fix: linting no longer removed git change marks from the gutter.
- Unit tests (`make test`) and GitHub Actions CI.
- **One-line install:** `curl -fsSL …/get.sh | bash`. Also `aether --update` and `aether --uninstall`.
- The installer has a banner, numbered steps and spinners, asks once, installs dependencies by default, asks for your password before the spinner starts, and falls back to `~/.local` without sudo.
- `publish.sh`: one command to create the GitHub repo, push, add topics and cut a release.
- **New look:** the Aether Crimson default theme (black and red), plus Obsidian, Synthwave, Cyberpunk and Abyss. A new black-and-red icon, a glowing title and Run button, toasts, a live activity chip and welcome-screen tips.
- Fix: breakpoints now work in moved or symlinked project folders.
- **VS Code-style workbench:** activity bar with a git change badge, file-type icons in the tree and tabs, bracket pair colourisation, minimap on by default, red status bar while debugging, and icon buttons for the sidebar and panel.
- **Code::Blocks-style toolbar:** Debug/Release configuration selector, Build, Stop, Debug and Run.
- All icons are drawn in code, so they look sharp and follow the theme without needing an icon theme.
- Fix: the terminal (and every text box outside the editor) couldn't be clicked into. The editor re-grabbed focus forever (a bug from v2).
- The bottom panel is taller by default.

## 2.1
Layouts and presets, 39 themes, text commands (move/delete/join/sort lines, case changes).

## 2.0
Islands UI, Files/Search/Git sidebar, Preferences, Theme Studio, LSP, formatters, split view, zen mode, multiple terminals.

## 1.0
First release.
