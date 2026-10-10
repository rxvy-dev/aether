import os, shutil
from gi.repository import Gio, GLib

HINT = {"clang-format": "clang (pacman: clang / apt: clang-format)", "black": "black or ruff (pip install black)",
        "gofmt": "go", "rustfmt": "rust (rustup component add rustfmt)", "prettier": "prettier (npm i -g prettier)",
        "shfmt": "shfmt", "stylua": "stylua", "zig": "zig", "taplo": "taplo"}


def command(key, path, width=4):
    name = os.path.basename(path) if path else "stdin"
    w = shutil.which
    if key in ("c", "cpp"):
        return ["clang-format", f"--assume-filename={name if path else ('a.c' if key == 'c' else 'a.cpp')}"] if w("clang-format") else "clang-format"
    if key == "python":
        if w("ruff"):
            return ["ruff", "format", "--stdin-filename", name, "-"]
        return ["black", "-q", "-"] if w("black") else "black"
    if key == "go":
        return ["gofmt"] if w("gofmt") else "gofmt"
    if key == "rust":
        return ["rustfmt", "--edition", "2021"] if w("rustfmt") else "rustfmt"
    if key in ("javascript", "typescript", "javascriptreact", "typescriptreact", "css", "html", "json", "yaml", "markdown"):
        ext = {"javascript": ".js", "typescript": ".ts", "javascriptreact": ".jsx", "typescriptreact": ".tsx", "css": ".css",
               "html": ".html", "json": ".json", "yaml": ".yaml", "markdown": ".md"}[key]
        return ["prettier", "--stdin-filepath", name if path else "a" + ext] if w("prettier") else "prettier"
    if key == "shellscript":
        return ["shfmt", "-i", str(width)] if w("shfmt") else "shfmt"
    if key == "lua":
        return ["stylua", "-"] if w("stylua") else "stylua"
    if key == "zig":
        return ["zig", "fmt", "--stdin"] if w("zig") else "zig"
    if key == "toml":
        return ["taplo", "fmt", "-"] if w("taplo") else "taplo"
    return None


def run(argv, text, cwd, cb):
    """cb(ok, output_or_error)"""
    try:
        l = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
        if cwd:
            l.set_cwd(cwd)
        p = l.spawnv(argv)
    except GLib.Error as e:
        cb(False, str(e))
        return

    def done(proc, res):
        try:
            _ok, out, err = proc.communicate_utf8_finish(res)
        except GLib.Error as e:
            cb(False, str(e))
            return
        if proc.get_exit_status() == 0 and out:
            cb(True, out)
        else:
            cb(False, (err or "formatter failed").strip().splitlines()[0] if (err or "").strip() else "formatter failed")
    p.communicate_utf8_async(text, None, done)
