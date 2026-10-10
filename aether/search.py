import fnmatch, os, re, threading
from gi.repository import GLib

IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", "dist", "build", ".cache", ".idea", ".mypy_cache"}
MAX_RESULTS = 3000
MAX_SIZE = 1_500_000


def compile_pattern(q, case, regex, word):
    p = q if regex else re.escape(q)
    if word:
        p = r"\b" + p + r"\b"
    return re.compile(p, 0 if case else re.IGNORECASE)


def iter_files(root, include=""):
    globs = [g.strip() for g in include.split(",") if g.strip()]
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in IGNORE and not d.startswith(".")]
        for f in fns:
            if globs and not any(fnmatch.fnmatch(f, g) for g in globs):
                continue
            yield os.path.join(dp, f)


def _read(path):
    try:
        if os.path.getsize(path) > MAX_SIZE:
            return None
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace")


class ProjectSearch:
    """Threaded project search; callbacks always run on the GTK main loop."""

    def __init__(self, root, query, case, regex, word, include, on_batch, on_done):
        self.cancel = threading.Event()
        self.args = (root, query, case, regex, word, include)
        self.on_batch, self.on_done = on_batch, on_done

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        root, q, case, regex, word, include = self.args
        try:
            pat = compile_pattern(q, case, regex, word)
        except re.error as e:
            GLib.idle_add(self.on_done, 0, f"Invalid pattern: {e}")
            return
        total, batch = 0, []
        for path in iter_files(root, include):
            if self.cancel.is_set():
                return
            text = _read(path)
            if text is None:
                continue
            for ln, line in enumerate(text.splitlines(), 1):
                m = pat.search(line)
                if m:
                    batch.append((path, ln, m.start() + 1, line.strip()[:200]))
                    total += 1
                    if len(batch) >= 40:
                        GLib.idle_add(self.on_batch, batch)
                        batch = []
                    if total >= MAX_RESULTS:
                        break
            if total >= MAX_RESULTS:
                break
        if batch:
            GLib.idle_add(self.on_batch, batch)
        GLib.idle_add(self.on_done, total, "limit reached" if total >= MAX_RESULTS else "")


def replace_in_files(root, query, repl, case, regex, word, include, skip_paths, on_done):
    def work():
        try:
            pat = compile_pattern(query, case, regex, word)
        except re.error as e:
            GLib.idle_add(on_done, [], f"Invalid pattern: {e}")
            return
        changed = []
        for path in iter_files(root, include):
            if path in skip_paths:
                continue
            text = _read(path)
            if text is None:
                continue
            new, n = pat.subn(repl if regex else repl.replace("\\", "\\\\"), text)
            if n:
                try:
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        f.write(new)
                    changed.append((path, n))
                except OSError:
                    pass
        GLib.idle_add(on_done, changed, "")
    threading.Thread(target=work, daemon=True).start()
