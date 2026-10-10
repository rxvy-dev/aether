"""A small gdb/MI client: start a program under gdb, breakpoints, stepping, stack, variables.

All I/O is asynchronous on the GLib main loop, so the UI never blocks.
"""
import os, re, shlex, shutil
import gi
from gi.repository import Gio, GLib


# ------------------------------------------------------------------ MI parser
class _P:
    def __init__(self, s):
        self.s, self.i = s, 0

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def cstring(self):
        assert self.s[self.i] == '"'
        self.i += 1
        out = []
        esc = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "e": "\x1b", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\\" and self.i + 1 < len(self.s):
                n = self.s[self.i + 1]
                if n in "01234567":
                    m = re.match(r"[0-7]{1,3}", self.s[self.i + 1:])
                    out.append(chr(int(m.group(0), 8)))
                    self.i += 1 + len(m.group(0))
                    continue
                out.append(esc.get(n, n))
                self.i += 2
                continue
            if c == '"':
                self.i += 1
                break
            out.append(c)
            self.i += 1
        return "".join(out)

    def value(self):
        c = self.peek()
        if c == '"':
            return self.cstring()
        if c == "{":
            self.i += 1
            d = {}
            while self.peek() and self.peek() != "}":
                k, v = self.result()
                d[k] = v
                if self.peek() == ",":
                    self.i += 1
            self.i += 1
            return d
        if c == "[":
            self.i += 1
            lst = []
            while self.peek() and self.peek() != "]":
                if self.peek() in '"{[':
                    lst.append(self.value())
                else:
                    k, v = self.result()
                    lst.append({k: v} if k not in ("frame", "bkpt", "thread") else v)
                if self.peek() == ",":
                    self.i += 1
            self.i += 1
            return lst
        return ""

    def result(self):
        m = re.match(r"[\w\-]+", self.s[self.i:])
        k = m.group(0) if m else ""
        self.i += len(k)
        if self.peek() == "=":
            self.i += 1
        return k, self.value()


def parse_record(line):
    """-> (kind, token, cls, payload)   kind in ^ * = ~ @ & or None for program output."""
    m = re.match(r"^(\d*)([\^*=+~@&])", line)
    if not m:
        return None, None, None, line
    token = int(m.group(1)) if m.group(1) else None
    kind = m.group(2)
    rest = line[m.end():]
    if kind in "~@&":
        return kind, token, None, _P(rest).cstring() if rest.startswith('"') else rest
    m2 = re.match(r"[\w\-]+", rest)
    cls = m2.group(0) if m2 else ""
    rest = rest[len(cls):]
    payload = {}
    p = _P(rest)
    while p.peek() == ",":
        p.i += 1
        k, v = p.result()
        payload[k] = v
    return kind, token, cls, payload


# ------------------------------------------------------------------ value pretty-tree
def value_children(text):
    """Split a gdb value like '{x = 1, p = {a = 2}, 0x0}' into [(name, value)] or None if scalar."""
    t = text.strip()
    if not (t.startswith("{") and t.endswith("}")):
        return None
    inner = t[1:-1]
    parts, depth, cur, q = [], 0, [], None
    i = 0
    while i < len(inner):
        c = inner[i]
        if q:
            cur.append(c)
            if c == "\\" and i + 1 < len(inner):
                cur.append(inner[i + 1])
                i += 1
            elif c == q:
                q = None
        elif c in "\"'":
            q = c
            cur.append(c)
        elif c in "{[(<":
            depth += 1
            cur.append(c)
        elif c in "}])>":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    out = []
    for n, p in enumerate(parts):
        m = re.match(r"^([A-Za-z_]\w*|\[\d+\])\s=\s(.*)$", p, re.S)
        if m:
            out.append((m.group(1), m.group(2)))
        else:
            out.append((f"[{n}]", p))
    return out


# ------------------------------------------------------------------ session
class GdbSession:
    """Callbacks (all optional): on_state(state, info), on_console(text, kind),
    on_stopped(payload), on_bkpts(), on_exit(code)."""

    def __init__(self, program, args="", cwd=None, tty=None, **cbs):
        self.program = program
        self.args = args
        self.cwd = cwd or os.path.dirname(program)
        self.tty = tty
        self.cb = cbs
        self.state = "starting"
        self._tok = 0
        self._pending = {}
        self.bkpts = {}          # (file, line1) -> gdb number
        self.frame = None
        self.frames = []
        self.vars = []
        self.watches = []        # [(expr, value)]
        self._dead = False
        argv = ["gdb", "--interpreter=mi3", "-q", "-nx",
                "-iex", "set pagination off", "-iex", "set confirm off", "-iex", "set print pretty off",
                "-iex", "set width 0", "--args", program] + (shlex.split(args) if args else [])
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE |
                                              Gio.SubprocessFlags.STDERR_MERGE)
        launcher.set_cwd(self.cwd)
        launcher.setenv("TERM", "xterm-256color", True)
        self.proc = launcher.spawnv(argv)
        self.stdin = self.proc.get_stdin_pipe()
        self.out = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self._read()
        self.proc.wait_async(None, self._gdb_exited)
        if tty:
            self.mi(f"-inferior-tty-set {tty}")
        self.mi(f"-environment-cd {self._q(self.cwd)}")

    @staticmethod
    def available():
        return shutil.which("gdb") is not None

    @staticmethod
    def _q(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _emit(self, name, *a):
        fn = self.cb.get(name)
        if fn:
            fn(*a)

    # ---------- transport ----------
    def mi(self, cmd, cb=None):
        if self._dead:
            return
        self._tok += 1
        if cb:
            self._pending[self._tok] = cb
        data = f"{self._tok}{cmd}\n".encode()
        try:
            self.stdin.write_all(data, None)
            self.stdin.flush(None)
        except GLib.Error:
            pass

    def _read(self):
        self.out.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)

    def _on_line(self, stream, res):
        try:
            line, _n = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:
            return
        line = line.rstrip("\r")
        if line and line != "(gdb) ":
            try:
                self._handle(line)
            except Exception as e:                 # never let a weird record kill the reader
                self._emit("on_console", f"[aether] could not parse: {line} ({e})\n", "error")
        self._read()

    def _handle(self, line):
        kind, token, cls, payload = parse_record(line)
        if kind is None:
            if payload.strip() != "(gdb)":
                self._emit("on_console", payload + "\n", "program")
            return
        if kind == "~":
            self._emit("on_console", payload, "console")
        elif kind == "@":
            self._emit("on_console", payload, "program")
        elif kind == "&":
            self._emit("on_console", payload, "log")
        elif kind == "^":
            cb = self._pending.pop(token, None) if token is not None else None
            if cls == "error":
                msg = payload.get("msg", "error")
                if cb is None:
                    self._emit("on_console", msg + "\n", "error")
            if cls == "running":
                self._set_state("running")
            if cb:
                cb(cls, payload)
        elif kind == "*":
            if cls == "running":
                self._set_state("running")
            elif cls == "stopped":
                self._stopped(payload)
        elif kind == "=":
            if cls == "thread-group-exited":
                pass
            elif cls in ("breakpoint-modified",):
                self._emit("on_bkpts")

    def _set_state(self, st, info=""):
        self.state = st
        self._emit("on_state", st, info)

    def _stopped(self, p):
        reason = p.get("reason", "")
        if reason.startswith("exited"):
            code = p.get("exit-code", "0")
            try:
                code = int(code, 8) if code.startswith("0") and len(code) > 1 else int(code)
            except ValueError:
                code = 0
            self._set_state("exited", f"exited with code {code}")
            self._emit("on_exit", code)
            return
        if reason == "signal-received":
            info = f"{p.get('signal-name', 'signal')} — {p.get('signal-meaning', '')}"
        elif reason == "breakpoint-hit":
            info = "breakpoint"
        elif reason == "end-stepping-range":
            info = "step"
        elif reason == "function-finished":
            info = "returned" + (f" {p.get('return-value')}" if p.get("return-value") else "")
        else:
            info = reason or "paused"
        self.frame = p.get("frame") or {}
        self._set_state("stopped", info)
        self._emit("on_stopped", p)
        self.refresh()

    # ---------- inspection ----------
    def refresh(self):
        def frames(cls, p):
            if cls == "done":
                self.frames = [f if "level" in f else f.get("frame", f) for f in p.get("stack", [])]
            self._emit("on_frames")
        self.mi("-stack-list-frames 0 50", frames)

        def variables(cls, p):
            if cls == "done":
                self.vars = [(v.get("name", "?"), v.get("value", ""), "arg" if v.get("arg") == "1" else "local")
                             for v in p.get("variables", [])]
            else:
                self.vars = []
            self._emit("on_vars")
        self.mi("-stack-list-variables --all-values", variables)
        self.eval_watches()

    def eval_watches(self):
        if not self.watches:
            self._emit("on_watches")
            return
        res = list(self.watches)
        left = [len(res)]

        def one(i, expr):
            def cb(cls, p):
                res[i] = (expr, p.get("value", "") if cls == "done" else "‹" + p.get("msg", "error") + "›")
                left[0] -= 1
                if left[0] == 0:
                    self.watches = res
                    self._emit("on_watches")
            self.mi(f"-data-evaluate-expression {self._q(expr)}", cb)
        for i, (expr, _v) in enumerate(res):
            one(i, expr)

    def evaluate(self, expr, cb):
        self.mi(f"-data-evaluate-expression {self._q(expr)}",
                lambda cls, p: cb(p.get("value") if cls == "done" else None, p.get("msg")))

    def select_frame(self, level):
        def done(cls, p):
            self.mi("-stack-info-frame", lambda c, pp: (setattr(self, "frame", pp.get("frame", self.frame)),
                                                        self._emit("on_frame_selected", self.frame)))
            self.mi("-stack-list-variables --all-values", lambda c, pp: (
                setattr(self, "vars", [(v.get("name", "?"), v.get("value", ""), "arg" if v.get("arg") == "1" else "local")
                                       for v in pp.get("variables", [])] if c == "done" else []),
                self._emit("on_vars")))
            self.eval_watches()
        self.mi(f"-stack-select-frame {int(level)}", done)

    # ---------- breakpoints ----------
    def set_breakpoint(self, path, line1, cb=None):
        key = (path, line1)
        if key in self.bkpts:
            return

        def done(cls, p):
            if cls == "done":
                self.bkpts[key] = p.get("bkpt", {}).get("number")
            else:
                self._emit("on_console", f"breakpoint {os.path.basename(path)}:{line1}: {p.get('msg')}\n", "error")
            if cb:
                cb()
        # Use the path relative to the program's folder: gdb matches it as a suffix of the file
        # recorded in the debug info, so it still works for moved / symlinked projects.
        root = os.path.realpath(self.cwd)
        real = os.path.realpath(path)
        loc = os.path.relpath(real, root) if real.startswith(root + os.sep) else os.path.basename(path)
        self.mi(f"-break-insert -f {self._q(f'{loc}:{line1}')}", done)

    def clear_breakpoint(self, path, line1):
        n = self.bkpts.pop((path, line1), None)
        if n:
            self.mi(f"-break-delete {n}")

    # ---------- execution ----------
    def run(self):
        self._set_state("running")
        self.mi("-exec-run")

    def cont(self):
        self.mi("-exec-continue")

    def step_over(self):
        self.mi("-exec-next")

    def step_into(self):
        self.mi("-exec-step")

    def step_out(self):
        self.mi("-exec-finish")

    def pause(self):
        # -exec-interrupt needs target-async; a SIGINT to the inferior works everywhere
        self.mi("-exec-interrupt --all")

    def console(self, text):
        self.mi(f"-interpreter-exec console {self._q(text)}")

    def stop(self):
        if self._dead:
            return
        self.mi("-gdb-exit")
        GLib.timeout_add(800, lambda: (not self._dead and self.proc.force_exit(), False)[1])

    def _gdb_exited(self, proc, res):
        try:
            proc.wait_finish(res)
        except GLib.Error:
            pass
        self._dead = True
        if self.state != "exited":
            self._set_state("ended", "debugger stopped")
        self._emit("on_gdb_exit")
