import os, re, shlex, shutil, sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gtk, Gdk, GtkSource, GLib, Gio, Pango

try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte
except (ValueError, ImportError):
    Vte = None

from . import NAME, VERSION, data_dir, templates, runner, chrome, keys, gitutil
from .sidebar import Sidebar
from .extras import ExtrasMixin
from .ide import IdeMixin
from .welcome import Welcome
from . import icons
from .editor import EditorTab
from .palette import Palette, fuzzy
from .settings import CFG_DIR

IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", ".cache", ".idea", ".mypy_cache"}


def _lum(hexcolor):
    c = Gdk.RGBA()
    c.parse(hexcolor)
    return 0.2126 * c.red + 0.7152 * c.green + 0.0722 * c.blue


def _mix(hexcolor, other, t):
    a, b = Gdk.RGBA(), Gdk.RGBA()
    a.parse(hexcolor)
    b.parse(other)
    r, g, bl = (a.red * (1 - t) + b.red * t, a.green * (1 - t) + b.green * t, a.blue * (1 - t) + b.blue * t)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(bl * 255))


def _rgba(hexcolor, a):
    c = Gdk.RGBA()
    c.parse(hexcolor)
    return "rgba(%d,%d,%d,%.2f)" % (int(c.red * 255), int(c.green * 255), int(c.blue * 255), a)


def _families(font):
    names = [f.strip().strip("'\"") for f in font.split(",") if f.strip()]
    return ", ".join('"%s"' % n if n.lower() != "monospace" else "monospace" for n in names)


def git_branch(folder):
    d = folder
    for _ in range(6):
        if not d:
            return None
        head = os.path.join(d, ".git", "HEAD")
        if os.path.isfile(head):
            try:
                t = open(head).read().strip()
            except OSError:
                return None
            return t.split("/")[-1] if t.startswith("ref:") else t[:7]
        n = os.path.dirname(d)
        if n == d:
            break
        d = n
    return None


class AetherWindow(IdeMixin, ExtrasMixin, Gtk.ApplicationWindow):
    def __init__(self, app, settings):
        super().__init__(application=app, title=NAME)
        self.app = app
        self.settings = settings
        self.folder = None
        self.terms = []
        self.git_status = {}
        self.closed_paths = []
        self.lsp = {}
        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.set_default_size(1280, 800)
        self._setup_styles()
        self._build_ui()
        self._apply_font()
        self._setup_actions()
        self.apply_theme(self.settings["theme"])
        self.connect("close-request", self._on_close_request)
        self._flash_id = 0
        self._setup_drop()

    # ================= styles / themes =================
    def _setup_styles(self):
        mgr = GtkSource.StyleSchemeManager.get_default()
        mgr.append_search_path(os.path.join(data_dir(), "styles"))
        mgr.append_search_path(os.path.join(CFG_DIR, "styles"))
        smgr = GtkSource.SnippetManager.get_default()
        paths = list(smgr.get_search_path())
        smgr.set_search_path(paths + [os.path.join(data_dir(), "snippets"), os.path.join(CFG_DIR, "snippets")])
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        theme.add_search_path(os.path.join(data_dir(), "icons"))
        self.set_icon_name("aether")

    def theme_ids(self):
        mgr = GtkSource.StyleSchemeManager.get_default()
        ids = mgr.get_scheme_ids() or []
        mine = [i for i in ids if i.startswith("aether-")]
        return mine + [i for i in ids if i not in mine]

    def apply_theme(self, sid):
        mgr = GtkSource.StyleSchemeManager.get_default()
        scheme = mgr.get_scheme(sid) or mgr.get_scheme("Adwaita-dark") or mgr.get_scheme("classic")
        self.scheme = scheme
        self.settings["theme"] = scheme.get_id()
        for t in self.tabs():
            t.buffer.set_style_scheme(scheme)
        st = scheme.get_style("text")
        bg = (st.props.background if st and st.props.background_set else None) or "#1e1e1e"
        fg = (st.props.foreground if st and st.props.foreground_set else None) or "#d4d4d4"
        dark = chrome.lum(bg) < 0.5
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", dark)
        Gtk.Settings.get_default().set_property("gtk-cursor-blink", bool(self.settings["cursor_blink"]))
        afs = scheme.get_style("def:function")
        hint = (afs.props.foreground if afs and afs.props.foreground_set else None) or "#7aa2f7"
        self.pal = chrome.palette(bg, fg, dark, hint, self.settings)
        self.accent = self.pal["accent"]
        css = chrome.build_css(self.pal, self.settings)
        try:
            self.css.load_from_string(css)
        except AttributeError:
            self.css.load_from_data(css.encode())
        self._apply_font()
        self._theme_term(fg, bg)
        for t in self.tabs():
            t.apply_prefs()

    def apply_look(self):
        """Re-apply theme + chrome after a preference changed."""
        self.apply_theme(self.settings["theme"])
        self.apply_layout()

    def cycle_pref(self, key, options):
        cur = self.settings[key]
        self.settings[key] = options[(options.index(cur) + 1) % len(options)] if cur in options else options[0]
        self.apply_look()
        self.flash(f"{key.replace('_', ' ').title()}: {self.settings[key]}")

    def cycle_theme(self):
        ids = self.theme_ids()
        cur = self.settings["theme"]
        self.apply_theme(ids[(ids.index(cur) + 1) % len(ids)] if cur in ids else ids[0])
        self.flash("Theme: " + self.scheme.get_name())

    def apply_layout(self):
        """Structural layout options (sidebar side, panel position, header, status bar). Cheap when unchanged."""
        s = self.settings
        if getattr(self, "_zen", False):
            return
        sig = (s["sidebar_side"], s["panel_position"])
        if sig != getattr(self, "_layout_sig", None):
            self._layout_sig = sig
            right = s["sidebar_side"] == "right"
            self.outer.set_start_child(None)
            self.outer.set_end_child(None)
            if right:
                self.outer.set_start_child(self.vpane)
                self.outer.set_end_child(self.sidebar)
                self.outer.set_resize_start_child(True)
                self.outer.set_resize_end_child(False)
                self.outer.set_shrink_end_child(False)
            else:
                self.outer.set_start_child(self.sidebar)
                self.outer.set_end_child(self.vpane)
                self.outer.set_resize_start_child(False)
                self.outer.set_resize_end_child(True)
            wd = self.get_width() or 1200
            self.outer.set_position(wd - 280 if right else 280)
            side = s["panel_position"] == "right"
            self.vpane.set_orientation(Gtk.Orientation.HORIZONTAL if side else Gtk.Orientation.VERTICAL)
            self.panel.set_size_request(280 if side else -1, -1 if side else 110)
            ht = self.get_height() or 800
            self.vpane.set_position(int((wd - 280) * 0.62) if side else max(200, int((self.vpane.get_height() or ht - 100) * 0.68)))
        self.statusbar.set_visible(bool(s["show_statusbar"]))
        plain = s["header_style"] == "title"
        if plain:
            self.pill_label.set_text(os.path.basename(self.folder) if self.folder else NAME)
        elif self.folder:
            self.pill_label.set_text(os.path.basename(self.folder) + " — search files, commands, symbols")
        else:
            self.pill_label.set_text("Search files, commands, symbols")
        (self.pill.add_css_class if plain else self.pill.remove_css_class)("plain")
        self.pillkey.set_visible(not plain)
        if not s["breadcrumbs"]:
            self.crumb.set_visible(False)

    def _theme_term(self, fg, bg):
        f, b = Gdk.RGBA(), Gdk.RGBA()
        f.parse(fg)
        b.parse(bg)
        b.alpha = self.pal["op"]
        for term in self.terms:
            try:
                term.set_colors(f, b, [])
            except Exception:
                pass

    def theme_items(self):
        mgr = GtkSource.StyleSchemeManager.get_default()
        out = []
        for i in self.theme_ids():
            sc = mgr.get_scheme(i)
            out.append((sc.get_name(), "theme", (lambda i=i: self.apply_theme(i))))
        return out

    # ================= UI =================
    def _build_ui(self):
        hb = Gtk.HeaderBar()
        self.set_titlebar(hb)
        hb.set_show_title_buttons(True)
        side_btn = icons.icon_button("sidebar", tooltip="Toggle sidebar (Ctrl+B)", size=17)
        side_btn.set_action_name("win.toggle_sidebar")
        hb.pack_start(side_btn)
        term_btn = icons.icon_button("terminal", tooltip="Toggle panel (Ctrl+`)", size=17)
        term_btn.set_action_name("win.toggle_panel")
        hb.pack_start(term_btn)
        pill = Gtk.Button()
        self.pill = pill
        pill.set_action_name("win.palette")
        pill.add_css_class("aether-pill")
        pb = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        self.pill_label = Gtk.Label(label="Search files, commands, symbols")
        pk = Gtk.Label(label="Ctrl+Shift+P")
        pk.add_css_class("aether-key")
        self.pillkey = pk
        pb.append(self.pill_label)
        pb.append(pk)
        pill.set_child(pb)
        hb.set_title_widget(pill)

        menu = Gio.Menu()
        sec = Gio.Menu()
        for lbl, act in (("New file…", "win.new"), ("Open file…", "win.open"), ("Open folder…", "win.open_folder")):
            sec.append(lbl, act)
        menu.append_section(None, sec)
        sec = Gio.Menu()
        for lbl, act in (("Command palette", "win.palette"), ("Quick open file", "win.quick_open"), ("Go to symbol…", "win.goto_symbol"),
                         ("Go to line…", "win.goto"), ("Find", "win.find"), ("Search in project", "win.find_in_files")):
            sec.append(lbl, act)
        menu.append_section(None, sec)
        sec = Gio.Menu()
        for lbl, act in (("New project…", "win.new_project"), ("Clone repository…", "win.clone"), ("Build project", "win.build"),
                         ("Project tasks…", "win.tasks"), ("Start debugging", "win.debug"), ("Project settings", "win.project_settings")):
            sec.append(lbl, act)
        menu.append_section(None, sec)
        sec = Gio.Menu()
        for lbl, act in (("Save", "win.save"), ("Save as…", "win.save_as"), ("Format document", "win.format"),
                         ("Split editor", "win.split"), ("Toggle comment", "win.comment"), ("Insert starter template", "win.starter")):
            sec.append(lbl, act)
        menu.append_section(None, sec)
        sec = Gio.Menu()
        for lbl, act in (("Preferences…", "win.preferences"), ("Theme studio…", "win.theme_studio"), ("Change theme…", "win.themes"),
                         ("Zen mode", "win.zen"), ("Toggle terminal / panel", "win.toggle_panel"), ("Toggle minimap", "win.toggle_minimap"),
                         ("About", "win.about"), ("Quit", "win.quit")):
            sec.append(lbl, act)
        menu.append_section(None, sec)
        hb.pack_end(Gtk.MenuButton(label="≡", menu_model=menu, tooltip_text="Menu"))
        # Code::Blocks-style build toolbar:  [Debug ▾] [Build] [Stop] [Debug] [Run]
        run = icons.icon_button("run", "Run", "Build if needed and run (F5)", 14)
        run.set_action_name("win.run")
        run.add_css_class("aether-run")
        hb.pack_end(run)
        dbg = icons.icon_button("bug", "Debug", "Start debugging (F6) — breakpoints with F9", 16)
        dbg.set_action_name("win.debug")
        dbg.add_css_class("aether-tool")
        hb.pack_end(dbg)
        self.stop_btn = icons.icon_button("stop", None, "Stop the build / debugger (Shift+F6)", 14)
        self.stop_btn.connect("clicked", lambda *_: self.stop_everything())
        self.stop_btn.add_css_class("aether-tool")
        self.stop_btn.add_css_class("aether-stop")
        self.stop_btn.set_sensitive(False)
        hb.pack_end(self.stop_btn)
        bld = icons.icon_button("build", "Build", "Build the project (Ctrl+Shift+B)", 16)
        bld.set_action_name("win.build")
        bld.add_css_class("aether-tool")
        hb.pack_end(bld)
        self.config_dd = Gtk.DropDown.new_from_strings(["Debug", "Release"])
        self.config_dd.set_tooltip_text("Build configuration")
        self.config_dd.add_css_class("aether-config")
        self.config_dd.set_selected(1 if self.settings["build_config"] == "Release" else 0)
        self.config_dd.connect("notify::selected", lambda dd, _p: self.set_build_config(["Debug", "Release"][dd.get_selected()]))
        hb.pack_end(self.config_dd)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)
        body = Gtk.Box()
        body.add_css_class("aether-body")
        body.set_vexpand(True)
        self.body = body
        root.append(body)
        self.outer = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.outer.set_hexpand(True)
        self.outer.set_wide_handle(True)
        self.outer.set_shrink_start_child(False)
        self.outer.set_shrink_end_child(False)
        body.append(self.outer)

        self.sidebar = Sidebar(self)
        self.sidebar.set_size_request(250, -1)
        self.sidebar.set_overflow(Gtk.Overflow.HIDDEN)
        self.outer.set_start_child(self.sidebar)
        self.outer.set_position(280)
        self.outer.set_resize_start_child(False)

        self.vpane = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.vpane.set_wide_handle(True)
        self.vpane.set_shrink_start_child(False)
        self.vpane.set_shrink_end_child(False)
        self.outer.set_end_child(self.vpane)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top.add_css_class("aether-island")
        top.set_overflow(Gtk.Overflow.HIDDEN)
        self.editor_island = top
        self.vpane.set_start_child(top)
        self.vpane.set_resize_start_child(True)
        self._build_findbar(top)
        self.crumb = Gtk.Label(label="", xalign=0)
        self.crumb.add_css_class("aether-crumb")
        self.crumb.set_ellipsize(Pango.EllipsizeMode.START)
        self.crumb.set_visible(False)
        top.append(self.crumb)
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(180)
        self.toast_overlay = Gtk.Overlay()
        self.toast_overlay.set_child(self.stack)
        self.toast_overlay.set_vexpand(True)
        top.append(self.toast_overlay)
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.connect("switch-page", self._on_switch)
        self.notebook.connect("page-removed", lambda *_: self._after_tabs_changed())
        self.stack.add_named(self.notebook, "editor")
        self.welcome = Welcome(self)
        self.stack.add_named(self.welcome, "welcome")
        self.stack.set_visible_child_name("welcome")

        self.panel = Gtk.Notebook()
        self.panel.add_css_class("aether-island")
        self.panel.add_css_class("aether-bottom")
        self.panel.set_size_request(-1, 110)
        self.panel.set_overflow(Gtk.Overflow.HIDDEN)
        self.vpane.set_end_child(self.panel)
        self.vpane.set_resize_end_child(False)
        if Vte:
            plus = Gtk.Button(label="+", tooltip_text="New terminal (Ctrl+Shift+`)")
            plus.connect("clicked", lambda *_: self.new_terminal())
            self.panel.set_action_widget(plus, Gtk.PackType.END)
            plus.show()
        self.problems = Gtk.ListBox()
        self.problems.connect("row-activated", self._on_problem)
        psw = Gtk.ScrolledWindow()
        psw.set_child(self.problems)
        self.problems_label = Gtk.Label(label="Problems")
        self.panel.append_page(psw, self.problems_label)
        self.output = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
        self.output.set_left_margin(10)
        self.output.set_top_margin(6)
        osw = Gtk.ScrolledWindow()
        osw.set_child(self.output)
        self.output_sw = osw
        self.panel.append_page(osw, Gtk.Label(label="Output"))
        self.vpane.set_position(int(self.settings["panel_pos"] or 500))     # remembered between sessions

        sb = Gtk.Box(spacing=14)
        self.statusbar = sb
        sb.add_css_class("aether-status")
        self.branch_label = Gtk.Label(label="")
        self.msg = Gtk.Label(label="", xalign=0)
        self.msg.set_hexpand(True)
        self.msg.set_ellipsize(Pango.EllipsizeMode.END)
        self.lsp_label = Gtk.Label(label="")
        self.diag_label = Gtk.Label(label="")
        self.pos_label = Gtk.Label(label="")
        self.indent_label = Gtk.Label(label="")
        self.enc_label = Gtk.Label(label="")
        self.lang_label = Gtk.Label(label="")
        self.lang_label.add_css_class("aether-chip")
        self.lang_label.set_visible(False)
        sb.append(self.lang_label)
        sb.append(self.branch_label)
        sb.append(self.msg)
        for w in (self.lsp_label, self.diag_label, self.pos_label, self.indent_label, self.enc_label):
            sb.append(w)
        root.append(sb)
        self._ide_setup()
        self.sidebar.set_visible(bool(self.settings["sidebar"]))
        self.panel.set_visible(bool(self.settings["terminal"]))
        self._layout_sig = ("left", "bottom")
        GLib.idle_add(lambda: (self.apply_layout(), False)[1])
        if Vte:
            GLib.idle_add(lambda: (self.new_terminal(), False)[1])

    def _fill_recent(self):
        if hasattr(self, "welcome"):
            self.welcome.fill()

    def _remember(self, path):
        rec = [p for p in self.settings["recent"] if p != path]
        self.settings["recent"] = ([path] + rec)[:12]
        self._fill_recent()

    def _build_findbar(self, parent):
        self.search_settings = GtkSource.SearchSettings()
        self.search_settings.set_wrap_around(True)
        self.findbar = Gtk.SearchBar()
        box = Gtk.Box(spacing=6)
        self.find_entry = Gtk.SearchEntry()
        self.find_entry.set_placeholder_text("Find")
        self.find_entry.set_hexpand(True)
        self.repl_entry = Gtk.Entry()
        self.repl_entry.set_placeholder_text("Replace")
        self.repl_entry.set_hexpand(True)
        self.count_label = Gtk.Label(label="")
        self.case_btn = Gtk.ToggleButton(label="Aa", tooltip_text="Match case")
        self.regex_btn = Gtk.ToggleButton(label=".*", tooltip_text="Regular expression")
        prev = Gtk.Button(icon_name="go-up-symbolic")
        nxt = Gtk.Button(icon_name="go-down-symbolic")
        rep = Gtk.Button(label="Replace")
        repa = Gtk.Button(label="All")
        for w in (self.find_entry, self.count_label, self.case_btn, self.regex_btn, prev, nxt, self.repl_entry, rep, repa):
            box.append(w)
        self.findbar.set_child(box)
        self.findbar.connect_entry(self.find_entry)
        self.findbar.set_key_capture_widget(None)
        parent.append(self.findbar)
        self.find_entry.connect("search-changed", self._find_changed)
        self.find_entry.connect("activate", lambda *_: self.find_next(False))
        self.find_entry.connect("next-match", lambda *_: self.find_next(False))
        self.find_entry.connect("previous-match", lambda *_: self.find_next(True))
        self.case_btn.connect("toggled", lambda b: self.search_settings.set_case_sensitive(b.get_active()))
        self.regex_btn.connect("toggled", lambda b: self.search_settings.set_regex_enabled(b.get_active()))
        prev.connect("clicked", lambda *_: self.find_next(True))
        nxt.connect("clicked", lambda *_: self.find_next(False))
        rep.connect("clicked", lambda *_: self.replace_one())
        repa.connect("clicked", lambda *_: self.replace_all())
        self.repl_entry.connect("activate", lambda *_: self.replace_one())
        self.findbar.connect("notify::search-mode-enabled", lambda b, _p: (not b.get_search_mode()) and self._focus_editor())

    # ================= actions =================
    def _callbacks(self):
        cur = lambda: self.cur()
        return {**self._ide_callbacks(),
            "new": self.act_new, "open": self.act_open, "open_folder": self.act_open_folder, "save": self.act_save,
            "save_as": self.act_save_as, "close_tab": self.act_close_tab, "reopen_tab": lambda *_: self.reopen_tab(),
            "quit": lambda *_: self.close(), "run": self.act_run, "find": lambda *_: self.show_find(False),
            "replace": lambda *_: self.show_find(True), "find_in_files": lambda *_: self.show_search(),
            "goto": self.act_goto, "goto_symbol": lambda *_: self.act_goto_symbol(), "palette": self.act_palette,
            "quick_open": self.act_quick_open, "themes": self.act_themes,
            "comment": lambda *_: cur() and cur().toggle_comment(), "dup": lambda *_: cur() and cur().duplicate_line(),
            "starter": self.act_starter, "format": lambda *_: self.format_document(),
            "toggle_sidebar": lambda *_: self.toggle("sidebar", self.sidebar),
            "toggle_panel": lambda *_: self.toggle("terminal", self.panel),
            "toggle_minimap": lambda *_: self.set_pref("minimap", not self.settings["minimap"]),
            "toggle_wrap": lambda *_: self.set_pref("word_wrap", not self.settings["word_wrap"]),
            "zoom_in": lambda *_: self.zoom(1), "zoom_out": lambda *_: self.zoom(-1), "zoom_reset": lambda *_: self.zoom(0),
            "open_settings": self.act_open_settings, "about": self.act_about,
            "next_tab": lambda *_: self.notebook.next_page(), "prev_tab": lambda *_: self.notebook.prev_page(),
            "split": lambda *_: cur() and cur().toggle_split(), "zen": lambda *_: self.toggle_zen(),
            "new_terminal": lambda *_: self.new_terminal(), "focus_term": lambda *_: self.focus_terminal(),
            "show_files": lambda *_: self.show_sidebar("files"), "show_git": lambda *_: self.show_sidebar("git"),
            "preferences": lambda *_: self.show_preferences(), "theme_studio": lambda *_: self.show_studio(),
            "definition": lambda *_: self.lsp_definition(), "hover": lambda *_: self.lsp_hover(),
            "complete": lambda *_: self.lsp_complete(), "references": lambda *_: self.lsp_references(),
            "rename_symbol": lambda *_: self.lsp_rename(), "import_theme": lambda *_: self.import_vscode_theme(),
            "open_snippets": lambda *_: self.open_snippets_dir(),
            "move_up": lambda *_: cur() and cur().move_lines(-1), "move_down": lambda *_: cur() and cur().move_lines(1),
            "delete_line": lambda *_: cur() and cur().delete_lines(), "join_lines": lambda *_: cur() and cur().join_lines(),
            "sort_lines": lambda *_: cur() and cur().sort_lines(), "sort_lines_desc": lambda *_: cur() and cur().sort_lines(True),
            "upper_case": lambda *_: cur() and cur().change_case("upper"), "lower_case": lambda *_: cur() and cur().change_case("lower"),
            "title_case": lambda *_: cur() and cur().change_case("title"), "trim_ws": lambda *_: cur() and cur().trim_whitespace(),
            "cycle_layout": lambda *_: self.cycle_pref("layout", ["islands", "classic", "flat", "floating"]),
            "cycle_theme": lambda *_: self.cycle_theme(),
            "toggle_statusbar": lambda *_: self.set_pref("show_statusbar", not self.settings["show_statusbar"]),
            "toggle_line_numbers": lambda *_: self.set_pref("show_line_numbers", not self.settings["show_line_numbers"]),
        }

    def _setup_actions(self):
        self._cbs = self._callbacks()
        for name, cb in self._cbs.items():
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
        self.reload_keys()

    def reload_keys(self):
        eff = keys.effective(self.settings)
        for name in self._cbs:
            self.app.set_accels_for_action("win." + name, eff.get(name, []))

    def _setup_drop(self):
        try:
            dt = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
            dt.connect("drop", lambda t, val, x, y: [self.open_path(f.get_path()) for f in val.get_files()] and True)
            self.add_controller(dt)
        except Exception:
            pass

    # ================= helpers =================
    def tabs(self):
        return [self.notebook.get_nth_page(i) for i in range(self.notebook.get_n_pages())]

    def cur(self):
        i = self.notebook.get_current_page()
        return self.notebook.get_nth_page(i) if i >= 0 else None

    def flash(self, text, ms=5000):
        self.msg.set_text(text)
        if self._flash_id:
            GLib.source_remove(self._flash_id)
        self._flash_id = GLib.timeout_add(ms, lambda: (self.msg.set_text(""), setattr(self, "_flash_id", 0), False)[2])

    def _focus_editor(self):
        t = self.cur()
        if t:
            t.view.grab_focus()

    def toggle(self, key, widget):
        v = not widget.get_visible()
        widget.set_visible(v)
        self.settings[key] = v

    def show_panel(self, page=None):
        self.panel.set_visible(True)
        self.settings["terminal"] = True
        if page is not None:
            self.panel.set_current_page(page)

    def set_pref(self, key, val):
        self.settings[key] = val
        for t in self.tabs():
            t.apply_prefs()

    def zoom(self, d):
        s = self.settings
        size = 12 if d == 0 else max(6, min(48, int(s["font_size"]) + d))
        s["font_size"] = size
        self._apply_font()

    def _apply_font(self):
        st = self.settings
        feat = '"calt" 1, "liga" 1' if st["ligatures"] else '"calt" 0, "liga" 0'
        css = (f"textview.aether-code, .aether-bottom textview {{ font-family: {chrome.families(st['font'])}; "
               f"font-size: {st['font_size']}pt; font-feature-settings: {feat}; }}")
        if not hasattr(self, "fontcss"):
            self.fontcss = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.fontcss, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            self.alphacss = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.alphacss, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 3)
        self._load(self.fontcss, css)
        op = float(st["opacity"])
        if op < 0.999 and hasattr(self, "pal"):
            self._load(self.alphacss, f"textview.aether-code, textview.aether-code text {{ background-color: {chrome.rgba(self.pal['bg'], op)}; }} "
                                       "textview.aether-code gutter { background-color: transparent; }")
        else:
            self._load(self.alphacss, "")
        for term in self.terms:
            term.set_font(Pango.FontDescription(f"{st['font']} {st['font_size']}"))
        for t in self.tabs():
            t.folding.refresh_metrics()
            t.view.queue_resize()
            t.view.queue_draw()

    @staticmethod
    def _load(provider, css):
        try:
            provider.load_from_string(css)
        except AttributeError:
            provider.load_from_data(css.encode())

    # ================= tabs =================
    def add_tab(self, tab, activate=True):
        tab.buffer.set_style_scheme(self.scheme)
        label = Gtk.Box(spacing=6)
        tab._icon = icons.file_image(tab.path or tab.title, 16)
        tab._icon_key = tab.path or tab.title
        label.append(tab._icon)
        lbl = Gtk.Label(label=tab.title)
        btn = Gtk.Button(icon_name="window-close-symbolic")
        btn.set_has_frame(False)
        label.append(lbl)
        label.append(btn)
        tab._label = lbl
        btn.connect("clicked", lambda *_: self.close_tab(tab))
        idx = self.notebook.append_page(tab, label)
        self.notebook.set_tab_reorderable(tab, True)
        tab.connect("state-changed", self._on_tab_state)
        tab.connect("diagnostics", self._on_tab_diags)
        self._ide_tab_added(tab)
        if activate:
            self.notebook.set_current_page(idx)
        self.stack.set_visible_child_name("editor")
        GLib.idle_add(lambda: (tab.view.grab_focus(), False)[1])   # must return False or it re-grabs forever
        return tab

    def _after_tabs_changed(self):
        if self.notebook.get_n_pages() == 0:
            self.stack.set_visible_child_name("welcome")
            self.pos_label.set_text("")
            self.lang_label.set_text("")
            self.lang_label.set_visible(False)
            self.indent_label.set_text("")
            self.enc_label.set_text("")
            self.lsp_label.set_text("")
            self.diag_label.set_text("")
            self.crumb.set_visible(False)
            self._refresh_problems()
            self._update_title()
            self._ide_tab_state(None)

    def _on_switch(self, nb, page, idx):
        GLib.idle_add(self._on_tab_state, page)
        GLib.idle_add(self._refresh_problems)
        GLib.idle_add(self._rebind_search)

    def _on_tab_state(self, tab, *_):
        if tab is not self.cur() and tab is not None and not isinstance(tab, EditorTab):
            return
        t = self.cur()
        for tb in self.tabs():
            mod = "● " if tb.buffer.get_modified() else ""
            tb._label.set_text(mod + tb.title)
            key = tb.path or tb.title
            if getattr(tb, "_icon_key", key) != key:
                tb._icon_key = key
                tex = icons.file_texture(key)
                if tex:
                    tb._icon.set_from_paintable(tex)
        if t:
            l, c = t.position()
            self.pos_label.set_text(f"Ln {l}, Col {c}")
            name = t.language.get_name() if t.language else "Plain Text"
            self.lang_label.set_text(name)
            self.lang_label.set_visible(True)
            style = "Spaces" if t.view.get_insert_spaces_instead_of_tabs() else "Tabs"
            self.indent_label.set_text(f"{style}: {t.view.get_tab_width()}")
            self.enc_label.set_text("UTF-8  " + ("CRLF" if getattr(t, "crlf", False) else "LF"))
            self.lsp_label.set_text(self.lsp_status(t))
            ne = sum(1 for d in t.diags if d["sev"] == "error")
            nw = len(t.diags) - ne
            self.diag_label.set_text(f"✖ {ne}   ⚠ {nw}" if t.diags else "✔ no problems" if self.settings["lint"] and t.tkey else "")
            if t.path:
                rel = os.path.relpath(t.path, self.folder) if self.folder and t.path.startswith(self.folder) else t.path
                self.crumb.set_text("  ›  ".join(rel.strip("/").split("/")))
            else:
                self.crumb.set_text(t.title + "  (unsaved)")
            self.crumb.set_visible(bool(self.settings["breadcrumbs"]))
        self._ide_tab_state(t)
        self._update_title()
        return False

    def _update_title(self):
        t = self.cur()
        if t:
            self.set_title(f"{'● ' if t.buffer.get_modified() else ''}{t.title}")
        else:
            self.set_title(NAME)

    def open_path(self, path, line=None, col=None):
        if not path:
            return
        path = os.path.abspath(path)
        if os.path.isdir(path):
            self.open_folder(path)
            return
        for t in self.tabs():
            if t.path == path:
                self.notebook.set_current_page(self.notebook.page_num(t))
                if line:
                    GLib.idle_add(lambda: (t.goto(line, col), False)[1])
                return t
        tab = EditorTab(self, None)
        try:
            tab.load(path)
        except OSError as e:
            self.flash(f"Cannot open {path}: {e}")
            return None
        self.add_tab(tab)
        self._remember(path)
        if line:
            GLib.idle_add(lambda: (tab.goto(line, col), False)[1])
        return tab

    def close_tab(self, tab, force=False):
        if tab.buffer.get_modified() and not force:
            self.confirm([tab], lambda ok: ok and self.close_tab(tab, True))
            return
        idx = self.notebook.page_num(tab)
        if tab.path:
            self.closed_paths.append(tab.path)
            self.lsp_close(tab)
        if idx >= 0:
            self.notebook.remove_page(idx)

    def confirm(self, tabs, done):
        names = ", ".join(t.title for t in tabs)
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                text=f"Save changes to {names}?", secondary_text="Your changes will be lost if you don't save.")
        dlg.add_button("Cancel", 0)
        dlg.add_button("Discard", 1)
        dlg.add_button("Save", 2)

        def resp(d, r):
            d.destroy()
            if r == 2:
                for t in tabs:
                    if not (t.save() if t.path else self.save_as_sync(t)):
                        return
                done(True)
            elif r == 1:
                done(True)
        dlg.connect("response", resp)
        dlg.present()

    def _on_close_request(self, *_):
        s = self.settings
        s["session"] = {"folder": self.folder, "files": [t.path for t in self.tabs() if t.path],
                        "active": max(0, self.notebook.get_current_page())}
        s["sidebar"] = self.sidebar.get_visible()
        if self.settings["panel_position"] == "bottom" and self.panel.get_visible():
            s["panel_pos"] = self.vpane.get_position()
        self.ide_shutdown()
        dirty = [t for t in self.tabs() if t.buffer.get_modified()]
        if not dirty or getattr(self, "_force_close", False):
            self.lsp_shutdown_all()
        if dirty and not getattr(self, "_force_close", False):
            def done(ok):
                self._force_close = True
                self.close()
            self.confirm(dirty, done)
            return True
        return False

    # ================= file actions =================
    def act_new(self, *_):
        items = []
        for k in ("c", "cpp", "python", "rust", "go", "java", "javascript", "typescript", "shellscript", "csharp",
                  "kotlin", "lua", "ruby", "php", "html", "zig", "swift", "dart", "haskell", "elixir", "julia", "r",
                  "perl", "scala", "css", "sql", "makefile", "dockerfile", "markdown", "json", "yaml", "toml"):
            items.append((templates.PRETTY[k], "new file", (lambda k=k: self.new_untitled(k))))
        Palette(self, "New file — pick a language", items).present()

    def new_untitled(self, key):
        tab = EditorTab(self, None, suggest_key=key)
        n = sum(1 for t in self.tabs() if t.path is None) + 1
        ext = templates.KEY_EXT.get(key, "")
        tab.untitled_name = ("main" if n == 1 else f"untitled{n}") + ext if ext.startswith(".") else ext
        tab.apply_language()
        self.add_tab(tab)
        if self.settings["starter_on_new_file"] and key not in templates.NO_AUTO:
            tab.insert_starter(key)
        tab.buffer.set_modified(False)
        self._on_tab_state(tab)

    def _chooser(self, title, action, accept, cb, name=None, folder=None):
        dlg = Gtk.FileChooserNative.new(title, self, action, accept, "Cancel")
        if folder:
            dlg.set_current_folder(Gio.File.new_for_path(folder))
        if name:
            dlg.set_current_name(name)
        dlg.set_modal(True)
        self._native = dlg

        def resp(d, r):
            if r == Gtk.ResponseType.ACCEPT:
                f = d.get_file()
                if f:
                    cb(f.get_path())
        dlg.connect("response", resp)
        dlg.show()

    def act_open(self, *_):
        self._chooser("Open file", Gtk.FileChooserAction.OPEN, "Open", self.open_path, folder=self.folder)

    def act_open_folder(self, *_):
        self._chooser("Open folder", Gtk.FileChooserAction.SELECT_FOLDER, "Open", self.open_folder)

    def act_save(self, *_):
        t = self.cur()
        if not t:
            return
        if t.path:
            def do():
                if t.save():
                    self.flash(f"Saved {t.title}", 2000)
                    self.refresh_git_soon()
            if self.settings["format_on_save_tool"] and t.tkey:
                self.format_document(after=do)
            else:
                do()
        else:
            self.act_save_as()

    def act_save_as(self, *_):
        t = self.cur()
        if not t:
            return
        self._chooser("Save as", Gtk.FileChooserAction.SAVE, "Save", lambda p: self._save_to(t, p),
                      name=t.title, folder=self.folder)

    def save_as_sync(self, tab):
        self.notebook.set_current_page(self.notebook.page_num(tab))
        self.act_save_as()
        return False

    def _save_to(self, tab, path):
        if tab.save(path):
            self.flash(f"Saved {os.path.basename(path)}", 2000)
            tab._label.set_text(tab.title)
            self._on_tab_state(tab)
            if self.folder and path.startswith(self.folder):
                self.refresh_tree()

    def act_close_tab(self, *_):
        t = self.cur()
        if t:
            self.close_tab(t)

    # ================= find / replace =================
    def show_find(self, replace):
        self.findbar.set_search_mode(True)
        t = self.cur()
        if t and t.buffer.get_has_selection():
            s, e = t.buffer.get_selection_bounds()
            txt = t.buffer.get_text(s, e, False)
            if "\n" not in txt:
                self.find_entry.set_text(txt)
        (self.repl_entry if replace else self.find_entry).grab_focus()
        self._rebind_search()

    def _rebind_search(self):
        t = self.cur()
        self._ctx = None
        if t:
            self._ctx = GtkSource.SearchContext.new(t.buffer, self.search_settings)
            self._ctx.set_highlight(True)
            self._ctx.connect("notify::occurrences-count", self._count)
            self._count()
        return False

    def _count(self, *_):
        if not getattr(self, "_ctx", None) or not self.find_entry.get_text():
            self.count_label.set_text("")
            return
        n = self._ctx.get_occurrences_count()
        self.count_label.set_text("…" if n < 0 else (f"{n} found" if n else "no results"))

    def _find_changed(self, *_):
        self.search_settings.set_search_text(self.find_entry.get_text() or None)
        self._rebind_search()
        self.find_next(False, from_start=True)

    def find_next(self, backward, from_start=False):
        t = self.cur()
        ctx = getattr(self, "_ctx", None)
        if not t or not ctx or not self.find_entry.get_text():
            return
        b = t.buffer
        if backward:
            s, e = (b.get_selection_bounds() or (b.get_iter_at_mark(b.get_insert()),) * 2)
            ok, ms, me, _w = ctx.backward(s)
        else:
            s, e = (b.get_selection_bounds() or (b.get_iter_at_mark(b.get_insert()),) * 2)
            start = s if from_start else e
            ok, ms, me, _w = ctx.forward(start)
        if ok:
            b.select_range(ms, me)
            t.view.scroll_to_iter(ms, 0.2, True, 0.5, 0.4)

    def replace_one(self):
        t = self.cur()
        ctx = getattr(self, "_ctx", None)
        if not t or not ctx:
            return
        b = t.buffer
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            try:
                ctx.replace(s, e, self.repl_entry.get_text(), -1)
            except GLib.Error as err:
                self.flash(str(err))
        self.find_next(False)

    def replace_all(self):
        ctx = getattr(self, "_ctx", None)
        if ctx:
            try:
                n = ctx.replace_all(self.repl_entry.get_text(), -1)
                self.flash(f"Replaced {n} occurrence(s)")
            except GLib.Error as err:
                self.flash(str(err))

    def act_goto(self, *_):
        t = self.cur()
        if not t:
            return

        def go(txt):
            m = re.match(r"\s*(\d+)(?::(\d+))?", txt)
            if m:
                t.goto(int(m.group(1)), int(m.group(2)) if m.group(2) else None)
        Palette(self, "Go to line[:column]", on_text=go).present()

    # ================= palette =================
    def act_palette(self, *_):
        c = self._cbs
        eff = keys.effective(self.settings)
        def k(name):
            a = eff.get(name) or []
            if not a:
                return ""
            ok, key, mods = Gtk.accelerator_parse(a[0])
            return Gtk.accelerator_get_label(key, mods) if ok else ""
        cmds = [("New file…", "new"), ("Open file…", "open"), ("Open folder…", "open_folder"), ("Save", "save"), ("Save as…", "save_as"),
                ("Run file", "run"), ("Quick open file", "quick_open"), ("Go to symbol…", "goto_symbol"), ("Go to line…", "goto"),
                ("Search in project", "find_in_files"), ("Find", "find"), ("Replace", "replace"), ("Format document", "format"),
                ("Split editor", "split"), ("Zen mode", "zen"), ("Change theme…", "themes"), ("Theme studio…", "theme_studio"),
                ("Import VS Code theme…", "import_theme"), ("Preferences…", "preferences"), ("Show files", "show_files"),
                ("Show source control", "show_git"), ("New terminal", "new_terminal"), ("Focus terminal", "focus_term"),
                ("Reopen closed tab", "reopen_tab"), ("Insert starter template (main)", "starter"), ("Toggle comment", "comment"),
                ("Duplicate line", "dup"), ("Toggle sidebar", "toggle_sidebar"), ("Toggle terminal / panel", "toggle_panel"),
                ("Toggle minimap", "toggle_minimap"), ("Toggle word wrap", "toggle_wrap"), ("Go to definition", "definition"),
                ("Show documentation (hover)", "hover"), ("Trigger completion", "complete"), ("Find references", "references"),
                ("Rename symbol", "rename_symbol"), ("Edit my snippets", "open_snippets"), ("Open settings (JSON)", "open_settings"),
                ("Zoom in", "zoom_in"), ("Zoom out", "zoom_out"), ("About", "about"), ("Quit", "quit"),
                ("Move line up", "move_up"), ("Move line down", "move_down"), ("Delete line", "delete_line"), ("Join lines", "join_lines"),
                ("Sort lines A-Z", "sort_lines"), ("Sort lines Z-A", "sort_lines_desc"), ("UPPERCASE", "upper_case"),
                ("lowercase", "lower_case"), ("Title Case", "title_case"), ("Trim trailing whitespace", "trim_ws"),
                ("Cycle layout", "cycle_layout"), ("Next theme", "cycle_theme"), ("Toggle status bar", "toggle_statusbar"),
                ("Toggle line numbers", "toggle_line_numbers")]
        cmds = cmds + self.IDE_COMMANDS
        items = [(n, k(a), (lambda a=a: c[a]())) for n, a in cmds if a in c]
        extra = [("Toggle activity bar", lambda: (self.settings.__setitem__("activity_bar", not self.settings["activity_bar"]), self.apply_activity_bar())),
                 ("Toggle bracket pair colours", lambda: self.set_pref("bracket_colors", not self.settings["bracket_colors"])),
                 ("Build configuration: Debug", lambda: self.config_dd.set_selected(0)),
                 ("Build configuration: Release", lambda: self.config_dd.set_selected(1)),
                 ("Toggle show whitespace", lambda: self.set_pref("show_whitespace", not self.settings["show_whitespace"])),
                 ("Toggle auto-pairs", lambda: self.set_pref("auto_pairs", not self.settings["auto_pairs"])),
                 ("Toggle linting", lambda: (self.set_pref("lint", not self.settings["lint"]), [t.schedule_lint(50) for t in self.tabs()])),
                 ("Indent: use spaces (2)", lambda: self.cur() and self.cur().apply_indent("spaces", 2)),
                 ("Indent: use spaces (4)", lambda: self.cur() and self.cur().apply_indent("spaces", 4)),
                 ("Indent: use tabs", lambda: self.cur() and self.cur().apply_indent("tabs", 4)),
                 ("Window: more transparent", lambda: self.set_opacity_pref(-0.05)),
                 ("Window: less transparent", lambda: self.set_opacity_pref(0.05))]
        items += [(n, "", cb) for n, cb in extra]
        Palette(self, "Type a command…", items).present()

    def set_opacity_pref(self, d):
        self.settings["opacity"] = round(max(0.4, min(1.0, float(self.settings["opacity"]) + d)), 2)
        self.apply_look()
        self.flash(f"Opacity {int(self.settings['opacity'] * 100)}%", 1500)

    def act_themes(self, *_):
        Palette(self, "Choose a theme…", self.theme_items()).present()

    def act_starter(self, *_):
        t = self.cur()
        if not t:
            return
        if t.get_text().strip():
            self.flash("Starter replaces the whole file — clear it first (or type 'main' + Enter in the file)")
            return
        t.insert_starter()

    def act_quick_open(self, *_):
        if not self.folder:
            self.act_open_folder()
            return
        files = []
        for dp, dns, fns in os.walk(self.folder):
            dns[:] = [d for d in dns if d not in IGNORE and not d.startswith(".")]
            for f in fns:
                files.append(os.path.relpath(os.path.join(dp, f), self.folder))
            if len(files) > 5000:
                break
        items = [(f, "", (lambda f=f: self.open_path(os.path.join(self.folder, f)))) for f in sorted(files)]
        Palette(self, "Quick open…", items).present()

    def act_open_settings(self, *_):
        from .settings import CFG_FILE
        self.settings.save()
        self.open_path(CFG_FILE)

    def act_about(self, *_):
        d = Gtk.AboutDialog(transient_for=self, modal=True, program_name=NAME, version=VERSION,
                            comments="A fast IDE for Linux: projects & builds, a gdb debugger, LSP, git, folding and multiple cursors.",
                            license_type=Gtk.License.MIT_X11, logo_icon_name="aether")
        d.present()

    # ================= sidebar =================
    def open_folder(self, path):
        self.folder = os.path.abspath(path)
        self.sidebar.files.set_folder(self.folder)
        self.sidebar.set_visible(True)
        self.settings["sidebar"] = True
        for term in self.terms[:1]:
            term.feed_child(f"cd {shlex.quote(self.folder)} && clear\n".encode())
        self.apply_layout()
        self._remember(self.folder)
        self.set_project(self.folder)
        self.sidebar.git.refresh()
        self.flash(f"Opened folder {self.folder}")

    def refresh_tree(self):
        self.sidebar.files.refresh()

    # ================= problems =================
    def _on_tab_diags(self, tab):
        if tab is self.cur():
            self._refresh_problems()
            self._on_tab_state(tab)

    def _refresh_problems(self):
        child = self.problems.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.problems.remove(child)
            child = nxt
        t = self.cur()
        diags = t.diags if t else []
        for d in diags:
            row = Gtk.ListBoxRow()
            h = Gtk.Box(spacing=8)
            h.set_margin_start(8); h.set_margin_top(2); h.set_margin_bottom(2)
            h.append(Gtk.Image.new_from_icon_name("dialog-error-symbolic" if d["sev"] == "error" else "dialog-warning-symbolic"))
            h.append(Gtk.Label(label=f"{d['line']}:{d['col'] or 1}   {d['msg']}", xalign=0))
            row.set_child(h)
            row._d = d
            self.problems.append(row)
        ne = sum(1 for d in diags if d["sev"] == "error")
        nw = len(diags) - ne
        self.problems_label.set_text(f"Problems ({ne}✖ {nw}⚠)" if diags else "Problems")
        return False

    def _on_problem(self, lb, row):
        t = self.cur()
        if t and hasattr(row, "_d"):
            t.goto(row._d["line"], row._d["col"])

    # ================= run =================
    def act_run(self, *_, force_file=False):
        if not force_file and self.project_run():
            return
        t = self.cur()
        if not t:
            self.flash("Open a file first")
            return
        if not t.path:
            self.flash("Save the file first (Ctrl+S) — then press F5")
            self.act_save_as()
            return
        if t.buffer.get_modified() and not t.save():
            return
        ov = (self.settings["run_commands"] or {}).get(t.tkey)
        if ov:
            cmd, tool = runner.expand(ov, t.path), None
        else:
            cmd, tool = runner.build_command(t.tkey, t.path)
        if not cmd:
            self.flash(f"Don't know how to run {t.title} — set a run command in Preferences, or use the terminal")
            return
        if runner.missing_tool(tool):
            msg = runner.install_hint(tool)
            self.flash(msg, 12000)
            self._write_output(msg + "\n")
            self.show_panel(self.panel.page_num(self.output_sw))
            return
        self.show_panel()
        cwd = os.path.dirname(t.path)
        if Vte:
            self.run_in_terminal(f"clear; cd {shlex.quote(cwd)}; {cmd}")
        else:
            self._run_captured(cmd, cwd)

    def _write_output(self, text, append=False):
        buf = self.output.get_buffer()
        if append:
            buf.insert(buf.get_end_iter(), text)
        else:
            buf.set_text(text)

    def _run_captured(self, cmd, cwd):
        self.panel.set_current_page(self.panel.page_num(self.output_sw))
        self._write_output(f"$ {cmd}\n")
        try:
            p = Gio.Subprocess.new(["bash", "-lc", f"cd {shlex.quote(cwd)} && {cmd}"],
                                   Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as e:
            self._write_output(str(e))
            return

        def done(proc, res):
            try:
                _ok, out, _ = proc.communicate_utf8_finish(res)
            except GLib.Error as e:
                out = str(e)
            self._write_output((out or "") + f"\n[exit {proc.get_exit_status()}]\n", append=True)
        p.communicate_utf8_async(None, None, done)
