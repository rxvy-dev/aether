"""Build/run commands per language + install hints for missing tools."""
import os, shlex, shutil

CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aether", "build")

# tool -> package per distro family
HINTS = {
    "cc": ("base-devel", "build-essential", "gcc"), "c++": ("base-devel", "build-essential", "gcc-c++"),
    "python3": ("python", "python3", "python3"), "node": ("nodejs", "nodejs", "nodejs"),
    "rustc": ("rust", "rustc cargo", "rust cargo"), "go": ("go", "golang-go", "golang"),
    "java": ("jdk-openjdk", "default-jdk", "java-latest-openjdk-devel"), "lua": ("lua", "lua5.4", "lua"),
    "ruby": ("ruby", "ruby", "ruby"), "php": ("php", "php-cli", "php-cli"), "perl": ("perl", "perl", "perl"),
    "make": ("make", "make", "make"), "bash": ("bash", "bash", "bash"), "runghc": ("ghc", "ghc", "ghc"),
    "Rscript": ("r", "r-base", "R"), "julia": ("julia", "julia", "julia"), "elixir": ("elixir", "elixir", "elixir"),
    "zig": ("zig", "zig", "zig"), "dart": ("dart", "dart", "dart"), "swift": ("swift", "swiftlang", "swift-lang"),
}


def distro_family():
    try:
        d = {}
        with open("/etc/os-release") as f:
            for l in f:
                if "=" in l:
                    k, v = l.rstrip().split("=", 1)
                    d[k] = v.strip('"')
        ids = (d.get("ID", "") + " " + d.get("ID_LIKE", "")).lower()
    except OSError:
        ids = ""
    if any(x in ids for x in ("arch", "manjaro", "endeavour", "cachy")):
        return 0
    if any(x in ids for x in ("debian", "ubuntu", "mint", "pop")):
        return 1
    if any(x in ids for x in ("fedora", "rhel", "centos")):
        return 2
    return None


def install_hint(tool):
    h = HINTS.get(tool)
    fam = distro_family()
    if not h:
        return f"'{tool}' not found in PATH"
    if fam is None:
        return f"'{tool}' not found. Install it with your package manager."
    cmd = ("sudo pacman -S ", "sudo apt install ", "sudo dnf install ")[fam]
    return f"'{tool}' not found. Install it:  {cmd}{h[fam]}"


def _up(path, name):
    d = os.path.dirname(path)
    for _ in range(8):
        if os.path.exists(os.path.join(d, name)):
            return d
        n = os.path.dirname(d)
        if n == d:
            break
        d = n
    return None


def build_command(key, path):
    """Return (shell_command, required_tool) or (None, tool_or_msg)."""
    q = shlex.quote(path)
    os.makedirs(CACHE, exist_ok=True)
    out = shlex.quote(os.path.join(CACHE, os.path.splitext(os.path.basename(path))[0] or "a.out"))
    d = shlex.quote(os.path.dirname(path))
    cc = "cc" if shutil.which("cc") else ("gcc" if shutil.which("gcc") else "clang")
    cxx = "c++" if shutil.which("c++") else ("g++" if shutil.which("g++") else "clang++")
    if key == "c":
        return f"{cc} -g -Wall -Wextra -I{d} -o {out} {q} -lm && {out}", "cc"
    if key == "cpp":
        return f"{cxx} -std=c++20 -g -Wall -Wextra -I{d} -o {out} {q} && {out}", "c++"
    if key == "python":
        return f"python3 {q}", "python3"
    if key == "javascript":
        return f"node {q}", "node"
    if key == "typescript":
        return f"npx --yes tsx {q}", "node"
    if key == "rust":
        root = _up(path, "Cargo.toml")
        if root:
            return f"cd {shlex.quote(root)} && cargo run", "rustc"
        return f"rustc -o {out} {q} && {out}", "rustc"
    if key == "go":
        return f"go run {q}", "go"
    if key == "java":
        return f"java {q}", "java"
    if key == "shellscript":
        return f"bash {q}", "bash"
    if key == "lua":
        return f"lua {q}", "lua"
    if key == "ruby":
        return f"ruby {q}", "ruby"
    if key == "php":
        return f"php {q}", "php"
    if key == "perl":
        return f"perl {q}", "perl"
    if key == "haskell":
        return f"runghc {q}", "runghc"
    if key == "r":
        return f"Rscript {q}", "Rscript"
    if key == "julia":
        return f"julia {q}", "julia"
    if key == "elixir":
        return f"elixir {q}", "elixir"
    if key == "zig":
        return f"zig run {q}", "zig"
    if key == "dart":
        return f"dart run {q}", "dart"
    if key == "swift":
        return f"swift {q}", "swift"
    if key == "makefile":
        return f"make -C {d}", "make"
    if key == "html":
        return f"xdg-open {q}", "xdg-open"
    return None, None


def missing_tool(tool):
    return tool and shutil.which(tool) is None and not (tool == "cc" and (shutil.which("gcc") or shutil.which("clang"))) \
        and not (tool == "c++" and (shutil.which("g++") or shutil.which("clang++")))


def expand(template, path):
    """Custom run command: {file} {dir} {name} {base} are replaced (shell-quoted)."""
    d = os.path.dirname(path)
    name = os.path.basename(path)
    base = os.path.splitext(name)[0]
    out = os.path.join(CACHE, base)
    os.makedirs(CACHE, exist_ok=True)
    return (template.replace("{file}", shlex.quote(path)).replace("{dir}", shlex.quote(d))
            .replace("{name}", shlex.quote(name)).replace("{base}", shlex.quote(base)).replace("{out}", shlex.quote(out)))


def template_for(key):
    """Default command for a language as an editable template, e.g. 'cc -g -o {out} {file} && {out}'."""
    fake = "/__d__/__n__.x"
    cmd, _ = build_command(key, fake)
    if not cmd:
        return ""
    cmd = cmd.replace(shlex.quote(os.path.join(CACHE, "__n__")), "{out}").replace(os.path.join(CACHE, "__n__"), "{out}")
    cmd = cmd.replace("/__d__/__n__.x", "{file}").replace("-I/__d__", "-I{dir}").replace("/__d__", "{dir}")
    return cmd
