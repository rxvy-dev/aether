import os, re
from gi.repository import Gio, GLib


def run(argv, cwd, cb, stdin=None):
    """Run a command async; cb(exit_status, output). Never blocks the UI."""
    flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
    if stdin is not None:
        flags |= Gio.SubprocessFlags.STDIN_PIPE
    try:
        l = Gio.SubprocessLauncher.new(flags)
        l.set_cwd(cwd)
        l.setenv("LC_ALL", "C.UTF-8", True)
        l.setenv("GIT_TERMINAL_PROMPT", "0", True)
        p = l.spawnv(argv)
    except GLib.Error:
        cb(-1, "")
        return

    def done(proc, res):
        try:
            _ok, out, _e = proc.communicate_utf8_finish(res)
        except GLib.Error:
            cb(-1, "")
            return
        cb(proc.get_exit_status(), out or "")
    p.communicate_utf8_async(stdin, None, done)


def repo_root(path):
    d = path if os.path.isdir(path) else os.path.dirname(path)
    for _ in range(12):
        if os.path.exists(os.path.join(d, ".git")):
            return d
        n = os.path.dirname(d)
        if n == d:
            break
        d = n
    return None


def parse_status(out):
    """`git status --porcelain=v1 -z` -> [(X, Y, path)]"""
    items, parts, i = [], out.split("\0"), 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        x, y, path = e[0], e[1], e[3:]
        if x in "RC":
            i += 1
        items.append((x, y, path))
    return items


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def parse_hunks(diff):
    """-> list of (kind, first_line, last_line) kind in add/mod/del (1-based new-file lines)."""
    res = []
    for m in HUNK.finditer(diff):
        old_n = int(m.group(2)) if m.group(2) is not None else 1
        new_start = int(m.group(3))
        new_n = int(m.group(4)) if m.group(4) is not None else 1
        if new_n == 0:
            res.append(("del", max(1, new_start), max(1, new_start)))
        elif old_n == 0:
            res.append(("add", new_start, new_start + new_n - 1))
        else:
            res.append(("mod", new_start, new_start + new_n - 1))
    return res


def branch(folder):
    root = repo_root(folder)
    if not root:
        return None
    try:
        t = open(os.path.join(root, ".git", "HEAD")).read().strip()
    except OSError:
        return None
    return t.split("/", 2)[-1] if t.startswith("ref:") else t[:7]
