"""Projects: detect the build system, run build/run/test/clean tasks, create new projects.

Detected (first match wins): Cargo, CMake, Meson, Makefile, Go modules, Zig, npm, Python.
Every command can be overridden per project in  <project>/.aether/project.json :

    { "build": "make -j8", "run": "./bin/app --verbose", "test": "make check",
      "clean": "make clean", "debug_program": "bin/app", "debug_args": "" }
"""
import json, os, re, shlex, shutil, glob

CONFIG = os.path.join(".aether", "project.json")

# file:line[:col]: (fatal )?error|warning|note: message     (gcc, clang, go, zig, tsc-ish)
DIAG_RE = re.compile(r"^(?P<file>[^\s:][^:]*?):(?P<line>\d+)(?::(?P<col>\d+))?:\s*(?:(?P<sev>fatal error|error|warning|note)\b:?\s*)?(?P<msg>.*)$")
# rustc / cargo:   --> src/main.rs:3:5
RUST_LOC = re.compile(r"^\s*-->\s+(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+)")
RUST_HEAD = re.compile(r"^(?P<sev>error|warning)(?:\[\w+\])?:\s*(?P<msg>.*)$")
# python traceback:   File "x.py", line 12, in f
PY_RE = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)')


class Project:
    def __init__(self, root, config="Debug"):
        self.root = os.path.abspath(root)
        self.config = config
        self.kind, self.tasks = detect(self.root, config)
        self.cfg = self._load()
        for k in ("build", "run", "test", "clean", "configure"):
            if self.cfg.get(k):
                self.tasks[k] = self.cfg[k]

    @property
    def name(self):
        return os.path.basename(self.root.rstrip("/"))

    def _load(self):
        try:
            with open(os.path.join(self.root, CONFIG)) as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_cfg(self, **kv):
        self.cfg.update(kv)
        p = os.path.join(self.root, CONFIG)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump(self.cfg, f, indent=2)
        for k in ("build", "run", "test", "clean", "configure"):
            if self.cfg.get(k):
                self.tasks[k] = self.cfg[k]

    def label(self):
        return self.kind or "folder"

    # ---------- debugging ----------
    def debug_candidates(self):
        """Executables that look like this project's program (newest first)."""
        if self.cfg.get("debug_program"):
            return [os.path.join(self.root, self.cfg["debug_program"])]
        pats = {"Cargo": ["target/debug/*", "target/release/*"], "CMake": ["build/*", "build/*/*", "build-release/*", "cmake-build-*/*"],
                "Meson": ["build/*", "build-release/*", "builddir/*"], "Zig": ["zig-out/bin/*"]}.get(self.kind, []) + \
            ["*", "bin/*", "build/*", "out/*"]
        out = []
        for p in pats:
            for f in glob.glob(os.path.join(self.root, p)):
                if os.path.isfile(f) and os.access(f, os.X_OK) and not f.endswith((".sh", ".py", ".so", ".a", ".o")) \
                        and _is_elf(f) and f not in out:
                    out.append(f)
        out.sort(key=lambda f: -os.path.getmtime(f))
        return out


def _is_elf(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def _has_target(makefile, target):
    try:
        with open(makefile, errors="replace") as f:
            return re.search(rf"^{re.escape(target)}\s*:", f.read(), re.M) is not None
    except OSError:
        return False


def _npm_scripts(root):
    try:
        with open(os.path.join(root, "package.json")) as f:
            return json.load(f).get("scripts", {}) or {}
    except (OSError, ValueError):
        return {}


def detect(root, config="Debug"):
    """-> (kind, {task: shell command}).  config: "Debug" or "Release"."""
    rel = config == "Release"
    j = lambda *p: os.path.join(root, *p)
    ex = lambda *p: os.path.exists(j(*p))
    nproc = os.cpu_count() or 4
    if ex("Cargo.toml"):
        r = " --release" if rel else ""
        return "Cargo", {"build": "cargo build" + r, "run": "cargo run" + r, "test": "cargo test" + r, "clean": "cargo clean"}
    if ex("CMakeLists.txt"):
        b = "build-release" if rel else "build"
        cfg = f"cmake -S . -B {b} -DCMAKE_BUILD_TYPE={'Release' if rel else 'Debug'} -DCMAKE_EXPORT_COMPILE_COMMANDS=ON"
        return "CMake", {"configure": cfg,
                         "build": f"[ -f {b}/CMakeCache.txt ] || {cfg}; cmake --build {b} -j{nproc}",
                         "test": f"ctest --test-dir {b} --output-on-failure", "clean": f"cmake --build {b} --target clean"}
    if ex("meson.build"):
        b, bt = ("build-release", "release") if rel else ("build", "debug")
        return "Meson", {"configure": f"meson setup {b} --buildtype={bt}",
                         "build": f"[ -d {b} ] || meson setup {b} --buildtype={bt}; meson compile -C {b}",
                         "test": f"meson test -C {b}", "clean": f"meson compile -C {b} --clean"}
    for mk in ("Makefile", "makefile", "GNUmakefile"):
        if ex(mk):
            t = {"build": f"make -j{nproc}", "clean": "make clean"}
            if _has_target(j(mk), "run"):
                t["run"] = "make run"
            if _has_target(j(mk), "test"):
                t["test"] = "make test"
            elif _has_target(j(mk), "check"):
                t["test"] = "make check"
            return "Makefile", t
    if ex("go.mod"):
        return "Go", {"build": "go build ./...", "run": "go run .", "test": "go test ./...", "clean": "go clean"}
    if ex("build.zig"):
        o = " -Doptimize=ReleaseFast" if rel else ""
        return "Zig", {"build": "zig build" + o, "run": "zig build run" + o, "test": "zig build test"}
    if ex("package.json"):
        sc = _npm_scripts(root)
        t = {}
        if "build" in sc:
            t["build"] = "npm run build"
        if "dev" in sc:
            t["run"] = "npm run dev"
        elif "start" in sc:
            t["run"] = "npm start"
        if "test" in sc:
            t["test"] = "npm test"
        return "npm", t
    if ex("pyproject.toml") or ex("setup.py") or ex("requirements.txt") or ex("main.py"):
        t = {}
        for m in ("main.py", "app.py", "__main__.py"):
            if ex(m):
                t["run"] = f"python3 {m}"
                break
        if ex("tests") or glob.glob(j("test_*.py")):
            t["test"] = "python3 -m pytest -q"
        return "Python", t
    return None, {}


def parse_line(line, cwd):
    """A build-output line -> (abs_path, line, col, severity, message) or None."""
    m = PY_RE.match(line)
    if m:
        p = m.group("file")
        return (os.path.join(cwd, p) if not os.path.isabs(p) else p, int(m.group("line")), 1, "error", line.strip())
    m = RUST_LOC.match(line)
    if m:
        p = m.group("file")
        return (os.path.join(cwd, p) if not os.path.isabs(p) else p, int(m.group("line")), int(m.group("col")), "error", "")
    m = DIAG_RE.match(line)
    if m and m.group("sev"):
        p = m.group("file")
        full = p if os.path.isabs(p) else os.path.join(cwd, p)
        if not os.path.isfile(full):
            return None
        sev = "warning" if m.group("sev") == "warning" else "note" if m.group("sev") == "note" else "error"
        return (full, int(m.group("line")), int(m.group("col") or 1), sev, m.group("msg"))
    return None


# ------------------------------------------------------------------ new project templates
C_MAKEFILE = """CC      ?= cc
CFLAGS  ?= -std=c17 -Wall -Wextra -g -O0
LDLIBS  ?= -lm
SRC     := $(wildcard src/*.c)
OBJ     := $(SRC:src/%.c=build/%.o)
BIN     := build/{name}

all: $(BIN)

$(BIN): $(OBJ)
\t$(CC) $(CFLAGS) -o $@ $^ $(LDLIBS)

build/%.o: src/%.c | build
\t$(CC) $(CFLAGS) -Iinclude -c -o $@ $<

build:
\tmkdir -p build

run: all
\t./$(BIN)

clean:
\trm -rf build

.PHONY: all run clean
"""
C_MAIN = """#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    printf("Hello from {name}!\\n");
    return EXIT_SUCCESS;
}
"""
MESON = """project('{name}', 'c', version: '0.1.0', default_options: ['c_std=c17', 'warning_level=3'])
executable('{name}', 'src/main.c', install: true)
"""
CMAKE = """cmake_minimum_required(VERSION 3.16)
project({name} LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
add_executable({name} src/main.cpp)
target_compile_options({name} PRIVATE -Wall -Wextra)
"""
CPP_MAIN = """#include <iostream>
#include <string>
#include <vector>

int main() {
    std::vector<std::string> words{"Hello", "from", "{name}!"};
    for (const auto& w : words) std::cout << w << ' ';
    std::cout << '\\n';
    return 0;
}
"""
PY_MAIN = '''"""{name}"""


def main() -> None:
    print("Hello from {name}!")


if __name__ == "__main__":
    main()
'''
RUST_TOML = """[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

[dependencies]
"""
RUST_MAIN = """fn main() {
    println!("Hello from {name}!");
}
"""
GO_MOD = "module {name}\n\ngo 1.22\n"
GO_MAIN = """package main

import "fmt"

func main() {
\tfmt.Println("Hello from {name}!")
}
"""
WEB_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main>
    <h1>{name}</h1>
    <p>Edit <code>index.html</code>, <code>style.css</code> and <code>script.js</code>.</p>
  </main>
  <script src="script.js"></script>
</body>
</html>
"""
WEB_CSS = """:root { color-scheme: dark; --bg: #0d0d10; --fg: #e8e8ea; --accent: #e53935; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg); color: var(--fg);
       font: 16px/1.5 system-ui, sans-serif; }
h1 { color: var(--accent); }
"""
WEB_JS = 'console.log("{name} loaded");\n'
SH_MAIN = """#!/usr/bin/env bash
set -euo pipefail

main() {
    echo "Hello from {name}!"
}

main "$@"
"""
GITIGNORE = {"c": "build/\n*.o\n", "c-meson": "build/\n", "cpp": "build/\n", "python": "__pycache__/\n.venv/\n*.pyc\n",
             "rust": "target/\n", "go": "/{name}\n", "web": "node_modules/\n", "bash": ""}

TEMPLATES = {
    # key: (label, description, {path: content}, file to open)
    "c": ("C — Makefile", "src/main.c + a Makefile with build / run / clean",
          {"Makefile": C_MAKEFILE, "src/main.c": C_MAIN, "include/.keep": ""}, "src/main.c"),
    "c-meson": ("C — Meson", "src/main.c + meson.build", {"meson.build": MESON, "src/main.c": C_MAIN}, "src/main.c"),
    "cpp": ("C++ — CMake", "src/main.cpp + CMakeLists.txt (C++20)", {"CMakeLists.txt": CMAKE, "src/main.cpp": CPP_MAIN}, "src/main.cpp"),
    "python": ("Python", "main.py with a main() function", {"main.py": PY_MAIN, "requirements.txt": ""}, "main.py"),
    "rust": ("Rust — Cargo", "Cargo.toml + src/main.rs", {"Cargo.toml": RUST_TOML, "src/main.rs": RUST_MAIN}, "src/main.rs"),
    "go": ("Go module", "go.mod + main.go", {"go.mod": GO_MOD, "main.go": GO_MAIN}, "main.go"),
    "web": ("Web page", "index.html + style.css + script.js", {"index.html": WEB_HTML, "style.css": WEB_CSS, "script.js": WEB_JS}, "index.html"),
    "bash": ("Bash script", "main.sh with strict mode", {"main.sh": SH_MAIN}, "main.sh"),
}


def safe_name(name):
    n = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-")
    return n or "project"


def create(parent, name, key, git=True):
    """Create a project folder from a template. Returns (folder, file_to_open). Raises OSError."""
    name = safe_name(name)
    root = os.path.join(os.path.expanduser(parent), name)
    if os.path.exists(root) and os.listdir(root):
        raise OSError(f"{root} already exists and is not empty")
    _label, _desc, files, main = TEMPLATES[key]
    ident = name.replace("-", "_") if key in ("rust", "c", "c-meson", "cpp") else name
    for rel, content in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content.replace("{name}", ident))
        if rel.endswith(".sh"):
            os.chmod(p, 0o755)
    gi_text = GITIGNORE.get(key, "").replace("{name}", ident)
    if gi_text:
        with open(os.path.join(root, ".gitignore"), "w") as f:
            f.write(gi_text)
    with open(os.path.join(root, "README.md"), "w") as f:
        f.write(f"# {name}\n")
    if git and shutil.which("git"):
        os.system(f"git -C {shlex.quote(root)} init -q >/dev/null 2>&1")
    return root, os.path.join(root, main)
