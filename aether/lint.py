"""Lightweight diagnostics: pipe the buffer to whatever checker the system has (stdin only, never touches disk)."""
import os, re, shutil
import gi
from gi.repository import Gio, GLib

LINE_RE = re.compile(r"^(?:<stdin>|-|<anon>|<standard input>|stdin|\[stdin\]):(\d+):(?:(\d+):)?\s*(?:(error|warning|fatal error|info|style)\s*:)?\s*(.*)$")

PYCHECK = r'''
import sys, ast, shutil, subprocess
src = sys.stdin.read()
try:
    ast.parse(src)
except SyntaxError as e:
    print("<stdin>:%d:%d: error: %s" % (e.lineno or 1, e.offset or 1, e.msg)); sys.exit(0)
if shutil.which("pyflakes"):
    r = subprocess.run(["pyflakes"], input=src, capture_output=True, text=True)
    for l in (r.stdout + r.stderr).splitlines():
        print(l.replace("<stdin>:", "<stdin>:", 1).replace(": ", ": warning: ", 1) if "warning:" not in l else l)
'''
JSONCHECK = r'''
import sys, json
try:
    json.loads(sys.stdin.read())
except json.JSONDecodeError as e:
    print("<stdin>:%d:%d: error: %s" % (e.lineno, e.colno, e.msg))
'''
JSCHECK = r'''
const vm = require("vm"); let src = require("fs").readFileSync(0, "utf8");
if (/^\s*(import|export)\s/m.test(src)) process.exit(0);
try { new vm.Script(src, {filename: "stdin"}); }
catch (e) { const m = /stdin:(\d+)/.exec(e.stack || ""); console.log("<stdin>:" + (m ? m[1] : 1) + ":1: error: " + e.message); }
'''


def _has_up(path, name):
    d = os.path.dirname(path) if path else os.getcwd()
    for _ in range(8):
        if os.path.exists(os.path.join(d, name)):
            return True
        n = os.path.dirname(d)
        if n == d:
            break
        d = n
    return False


def command_for(key, path):
    """Return (argv, default_severity) or None."""
    d = os.path.dirname(path) if path else os.getcwd()
    if path and path.lower().endswith((".ino", ".pde")):
        return None                       # Arduino.h is injected at build time — a host compiler would flag every pinMode()
    if key in ("c", "cpp"):
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang") if key == "c" else \
             shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if not cc:
            return None
        lang = "c" if key == "c" else "c++"
        return [cc, "-fsyntax-only", "-Wall", "-Wextra", "-fdiagnostics-color=never",
                "-I", d, "-x", lang, "-"], "error"
    if key == "python":
        py = shutil.which("python3")
        return ([py, "-c", PYCHECK], "warning") if py else None
    if key == "json":
        py = shutil.which("python3")
        return ([py, "-c", JSONCHECK], "error") if py else None
    if key == "shellscript":
        sc = shutil.which("shellcheck")
        return ([sc, "-f", "gcc", "-"], "warning") if sc else None
    if key == "javascript":
        n = shutil.which("node")
        return ([n, "-e", JSCHECK], "error") if n else None
    if key == "go":
        g = shutil.which("gofmt")
        return ([g, "-e"], "error") if g else None
    if key == "rust":
        r = shutil.which("rustc")
        if not r or _has_up(path, "Cargo.toml"):
            return None
        return [r, "--edition", "2021", "--crate-type", "lib", "--emit=metadata", "--out-dir",
                GLib.get_tmp_dir(), "--error-format=short", "-Awarnings", "-"], "error"
    return None


def parse(output, default_sev):
    res = []
    for line in output.splitlines():
        line = line.replace("<standard input>", "<stdin>")
        m = LINE_RE.match(line)
        if not m:
            continue
        ln, col, sev, msg = int(m.group(1)), m.group(2), m.group(3) or default_sev, m.group(4).strip()
        if sev in ("info", "style"):
            sev = "warning"
        if sev == "fatal error":
            sev = "error"
        res.append({"line": ln, "col": int(col) if col else None, "sev": sev, "msg": msg})
    return res[:200]


def run(key, path, text, callback):
    cmd = command_for(key, path)
    if not cmd:
        callback(None)
        return None
    argv, sev = cmd
    try:
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE |
                                              Gio.SubprocessFlags.STDERR_MERGE)
        launcher.setenv("LC_ALL", "C.UTF-8", True)
        proc = launcher.spawnv(argv)
    except GLib.Error:
        callback(None)
        return None

    def done(p, res):
        try:
            _ok, out, _err = p.communicate_utf8_finish(res)
        except GLib.Error:
            callback(None)
            return
        callback(parse(out or "", sev))

    proc.communicate_utf8_async(text, None, done)
    return proc
