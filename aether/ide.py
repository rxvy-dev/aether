"""IDE features wired into the main window: projects & build tasks, the debugger,
breakpoints, folding / multi-cursor commands and the outline."""
import os, shlex, shutil
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gtk, GLib, GtkSource

try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte
except (ValueError, ImportError):
    Vte = None

from . import project, runner
from .debugger import GdbSession
from .debugui import DebugConsole
from .palette import Palette
from .tasks import BuildPanel
from . import icons

def _ptsname(fd):
    """/dev/pts/N for a pty master fd (Linux)."""
    import ctypes
    try:
        libc = ctypes.CDLL(None)
        libc.ptsname.restype = ctypes.c_char_p
        libc.ptsname.argtypes = [ctypes.c_int]
        name = libc.ptsname(fd)
        if name:
            return name.decode()
    except (OSError, AttributeError):
        pass
    import fcntl, struct, termios
    req = getattr(termios, "TIOCGPTN", 0x80045430)
    n = struct.unpack("I", fcntl.ioctl(fd, req, struct.pack("I", 0)))[0]
    return f"/dev/pts/{n}"


COMPILED = {"Cargo", "CMake", "Meson", "Makefile", "Zig", "Go"}
DEBUGGABLE = {"c", "cpp", "rust", "go"}


class IdeMixin:
    # ================================================================ setup
    def _ide_setup(self):
        self.project = None
        self.dbg = None
        self.dbg_term = None
        self.watches = []
        self._dbg_target = None
        self._bp_store = {k: set(v) for k, v in (self.settings["breakpoints"] or {}).items()}
        self.build = BuildPanel(self)
        self.panel.append_page(self.build, Gtk.Label(label="Build"))
        self.dbg_console = DebugConsole(self)
        self.panel.append_page(self.dbg_console, Gtk.Label(label="Debug console"))
        self.project_label = Gtk.Button(label="", tooltip_text="Project tasks")
        self.project_label.add_css_class("flat")
        self.project_label.add_css_class("aether-status-btn")
        self.project_label.connect("clicked", lambda *_: self.act_tasks())
        self.project_label.set_visible(False)
        self.statusbar.insert_child_after(self.project_label, self.branch_label)
        # live activity chip (spinner while building / debugging)
        self.activity = Gtk.Box(spacing=6)
        self.activity.add_css_class("aether-activity")
        self.activity_spin = Gtk.Spinner()
        self.activity_dot = Gtk.Label(label="●")
        self.activity_dot.add_css_class("dot")
        self.activity_label = Gtk.Label(label="")
        for w in (self.activity_spin, self.activity_dot, self.activity_label):
            self.activity.append(w)
        self.activity.set_visible(False)
        self.statusbar.insert_child_after(self.activity, self.project_label)
        # toasts in the top-right corner of the editor
        self.toast_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=220,
                                      halign=Gtk.Align.END, valign=Gtk.Align.START)
        self.toast_rev.set_margin_top(10)
        self.toast_rev.set_margin_end(14)
        self.toast_box = Gtk.Box(spacing=10)
        self.toast_box.add_css_class("aether-toast")
        self.toast_icon = Gtk.Label()
        self.toast_icon.add_css_class("icon")
        self.toast_text = Gtk.Label(wrap=True, max_width_chars=48, xalign=0)
        self.toast_box.append(self.toast_icon)
        self.toast_box.append(self.toast_text)
        self.toast_rev.set_child(self.toast_box)
        self.toast_rev.set_can_target(False)
        self.toast_overlay.add_overlay(self.toast_rev)
        self._toast_id = 0
        self._build_activity_bar()
        self._refresh_bp_list()

    # ================================================================ activity bar (VS Code style)
    ACTIVITIES = [("files", "files", "Explorer (Ctrl+Shift+E)"), ("search", "search", "Search (Ctrl+Shift+F)"),
                  ("git", "git", "Source control (Ctrl+Shift+G)"), ("outline", "outline", "Outline (Ctrl+Alt+O)"),
                  ("debug", "debug", "Run and debug (Ctrl+Alt+D)")]

    def _build_activity_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        bar.add_css_class("aether-activity-bar")
        self.activity_bar = bar
        self.act_buttons = {}
        for page, icon, tip in self.ACTIVITIES:
            b = Gtk.Button(tooltip_text=tip)
            b.add_css_class("aether-act")
            ov = Gtk.Overlay()
            ov.set_child(icons.IconView(icon, 24))
            if page == "git":
                self.git_badge = Gtk.Label(label="", halign=Gtk.Align.END, valign=Gtk.Align.END)
                self.git_badge.add_css_class("aether-act-badge")
                self.git_badge.set_visible(False)
                ov.add_overlay(self.git_badge)
            b.set_child(ov)
            b.connect("clicked", lambda _b, p=page: self._activity_clicked(p))
            bar.append(b)
            self.act_buttons[page] = b
        spacer = Gtk.Box(vexpand=True)
        bar.append(spacer)
        gear = Gtk.Button(tooltip_text="Preferences (Ctrl+,)")
        gear.add_css_class("aether-act")
        gear.set_child(icons.IconView("settings", 23))
        gear.connect("clicked", lambda *_: self.show_preferences())
        bar.append(gear)
        self.body.prepend(bar)
        self.sidebar.stack.connect("notify::visible-child-name", lambda *_: self._sync_activity())
        self.sidebar.connect("notify::visible", lambda *_: self._sync_activity())
        self.apply_activity_bar()

    def apply_activity_bar(self):
        on = bool(self.settings["activity_bar"])
        self.activity_bar.set_visible(on)
        self.sidebar.switch.set_visible(not on)
        self._sync_activity()

    def _activity_clicked(self, page):
        if self.sidebar.get_visible() and self.sidebar.stack.get_visible_child_name() == page:
            self.sidebar.set_visible(False)          # VS Code: clicking the active view hides the sidebar
            self.settings["sidebar"] = False
        else:
            self.show_sidebar(page)

    def _sync_activity(self):
        cur = self.sidebar.stack.get_visible_child_name() if self.sidebar.get_visible() else None
        for page, b in getattr(self, "act_buttons", {}).items():
            (b.add_css_class if page == cur else b.remove_css_class)("active")

    def set_git_status(self, status, root):
        super().set_git_status(status, root)
        n = len(status or {})
        if hasattr(self, "git_badge"):
            self.git_badge.set_text(str(n) if n < 100 else "99+")
            self.git_badge.set_visible(n > 0)

    # ================================================================ build configuration
    def set_build_config(self, cfg):
        if cfg == self.settings["build_config"]:
            return
        self.settings["build_config"] = cfg
        if self.folder:
            self.set_project(self.folder)
        self.toast(f"Build configuration: {cfg}", "info", 1800)

    def stop_everything(self):
        if self.build.running:
            self.build.stop()
        if self.dbg:
            self.dbg.stop()

    def toast(self, text, kind="info", ms=3200):
        icon = {"ok": "✓", "bad": "✕", "info": "●", "debug": "◆"}.get(kind, "●")
        for k in ("ok", "bad", "info", "debug"):
            self.toast_box.remove_css_class(k)
        self.toast_box.add_css_class(kind)
        self.toast_icon.set_text(icon)
        self.toast_text.set_text(text)
        self.toast_rev.set_reveal_child(True)
        if self._toast_id:
            GLib.source_remove(self._toast_id)
        self._toast_id = GLib.timeout_add(ms, lambda: (self.toast_rev.set_reveal_child(False), setattr(self, "_toast_id", 0), False)[2])

    def set_activity(self, text, kind="busy"):
        """Status-bar chip: spinner for builds, pulsing dot while debugging; None hides it."""
        busy_now = bool(text) or (self.dbg is not None)
        self.stop_btn.set_sensitive(busy_now or self.build.running)
        (self.statusbar.add_css_class if self.dbg is not None else self.statusbar.remove_css_class)("debugging")
        if self.dbg is not None:
            self.act_buttons["debug"].add_css_class("running")
        else:
            self.act_buttons["debug"].remove_css_class("running")
        if not text:
            self.activity.set_visible(False)
            self.activity_spin.stop()
            return
        self.activity_label.set_text(text)
        busy = kind == "busy"
        self.activity_spin.set_visible(busy)
        self.activity_dot.set_visible(not busy)
        (self.activity_spin.start if busy else self.activity_spin.stop)()
        self.activity.set_visible(True)

    def _ide_callbacks(self):
        cur = lambda: self.cur()
        return {
            "build": lambda *_: self.act_build(), "test": lambda *_: self.act_task("test"),
            "clean": lambda *_: self.act_task("clean"), "configure": lambda *_: self.act_task("configure"),
            "tasks": lambda *_: self.act_tasks(), "run_file": lambda *_: self.act_run(force_file=True),
            "project_settings": lambda *_: self.act_project_settings(),
            "new_project": lambda *_: self.act_new_project(), "clone": lambda *_: self.act_clone(),
            "debug": lambda *_: self.debug_continue(), "debug_stop": lambda *_: self.debug_stop(),
            "step_over": lambda *_: self.debug_step_over(), "step_into": lambda *_: self.debug_step_into(),
            "step_out": lambda *_: self.debug_step_out(), "debug_pause": lambda *_: self.debug_pause(),
            "toggle_breakpoint": lambda *_: cur() and self.toggle_breakpoint(cur(), cur().position()[0] - 1),
            "watch_selection": lambda *_: self.debug_watch_selection(),
            "show_outline": lambda *_: self.show_sidebar("outline"), "show_debug": lambda *_: self.show_sidebar("debug"),
            "fold": lambda *_: cur() and cur().folding.fold_at_cursor(),
            "unfold": lambda *_: cur() and cur().folding.unfold_at_cursor(),
            "fold_all": lambda *_: cur() and cur().folding.fold_all(),
            "unfold_all": lambda *_: cur() and cur().folding.unfold_all(),
            "add_next_occurrence": lambda *_: cur() and cur().mc.add_next_occurrence(),
            "select_all_occurrences": lambda *_: cur() and cur().mc.select_all_occurrences(),
            "cursor_above": lambda *_: cur() and cur().mc.add_vertical(-1),
            "cursor_below": lambda *_: cur() and cur().mc.add_vertical(1),
        }

    IDE_COMMANDS = [
        ("Build project", "build"), ("Run tests", "test"), ("Clean build", "clean"), ("Configure project", "configure"),
        ("Project tasks…", "tasks"), ("Run current file", "run_file"), ("Project settings (build / run / debug)", "project_settings"),
        ("New project…", "new_project"), ("Clone repository…", "clone"),
        ("Debug: start / continue", "debug"), ("Debug: stop", "debug_stop"), ("Debug: step over", "step_over"),
        ("Debug: step into", "step_into"), ("Debug: step out", "step_out"), ("Debug: pause", "debug_pause"),
        ("Debug: toggle breakpoint", "toggle_breakpoint"), ("Debug: watch selection", "watch_selection"),
        ("Show outline", "show_outline"), ("Show debugger", "show_debug"),
        ("Fold block", "fold"), ("Unfold block", "unfold"), ("Fold all", "fold_all"), ("Unfold all", "unfold_all"),
        ("Add cursor at next occurrence", "add_next_occurrence"), ("Select all occurrences", "select_all_occurrences"),
        ("Add cursor above", "cursor_above"), ("Add cursor below", "cursor_below"),
    ]

    # ================================================================ tab hooks
    def _ide_tab_added(self, tab):
        if tab.path:
            for line0 in sorted(self._bp_store.get(tab.path, ())):
                ok, it = tab.buffer.get_iter_at_line(line0)
                if ok:
                    tab.buffer.create_source_mark(None, "breakpoint", it)
        tab.buffer.connect("changed", lambda *_: tab is self.cur() and self.sidebar.outline.schedule())

    def _ide_tab_state(self, t):
        ol = self.sidebar.outline
        if t is not ol.tab:
            ol.set_tab(t)
        elif t:
            ol.follow_cursor()
        if t and t.mc.active:
            self.pos_label.set_text(f"{t.mc.count()} cursors")

    # ================================================================ projects
    def set_project(self, folder):
        self.project = project.Project(folder, self.settings["build_config"]) if folder else None
        p = self.project
        if p and p.kind:
            self.project_label.set_label(f"⚙ {p.kind}")
            self.project_label.set_visible(True)
        else:
            self.project_label.set_visible(False)

    def show_build_panel(self):
        self.show_panel(self.panel.page_num(self.build))

    def save_all(self):
        for t in self.tabs():
            if t.path and t.buffer.get_modified():
                t.save()

    def act_build(self, done=None, proj=None):
        self.save_all()
        p = proj or self.project
        if p and p.tasks.get("build"):
            self.show_build_panel()
            self.build.run("Build", p.tasks["build"], p.root, done)
            return True
        t = self.cur()
        if t and t.path and t.tkey in ("c", "cpp", "rust", "go"):
            cmd, out = self._debug_compile_cmd(t, release=self.settings["build_config"] == "Release")
            self.show_build_panel()
            self.build.run(f"Build {t.title}", cmd, os.path.dirname(t.path), done)
            return True
        self.flash("Nothing to build — open a project folder (Makefile, CMake, Meson, Cargo, Go, Zig…) or a C/C++/Rust/Go file")
        return False

    def act_task(self, name):
        p = self.project
        if not p or not p.tasks.get(name):
            self.flash(f"This project has no '{name}' task — add one in Project settings")
            return
        self.save_all()
        self.show_build_panel()
        self.build.run(name.title(), p.tasks[name], p.root)

    def act_tasks(self):
        p = self.project
        if not p:
            self.flash("Open a project folder first")
            return
        items = []
        for name in ("build", "run", "test", "clean", "configure"):
            cmd = p.tasks.get(name)
            if cmd:
                cb = (lambda: self.act_run()) if name == "run" else (lambda n=name: self.act_build() if n == "build" else self.act_task(n))
                items.append((f"{name.title()}   —   {cmd}", "", cb))
        items.append(("Project settings…", "", lambda: self.act_project_settings()))
        Palette(self, f"{p.name} · {p.label()} tasks", items).present()

    def act_project_settings(self):
        p = self.project
        if not p:
            self.flash("Open a project folder first")
            return
        path = os.path.join(p.root, project.CONFIG)
        if not os.path.exists(path):
            p.save_cfg(**{k: v for k, v in p.tasks.items()}, debug_program=p.cfg.get("debug_program", ""), debug_args="")
        self.open_path(path)

    def project_run(self):
        """F5 inside a project: run its run task (or build + run its program). Returns False to fall back."""
        p = self.project
        t = self.cur()
        if not p or not p.kind:
            return False
        if t and t.path and not t.path.startswith(p.root + os.sep):
            return False
        if t and t.tkey in ("python", "shellscript", "javascript", "html") and p.kind not in ("Python", "npm"):
            return False
        self.save_all()
        if p.tasks.get("run"):
            self.show_panel()
            self.run_in_terminal(f"clear; cd {shlex.quote(p.root)} && {p.tasks['run']}")
            return True
        if p.kind in COMPILED and p.tasks.get("build"):
            def after(ok):
                if not ok:
                    return
                self._pick_program(lambda prog: self.run_in_terminal(
                    f"clear; cd {shlex.quote(p.root)} && {shlex.quote(prog)} {p.cfg.get('debug_args', '')}"))
            self.act_build(after)
            return True
        return False

    def act_new_project(self):
        from .welcome import NewProjectDialog
        NewProjectDialog(self).present()

    def act_clone(self):
        from .welcome import CloneDialog
        CloneDialog(self).present()

    def on_task_finished(self, label, ok, problems):
        ne = sum(1 for p in problems if p[3] == "error")
        nw = sum(1 for p in problems if p[3] == "warning")
        extra = f" — {ne} error(s), {nw} warning(s)" if problems else ""
        self.flash(f"{'✓' if ok else '✗'} {label} {'succeeded' if ok else 'failed'}{extra}", 6000)
        self.set_activity(None if not self.dbg else "Debugging", "debug")
        if not self.dbg:
            self.toast(f"{label} {'succeeded' if ok else 'failed'}{extra}", "ok" if ok else "bad")
        if not ok and problems:
            first = next((p for p in problems if p[3] == "error"), problems[0])
            self.open_path(first[0], first[1], first[2])

    # ================================================================ breakpoints
    def _bp_lines(self, tab):
        # (forward_iter_to_source_mark is not usable from Python: its in/out iter is broken)
        b = tab.buffer
        return {ln for ln in range(b.get_line_count()) if b.get_source_marks_at_line(ln, "breakpoint")}

    def _collect_bps(self):
        open_paths = set()
        for t in self.tabs():
            if t.path:
                open_paths.add(t.path)
                lines = self._bp_lines(t)
                if lines:
                    self._bp_store[t.path] = lines
                else:
                    self._bp_store.pop(t.path, None)
        self._bp_store = {k: v for k, v in self._bp_store.items() if v and (k in open_paths or os.path.exists(k))}
        return sorted((p, l) for p, ls in self._bp_store.items() for l in ls)

    def _save_bps(self):
        bps = self._collect_bps()
        store = {}
        for p, l in bps:
            store.setdefault(p, []).append(l)
        self.settings["breakpoints"] = store
        self._refresh_bp_list(bps)

    def _refresh_bp_list(self, bps=None):
        if hasattr(self.sidebar, "debug"):
            self.sidebar.debug.set_breakpoints(bps if bps is not None else self._collect_bps())

    def toggle_breakpoint(self, tab, line0):
        if not tab.path:
            self.flash("Save the file before setting breakpoints")
            return
        b = tab.buffer
        marks = b.get_source_marks_at_line(line0, "breakpoint")
        if marks:
            for m in marks:
                b.delete_mark(m)
            if self.dbg:
                self.dbg.clear_breakpoint(tab.path, line0 + 1)
        else:
            ok, it = b.get_iter_at_line(line0)
            b.create_source_mark(None, "breakpoint", it)
            if self.dbg:
                self.dbg.set_breakpoint(tab.path, line0 + 1)
        self._save_bps()

    def remove_breakpoint(self, path, line0):
        for t in self.tabs():
            if t.path == path:
                for m in t.buffer.get_source_marks_at_line(line0, "breakpoint"):
                    t.buffer.delete_mark(m)
        self._bp_store.get(path, set()).discard(line0)
        if self.dbg:
            self.dbg.clear_breakpoint(path, line0 + 1)
        self._save_bps()

    def clear_breakpoints(self):
        for p, l in self._collect_bps():
            self.remove_breakpoint(p, l)

    # ================================================================ debugger
    def _debug_compile_cmd(self, t, release=False):
        os.makedirs(runner.CACHE, exist_ok=True)
        base = os.path.splitext(os.path.basename(t.path))[0] or "a.out"
        out = os.path.join(runner.CACHE, base + ("-release" if release else "-debug"))
        q, o, d = shlex.quote(t.path), shlex.quote(out), shlex.quote(os.path.dirname(t.path))
        opt = "-O2 -DNDEBUG" if release else "-g3 -O0"
        if t.tkey == "c":
            cc = "cc" if shutil.which("cc") else "gcc" if shutil.which("gcc") else "clang"
            return f"{cc} {opt} -Wall -Wextra -I{d} -o {o} {q} -lm", out
        if t.tkey == "cpp":
            cxx = "c++" if shutil.which("c++") else "g++" if shutil.which("g++") else "clang++"
            return f"{cxx} -std=c++20 {opt} -Wall -Wextra -I{d} -o {o} {q}", out
        if t.tkey == "rust":
            return f"rustc {'-C opt-level=3' if release else '-g -C opt-level=0'} -o {o} {q}", out
        if t.tkey == "go":
            return f"go build -gcflags=all='-N -l' -o {o} {q}", out
        return None, None

    def _pick_program(self, cb, proj=None):
        p = proj or self.project
        cands = p.debug_candidates()
        if p.cfg.get("debug_program") and cands:
            cb(cands[0])
            return
        if len(cands) == 1:
            p.save_cfg(debug_program=os.path.relpath(cands[0], p.root))
            cb(cands[0])
            return

        def chosen(path):
            path = os.path.join(p.root, os.path.expanduser(path)) if not os.path.isabs(path) else path
            if not os.path.isfile(path):
                self.flash(f"{path} does not exist — build first, or check the path")
                return
            p.save_cfg(debug_program=os.path.relpath(path, p.root))
            cb(path)
        if cands:
            items = [(os.path.relpath(c, p.root), "", (lambda c=c: chosen(c))) for c in cands]
            Palette(self, "Which program should run? (saved in .aether/project.json)", items).present()
        else:
            Palette(self, "Path to the built program, relative to the project (e.g. build/app)", on_text=chosen).present()

    def debug_continue(self):
        if self.dbg:
            if self.dbg.state == "stopped":
                self.dbg.cont()
            return
        if not GdbSession.available():
            fam = runner.distro_family()
            hint = {0: "sudo pacman -S gdb", 1: "sudo apt install gdb", 2: "sudo dnf install gdb"}.get(fam, "install gdb with your package manager (xbps-install -S gdb on Void)")
            self.flash(f"The debugger needs gdb:  {hint}", 12000)
            return
        self.save_all()
        p = self.project
        t = self.cur()
        in_project = p and p.kind in COMPILED and (not t or not t.path or t.path.startswith(p.root + os.sep))
        if in_project and p.config != "Debug":
            self.toast("Debugging uses the Debug configuration", "info", 2500)
            p = project.Project(p.root, "Debug")          # just for this debug build
        if in_project and p.tasks.get("build"):
            self.act_build(lambda ok: ok and self._pick_program(lambda prog: self._debug_launch(prog, p.root, p.cfg.get("debug_args", "")), p), p)
            return
        if t and t.path and t.tkey in DEBUGGABLE:
            cmd, out = self._debug_compile_cmd(t)
            self.show_build_panel()
            self.build.run(f"Compile {t.title} for debugging", cmd, os.path.dirname(t.path),
                           lambda ok: ok and self._debug_launch(out, os.path.dirname(t.path), ""))
            return
        self.flash("Debugging works for C, C++, Rust and Go (gdb). Open one of those files, or a project folder.")

    def _program_terminal(self):
        """A terminal tab wired to a fresh pty for the debugged program's input/output."""
        if not Vte:
            return None
        if self.dbg_term is not None and self.panel.page_num(self.dbg_term) >= 0:
            self.dbg_term.reset(True, True)
            term = self.dbg_term
        else:
            term = Vte.Terminal()
            term.set_hexpand(True)
            term.set_vexpand(True)
            term.set_scrollback_lines(5000)
            from gi.repository import Pango
            term.set_font(Pango.FontDescription(f"{self.settings['font']} {self.settings['font_size']}"))
            self.panel.append_page(term, Gtk.Label(label="Program"))
            self.dbg_term = term
            if hasattr(self, "pal"):
                self.terms.append(term)
                self._theme_term(self.pal["fg"], self.pal["bg"])
                self.terms.remove(term)
        try:
            pty = Vte.Pty.new_sync(Vte.PtyFlags.DEFAULT, None)
        except Exception:
            return None
        term.set_pty(pty)
        self._dbg_pty = pty
        return _ptsname(pty.get_fd())

    def _debug_launch(self, program, cwd, args):
        self._dbg_target = (program, cwd, args)
        self.dbg_console.clear()
        tty = self._program_terminal()
        self.dbg_console.write(f"Debugging {program}\n", "info")
        cb = dict(on_state=self._dbg_state, on_stopped=self._dbg_stopped, on_console=self.dbg_console.write,
                  on_vars=lambda: self.sidebar.debug.set_vars(self.dbg.vars if self.dbg else []),
                  on_frames=lambda: self.sidebar.debug.set_frames(self.dbg.frames if self.dbg else []),
                  on_watches=lambda: self.sidebar.debug.set_watches(self.dbg.watches if self.dbg else []),
                  on_frame_selected=self._dbg_frame_selected, on_exit=self._dbg_program_exit, on_gdb_exit=self._dbg_gone)
        try:
            self.dbg = GdbSession(program, args, cwd, tty, **cb)
        except GLib.Error as e:
            self.flash(f"Could not start gdb: {e.message}")
            return
        self.dbg.watches = [(w, "") for w in self.watches]
        self.show_sidebar("debug")
        self.toast(f"Debugging {os.path.basename(program)}", "debug", 2200)
        if self.dbg_term is not None:
            self.show_panel(self.panel.page_num(self.dbg_term))
        bps = self._collect_bps()
        left = [len(bps)]

        def one_done():
            left[0] -= 1
            if left[0] <= 0:
                self.dbg.run()
        if not bps:
            self.flash("No breakpoints set — pausing at main(). Press F9 on a line to add one.", 5000)
            self.dbg.mi("-break-insert -t main", lambda *_: self.dbg and self.dbg.run())
        for path, line0 in bps:
            self.dbg.set_breakpoint(path, line0 + 1, one_done)

    def _clear_pc(self):
        for t in self.tabs():
            s, e = t.buffer.get_bounds()
            t.buffer.remove_source_marks(s, e, "debug-pc")

    def _show_pc(self, f):
        path, line = f.get("fullname") or f.get("file"), f.get("line")
        self._clear_pc()
        if not path or not line or not os.path.isfile(path):
            self.dbg_console.write(f"(paused in {f.get('func', '??')} — no source available)\n", "log")
            return
        tab = self.open_path(path, int(line))
        if tab:
            ok, it = tab.buffer.get_iter_at_line(int(line) - 1)
            tab.buffer.create_source_mark(None, "debug-pc", it)

    def _dbg_state(self, st, info):
        page = self.sidebar.debug
        active = st in ("running", "stopped", "starting")
        page.set_running(active, st == "stopped")
        if active:
            self.set_activity("Debugging" if st == "stopped" else "Running under gdb", "debug")
        if st == "running":
            page.set_status("Running…")
            self._clear_pc()
        elif st == "stopped":
            f = self.dbg.frame if self.dbg else {}
            page.set_status(f"Paused ({info}) in {f.get('func', '??')} — {os.path.basename(f.get('file', '') or '')}:{f.get('line', '?')}")
        elif st == "exited":
            page.set_status(f"Program {info}.")
        elif st == "ended":
            page.set_status("Not running.")

    def _dbg_stopped(self, payload):
        self._show_pc(payload.get("frame") or {})

    def _dbg_frame_selected(self, frame):
        self._show_pc(frame or {})
        if self.dbg:
            self.sidebar.debug.set_frames(self.dbg.frames, int((frame or {}).get("level", 0)))

    def _dbg_program_exit(self, code):
        self.flash(f"Program exited with code {code}", 6000)
        self.toast(f"Program exited with code {code}", "ok" if code == 0 else "bad")
        self.dbg_console.write(f"\n[program exited with code {code}]\n", "info")
        self._clear_pc()
        if self.dbg:
            self.dbg.stop()

    def _dbg_gone(self):
        self.dbg = None
        self.set_activity(None)
        self._clear_pc()
        page = self.sidebar.debug
        page.set_running(False, False)
        page.set_vars([])
        page.set_frames([])

    def debug_stop(self):
        if self.dbg:
            self.dbg.stop()

    def debug_restart(self):
        tgt = self._dbg_target
        if self.dbg and tgt:
            old = self.dbg
            self._restart_pending = True

            def relaunch():
                self._dbg_gone()
                self._debug_launch(*tgt)
            old.cb["on_gdb_exit"] = relaunch
            old.stop()

    def debug_pause(self):
        if self.dbg and self.dbg.state == "running":
            self.dbg.pause()

    def debug_step_over(self):
        if self.dbg and self.dbg.state == "stopped":
            self.dbg.step_over()

    def debug_step_into(self):
        if self.dbg and self.dbg.state == "stopped":
            self.dbg.step_into()

    def debug_step_out(self):
        if self.dbg and self.dbg.state == "stopped":
            self.dbg.step_out()

    def debug_select_frame(self, f):
        if self.dbg and self.dbg.state == "stopped":
            self.dbg.select_frame(f.get("level", 0))

    def debug_add_watch(self, expr):
        self.watches.append(expr)
        if self.dbg:
            self.dbg.watches.append((expr, ""))
            if self.dbg.state == "stopped":
                self.dbg.eval_watches()
                return
        self.sidebar.debug.set_watches([(w, "") for w in self.watches])

    def debug_remove_watch(self, i):
        if 0 <= i < len(self.watches):
            self.watches.pop(i)
        if self.dbg and 0 <= i < len(self.dbg.watches):
            self.dbg.watches.pop(i)
        self.sidebar.debug.set_watches(self.dbg.watches if self.dbg else [(w, "") for w in self.watches])

    def debug_watch_selection(self):
        t = self.cur()
        if t and t.buffer.get_has_selection():
            s, e = t.buffer.get_selection_bounds()
            txt = t.buffer.get_text(s, e, False).strip()
            if txt and "\n" not in txt:
                self.debug_add_watch(txt)
                self.show_sidebar("debug")
                return
        self.flash("Select an expression first")

    def debug_console_command(self, text):
        if self.dbg:
            self.dbg.console(text)
            if self.dbg.state == "stopped":
                GLib.timeout_add(150, lambda: (self.dbg and self.dbg.refresh(), False)[1])
        else:
            self.dbg_console.write("Not debugging — press F6 to start.\n", "error")

    def ide_shutdown(self):
        self._save_bps()
        if self.dbg:
            self.dbg.stop()
