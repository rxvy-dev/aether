import os, re
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Gio, GLib, Pango, GObject

from . import gitutil, search
from .palette import Palette
from . import icons
from .outline import OutlinePage
from .debugui import DebugPage

IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", ".cache", ".idea", ".mypy_cache"}
BADGE = {"M": "#e0af68", "A": "#73daca", "?": "#73daca", "D": "#f7768e", "R": "#7aa2f7", "U": "#f7768e", "C": "#7aa2f7"}


def tool(label, tip, cb):
    b = Gtk.Button(label=label, tooltip_text=tip)
    b.add_css_class("flat")
    b.add_css_class("tool")
    b.connect("clicked", lambda *_: cb())
    return b


class FilesPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.title = Gtk.Label(label="No folder open", xalign=0, hexpand=True)
        self.title.add_css_class("aether-proj")
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.append(self.title)
        top = Gtk.Box(spacing=2)
        top.set_margin_start(8)
        top.set_margin_end(8)
        for lbl, tip, cb in (("+ File", "New file", lambda: self.new_file(self.win.folder)),
                             ("+ Folder", "New folder", lambda: self.new_folder(self.win.folder)),
                             ("↻ Refresh", "Refresh", self.refresh)):
            top.append(tool(lbl, tip, cb))
        self.append(top)
        self.hint = Gtk.Label(label="Open a folder to see its files.", xalign=0)
        self.hint.add_css_class("aether-hint")
        self.append(self.hint)
        self.store = Gtk.TreeStore(str, str, bool, GObject.TYPE_OBJECT, str, str)    # name, path, isdir, icon texture, badge, badge colour
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_headers_visible(False)
        self.tree.set_enable_search(True)
        self.tree.set_search_column(0)
        col = Gtk.TreeViewColumn()
        r1 = Gtk.CellRendererPixbuf()
        col.pack_start(r1, False)
        col.add_attribute(r1, "texture", 3)
        r1.set_property("width", 24)
        r2 = Gtk.CellRendererText()
        r2.set_property("ellipsize", Pango.EllipsizeMode.END)
        col.pack_start(r2, True)
        col.add_attribute(r2, "text", 0)
        r3 = Gtk.CellRendererText()
        r3.set_property("weight", 700)
        col.pack_start(r3, False)
        col.add_attribute(r3, "text", 4)
        col.add_attribute(r3, "foreground", 5)
        col.set_expand(True)
        self.tree.append_column(col)
        self.tree.connect("row-expanded", self._on_expand)
        self.tree.connect("row-collapsed", lambda tv, it, p: self.store.set_value(it, 3, icons.file_texture("", True, False, px=16)))
        self.tree.connect("row-activated", self._on_activated)
        g = Gtk.GestureClick()
        g.set_button(3)
        g.connect("pressed", self._on_right_click)
        self.tree.add_controller(g)
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        sw.set_child(self.tree)
        self.append(sw)
        self._ctx = None
        self._actions()

    # ---- tree ----
    def set_folder(self, folder):
        self.title.set_text(os.path.basename(folder) if folder else "No folder open")
        self.hint.set_visible(not folder)
        self.refresh()

    def refresh(self):
        expanded = self._expanded_paths()
        self.store.clear()
        if self.win.folder:
            self._fill(None, self.win.folder)
            self._reexpand(expanded)
        self.apply_badges(getattr(self.win, "git_status", {}))

    def _expanded_paths(self):
        out = []
        def walk(it):
            while it:
                if self.store.get_value(it, 2) and self.tree.row_expanded(self.store.get_path(it)):
                    out.append(self.store.get_value(it, 1))
                ch = self.store.iter_children(it)
                if ch:
                    walk(ch)
                it = self.store.iter_next(it)
        walk(self.store.get_iter_first())
        return out

    def _reexpand(self, paths):
        for p in sorted(paths, key=len):
            it = self._find(p)
            if it:
                self.tree.expand_row(self.store.get_path(it), False)

    def _find(self, path):
        def walk(it):
            while it:
                p = self.store.get_value(it, 1)
                if p == path:
                    return it
                if self.store.get_value(it, 2) and path.startswith(p + os.sep):
                    ch = self.store.iter_children(it)
                    if ch and self.store.get_value(ch, 1) == "":
                        self.store.remove(ch)
                        self._fill(it, p)
                        ch = self.store.iter_children(it)
                    r = walk(ch) if ch else None
                    if r:
                        return r
                it = self.store.iter_next(it)
            return None
        return walk(self.store.get_iter_first())

    def _fill(self, parent, path):
        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
        except OSError:
            return
        for e in entries:
            if e.name in IGNORE or (e.name.startswith(".") and e.name not in (".gitignore", ".env", ".editorconfig")):
                continue
            isdir = e.is_dir()
            it = self.store.append(parent, [e.name, e.path, isdir, icons.file_texture(e.name, isdir, px=16), "", "#888888"])
            if isdir:
                self.store.append(it, ["", "", False, None, "", "#888888"])

    def _on_expand(self, tv, it, path):
        self.store.set_value(it, 3, icons.file_texture("", True, True, px=16))
        child = self.store.iter_children(it)
        if child and self.store.get_value(child, 1) == "":
            self.store.remove(child)
            self._fill(it, self.store.get_value(it, 1))
            self.apply_badges(getattr(self.win, "git_status", {}))

    def _on_activated(self, tv, path, col):
        it = self.store.get_iter(path)
        p, isdir = self.store.get_value(it, 1), self.store.get_value(it, 2)
        if isdir:
            tv.collapse_row(path) if tv.row_expanded(path) else tv.expand_row(path, False)
        else:
            self.win.open_path(p)

    def apply_badges(self, status):
        """status: {abs_path: letter}. Folders get a dot when something inside changed."""
        dirs = set()
        for p in status:
            d = os.path.dirname(p)
            while d and d != os.path.dirname(d) and self.win.folder and d.startswith(self.win.folder):
                dirs.add(d)
                d = os.path.dirname(d)
        def walk(it):
            while it:
                p = self.store.get_value(it, 1)
                if p:
                    if p in status:
                        self.store.set_value(it, 4, "  " + status[p])
                        self.store.set_value(it, 5, BADGE.get(status[p], "#e0af68"))
                    elif p in dirs:
                        self.store.set_value(it, 4, "  ●")
                        self.store.set_value(it, 5, "#e0af68")
                    else:
                        self.store.set_value(it, 4, "")
                        self.store.set_value(it, 5, "#888888")
                ch = self.store.iter_children(it)
                if ch:
                    walk(ch)
                it = self.store.iter_next(it)
        walk(self.store.get_iter_first())

    # ---- context menu ----
    def _actions(self):
        grp = Gio.SimpleActionGroup()
        def add(name, cb):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_: cb())
            grp.add_action(a)
        add("new_file", lambda: self.new_file(self._target_dir()))
        add("new_folder", lambda: self.new_folder(self._target_dir()))
        add("rename", self.rename)
        add("delete", self.delete)
        add("copy_path", lambda: self.tree.get_clipboard().set(self._ctx or ""))
        add("copy_rel", lambda: self.tree.get_clipboard().set(os.path.relpath(self._ctx, self.win.folder) if self._ctx and self.win.folder else ""))
        add("reveal", lambda: Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(self._target_dir()).get_uri(), None))
        add("terminal", lambda: self.win.new_terminal(self._target_dir()))
        self.tree.insert_action_group("tree", grp)

    def _target_dir(self):
        p = self._ctx or self.win.folder
        if p and not os.path.isdir(p):
            p = os.path.dirname(p)
        return p or self.win.folder

    def _on_right_click(self, g, n, x, y):
        bx, by = self.tree.convert_widget_to_bin_window_coords(int(x), int(y))
        res = self.tree.get_path_at_pos(bx, by)
        self._ctx = None
        if res and res[0]:
            self._ctx = self.store.get_value(self.store.get_iter(res[0]), 1) or None
            self.tree.get_selection().select_path(res[0])
        if not self.win.folder:
            return
        m = Gio.Menu()
        s1 = Gio.Menu()
        s1.append("New file", "tree.new_file")
        s1.append("New folder", "tree.new_folder")
        m.append_section(None, s1)
        if self._ctx:
            s2 = Gio.Menu()
            s2.append("Rename…", "tree.rename")
            s2.append("Move to trash", "tree.delete")
            m.append_section(None, s2)
            s3 = Gio.Menu()
            s3.append("Copy path", "tree.copy_path")
            s3.append("Copy relative path", "tree.copy_rel")
            s3.append("Open in terminal", "tree.terminal")
            s3.append("Show in file manager", "tree.reveal")
            m.append_section(None, s3)
        pop = Gtk.PopoverMenu.new_from_model(m)
        pop.set_parent(self.tree)
        r = Gdk.Rectangle()
        r.x, r.y, r.width, r.height = int(x), int(y), 1, 1
        pop.set_pointing_to(r)
        pop.set_has_arrow(False)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def new_file(self, d):
        if not d:
            return
        def go(name):
            name = name.strip()
            if not name:
                return
            path = os.path.join(d, name)
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "a").close()
            except OSError as e:
                self.win.flash(f"Could not create file: {e}")
                return
            self.refresh()
            self.win.open_path(path)
        Palette(self.win, "New file name (e.g. src/main.c)", on_text=go).present()

    def new_folder(self, d):
        if not d:
            return
        def go(name):
            if name.strip():
                try:
                    os.makedirs(os.path.join(d, name.strip()), exist_ok=True)
                except OSError as e:
                    self.win.flash(str(e))
                self.refresh()
        Palette(self.win, "New folder name", on_text=go).present()

    def rename(self):
        old = self._ctx
        if not old:
            return
        def go(name):
            name = name.strip()
            if not name or name == os.path.basename(old):
                return
            new = os.path.join(os.path.dirname(old), name)
            try:
                os.rename(old, new)
            except OSError as e:
                self.win.flash(f"Rename failed: {e}")
                return
            self.win.path_renamed(old, new)
            self.refresh()
        Palette(self.win, "Rename to…", on_text=go, initial=os.path.basename(old)).present()

    def delete(self):
        p = self._ctx
        if not p:
            return
        dlg = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.WARNING,
                                text=f"Move “{os.path.basename(p)}” to the trash?")
        dlg.add_button("Cancel", 0)
        dlg.add_button("Move to trash", 1)
        def resp(d, r):
            d.destroy()
            if r == 1:
                try:
                    Gio.File.new_for_path(p).trash(None)
                except GLib.Error as e:
                    self.win.flash(f"Could not trash: {e.message}")
                    return
                self.win.path_deleted(p)
                self.refresh()
        dlg.connect("response", resp)
        dlg.present()


class SearchPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.win = win
        self.job = None
        self._deb = 0
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_top(4)
        row = Gtk.Box(spacing=4)
        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("Search in project")
        self.entry.set_hexpand(True)
        row.append(self.entry)
        self.case, self.word, self.regex = (Gtk.ToggleButton(label=l, tooltip_text=t) for l, t in
                                            (("Aa", "Match case"), ("ab", "Whole word"), (".*", "Regular expression")))
        for b in (self.case, self.word, self.regex):
            b.add_css_class("tool")
            b.connect("toggled", lambda *_: self.run())
            row.append(b)
        self.append(row)
        self.include = Gtk.Entry()
        self.include.set_placeholder_text("Only in files… (e.g. *.c, *.h)")
        self.append(self.include)
        rr = Gtk.Box(spacing=4)
        self.repl = Gtk.Entry()
        self.repl.set_placeholder_text("Replace with")
        self.repl.set_hexpand(True)
        rr.append(self.repl)
        rb = Gtk.Button(label="Replace all")
        rb.connect("clicked", lambda *_: self.replace_all())
        rr.append(rb)
        self.append(rr)
        self.status = Gtk.Label(label="", xalign=0)
        self.status.add_css_class("aether-hint")
        self.status.set_margin_start(0)
        self.append(self.status)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", self._activated)
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        sw.set_child(self.list)
        self.append(sw)
        self.entry.connect("search-changed", lambda *_: self.schedule())
        self.entry.connect("activate", lambda *_: self.run())
        self.include.connect("changed", lambda *_: self.schedule())
        self._last = None
        self._nfiles = 0
        self._n = 0

    def focus(self, text=None):
        if text:
            self.entry.set_text(text)
        self.entry.grab_focus()

    def schedule(self):
        if self._deb:
            GLib.source_remove(self._deb)
        self._deb = GLib.timeout_add(350, self._fire)

    def _fire(self):
        self._deb = 0
        self.run()
        return False

    def _clear(self):
        c = self.list.get_first_child()
        while c:
            n = c.get_next_sibling()
            self.list.remove(c)
            c = n
        self._last, self._nfiles, self._n = None, 0, 0

    def run(self):
        if self.job:
            self.job.cancel.set()
            self.job = None
        self._clear()
        q = self.entry.get_text()
        if len(q) < 2 or not self.win.folder:
            self.status.set_text("" if self.win.folder else "Open a folder first.")
            return
        self.status.set_text("Searching…")
        job = search.ProjectSearch(self.win.folder, q, self.case.get_active(), self.regex.get_active(), self.word.get_active(),
                                   self.include.get_text(), lambda b, j=None: self._batch(b, job), lambda n, m: self._done(n, m, job))
        self.job = job
        job.start()

    def _batch(self, batch, job):
        if job is not self.job:
            return False
        for path, ln, col, text in batch:
            if path != self._last:
                self._last = path
                self._nfiles += 1
                h = Gtk.ListBoxRow()
                h.set_selectable(False)
                h.set_activatable(False)
                l = Gtk.Label(label=os.path.relpath(path, self.win.folder), xalign=0)
                l.add_css_class("file-head")
                l.set_ellipsize(Pango.EllipsizeMode.START)
                h.set_child(l)
                self.list.append(h)
            r = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=8)
            n = Gtk.Label(label=str(ln), xalign=1)
            n.set_size_request(34, -1)
            n.add_css_class("match")
            t = Gtk.Label(label=text, xalign=0)
            t.add_css_class("match")
            t.set_ellipsize(Pango.EllipsizeMode.END)
            box.append(n)
            box.append(t)
            r.set_child(box)
            r._hit = (path, ln, col)
            self.list.append(r)
            self._n += 1
        self.status.set_text(f"{self._n} results in {self._nfiles} files…")
        return False

    def _done(self, total, msg, job):
        if job is not self.job:
            return False
        self.status.set_text(msg if msg.startswith("Invalid") else (f"{total} results in {self._nfiles} files" + (" (limit reached)" if msg else "") if total else "No results"))
        return False

    def _activated(self, lb, row):
        if hasattr(row, "_hit"):
            p, ln, col = row._hit
            self.win.open_path(p, ln, col)

    def replace_all(self):
        q, rep = self.entry.get_text(), self.repl.get_text()
        if len(q) < 1 or not self.win.folder:
            return
        dlg = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.WARNING,
                                text=f"Replace “{q}” with “{rep}” in {self._nfiles} files?",
                                secondary_text="This edits files on disk. Files with unsaved changes are skipped.")
        dlg.add_button("Cancel", 0)
        dlg.add_button("Replace all", 1)
        def resp(d, r):
            d.destroy()
            if r != 1:
                return
            skip = {t.path for t in self.win.tabs() if t.path and t.buffer.get_modified()}
            def done(changed, err):
                if err:
                    self.win.flash(err)
                    return False
                for path, n in changed:
                    for t in self.win.tabs():
                        if t.path == path and not t.buffer.get_modified():
                            t.load(path)
                self.win.flash(f"Replaced in {len(changed)} files ({sum(n for _, n in changed)} matches)")
                self.run()
                return False
            search.replace_in_files(self.win.folder, q, rep, self.case.get_active(), self.regex.get_active(),
                                    self.word.get_active(), self.include.get_text(), skip, done)
        dlg.connect("response", resp)
        dlg.present()


class GitPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.win = win
        self.root = None
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_top(4)
        top = Gtk.Box(spacing=2)
        self.branch = Gtk.Label(label="", xalign=0, hexpand=True)
        self.branch.add_css_class("aether-proj")
        self.branch.set_margin_start(0)
        top.append(self.branch)
        for lbl, tip, cmd in (("Pull", "git pull", "git pull"), ("Push", "git push", "git push")):
            top.append(tool(lbl, tip, lambda c=cmd: self.win.run_in_terminal(c)))
        top.append(tool("↻", "Refresh", self.refresh))
        self.append(top)
        self.msg = Gtk.Entry()
        self.msg.set_placeholder_text("Commit message")
        self.msg.connect("activate", lambda *_: self.commit())
        self.append(self.msg)
        cb = Gtk.Button(label="Commit staged changes")
        cb.add_css_class("primary")
        cb.connect("clicked", lambda *_: self.commit())
        self.append(cb)
        self.note = Gtk.Label(label="", xalign=0)
        self.note.add_css_class("aether-hint")
        self.note.set_margin_start(0)
        self.note.set_wrap(True)
        self.append(self.note)
        self.init_btn = Gtk.Button(label="Initialize repository")
        self.init_btn.connect("clicked", lambda *_: self._git(["init"], lambda *_: self.refresh()))
        self.append(self.init_btn)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        sw.set_child(self.list)
        self.append(sw)

    def _git(self, args, cb=None):
        gitutil.run(["git"] + args, self.root or self.win.folder, cb or (lambda *_: None))

    def refresh(self):
        folder = self.win.folder
        self.root = gitutil.repo_root(folder) if folder else None
        self._clear()
        self.init_btn.set_visible(bool(folder) and not self.root)
        for w in (self.msg,):
            w.set_visible(bool(self.root))
        if not folder:
            self.note.set_text("Open a folder to use source control.")
            self.branch.set_text("")
            return
        if not self.root:
            self.note.set_text("This folder isn't a git repository.")
            self.branch.set_text("")
            self.win.set_git_status({}, None)
            return
        self.note.set_text("")
        gitutil.run(["git", "status", "--porcelain=v1", "-z"], self.root, self._status)
        gitutil.run(["git", "branch", "--show-current"], self.root, lambda st, out: self.branch.set_text("⎇  " + (out.strip() or "detached HEAD")))

    def _clear(self):
        c = self.list.get_first_child()
        while c:
            n = c.get_next_sibling()
            self.list.remove(c)
            c = n

    def _status(self, st, out):
        if st != 0:
            self.note.set_text(out.strip()[:200])
            return
        items = gitutil.parse_status(out)
        status = {}
        for x, y, path in items:
            status[os.path.join(self.root, path)] = "?" if x == "?" else (y if y not in " " else x)
        self.win.set_git_status(status, self.root)
        self._clear()
        staged = [(x, y, p) for x, y, p in items if x not in " ?"]
        changes = [(x, y, p) for x, y, p in items if y != " " or x == "?"]
        self._section("Staged changes", staged, True)
        self._section("Changes", changes, False)
        if not items:
            self.note.set_text("Working tree clean.")

    def _section(self, title, items, staged):
        if not items:
            return
        h = Gtk.ListBoxRow()
        h.set_selectable(False)
        h.set_activatable(False)
        box = Gtk.Box(spacing=4)
        l = Gtk.Label(label=f"{title}  {len(items)}", xalign=0, hexpand=True)
        l.add_css_class("file-head")
        box.append(l)
        if staged:
            box.append(tool("− all", "Unstage all", lambda: self._git(["reset", "-q"], lambda *_: self.refresh())))
        else:
            box.append(tool("+ all", "Stage all", lambda: self._git(["add", "-A"], lambda *_: self.refresh())))
        h.set_child(box)
        self.list.append(h)
        for x, y, path in items:
            r = Gtk.ListBoxRow()
            r.set_activatable(False)
            b = Gtk.Box(spacing=6)
            letter = "?" if x == "?" else (x if staged else y)
            bl = Gtk.Label(label=letter)
            bl.add_css_class("badge")
            bl.set_markup(f'<span foreground="{BADGE.get(letter, "#e0af68")}" weight="bold">{letter}</span>')
            b.append(bl)
            name = Gtk.Label(label=os.path.basename(path), xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            name.set_width_chars(8)
            d = Gtk.Label(label=os.path.dirname(path), xalign=0, hexpand=True)
            d.set_width_chars(1)
            d.add_css_class("aether-hint")
            d.set_margin_start(0)
            d.set_ellipsize(Pango.EllipsizeMode.START)
            b.append(name)
            b.append(d)
            b.append(tool("Δ", "Show diff", lambda p=path, s=staged: self.show_diff(p, s)))
            if staged:
                b.append(tool("−", "Unstage", lambda p=path: self._git(["reset", "-q", "--", p], lambda *_: self.refresh())))
            else:
                b.append(tool("+", "Stage", lambda p=path: self._git(["add", "--", p], lambda *_: self.refresh())))
                if x != "?":
                    b.append(tool("↶", "Discard changes", lambda p=path: self.discard(p)))
            r.set_child(b)
            click = Gtk.GestureClick()
            click.connect("released", lambda g, n, x_, y_, p=path: self.win.open_path(os.path.join(self.root, p)))
            name.add_controller(click)
            self.list.append(r)

    def show_diff(self, path, staged):
        args = ["diff", "--no-color"] + (["--cached"] if staged else []) + ["--", path]
        def done(st, out):
            self.win.open_text_tab(f"{os.path.basename(path)}.diff", out or "(no textual diff)", "diff")
        self._git(args, done)

    def discard(self, path):
        dlg = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.WARNING,
                                text=f"Discard changes to {path}?", secondary_text="This cannot be undone.")
        dlg.add_button("Cancel", 0)
        dlg.add_button("Discard", 1)
        def resp(d, r):
            d.destroy()
            if r == 1:
                def done(*_):
                    for t in self.win.tabs():
                        if t.path == os.path.join(self.root, path) and not t.buffer.get_modified():
                            t.load(t.path)
                    self.refresh()
                self._git(["checkout", "--", path], done)
        dlg.connect("response", resp)
        dlg.present()

    def commit(self):
        m = self.msg.get_text().strip()
        if not m:
            self.win.flash("Write a commit message first")
            self.msg.grab_focus()
            return
        def done(st, out):
            if st == 0:
                self.msg.set_text("")
                self.win.flash("Committed: " + m)
            else:
                self.win.flash((out.strip().splitlines() or ["Commit failed"])[-1][:160])
            self.refresh()
        self._git(["commit", "-m", m], done)


class Sidebar(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.add_css_class("aether-island")
        self.add_css_class("side")
        sw = Gtk.Box(spacing=2)
        sw.add_css_class("aether-switch")
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.files, self.search, self.git = FilesPage(win), SearchPage(win), GitPage(win)
        self.outline, self.debug = OutlinePage(win), DebugPage(win)
        from .embeddedui import DevicePage
        self.device = DevicePage(win)
        first = None
        self.buttons = {}
        for name, label, page in (("files", "Files", self.files), ("search", "Search", self.search), ("git", "Git", self.git),
                                  ("outline", "Outline", self.outline), ("debug", "Debug", self.debug),
                                  ("device", "Device", self.device)):
            b = Gtk.ToggleButton(label=label)
            if first:
                b.set_group(first)
            else:
                first = b
            b.connect("toggled", lambda btn, n=name: btn.get_active() and self.show(n))
            sw.append(b)
            self.buttons[name] = b
            self.stack.add_named(page, name)
        self.switch = sw
        self.append(sw)
        self.append(self.stack)
        self.buttons["files"].set_active(True)

    def show(self, name):
        self.stack.set_visible_child_name(name)
        if not self.buttons[name].get_active():
            self.buttons[name].set_active(True)
        if name == "git":
            self.git.refresh()
        elif name == "search":
            self.search.entry.grab_focus()
        elif name == "outline":
            self.outline.set_tab(self.win.cur())
