"""Preferences window: everything the editor can be customised with, applied live."""
import os, shutil
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, GtkSource, Pango

from . import keys, runner, templates, lsp, themegen
from .settings import CFG_DIR, CFG_FILE, DEFAULTS


def hexof(c):
    return "#%02x%02x%02x" % (int(c.red * 255 + 0.5), int(c.green * 255 + 0.5), int(c.blue * 255 + 0.5))


class PreferencesWindow(Gtk.Window):
    def __init__(self, win):
        super().__init__(title="Preferences", transient_for=win, default_width=980, default_height=700)
        self.win = win
        self.s = win.settings
        self.add_css_class("aether-prefs")
        self._capture = None
        self._debounce = {}
        box = Gtk.Box()
        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        side = Gtk.StackSidebar()
        side.set_stack(self.stack)
        side.set_size_request(190, -1)
        box.append(side)
        box.append(self.stack)
        self.set_child(box)
        for name, title, build in (("appearance", "Appearance", self._appearance), ("layout", "Layout", self._layout), ("editor", "Editor", self._editor),
                                   ("indent", "Indentation", self._indent), ("keys", "Keybindings", self._keys),
                                   ("run", "Run commands", self._run), ("lsp", "Language servers", self._lsp),
                                   ("advanced", "Advanced", self._advanced)):
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            for m in ("top", "bottom", "start", "end"):
                getattr(page, f"set_margin_{m}")(24)
            build(page)
            sw = Gtk.ScrolledWindow()
            sw.set_child(page)
            self.stack.add_titled(sw, name, title)
        kc = Gtk.EventControllerKey()
        kc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        kc.connect("key-pressed", self._on_key)
        self.add_controller(kc)

    def show_page(self, name):
        self.stack.set_visible_child_name(name)

    # ---------- widgets ----------
    def heading(self, page, text):
        l = Gtk.Label(label=text, xalign=0)
        l.add_css_class("heading")
        page.append(l)

    def group(self, page):
        g = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        g.add_css_class("group")
        page.append(g)
        return g

    def row(self, group, title, sub, widget):
        r = Gtk.Box(spacing=16)
        r.set_margin_top(8)
        r.set_margin_bottom(8)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label=title, xalign=0)
        left.append(t)
        if sub:
            sl = Gtk.Label(label=sub, xalign=0, wrap=True)
            sl.add_css_class("dim-label")
            left.append(sl)
        r.append(left)
        widget.set_valign(Gtk.Align.CENTER)
        r.append(widget)
        group.append(r)
        return r

    def _later(self, key, fn, ms=350):
        old = self._debounce.pop(key, 0)
        if old:
            GLib.source_remove(old)
        self._debounce[key] = GLib.timeout_add(ms, lambda: (self._debounce.pop(key, None), fn(), False)[2])

    def switch(self, g, title, sub, key, after=None):
        sw = Gtk.Switch(active=bool(self.s[key]))
        def changed(w, _p):
            self.s[key] = w.get_active()
            (after or self.win.apply_look)()
        sw.connect("notify::active", changed)
        self.row(g, title, sub, sw)

    def spin(self, g, title, sub, key, lo, hi, step=1, digits=0, after=None):
        sp = Gtk.SpinButton.new_with_range(lo, hi, step)
        sp.set_digits(digits)
        sp.set_value(float(self.s[key]))
        def changed(w):
            v = w.get_value()
            self.s[key] = int(v) if digits == 0 else v
            self._later(key, after or self.win.apply_look, 200)
        sp.connect("value-changed", changed)
        self.row(g, title, sub, sp)

    def entry(self, g, title, sub, key, after=None, width=300):
        e = Gtk.Entry()
        e.set_text(str(self.s[key] or ""))
        e.set_size_request(width, -1)
        def changed(w):
            self.s[key] = w.get_text()
            self._later(key, after or self.win.apply_look, 500)
        e.connect("changed", changed)
        self.row(g, title, sub, e)

    def dropdown(self, g, title, sub, key, options, after=None):
        dd = Gtk.DropDown.new_from_strings(options)
        cur = str(self.s[key])
        if cur in options:
            dd.set_selected(options.index(cur))
        def changed(w, _p):
            self.s[key] = options[w.get_selected()]
            (after or self.win.apply_look)()
        dd.connect("notify::selected", changed)
        self.row(g, title, sub, dd)

    # ---------- pages ----------
    def _appearance(self, page):
        self.heading(page, "Theme")
        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_max_children_per_line(4)
        self.flow.set_column_spacing(12)
        self.flow.set_row_spacing(12)
        self.flow.set_homogeneous(True)
        page.append(self.flow)
        self._fill_themes()
        bar = Gtk.Box(spacing=8)
        b1 = Gtk.Button(label="Theme studio…")
        b1.connect("clicked", lambda *_: self.win.show_studio())
        b2 = Gtk.Button(label="Import VS Code theme…")
        b2.connect("clicked", lambda *_: self.win.import_vscode_theme())
        bar.append(b1)
        bar.append(b2)
        page.append(bar)

        self.heading(page, "Look and feel")
        g = self.group(page)
        acc = Gtk.Box(spacing=8)
        cb = Gtk.ColorButton()
        c = Gdk.RGBA()
        c.parse(self.s["accent"] or getattr(self.win, "accent", "#7aa2f7"))
        cb.set_rgba(c)
        asw = Gtk.Switch(active=bool(self.s["accent"]))
        def acc_changed(*_):
            self.s["accent"] = hexof(cb.get_rgba()) if asw.get_active() else ""
            self._later("accent", self.win.apply_look, 120)
        cb.connect("color-set", lambda *_: (asw.set_active(True), acc_changed()))
        asw.connect("notify::active", acc_changed)
        acc.append(asw)
        acc.append(cb)
        self.row(g, "Accent colour", "Override the theme's accent for buttons, tabs and highlights.", acc)
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 40, 100, 5)
        sc.set_value(float(self.s["opacity"]) * 100)
        sc.set_size_request(240, -1)
        sc.connect("value-changed", lambda w: (self.s.__setitem__("opacity", round(w.get_value() / 100, 2)), self._later("op", self.win.apply_look, 120)))
        self.row(g, "Window opacity", "Below 100% the window is see-through. Turn on blur for it in your compositor (Hyprland, KWin, Picom).", sc)
        self.entry(g, "Interface font", "Comma-separated, in order of preference.", "ui_font")

    PRESETS = [
        ("Modern islands", "Floating panels, soft corners. The default.",
         dict(layout="islands", corner_style="soft", density="comfortable", tab_style="underline", sidebar_side="left", panel_position="bottom", header_style="command bar", show_statusbar=True, breadcrumbs=True)),
        ("Classic", "Joined panels, thin dividers, accent status bar, square tabs.",
         dict(layout="classic", corner_style="sharp", density="comfortable", tab_style="box", sidebar_side="left", panel_position="bottom", header_style="command bar", show_statusbar=True, breadcrumbs=True)),
        ("Minimal", "One seamless surface. No chrome, no breadcrumbs.",
         dict(layout="flat", corner_style="sharp", density="compact", tab_style="underline", sidebar_side="left", panel_position="bottom", header_style="title", show_statusbar=True, breadcrumbs=False)),
        ("Cards", "Big rounded cards with shadows and pill tabs.",
         dict(layout="floating", corner_style="round", density="spacious", tab_style="pill", sidebar_side="left", panel_position="bottom", header_style="command bar", show_statusbar=True, breadcrumbs=True)),
        ("Widescreen", "Sidebar on the right, terminal beside the editor.",
         dict(layout="islands", corner_style="soft", density="comfortable", tab_style="pill", sidebar_side="right", panel_position="right", header_style="command bar", show_statusbar=True, breadcrumbs=True)),
        ("Terminal", "Dense, flat, boxy tabs, title in the header.",
         dict(layout="flat", corner_style="sharp", density="compact", tab_style="box", sidebar_side="left", panel_position="right", header_style="title", show_statusbar=True, breadcrumbs=False)),
    ]

    def _layout(self, page):
        self.heading(page, "Presets")
        fb = Gtk.FlowBox()
        fb.set_selection_mode(Gtk.SelectionMode.NONE)
        fb.set_min_children_per_line(2)
        fb.set_max_children_per_line(3)
        fb.set_column_spacing(10)
        fb.set_row_spacing(10)
        fb.set_homogeneous(True)
        for name, sub, vals in self.PRESETS:
            b = Gtk.Button()
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
            t = Gtk.Label(label=name, xalign=0)
            t.add_css_class("heading")
            d = Gtk.Label(label=sub, xalign=0, wrap=True, max_width_chars=28)
            d.add_css_class("dim-label")
            v.append(t)
            v.append(d)
            b.set_child(v)
            b.connect("clicked", lambda _b, vals=vals: self._apply_preset(vals))
            fb.append(b)
        page.append(fb)

        self.heading(page, "Window layout")
        g = self.group(page)
        self.dropdown(g, "Layout style", "Islands: floating panels. Classic: joined with dividers. Flat: one seamless surface. Floating: big cards with shadows.", "layout", ["islands", "classic", "flat", "floating"])
        self.dropdown(g, "Tab style", "Underline, rounded pill, or square box.", "tab_style", ["underline", "pill", "box"])
        self.dropdown(g, "Sidebar position", None, "sidebar_side", ["left", "right"])
        self.dropdown(g, "Terminal / problems panel", "Below the editor or beside it.", "panel_position", ["bottom", "right"])
        self.dropdown(g, "Header", "A command bar in the middle, or just the folder name.", "header_style", ["command bar", "title"])
        self.dropdown(g, "Corners", "Roundness of buttons, tabs and panels (Islands/Floating).", "corner_style", ["sharp", "soft", "round"])
        self.dropdown(g, "Density", "Spacing of lists, tabs and the sidebar.", "density", ["compact", "comfortable", "spacious"])
        self.heading(page, "Show or hide")
        g = self.group(page)
        self.switch(g, "Sidebar", None, "sidebar", after=lambda: self.win.sidebar.set_visible(bool(self.s["sidebar"])))
        self.switch(g, "Bottom panel", "Terminal, problems and output.", "terminal", after=lambda: self.win.panel.set_visible(bool(self.s["terminal"])))
        self.switch(g, "Status bar", None, "show_statusbar")
        self.switch(g, "Breadcrumbs", "Path of the current file above the editor.", "breadcrumbs", after=lambda: (self.win.apply_look(), self.win._on_tab_state(self.win.cur())))
        self.switch(g, "Minimap", None, "minimap")
        self.switch(g, "Line numbers", None, "show_line_numbers")

    def _apply_preset(self, vals):
        for k, v in vals.items():
            self.s[k] = v
        self.win.apply_look()
        self.win._on_tab_state(self.win.cur())
        GLib.idle_add(lambda: (self.close(), self.win.show_preferences("layout"), False)[2])

    def _fill_themes(self):
        c = self.flow.get_first_child()
        while c:
            n = c.get_next_sibling()
            self.flow.remove(c)
            c = n
        mgr = GtkSource.StyleSchemeManager.get_default()
        cur = self.s["theme"]
        for sid in self.win.theme_ids():
            sc = mgr.get_scheme(sid)
            pal = themegen.scheme_to_palette(sc)
            btn = Gtk.Button()
            btn.set_has_frame(False)
            btn.add_css_class("swatch")
            if sid == cur:
                btn.add_css_class("current")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            da = Gtk.DrawingArea()
            da.set_content_width(170)
            da.set_content_height(84)
            da.set_draw_func(self._draw_swatch, pal)
            v.append(da)
            v.append(Gtk.Label(label=sc.get_name()))
            btn.set_child(v)
            btn.connect("clicked", lambda b, sid=sid: (self.win.apply_theme(sid), GLib.idle_add(self._fill_themes)))
            self.flow.append(btn)

    @staticmethod
    def _draw_swatch(area, cr, w, h, pal):
        def col(hexv):
            c = Gdk.RGBA()
            c.parse(hexv)
            return c.red, c.green, c.blue
        cr.set_source_rgb(*col(pal["bg"]))
        r = 8
        cr.new_sub_path()
        cr.arc(w - r, r, r, -1.5708, 0)
        cr.arc(w - r, h - r, r, 0, 1.5708)
        cr.arc(r, h - r, r, 1.5708, 3.1416)
        cr.arc(r, r, r, 3.1416, 4.7124)
        cr.close_path()
        cr.fill()
        rows = [("keyword", 36, "func", 60), ("fg", 20, "string", 70), ("comment", 90, None, 0), ("type", 28, "number", 22), ("fg", 54, None, 0)]
        y = 14
        for k1, w1, k2, w2 in rows:
            x = 14 + (14 if k1 == "fg" and y > 30 and y < 46 else 0)
            cr.set_source_rgb(*col(pal[k1]))
            cr.rectangle(x, y, w1, 6)
            cr.fill()
            if k2:
                cr.set_source_rgb(*col(pal[k2]))
                cr.rectangle(x + w1 + 8, y, w2, 6)
                cr.fill()
            y += 13

    def _editor(self, page):
        self.heading(page, "Text")
        g = self.group(page)
        self.entry(g, "Editor font", "Comma-separated list, e.g. JetBrains Mono, Fira Code, monospace", "font", width=380)
        self.spin(g, "Font size", None, "font_size", 6, 40)
        self.spin(g, "Line spacing", "Extra pixels between lines.", "line_spacing", 0, 16)
        self.switch(g, "Font ligatures", "Combine -> != => into single glyphs (needs a font that has them).", "ligatures")
        self.switch(g, "Word wrap", None, "word_wrap")
        self.switch(g, "Show whitespace", None, "show_whitespace")
        self.switch(g, "Highlight current line", None, "highlight_line")
        self.switch(g, "Minimap", None, "minimap")
        self.switch(g, "Line numbers", None, "show_line_numbers")
        self.switch(g, "Highlight matching brackets", None, "bracket_match")
        self.switch(g, "Smart Home / End", "Home jumps to the first character before the line start.", "smart_home_end")
        self.switch(g, "Blinking cursor", None, "cursor_blink", after=lambda: Gtk.Settings.get_default().set_property("gtk-cursor-blink", bool(self.s["cursor_blink"])))
        self.switch(g, "Scroll past end", "Let the last line scroll up to the middle of the screen.", "scroll_past_end")
        self.switch(g, "Ruler", "Draw a vertical line at the column below.", "show_ruler")
        self.spin(g, "Ruler column", None, "right_margin", 40, 200)
        self.heading(page, "Editing")
        g = self.group(page)
        self.switch(g, "Auto-close brackets and quotes", None, "auto_pairs")
        self.switch(g, "Starter template in new files", "Insert a ready-to-run main when you create an empty file.", "starter_on_new_file")
        self.switch(g, "Live diagnostics", "Underline problems while you type.", "lint")
        self.switch(g, "Git change marks", "Tint lines that were added, changed or removed.", "git_marks")
        self.switch(g, "Trim whitespace and add final newline on save", None, "format_on_save")
        self.switch(g, "Run the formatter on save", "clang-format, black/ruff, gofmt, rustfmt, prettier, shfmt…", "format_on_save_tool", after=lambda: None)
        self.switch(g, "Language servers", "Completions, hover, go to definition, rename (install the server for your language).", "lsp", after=lambda: None)

    def _indent(self, page):
        self.heading(page, "Default indentation")
        g = self.group(page)
        d = self.s["indent_default"]
        def save_default(style=None, width=None):
            cur = dict(self.s["indent_default"])
            cur.update({k: v for k, v in (("style", style), ("width", width)) if v is not None})
            self.s["indent_default"] = cur
            for t in self.win.tabs():
                t.apply_indent()
        dd = Gtk.DropDown.new_from_strings(["spaces", "tabs"])
        dd.set_selected(0 if d["style"] == "spaces" else 1)
        dd.connect("notify::selected", lambda w, _p: save_default(style=["spaces", "tabs"][w.get_selected()]))
        self.row(g, "Style", None, dd)
        sp = Gtk.SpinButton.new_with_range(1, 12, 1)
        sp.set_value(d["width"])
        sp.connect("value-changed", lambda w: save_default(width=int(w.get_value())))
        self.row(g, "Width", None, sp)
        self.heading(page, "Per language")
        g2 = self.group(page)
        for key in ("c", "cpp", "python", "javascript", "typescript", "rust", "go", "java", "csharp", "html", "css", "json",
                    "yaml", "shellscript", "lua", "ruby", "php", "makefile", "markdown"):
            ov = self.s["indent_by_language"].get(key)
            box = Gtk.Box(spacing=8)
            dd = Gtk.DropDown.new_from_strings(["default", "spaces", "tabs"])
            dd.set_selected(0 if not ov else (1 if ov["style"] == "spaces" else 2))
            sp = Gtk.SpinButton.new_with_range(1, 12, 1)
            sp.set_value((ov or self.s["indent_default"])["width"])
            def upd(*_, key=key, dd=dd, sp=sp):
                table = dict(self.s["indent_by_language"])
                sel = dd.get_selected()
                if sel == 0:
                    table.pop(key, None)
                else:
                    table[key] = {"style": ["", "spaces", "tabs"][sel], "width": int(sp.get_value())}
                self.s["indent_by_language"] = table
                for t in self.win.tabs():
                    if t.tkey == key:
                        t.apply_indent()
            dd.connect("notify::selected", upd)
            sp.connect("value-changed", upd)
            box.append(dd)
            box.append(sp)
            self.row(g2, templates.PRETTY.get(key, key), None, box)

    # ---- keybindings ----
    def _keys(self, page):
        self.heading(page, "Keybindings")
        hint = Gtk.Label(label="Click a shortcut, then press the new keys. Esc cancels, Backspace clears.", xalign=0)
        hint.add_css_class("dim-label")
        page.append(hint)
        self.key_buttons = {}
        g = self.group(page)
        for name in sorted(keys.LABELS, key=lambda n: keys.LABELS[n].lower()):
            b = Gtk.Button()
            b.set_size_request(190, -1)
            b.connect("clicked", lambda btn, n=name: self._start_capture(n))
            self.key_buttons[name] = b
            box = Gtk.Box(spacing=6)
            box.append(b)
            rb = Gtk.Button(label="Reset")
            rb.connect("clicked", lambda _b, n=name: self._reset_key(n))
            box.append(rb)
            self.row(g, keys.LABELS[name], None, box)
        self._refresh_keys()
        ra = Gtk.Button(label="Reset all keybindings")
        ra.connect("clicked", lambda *_: (self.s.__setitem__("keybindings", {}), self.win.reload_keys(), self._refresh_keys()))
        page.append(ra)

    def _label_for(self, accels):
        out = []
        for a in accels:
            ok, k, m = Gtk.accelerator_parse(a)
            if ok:
                out.append(Gtk.accelerator_get_label(k, m))
        return " / ".join(out) or "—"

    def _refresh_keys(self):
        eff = keys.effective(self.s)
        for n, b in self.key_buttons.items():
            b.set_label(self._label_for(eff.get(n, [])))

    def _start_capture(self, name):
        self._capture = name
        self.key_buttons[name].set_label("Press keys…")

    def _reset_key(self, name):
        kb = dict(self.s["keybindings"] or {})
        kb.pop(name, None)
        self.s["keybindings"] = kb
        self.win.reload_keys()
        self._refresh_keys()

    def _on_key(self, ctl, keyval, keycode, state):
        name = self._capture
        if not name:
            return False
        if keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
                      Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift):
            return True
        self._capture = None
        kb = dict(self.s["keybindings"] or {})
        if keyval == Gdk.KEY_Escape:
            self._refresh_keys()
            return True
        if keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete) and not (state & Gtk.accelerator_get_default_mod_mask()):
            kb[name] = []
        else:
            accel = Gtk.accelerator_name(Gdk.keyval_to_lower(keyval), state & Gtk.accelerator_get_default_mod_mask())
            eff = keys.effective(self.s)
            for other, acc in eff.items():                      # steal the combo from whoever had it
                if other != name and accel in acc:
                    kb[other] = [a for a in acc if a != accel]
            kb[name] = [accel]
        self.s["keybindings"] = kb
        self.win.reload_keys()
        self._refresh_keys()
        return True

    # ---- run commands ----
    def _run(self, page):
        self.heading(page, "Run commands (F5)")
        hint = Gtk.Label(label="Leave empty to use the default shown in grey. Placeholders: {file} {dir} {name} {base} {out}", xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        page.append(hint)
        g = self.group(page)
        cur = dict(self.s["run_commands"] or {})
        for key in templates.PRETTY:
            tpl = runner.template_for(key)
            if not tpl:
                continue
            e = Gtk.Entry()
            e.set_placeholder_text(tpl)
            e.set_text(cur.get(key, ""))
            e.set_size_request(460, -1)
            def changed(w, key=key):
                rc = dict(self.s["run_commands"] or {})
                if w.get_text().strip():
                    rc[key] = w.get_text()
                else:
                    rc.pop(key, None)
                self.s["run_commands"] = rc
            e.connect("changed", changed)
            self.row(g, templates.PRETTY[key], None, e)

    # ---- language servers ----
    def _lsp(self, page):
        self.heading(page, "Language servers")
        hint = Gtk.Label(label="Aether talks to standard language servers. Install the one for your language and it starts automatically.", xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        page.append(hint)
        g = self.group(page)
        self.switch(g, "Enable language servers", None, "lsp", after=lambda: None)
        g2 = self.group(page)
        ov = dict(self.s["lsp_servers"] or {})
        for key, argv in lsp.DEFAULT_SERVERS.items():
            e = Gtk.Entry()
            e.set_placeholder_text(" ".join(argv))
            e.set_text(ov.get(key, "") if isinstance(ov.get(key, ""), str) else " ".join(ov.get(key)))
            e.set_size_request(340, -1)
            def changed(w, key=key):
                t = dict(self.s["lsp_servers"] or {})
                if w.get_text().strip():
                    t[key] = w.get_text()
                else:
                    t.pop(key, None)
                self.s["lsp_servers"] = t
            e.connect("changed", changed)
            box = Gtk.Box(spacing=10)
            ok = shutil.which(argv[0]) is not None
            st = Gtk.Label(label="installed" if ok else "not installed")
            st.add_css_class("dim-label")
            box.append(e)
            box.append(st)
            self.row(g2, templates.PRETTY.get(key, key), None, box)

    def _advanced(self, page):
        self.heading(page, "Files")
        g = self.group(page)
        for title, sub, fn in (("settings.json", CFG_FILE, lambda: (self.s.save(), self.win.open_path(CFG_FILE))),
                               ("My snippets", os.path.join(CFG_DIR, "snippets"), self.win.open_snippets_dir),
                               ("Custom themes folder", os.path.join(CFG_DIR, "styles"), lambda: (os.makedirs(os.path.join(CFG_DIR, "styles"), exist_ok=True),
                                                                                                 self.win.open_path(os.path.join(CFG_DIR, "styles"))))):
            b = Gtk.Button(label="Open")
            b.connect("clicked", lambda *_, fn=fn: fn())
            self.row(g, title, sub, b)
        self.heading(page, "Reset")
        g = self.group(page)
        rb = Gtk.Button(label="Reset all settings")
        rb.add_css_class("destructive-action")
        def reset(*_):
            keep = {"session": self.s["session"], "recent": self.s["recent"]}
            self.s.d = {**{k: (v if not isinstance(v, (dict, list)) else __import__("json").loads(__import__("json").dumps(v))) for k, v in DEFAULTS.items()}, **keep}
            self.s.save()
            self.win.reload_keys()
            self.win.apply_look()
            self.close()
            self.win.flash("Settings reset to defaults")
        rb.connect("clicked", reset)
        self.row(g, "Restore defaults", "Keeps your recent files, removes every customisation.", rb)
