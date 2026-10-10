"""Build panel: runs build / test / clean tasks, streams the output, and turns compiler
errors into clickable links (gcc, clang, rustc/cargo, go, zig, python tracebacks)."""
import os, time
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Gio, GLib, Pango

from . import project


class BuildPanel(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.proc = None
        self.locs = {}               # buffer line -> (path, line, col)
        self.problems = []           # [(path, line, col, sev, msg)]
        self._pending = ""
        self._t0 = 0
        self._done_cb = None

        head = Gtk.Box(spacing=8)
        head.add_css_class("aether-build-head")
        self.title = Gtk.Label(label="No task has run yet", xalign=0, hexpand=True)
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        head.append(self.title)
        self.counts = Gtk.Label(label="")
        head.append(self.counts)
        self.stop_btn = Gtk.Button(label="■ Stop", tooltip_text="Stop the running task")
        self.stop_btn.add_css_class("flat")
        self.stop_btn.connect("clicked", lambda *_: self.stop())
        self.stop_btn.set_sensitive(False)
        head.append(self.stop_btn)
        self.append(head)

        self.view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(10)
        self.view.set_top_margin(4)
        b = self.view.get_buffer()
        b.create_tag("error", foreground="#f7768e", underline=Pango.Underline.SINGLE)
        b.create_tag("warning", foreground="#e0af68", underline=Pango.Underline.SINGLE)
        b.create_tag("note", foreground="#7dcfff", underline=Pango.Underline.SINGLE)
        b.create_tag("cmd", foreground="#7aa2f7", weight=700)
        b.create_tag("ok", foreground="#9ece6a", weight=700)
        b.create_tag("bad", foreground="#f7768e", weight=700)
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.view.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.view.add_controller(motion)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_child(self.view)
        self.sw = sw
        self.append(sw)

    # ---------- running ----------
    @property
    def running(self):
        return self.proc is not None

    def run(self, label, cmd, cwd, done=None):
        """Run `cmd` in bash in `cwd`; `done(ok)` is called at the end."""
        if self.proc:
            self.stop()
        b = self.view.get_buffer()
        b.set_text("")
        self.locs, self.problems = {}, []
        self.cwd = cwd
        self._done_cb = done
        self._t0 = time.monotonic()
        self.title.set_text(f"{label} — running…")
        self.win.set_activity(f"{label}…")
        self.counts.set_text("")
        self._write(f"$ {cmd}\n", "cmd")
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        launcher.set_cwd(cwd)
        launcher.setenv("TERM", "dumb", True)
        launcher.setenv("CLICOLOR_FORCE", "0", True)
        launcher.setenv("GCC_COLORS", "", True)
        try:
            self.proc = launcher.spawnv(["bash", "-lc", cmd])
        except GLib.Error as e:
            self._write(f"{e.message}\n", "bad")
            self._finish(False, label)
            return
        self.label = label
        self.stop_btn.set_sensitive(True)
        self.stream = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)
        self.proc.wait_async(None, self._on_exit)

    def _on_line(self, stream, res):
        try:
            line, _n = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:
            return
        self._add_line(line.rstrip("\r"))
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)

    def _add_line(self, line):
        b = self.view.get_buffer()
        loc = project.parse_line(line, self.cwd)
        if loc:
            path, ln, col, sev, msg = loc
            self.locs[b.get_line_count() - 1] = (path, ln, col)
            if sev in ("error", "warning") and msg:
                self.problems.append(loc)
            self._write(line + "\n", sev if sev in ("error", "warning", "note") else "error")
        else:
            self._write(line + "\n")

    def _on_exit(self, proc, res):
        try:
            proc.wait_finish(res)
        except GLib.Error:
            pass
        ok = proc.get_if_exited() and proc.get_exit_status() == 0
        # let the reader drain the last lines first
        GLib.timeout_add(60, lambda: (self._finish(ok, self.label), False)[1])

    def _finish(self, ok, label):
        self.proc = None
        self.stop_btn.set_sensitive(False)
        dt = time.monotonic() - self._t0
        ne = sum(1 for p in self.problems if p[3] == "error")
        nw = sum(1 for p in self.problems if p[3] == "warning")
        self._write(f"\n{'✓' if ok else '✗'} {label} {'succeeded' if ok else 'failed'} in {dt:.1f}s\n", "ok" if ok else "bad")
        self.title.set_text(f"{label} {'succeeded' if ok else 'failed'}  ·  {dt:.1f}s")
        self.counts.set_text((f"✖ {ne}  " if ne else "") + (f"⚠ {nw}" if nw else ""))
        if not self.problems:
            GLib.idle_add(self._scroll)
        else:
            # show the first error rather than the tail of the log
            first = min((ln for ln, loc in self.locs.items()), default=None)
            if first is not None:
                ok_, it = self.view.get_buffer().get_iter_at_line(max(0, first - 2))
                GLib.idle_add(lambda: (self.view.scroll_to_iter(it, 0, True, 0, 0), False)[1])
        self.win.on_task_finished(label, ok, self.problems)
        cb, self._done_cb = self._done_cb, None
        if cb:
            cb(ok)

    def stop(self):
        if self.proc:
            self.proc.force_exit()

    # ---------- output ----------
    def _write(self, text, tag=None):
        b = self.view.get_buffer()
        end = b.get_end_iter()
        if tag:
            b.insert_with_tags_by_name(end, text, tag)
        else:
            b.insert(end, text)
        if self.proc is not None:
            GLib.idle_add(self._scroll)

    def _scroll(self):
        adj = self.sw.get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    def _line_at(self, x, y):
        bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        ok, it = self.view.get_iter_at_location(bx, by)
        return it.get_line() if ok else None

    def _on_click(self, g, n, x, y):
        ln = self._line_at(x, y)
        loc = self.locs.get(ln)
        if loc:
            self.win.open_path(loc[0], loc[1], loc[2])

    def _on_motion(self, ctl, x, y):
        ln = self._line_at(x, y)
        self.view.set_cursor_from_name("pointer" if ln in self.locs else "text")
