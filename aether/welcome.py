"""Welcome screen (recent projects as cards, quick actions, shortcuts) plus the
New Project and Clone Repository dialogs."""
import os, shlex
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, GLib, Pango

from . import NAME, VERSION, project

SHORTCUTS = [("Command palette", "Ctrl+Shift+P"), ("Quick open file", "Ctrl+P"), ("Build project", "Ctrl+Shift+B"),
             ("Run", "F5"), ("Start debugging", "F6"), ("Toggle breakpoint", "F9"), ("Add next occurrence", "Ctrl+D"),
             ("Fold / unfold block", "Ctrl+Shift+[  ]"), ("Outline", "Ctrl+Alt+O")]


TIPS = ["Ctrl+D selects the word under the cursor — press again to add the next match as another cursor.",
        "Click the gutter (or press F9) to set a breakpoint, then F6 to debug.",
        "Ctrl+Shift+P opens the command palette — every action lives there.",
        "Alt+Click puts a cursor anywhere. Esc goes back to one.",
        "Ctrl+Shift+[ folds the block you're in. Ctrl+Alt+[ folds everything.",
        "Ctrl+K switches theme. Preferences → Theme Studio lets you make your own.",
        "Build errors are clickable — Ctrl+Shift+B, then click a red line.",
        "Type `main` + Enter in an empty file for a ready-to-run starter.",
        "Ctrl+Alt+O shows the outline of the current file.",
        "Override build / run / debug per project in .aether/project.json."]


def _home(p):
    h = os.path.expanduser("~")
    return "~" + p[len(h):] if p.startswith(h) else p


def _clear(box):
    c = box.get_first_child()
    while c:
        n = c.get_next_sibling()
        box.remove(c)
        c = n


class Welcome(Gtk.ScrolledWindow):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, spacing=0)
        outer.add_css_class("aether-welcome")
        outer.set_margin_top(36)
        outer.set_margin_bottom(36)
        outer.set_margin_start(24)
        outer.set_margin_end(24)
        self.set_child(outer)

        head = Gtk.Box(spacing=18)
        img = Gtk.Image.new_from_icon_name("aether")
        img.set_pixel_size(72)
        head.append(img)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        tl = Gtk.Box(spacing=10)
        t = Gtk.Label(label=NAME, xalign=0)
        t.add_css_class("title")
        tl.append(t)
        v = Gtk.Label(label=f"v{VERSION}", valign=Gtk.Align.END)
        v.add_css_class("aether-version")
        tl.append(v)
        tb.append(tl)
        sub = Gtk.Label(label="A fast IDE for Linux. Open a project, or start a new one.", xalign=0)
        sub.add_css_class("sub")
        tb.append(sub)
        head.append(tb)
        outer.append(head)

        actions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2,
                              column_spacing=10, row_spacing=10, homogeneous=True)
        actions.set_margin_top(28)
        for icon, title, desc, cb in (
                ("＋", "New project", "C, C++, Rust, Python, Go, web…", lambda: NewProjectDialog(win).present()),
                ("⌂", "Open folder", "Ctrl+Shift+O", lambda: win.act_open_folder()),
                ("⎇", "Clone repository", "git clone a URL", lambda: CloneDialog(win).present()),
                ("✎", "New file", "pick a language — Ctrl+N", lambda: win.act_new())):
            b = Gtk.Button()
            b.add_css_class("aether-action")
            bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            ic = Gtk.Label(label=icon, xalign=0)
            ic.add_css_class("aether-action-icon")
            bx.append(ic)
            l1 = Gtk.Label(label=title, xalign=0)
            l1.add_css_class("aether-action-title")
            bx.append(l1)
            l2 = Gtk.Label(label=desc, xalign=0)
            l2.add_css_class("aether-action-desc")
            bx.append(l2)
            b.set_child(bx)
            b.connect("clicked", lambda _b, cb=cb: cb())
            actions.append(b)
        outer.append(actions)

        self.tips = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=450, margin_top=18)
        for i, tip in enumerate(TIPS):
            l = Gtk.Label(xalign=0)
            l.set_markup(f'<span alpha="60%">TIP</span>   {GLib.markup_escape_text(tip)}')
            l.add_css_class("aether-tip")
            self.tips.add_named(l, str(i))
        outer.append(self.tips)
        self._tip = 0
        GLib.timeout_add_seconds(7, self._next_tip)

        cols = Gtk.Box(spacing=40, margin_top=30)
        outer.append(cols)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        cols.append(left)
        h = Gtk.Label(label="RECENT PROJECTS", xalign=0)
        h.add_css_class("aether-section")
        left.append(h)
        self.proj_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2, min_children_per_line=1,
                                    column_spacing=10, row_spacing=10, homogeneous=True)
        left.append(self.proj_box)
        h2 = Gtk.Label(label="RECENT FILES", xalign=0, margin_top=16)
        h2.add_css_class("aether-section")
        left.append(h2)
        self.file_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.append(self.file_box)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        cols.append(right)
        h3 = Gtk.Label(label="SHORTCUTS", xalign=0)
        h3.add_css_class("aether-section")
        right.append(h3)
        grid = Gtk.Grid(column_spacing=22, row_spacing=7)
        for i, (name, key) in enumerate(SHORTCUTS):
            a = Gtk.Label(label=name, xalign=0)
            a.add_css_class("dim-label")
            k = Gtk.Label(label=key, xalign=0)
            k.add_css_class("aether-key")
            grid.attach(a, 0, i, 1, 1)
            grid.attach(k, 1, i, 1, 1)
        right.append(grid)
        self.fill()

    def _next_tip(self):
        self._tip = (self._tip + 1) % len(TIPS)
        self.tips.set_visible_child_name(str(self._tip))
        return True

    def fill(self):
        _clear(self.proj_box)
        _clear(self.file_box)
        rec = [p for p in self.win.settings["recent"] if os.path.exists(p)]
        dirs = [p for p in rec if os.path.isdir(p)][:6]
        files = [p for p in rec if os.path.isfile(p)][:6]
        if not dirs:
            l = Gtk.Label(label="No projects yet — create one or open a folder.", xalign=0)
            l.add_css_class("dim-label")
            self.proj_box.append(l)
        for d in dirs:
            self.proj_box.append(self._card(d))
        if not files:
            l = Gtk.Label(label="Nothing yet", xalign=0)
            l.add_css_class("dim-label")
            self.file_box.append(l)
        for f in files:
            b = Gtk.Button(tooltip_text=f)
            b.add_css_class("link")
            b.set_has_frame(False)
            row = Gtk.Box(spacing=10)
            n = Gtk.Label(label=os.path.basename(f), xalign=0)
            row.append(n)
            d = Gtk.Label(label=_home(os.path.dirname(f)), xalign=0)
            d.add_css_class("dim-label")
            d.set_ellipsize(Pango.EllipsizeMode.START)
            row.append(d)
            b.set_child(row)
            b.set_halign(Gtk.Align.START)
            b.connect("clicked", lambda _b, f=f: self.win.open_path(f))
            self.file_box.append(b)

    def _card(self, path):
        kind, _t = project.detect(path)
        from .window import git_branch
        br = git_branch(path)
        b = Gtk.Button(tooltip_text=path)
        b.add_css_class("aether-card")
        bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        top = Gtk.Box(spacing=8)
        n = Gtk.Label(label=os.path.basename(path.rstrip("/")) or path, xalign=0, hexpand=True)
        n.add_css_class("aether-card-title")
        n.set_ellipsize(Pango.EllipsizeMode.END)
        top.append(n)
        if kind:
            k = Gtk.Label(label=kind)
            k.add_css_class("aether-chip")
            top.append(k)
        bx.append(top)
        meta = _home(path) + (f"   ⎇ {br}" if br else "")
        m = Gtk.Label(label=meta, xalign=0)
        m.add_css_class("aether-card-meta")
        m.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        bx.append(m)
        b.set_child(bx)
        b.connect("clicked", lambda *_: self.win.open_folder(path))
        return b


class _Dialog(Gtk.Window):
    def __init__(self, win, title):
        super().__init__(title=title, transient_for=win, modal=True)
        self.win = win
        self.set_default_size(560, -1)
        self.add_css_class("aether-prefs")
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(self.box, f"set_margin_{m}")(20)
        self.set_child(self.box)
        h = Gtk.Label(label=title, xalign=0)
        h.add_css_class("heading")
        self.box.append(h)
        kc = Gtk.EventControllerKey()
        kc.connect("key-pressed", lambda c, k, *_: (k == 0xff1b and (self.close() or True)) or False)
        self.add_controller(kc)

    def field(self, label, widget):
        r = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        l = Gtk.Label(label=label, xalign=0)
        l.add_css_class("dim-label")
        r.append(l)
        r.append(widget)
        self.box.append(r)
        return widget

    def location_row(self, default):
        row = Gtk.Box(spacing=6)
        e = Gtk.Entry(text=default, hexpand=True)
        row.append(e)
        b = Gtk.Button(label="Browse…")
        row.append(b)

        def pick(*_):
            dlg = Gtk.FileChooserNative.new("Choose a folder", self, Gtk.FileChooserAction.SELECT_FOLDER, "Choose", "Cancel")
            self._native = dlg

            def resp(d, r):
                if r == Gtk.ResponseType.ACCEPT and d.get_file():
                    e.set_text(d.get_file().get_path())
            dlg.connect("response", resp)
            dlg.show()
        b.connect("clicked", pick)
        self.field("Location", row)
        return e

    def buttons(self, ok_label, ok_cb):
        row = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=6)
        c = Gtk.Button(label="Cancel")
        c.connect("clicked", lambda *_: self.close())
        row.append(c)
        ok = Gtk.Button(label=ok_label)
        ok.add_css_class("suggested-action")
        ok.connect("clicked", lambda *_: ok_cb())
        row.append(ok)
        self.box.append(row)
        self.err = Gtk.Label(label="", xalign=0, wrap=True)
        self.err.add_css_class("error")
        self.box.append(self.err)
        return ok


def default_parent():
    for d in ("~/Projects", "~/projects", "~/Code", "~/code", "~/src", "~/dev"):
        if os.path.isdir(os.path.expanduser(d)):
            return os.path.expanduser(d)
    return os.path.expanduser("~/Projects")


class NewProjectDialog(_Dialog):
    def __init__(self, win):
        super().__init__(win, "New project")
        self.name = self.field("Project name", Gtk.Entry(text="my-project"))
        self.loc = self.location_row(default_parent())
        self.list = Gtk.ListBox()
        self.list.add_css_class("group")
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        for key, (label, desc, _files, _main) in project.TEMPLATES.items():
            row = Gtk.ListBoxRow()
            row._key = key
            bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, margin_top=5, margin_bottom=5)
            a = Gtk.Label(label=label, xalign=0)
            a.add_css_class("aether-card-title")
            bx.append(a)
            d = Gtk.Label(label=desc, xalign=0)
            d.add_css_class("dim-label")
            bx.append(d)
            row.set_child(bx)
            self.list.append(row)
        self.list.select_row(self.list.get_row_at_index(0))
        self.list.connect("row-activated", lambda *_: self.create())
        self.field("Template", self.list)
        gr = Gtk.Box(spacing=10)
        self.git = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
        gr.append(self.git)
        gr.append(Gtk.Label(label="Create a git repository"))
        self.box.append(gr)
        self.buttons("Create project", self.create)
        self.name.connect("activate", lambda *_: self.create())
        self.name.grab_focus()

    def create(self):
        row = self.list.get_selected_row()
        if not row:
            return
        try:
            root, main = project.create(self.loc.get_text(), self.name.get_text(), row._key, self.git.get_active())
        except OSError as e:
            self.err.set_text(str(e))
            return
        self.close()
        self.win.open_folder(root)
        self.win.open_path(main)
        self.win.flash(f"Created {os.path.basename(root)} — Ctrl+Shift+B builds, F5 runs, F6 debugs", 8000)


class CloneDialog(_Dialog):
    def __init__(self, win):
        super().__init__(win, "Clone repository")
        self.url = self.field("Repository URL", Gtk.Entry(placeholder_text="https://github.com/user/repo.git"))
        self.loc = self.location_row(default_parent())
        self.buttons("Clone", self.clone)
        self.url.connect("activate", lambda *_: self.clone())

    def clone(self):
        url = self.url.get_text().strip()
        if not url:
            self.err.set_text("Enter a repository URL")
            return
        name = os.path.basename(url.rstrip("/"))
        if name.endswith(".git"):
            name = name[:-4]
        parent = os.path.expanduser(self.loc.get_text().strip() or default_parent())
        dest = os.path.join(parent, name or "repo")
        if os.path.exists(dest):
            self.err.set_text(f"{dest} already exists")
            return
        os.makedirs(parent, exist_ok=True)
        self.close()
        win = self.win
        win.show_build_panel()
        win.build.run(f"Clone {name}", f"git clone --progress {shlex.quote(url)} {shlex.quote(dest)}", parent,
                      done=lambda ok: ok and win.open_folder(dest))
