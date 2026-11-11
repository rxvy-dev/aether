"""Web development in the main window.

  * Live preview beside the editor (WebKitGTK 6.0), updating as you type — CSS is swapped in place.
    Without WebKitGTK the same live server opens in your own browser. Everything is local / offline.
  * HTML | CSS | JS switcher: jump between a page and the stylesheets / scripts it loads; missing ones are
    created and linked for you.
  * Device sizes: responsive, laptop, desktop, tablet and phone (rotate with one click); big sizes are scaled to fit.
  * Console panel: console.log / warn / error and uncaught errors from the page, clickable file:line, and a
    prompt that runs JavaScript in the page.
  * Web sidebar page: pages of the project, files of the current page, actions.
Logic that needs no GTK lives in webdev.py; Emmet is in emmet.py.
"""
import os, re, time
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio, Pango

from . import webdev, icons, VERSION
from .palette import Palette

_WEBKIT = None
INSTALL_HINT = ("Install WebKitGTK 6.0 for the built-in preview — Arch: webkitgtk-6.0 · Debian/Ubuntu: gir1.2-webkit-6.0 · "
                "Fedora: webkitgtk6.0 · openSUSE: typelib-1_0-WebKit-6_0 · Void: libwebkitgtk60 · Alpine: webkit2gtk-6.0 · "
                "Gentoo: net-libs/webkit-gtk:6")
LEVEL_ICON = {"log": " ", "info": "i", "debug": "·", "warn": "▲", "error": "✖", "result": "←", "input": "›", "page": "↻"}
DEVICE_BUTTONS = [("Responsive", "globe", "Responsive — fill the pane"), ("Desktop · 1920", "desktop", "Desktop 1920 × 1080"),
                  ("Tablet · 768", "tablet", "Tablet 768 × 1024"), ("Phone · 390", "phone", "Phone 390 × 844")]


def webkit():
    """WebKitGTK 6.0, imported on first use (it's big — Aether still starts instantly without it)."""
    global _WEBKIT
    if _WEBKIT is None:
        try:
            gi.require_version("WebKit", "6.0")
            from gi.repository import WebKit
            _WEBKIT = WebKit
        except (ValueError, ImportError):
            _WEBKIT = False
    return _WEBKIT or None


def _icon_btn(icon, tip, cb, size=15):
    b = Gtk.Button(tooltip_text=tip)
    b.add_css_class("flat")
    b.set_child(icons.IconView(icon, size))
    b.connect("clicked", lambda *_: cb())
    return b


def _section(title):
    l = Gtk.Label(label=title.upper(), xalign=0)
    l.add_css_class("aether-section")
    return l


def _clear(box):
    c = box.get_first_child()
    while c:
        n = c.get_next_sibling()
        box.remove(c)
        c = n


# ====================================================================== preview pane
class _Frame(Gtk.Widget):
    """Holds one child (the web view). With a device size set it is exactly that big — a web view
    would happily grow to whatever it's given — otherwise it fills the space like a normal box."""

    def __init__(self):
        super().__init__()
        self.dev = None                    # (width, height) in screen pixels, or None to fill
        self.child = None

    def append(self, child):
        self.child = child
        child.set_parent(self)

    def get_first_child(self):
        return self.child

    def set_dev(self, size):
        self.dev = size
        self.queue_resize()

    def do_measure(self, orientation, for_size):
        if self.dev:
            n = self.dev[0] if orientation == Gtk.Orientation.HORIZONTAL else self.dev[1]
            return n, n, -1, -1
        if self.child is None:
            return 0, 0, -1, -1
        mn, nat, _a, _b = self.child.measure(orientation, for_size)
        return mn, nat, -1, -1

    def do_size_allocate(self, width, height, baseline):
        if self.child is not None:
            self.child.allocate(width, height, baseline, None)

    def do_dispose(self):
        if self.child is not None:
            self.child.unparent()
            self.child = None


class WebPreview(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.add_css_class("aether-web")
        self.set_size_request(220, -1)
        self.view = None
        self.url = None
        self.device = win.settings["web_device"] or "Responsive"
        self.landscape = False
        self._fit_id = 0
        self._last_w = -1

        bar = Gtk.Box(spacing=4)
        bar.add_css_class("aether-web-bar")
        seg = Gtk.Box(spacing=2)
        seg.add_css_class("aether-web-seg")
        self.kind_btns = {}
        for kind, label, tip in (("html", "HTML", "Go to the page (Ctrl+Alt+1)"), ("css", "CSS", "Go to its stylesheet (Ctrl+Alt+2) — created if missing"),
                                 ("js", "JS", "Go to its script (Ctrl+Alt+3) — created if missing")):
            b = Gtk.Button(label=label, tooltip_text=tip)
            b.connect("clicked", lambda _b, k=kind: win.web_goto(k))
            seg.append(b)
            self.kind_btns[kind] = b
        bar.append(seg)
        self.page_btn = Gtk.Button(tooltip_text="Preview another page")
        self.page_btn.add_css_class("flat")
        self.page_lbl = Gtk.Label(label="", ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=22)
        self.page_lbl.add_css_class("aether-web-page")
        self.page_btn.set_child(self.page_lbl)
        self.page_btn.connect("clicked", lambda *_: win.web_pick_page())
        bar.append(self.page_btn)
        bar.append(Gtk.Box(hexpand=True))
        self.dev_btns = {}
        for name, icon, tip in DEVICE_BUTTONS:
            b = _icon_btn(icon, tip, lambda n=name: self.set_device(n))
            self.dev_btns[name] = b
            bar.append(b)
        self.rot_btn = _icon_btn("rotate", "Rotate (portrait / landscape)", self.rotate)
        bar.append(self.rot_btn)
        bar.append(_icon_btn("reload", "Reload (F5)", lambda: win.web_reload(hard=True)))
        self.inspect_btn = _icon_btn("inspect", "Inspector / devtools", self.inspector)
        bar.append(self.inspect_btn)
        bar.append(_icon_btn("external", "Open in your browser", win.web_open_browser))
        bar.append(_icon_btn("close", "Close preview (Ctrl+Alt+W)", win.web_hide, 13))
        bsw = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, hscrollbar_policy=Gtk.PolicyType.EXTERNAL)
        bsw.set_child(bar)                     # the toolbar never forces the pane to be wide
        self.append(bsw)

        self.stage = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.stage.add_css_class("aether-web-stage")
        self.frame = _Frame()
        self.frame.add_css_class("aether-web-frame")
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.append(self.frame)
        self.dims = Gtk.Label(label="", halign=Gtk.Align.CENTER)
        self.dims.add_css_class("aether-web-dims")
        holder.append(self.dims)
        self.holder = holder
        self.stage.set_child(holder)
        self.append(self.stage)

        WK = webkit()
        if WK:
            try:
                session = WK.NetworkSession.new_ephemeral()          # no cache / cookies written to your disk
                self.view = WK.WebView(network_session=session)
            except (AttributeError, TypeError):
                self.view = WK.WebView()
            st = self.view.get_settings()
            st.set_enable_developer_extras(True)
            st.set_user_agent_with_application_details("AetherPreview", VERSION)
            for name, val in (("set_enable_write_console_messages_to_stdout", False), ("set_javascript_can_access_clipboard", True),
                              ("set_enable_back_forward_navigation_gestures", True)):
                fn = getattr(st, name, None)
                if fn:
                    fn(val)
            self.view.set_hexpand(True)
            self.view.set_vexpand(True)
            self.view.connect("decide-policy", self._policy)
            self.view.connect("load-changed", self._load_changed)
            self.frame.append(self.view)
        else:
            self.inspect_btn.set_sensitive(False)
            empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER, hexpand=True, vexpand=True)
            empty.add_css_class("aether-web-empty")
            t = Gtk.Label(label="Preview is open in your browser", wrap=True)
            t.add_css_class("title")
            empty.append(t)
            l = Gtk.Label(label="It still reloads live as you type, and its console shows up in the Console panel.\n\n" + INSTALL_HINT,
                          wrap=True, xalign=0, selectable=True)
            empty.append(l)
            b = Gtk.Button(label="Open in browser again", halign=Gtk.Align.START)
            b.connect("clicked", lambda *_: win.web_open_browser())
            empty.append(b)
            self.frame.append(empty)
            for b in self.dev_btns.values():
                b.set_sensitive(False)
            self.rot_btn.set_sensitive(False)
        self.apply_device()

    # ---------- loading
    def load(self, url):
        self.url = url
        if self.view:
            if self.view.get_uri() == url:
                self.view.reload()
            else:
                self.view.load_uri(url)

    def reload(self, hard=False):
        if self.view:
            (self.view.reload_bypass_cache if hard else self.view.reload)()

    def _policy(self, view, decision, dtype):
        WK = webkit()
        if dtype not in (WK.PolicyDecisionType.NAVIGATION_ACTION, WK.PolicyDecisionType.NEW_WINDOW_ACTION):
            return False
        try:
            uri = decision.get_navigation_action().get_request().get_uri()
        except AttributeError:
            return False
        srv = self.win.web_srv
        ours = srv and srv.running and uri.startswith(srv.origin)
        if uri.startswith(("http://", "https://", "mailto:")) and not ours:
            try:
                Gio.AppInfo.launch_default_for_uri(uri, None)      # external links go to your real browser
            except GLib.Error:
                pass
            decision.ignore()
            return True
        if dtype == WK.PolicyDecisionType.NEW_WINDOW_ACTION:
            view.load_uri(uri)
            decision.ignore()
            return True
        return False

    def _load_changed(self, view, event):
        uri = view.get_uri() or ""
        srv = self.win.web_srv
        if srv and srv.running and uri.startswith(srv.origin):
            path = srv.path_for_url(uri)
            if path and os.path.isdir(path):
                for idx in ("index.html", "index.htm"):
                    if os.path.isfile(os.path.join(path, idx)):
                        path = os.path.join(path, idx)
            if path and webdev.is_page(path) and path != self.win.web_page:
                self.win.web_page = path               # followed a link: the switcher follows too
                self.win.web_sync()

    def inspector(self):
        if self.view:
            self.view.get_inspector().show()

    def set_page_label(self, text):
        self.page_lbl.set_text(text)

    # ---------- devices
    def set_device(self, name):
        if name == self.device and name != "Responsive":
            name = "Responsive"                         # click the active size again to go back to responsive
        self.device = name
        self.landscape = False                          # a new size starts in its natural orientation
        self.win.settings["web_device"] = name
        self.apply_device()

    def rotate(self):
        if self.device == "Responsive":
            self.set_device("Phone · 390")
        self.landscape = not self.landscape
        self.apply_device()

    def _size(self):
        for name, w, h in webdev.DEVICES:
            if name == self.device:
                return (h, w) if self.landscape and w else (w, h)
        return 0, 0

    def apply_device(self):
        for name, b in self.dev_btns.items():
            (b.add_css_class if name == self.device else b.remove_css_class)("active")
        self.rot_btn.set_visible(self.device != "Responsive")
        w, h = self._size()
        f = self.frame
        for c in ("device", "phone"):
            f.remove_css_class(c)
        if not w:
            f.set_dev(None)
            f.set_halign(Gtk.Align.FILL)
            f.set_valign(Gtk.Align.FILL)
            f.set_hexpand(True)
            f.set_vexpand(True)
            self.holder.set_vexpand(True)
            self.stage.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
            self.dims.set_visible(False)
            if self.view:
                self.view.set_zoom_level(1.0)
            if self._fit_id:
                GLib.source_remove(self._fit_id)
                self._fit_id = 0
            return
        f.add_css_class("device")
        if w < 700:
            f.add_css_class("phone")
        f.set_halign(Gtk.Align.CENTER)
        f.set_valign(Gtk.Align.START)
        f.set_hexpand(False)
        f.set_vexpand(False)
        f.set_margin_top(14)
        self.holder.set_vexpand(False)
        self.stage.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.dims.set_visible(True)
        self._last_w = -1
        self._fit()
        if not self._fit_id:
            self._fit_id = GLib.timeout_add(300, self._fit)

    def _fit(self):
        """Scale big devices down to fit the pane (CSS still sees the real width — like browser devtools)."""
        w, h = self._size()
        if not w:
            self._fit_id = 0
            return False
        avail = (self.stage.get_width() - 40, self.stage.get_height() - 60)
        if avail == self._last_w:
            return True
        self._last_w = avail
        aw, ah = avail
        z = 1.0 if aw <= 0 or ah <= 0 else min(1.0, aw / float(w + 20), ah / float(h + 24))   # whole device visible
        z = max(0.25, z)
        pw = max(1, round(w * z))
        z = pw / float(w)                                       # exact, so the page sees exactly w CSS pixels
        self.frame.set_dev((pw, round(h * z)))                  # the device border is drawn around this
        if self.view:
            self.view.set_zoom_level(z)
        self.dims.set_text(f"{w} × {h}" + (f"   ·   {int(z * 100)}%" if z < 0.999 else ""))
        return True


# ====================================================================== console panel
class WebConsole(Gtk.Box):
    MAX = 2000

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.add_css_class("aether-console")
        self.counts = {"error": 0, "warn": 0}
        self.filter = "all"
        self.preserve = False
        self.history, self.hpos = [], 0

        bar = Gtk.Box(spacing=4)
        bar.set_margin_start(6)
        bar.set_margin_end(6)
        bar.set_margin_top(2)
        filt = Gtk.Box(spacing=2)
        filt.add_css_class("aether-web-filter")
        self.fbtns = {}
        first = None
        for key, label in (("all", "All"), ("error", "Errors"), ("warn", "Warnings"), ("log", "Logs")):
            b = Gtk.ToggleButton(label=label)
            b.add_css_class("flat")
            if first:
                b.set_group(first)
            else:
                first = b
                b.set_active(True)
            b.connect("toggled", lambda btn, k=key: btn.get_active() and self._set_filter(k))
            filt.append(b)
            self.fbtns[key] = b
        bar.append(filt)
        bar.append(Gtk.Box(hexpand=True))
        self.status = Gtk.Label(label="", xalign=1)
        self.status.add_css_class("dim-label")
        bar.append(self.status)
        pres = Gtk.CheckButton(label="Keep on reload")
        pres.connect("toggled", lambda b: setattr(self, "preserve", b.get_active()))
        bar.append(pres)
        clr = Gtk.Button(label="Clear")
        clr.add_css_class("flat")
        clr.connect("clicked", lambda *_: self.clear())
        bar.append(clr)
        self.append(bar)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.connect("row-activated", self._activated)
        self.list.set_filter_func(self._visible)
        self.sw = Gtk.ScrolledWindow(vexpand=True)
        self.sw.set_child(self.list)
        self.append(self.sw)

        inp = Gtk.Box(spacing=6)
        inp.add_css_class("aether-console-input")
        p = Gtk.Label(label="›")
        p.add_css_class("lvl")
        inp.append(p)
        self.entry = Gtk.Entry(hexpand=True, placeholder_text="Run JavaScript in the page — Enter  (↑ history)")
        self.entry.add_css_class("monospace")
        self.entry.connect("activate", self._run)
        kc = Gtk.EventControllerKey()
        kc.connect("key-pressed", self._key)
        self.entry.add_controller(kc)
        inp.append(self.entry)
        self.append(inp)
        self._n = 0

    def _set_filter(self, k):
        self.filter = k
        self.list.invalidate_filter()

    def _visible(self, row):
        lv = getattr(row, "_level", "log")
        if self.filter == "all":
            return True
        if self.filter == "log":
            return lv not in ("error", "warn")
        return lv == self.filter

    def label_text(self):
        e, w = self.counts["error"], self.counts["warn"]
        return "Console" + (f"  ✖ {e}" if e else "") + (f"  ▲ {w}" if w else "")

    def _update_counts(self):
        self.win.web_console_label.set_text(self.label_text())

    def clear(self):
        _clear(self.list)
        self._n = 0
        self.counts = {"error": 0, "warn": 0}
        self._update_counts()

    def add(self, msg):
        level = msg.get("level", "log")
        if level == "clear":
            self.clear()
            return False
        if level == "page":
            if not self.preserve:
                self.clear()
        text = msg.get("text", "")
        if level == "page":
            text = "Page loaded: " + text + ("   (browser)" if msg.get("from") == "browser" else "")
        vadj = self.sw.get_vadjustment()
        at_bottom = vadj.get_value() >= vadj.get_upper() - vadj.get_page_size() - 8
        row = Gtk.ListBoxRow()
        row._level = level
        row.add_css_class(level)
        h = Gtk.Box(spacing=8)
        lv = Gtk.Label(label=LEVEL_ICON.get(level, " "), valign=Gtk.Align.START)
        lv.add_css_class("lvl")
        h.append(lv)
        m = Gtk.Label(label=text, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, hexpand=True, selectable=False)
        m.add_css_class("msg")
        m.add_css_class("monospace")
        m.set_max_width_chars(400)
        h.append(m)
        srv = self.win.web_srv
        path = srv.path_for_url(msg.get("url")) if srv and msg.get("url") else None
        if path and msg.get("line"):
            row._loc = (path, int(msg["line"]), int(msg.get("col") or 0))
            loc = Gtk.Label(label=f"{os.path.basename(path)}:{msg['line']}", valign=Gtk.Align.START,
                            tooltip_text="Click to open")
            loc.add_css_class("loc")
            h.append(loc)
        row.set_child(h)
        row.set_activatable(hasattr(row, "_loc"))
        self.list.append(row)
        self._n += 1
        if level in self.counts:
            self.counts[level] += 1
            self._update_counts()
        while self._n > self.MAX:
            first = self.list.get_first_child()
            if not first:
                break
            self.list.remove(first)
            self._n -= 1
        if at_bottom:
            GLib.idle_add(lambda: (vadj.set_value(vadj.get_upper()), False)[1])
        return False

    def _activated(self, lb, row):
        loc = getattr(row, "_loc", None)
        if loc:
            self.win.open_path(loc[0], loc[1], loc[2] or None)

    def _run(self, *_):
        code = self.entry.get_text().strip()
        if not code:
            return
        self.history.append(code)
        self.hpos = len(self.history)
        self.entry.set_text("")
        self.add({"level": "input", "text": code})
        self.win.web_eval(code)

    def _key(self, ctl, keyval, kc, state):
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down) and self.history:
            self.hpos = max(0, min(len(self.history), self.hpos + (-1 if keyval == Gdk.KEY_Up else 1)))
            self.entry.set_text(self.history[self.hpos] if self.hpos < len(self.history) else "")
            self.entry.set_position(-1)
            return True
        return False


# ====================================================================== sidebar page
class WebPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.win = win
        title = Gtk.Label(label="Web", xalign=0)
        title.add_css_class("aether-proj")
        self.append(title)
        self.info = Gtk.Label(label="", xalign=0, wrap=True, selectable=True)
        self.info.add_css_class("aether-hint")
        self.append(self.info)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_child(box)
        self.append(sw)

        box.append(_section("Preview"))
        grid = Gtk.Grid(column_spacing=2, row_spacing=2, column_homogeneous=True)
        grid.set_margin_start(6)
        grid.set_margin_end(6)
        for i, (label, tip, cb) in enumerate([
                ("Live preview", "Show / hide the preview (Ctrl+Alt+W)", win.web_toggle),
                ("Open in browser", "Your browser, with live reload too", win.web_open_browser),
                ("HTML + CSS + JS tabs", "Open the page with its stylesheet and script (Ctrl+Alt+H)", win.web_open_tabs),
                ("Console", "Messages from the page", win.web_show_console),
                ("Phone size", "Preview at 390 × 844", lambda: win.web_device("Phone · 390")),
                ("Desktop size", "Preview at 1920 × 1080 (scaled to fit)", lambda: win.web_device("Desktop · 1920"))]):
            b = Gtk.Button(label=label, tooltip_text=tip)
            b.connect("clicked", lambda _b, cb=cb: cb())
            grid.attach(b, i % 2, i // 2, 1, 1)
        box.append(grid)
        live = Gtk.CheckButton(label="Update while typing (not only on save)", active=bool(win.settings["web_live"]))
        live.set_margin_start(10)
        live.connect("toggled", lambda b: win.settings.__setitem__("web_live", b.get_active()))
        box.append(live)

        box.append(_section("This page"))
        self.files = Gtk.ListBox()
        self.files.add_css_class("aether-dbg-list")
        self.files.connect("row-activated", self._open)
        box.append(self.files)

        box.append(_section("Pages"))
        self.pages = Gtk.ListBox()
        self.pages.add_css_class("aether-dbg-list")
        self.pages.connect("row-activated", lambda lb, row: win.web_show(row._path))
        box.append(self.pages)

        box.append(_section("Make"))
        for label, tip, cb in (("New page — HTML + CSS + JS", "Three linked files, opened side by side with the preview", win.web_new_page),
                               ("Export as one HTML file", "Inline the page's local CSS and JS (easy to share)", win.web_export)):
            b = Gtk.Button(label=label, tooltip_text=tip)
            b.add_css_class("flat")
            b.set_hexpand(True)
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, cb=cb: cb())
            box.append(b)
        hint = Gtk.Label(label="Tip: in HTML, type an Emmet abbreviation like  ul>li*3  or  !  and press Tab.", xalign=0, wrap=True)
        hint.add_css_class("aether-hint")
        box.append(hint)

    def _row(self, lb, text, path, tip=None):
        row = Gtk.ListBoxRow()
        row._path = path
        bx = Gtk.Box(spacing=8)
        bx.set_margin_start(8)
        bx.set_margin_top(2)
        bx.set_margin_bottom(2)
        if path:
            bx.append(icons.file_image(path, 16))
        l = Gtk.Label(label=text, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, tooltip_text=tip or path)
        bx.append(l)
        row.set_child(bx)
        lb.append(row)

    def _open(self, lb, row):
        if row._path:
            self.win.open_path(row._path)

    def update(self):
        w = self.win
        srv = w.web_srv
        page = w.web_page or w.web_guess_page()
        if srv and srv.running:
            self.info.set_text(f"Live at {srv.url_for(page) if page else srv.origin}  ·  offline, only this computer")
        else:
            self.info.set_text("Open an HTML file or a folder with index.html and press F5 (or Ctrl+Alt+W) for a live preview.")
        _clear(self.files)
        if page:
            a = w.web_assets(page)
            self._row(self.files, os.path.basename(page), page)
            for p in a["css"] + a["js"]:
                self._row(self.files, os.path.relpath(p, os.path.dirname(page)) + ("" if os.path.exists(p) else "   (missing)"), p)
            for u in a["external"][:8]:
                self._row(self.files, "↗ " + u, None, "Loaded from the internet — won't work offline")
        _clear(self.pages)
        root = w.web_root(page) if page else w.folder
        if root:
            for p in webdev.find_pages(root, 60):
                self._row(self.pages, os.path.relpath(p, root), p)


# ====================================================================== the mixin
class WebMixin:
    """Mixed into AetherWindow. Everything is prefixed web_ / _web_."""

    web_srv = None
    web_preview = None
    web_page = None

    WEB_COMMANDS = [
        ("Web: toggle live preview", "web_preview"), ("Web: open HTML + CSS + JS tabs", "web_tabs"),
        ("Web: go to HTML", "web_html"), ("Web: go to CSS", "web_css"), ("Web: go to JS", "web_js"),
        ("Web: open in browser", "web_browser"), ("Web: reload preview", "web_reload"),
        ("Web: new page (HTML + CSS + JS)", "web_new_page"), ("Web: export as one HTML file", "web_export"),
        ("Web: preview pages…", "web_pages"), ("Web: show console", "web_console"), ("Web: devtools / inspector", "web_devtools"),
        ("Web: preview size — responsive", "web_responsive"), ("Web: preview size — desktop", "web_desktop"),
        ("Web: preview size — tablet", "web_tablet"), ("Web: preview size — phone", "web_phone"),
        ("Web: show web sidebar", "show_web"),
    ]

    # ---------- setup
    def _web_setup(self):
        self.web_srv = None
        self.web_preview = None
        self.web_page = None
        self._web_timers = {}
        self._web_mtimes = {}
        self._web_poll_id = 0
        self.web_console = WebConsole(self)
        self.web_console_label = Gtk.Label(label="Console")
        self.panel.append_page(self.web_console, self.web_console_label)
        self.web_chip = Gtk.Button(label="", tooltip_text="Live preview")
        self.web_chip.add_css_class("flat")
        self.web_chip.add_css_class("aether-status-btn")
        self.web_chip.connect("clicked", lambda *_: self.web_menu())
        self.web_chip.set_visible(False)
        self.statusbar.insert_child_after(self.web_chip, self.project_label)
        self.notebook.connect("switch-page", lambda *_: GLib.idle_add(lambda: (self.web_sync(), False)[1]))

    def _web_callbacks(self):
        return {
            "web_preview": lambda *_: self.web_toggle(), "web_tabs": lambda *_: self.web_open_tabs(),
            "web_html": lambda *_: self.web_goto("html"), "web_css": lambda *_: self.web_goto("css"),
            "web_js": lambda *_: self.web_goto("js"), "web_browser": lambda *_: self.web_open_browser(),
            "web_reload": lambda *_: self.web_reload(hard=True), "web_new_page": lambda *_: self.web_new_page(),
            "web_export": lambda *_: self.web_export(), "web_pages": lambda *_: self.web_pick_page(),
            "web_console": lambda *_: self.web_show_console(), "web_devtools": lambda *_: self.web_devtools(),
            "web_responsive": lambda *_: self.web_device("Responsive"), "web_desktop": lambda *_: self.web_device("Desktop · 1920"),
            "web_tablet": lambda *_: self.web_device("Tablet · 768"), "web_phone": lambda *_: self.web_device("Phone · 390"),
            "show_web": lambda *_: self.show_sidebar("web"),
        }

    # ---------- which page / folder
    def _web_text(self, path):
        """Editor text if the file is open (unsaved edits included), else the file on disk."""
        for t in self.tabs():
            if t.path == path:
                return t.get_text()
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def web_root(self, page):
        if self.folder and (page == self.folder or page.startswith(self.folder.rstrip(os.sep) + os.sep)):
            return self.folder
        return os.path.dirname(page)

    def web_assets(self, page):
        return webdev.linked_assets(self._web_text(page) or "", page, self.web_root(page))

    def web_guess_page(self, tab=None):
        """The page that goes with the current tab: itself, a page that loads this CSS/JS, or the project's index."""
        t = tab or self.cur()
        p = t.path if t else None
        if t and not p and t.tkey == "html":
            return self._web_scratch(t)
        if p and webdev.is_page(p):
            return p
        if p and p.lower().endswith((".css", ".js", ".mjs")):
            if self.web_page:
                a = self.web_assets(self.web_page)
                if p in a["css"] or p in a["js"]:
                    return self.web_page
            hits = webdev.pages_linking(p, self.folder if self.folder and p.startswith(self.folder + os.sep) else os.path.dirname(p),
                                        read=self._web_open_text)
            if hits:
                return hits[0]
        if self.web_page and os.path.exists(self.web_page):
            return self.web_page
        if self.folder:
            return webdev.entry_page(self.folder)
        return None

    def _web_open_text(self, path):
        for t in self.tabs():
            if t.path == path:
                return t.get_text()
        return None

    def _web_scratch(self, tab):
        """An unsaved HTML tab is served from a scratch folder (its text lives only in memory)."""
        if not getattr(tab, "_web_scratch", None):
            from .runner import CACHE
            d = os.path.join(CACHE, "web-scratch", str(id(tab)))
            os.makedirs(d, exist_ok=True)
            tab._web_scratch = os.path.join(d, "index.html")
        return tab._web_scratch

    # ---------- server
    def _web_server(self, root):
        if self.web_srv is None:
            self.web_srv = webdev.PreviewServer(root, on_console=lambda m: GLib.idle_add(self.web_console.add, m))
        else:
            self.web_srv.set_root(root)
        if not self.web_srv.running:
            try:
                self.web_srv.start()
            except OSError as e:
                self.flash(f"Couldn't start the preview server: {e}")
                return None
        self.web_srv.clear_overlay()
        for t in self.tabs():                         # unsaved edits are served instead of what's on disk
            path = t.path or getattr(t, "_web_scratch", None)
            if path and (t.buffer.get_modified() or not t.path):
                self.web_srv.set_overlay(path, t.get_text())
        self.web_chip.set_label(f"◉ Live :{self.web_srv.port}")
        self.web_chip.set_visible(True)
        if not self._web_poll_id:
            self._web_poll_id = GLib.timeout_add(1000, self._web_poll)
        return self.web_srv

    def _web_poll(self):
        """Pick up files changed outside Aether (a build tool, an image editor…) for the page being previewed."""
        srv = self.web_srv
        if not srv or not srv.running:
            self._web_poll_id = 0
            return False
        if not srv.clients or not self.web_page:
            return True
        a = self.web_assets(self.web_page)
        changed_css, changed = [], False
        for p in [self.web_page] + a["css"] + a["js"]:
            if srv.overlay(p) is not None:
                continue
            try:
                m = os.stat(p).st_mtime
            except OSError:
                m = 0
            old = self._web_mtimes.get(p)
            self._web_mtimes[p] = m
            if old is not None and old != m:
                (changed_css.append(p) if p.lower().endswith(".css") else None)
                changed = changed or not p.lower().endswith(".css")
        if changed:
            srv.reload()
        else:
            for p in changed_css:
                srv.reload_css(srv.url_path(p))
        return True

    # ---------- show / hide
    def _web_pane(self):
        if self.web_preview is None:
            self.web_preview = WebPreview(self)
            self.editor_split.set_end_child(self.web_preview)
            self.editor_split.set_resize_end_child(True)
            self.editor_split.set_shrink_end_child(False)
        return self.web_preview

    def web_show(self, page=None):
        page = page or self.web_guess_page()
        if not page:
            self.flash("Open an HTML file (or a folder with index.html) to preview it — or make one: Web: new page")
            return False
        srv = self._web_server(os.path.dirname(page) if getattr(self.cur(), "_web_scratch", None) == page else self.web_root(page))
        if not srv:
            return False
        self.web_page = page
        self._web_mtimes = {}
        url = srv.url_for(page)
        if not webkit():
            self._web_launch(url)
            self.toast("Live preview opened in your browser", "info")
        pane = self._web_pane()
        if self.stack.get_visible_child_name() != "editor" and self.notebook.get_n_pages():
            self.stack.set_visible_child_name("editor")
        was_visible = pane.get_visible() and pane.get_mapped()
        pane.set_visible(True)
        if not was_visible:
            self._web_place_split()
        pane.load(url)
        self.web_sync()
        return True

    def _web_place_split(self):
        w = self.editor_split.get_width() or (self.get_width() - 300)
        saved = int(self.settings["web_preview_width"] or 0)
        pos = (w - saved) if 200 < saved < w - 250 else w // 2
        GLib.idle_add(lambda: (self.editor_split.set_position(max(250, pos)), False)[1])

    def web_hide(self):
        if self.web_preview and self.web_preview.get_visible():
            w = self.editor_split.get_width()
            if w > 0:
                self.settings["web_preview_width"] = max(0, w - self.editor_split.get_position())
            self.web_preview.set_visible(False)
            if self.web_preview.view:
                self.web_preview.view.load_uri("about:blank")      # stop scripts / audio of the hidden page
                self.web_preview.url = None
        self._focus_editor()

    def web_toggle(self):
        if self.web_preview and self.web_preview.get_visible():
            self.web_hide()
        else:
            self.web_show()

    def web_reload(self, hard=False):
        if self.web_preview and self.web_preview.get_visible():
            self.web_preview.reload(hard)
        elif self.web_srv and self.web_srv.running:
            self.web_srv.reload()
        else:
            self.web_show()

    def web_device(self, name):
        if not (self.web_preview and self.web_preview.get_visible()):
            self.web_show()
        if self.web_preview:
            if self.web_preview.device == name and name != "Responsive":
                return
            self.web_preview.set_device(name)

    def web_devtools(self):
        if not (self.web_preview and self.web_preview.get_visible()):
            self.web_show()
        if self.web_preview and self.web_preview.view:
            self.web_preview.inspector()
        else:
            self.flash("Devtools need the built-in preview (WebKitGTK 6.0) — or use your browser's (F12)")

    def web_run(self, force_file=False):
        """F5: preview HTML / CSS (and scripts that a page loads). Returns False to let Aether run it normally."""
        t = self.cur()
        p = t.path if t else None
        if t and not p and t.tkey == "html":
            return self.web_show(self._web_scratch(t))
        if p and (webdev.is_page(p) or p.lower().endswith((".css", ".scss"))):
            return self.web_show(self.web_guess_page(t) if not webdev.is_page(p) else p) or True
        if p and p.lower().endswith((".js", ".mjs")):
            proj = self.project
            if proj and proj.kind not in (None, "Web"):
                return False
            page = self.web_guess_page(t)
            if page and p in self.web_assets(page)["js"]:     # a page's script: preview the page, don't run it in node
                return self.web_show(page)
            return False
        proj = self.project
        if not force_file and proj and proj.kind == "Web" and (not p or p.startswith(proj.root + os.sep)):
            return self.web_show(webdev.entry_page(proj.root) if not p or not webdev.is_web_file(p) else None)
        return False

    def web_open_browser(self):
        page = self.web_page or self.web_guess_page()
        if not page:
            self.flash("Nothing to open — open an HTML file first")
            return
        srv = self._web_server(self.web_root(page) if not getattr(self.cur(), "_web_scratch", None) else os.path.dirname(page))
        if srv:
            self.web_page = page
            self._web_launch(srv.url_for(page))
            self.web_sync()

    def _web_launch(self, url):
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except GLib.Error:
            os.system(f"xdg-open '{url}' >/dev/null 2>&1 &")

    def web_eval(self, code):
        srv = self.web_srv
        if not srv or not srv.running or not srv.clients:
            self.web_console.add({"level": "warn", "text": "No page is connected — open the preview first (Ctrl+Alt+W)"})
            return
        visible = self.web_preview is not None and self.web_preview.get_visible() and self.web_preview.view is not None
        srv.eval(code, "preview" if visible else "browser")

    def web_show_console(self):
        self.show_panel(self.panel.page_num(self.web_console))
        self.web_console.entry.grab_focus()

    def web_menu(self):
        srv = self.web_srv
        items = [("Toggle live preview", "Ctrl+Alt+W", self.web_toggle), ("Open in browser", "", self.web_open_browser),
                 ("Copy preview URL", "", self._web_copy_url), ("Show console", "", self.web_show_console),
                 ("Preview pages…", "", self.web_pick_page), ("Stop the preview server", "", self.web_stop)]
        Palette(self, f"Live preview — {srv.origin if srv and srv.running else 'stopped'}", items).present()

    def _web_copy_url(self):
        if self.web_srv and self.web_srv.running:
            url = self.web_srv.url_for(self.web_page) if self.web_page else self.web_srv.origin
            self.get_clipboard().set(url)
            self.flash("Copied " + url)

    def web_stop(self):
        if self.web_preview and self.web_preview.get_visible():
            self.web_hide()
        if self.web_srv:
            self.web_srv.stop()
        self.web_chip.set_visible(False)
        self.flash("Preview server stopped")

    def web_shutdown(self):
        for tid in self._web_timers.values():
            GLib.source_remove(tid)
        self._web_timers = {}
        if self.web_srv:
            self.web_srv.stop()

    def web_pick_page(self):
        root = self.folder or (os.path.dirname(self.web_page) if self.web_page else None)
        if not root:
            self.flash("Open a folder first")
            return
        pages = webdev.find_pages(root)
        if not pages:
            self.flash("No .html pages in this folder")
            return
        items = [(os.path.relpath(p, root), "● previewing" if p == self.web_page else "", (lambda p=p: self.web_show(p)), icons.file_texture(p))
                 for p in pages]
        Palette(self, "Preview which page?", items).present()

    # ---------- live updates from the editor
    def _web_tab_added(self, tab):
        tab.buffer.connect("changed", lambda *_: self._web_changed(tab))
        tab.buffer.connect("modified-changed", lambda *_: (not tab.buffer.get_modified()) and self._web_saved(tab))

    def _web_tab_closed(self, tab):
        srv = self.web_srv
        path = tab.path or getattr(tab, "_web_scratch", None)
        tid = self._web_timers.pop(id(tab), None)
        if tid:
            GLib.source_remove(tid)
        if srv and srv.running and path and srv.overlay(path) is not None:
            srv.clear_overlay(path)                   # unsaved edits were discarded: back to the file on disk
            srv.reload()

    def _web_changed(self, tab):
        srv = self.web_srv
        if not srv or not srv.running or not (self.settings["web_live"] or not tab.path):
            return
        tid = self._web_timers.pop(id(tab), None)
        if tid:
            GLib.source_remove(tid)
        self._web_timers[id(tab)] = GLib.timeout_add(280, self._web_push, tab)

    def _web_push(self, tab, *_):
        self._web_timers.pop(id(tab), None)
        srv = self.web_srv
        path = tab.path or getattr(tab, "_web_scratch", None)
        if not srv or not srv.running or not path or srv.url_path(path) is None:
            return False
        srv.set_overlay(path, tab.get_text())
        self._web_notify(path)
        return False

    def _web_notify(self, path):
        srv = self.web_srv
        low = path.lower()
        if low.endswith(".css"):
            srv.reload_css(srv.url_path(path))
        elif webdev.is_web_file(path) or low.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
            srv.reload()
        if webdev.is_page(path) and path == self.web_page:
            GLib.idle_add(lambda: (self.web_sync(), False)[1])     # links may have changed

    def _web_saved(self, tab):
        srv = self.web_srv
        if not srv or not srv.running or not tab.path or srv.url_path(tab.path) is None:
            return
        tid = self._web_timers.pop(id(tab), None)
        if tid:
            GLib.source_remove(tid)
        had = srv.overlay(tab.path)
        srv.clear_overlay(tab.path)
        if not self.settings["web_live"] or had is None or had != tab.get_text():
            self._web_notify(tab.path)
        self._web_mtimes.pop(tab.path, None)

    # ---------- HTML | CSS | JS
    def web_sync(self):
        """Refresh the switcher (which file you're on, what's missing), the page label and the sidebar page."""
        pane = self.web_preview
        t = self.cur()
        page = self.web_page if (self.web_page and pane and pane.get_visible()) else self.web_guess_page()
        if pane:
            a = self.web_assets(page) if page else {"css": [], "js": [], "external": []}
            cur = t.path if t else None
            for kind, b in pane.kind_btns.items():
                files = [page] if kind == "html" and page else a.get(kind, [])
                on = bool(cur) and cur in files or (kind == "html" and t is not None and getattr(t, "_web_scratch", None) == page)
                (b.add_css_class if on else b.remove_css_class)("active")
                (b.add_css_class if not files else b.remove_css_class)("missing")
                n = len(files)
                b.set_label(kind.upper() + (f" {n}" if n > 1 else ""))
            if page:
                root = self.web_root(page)
                pane.set_page_label(os.path.relpath(page, root) if not getattr(t, "_web_scratch", None) else "untitled")
        if hasattr(self.sidebar, "web") and self.sidebar.get_visible() and self.sidebar.stack.get_visible_child_name() == "web":
            self.sidebar.web.update()

    def web_goto(self, kind):
        """Jump to the page's HTML, CSS or JS (cycling through several). A missing CSS / JS file is created and linked."""
        page = self.web_page if self.web_page and self.web_preview and self.web_preview.get_visible() else self.web_guess_page()
        if not page:
            self.flash("Open an HTML page first — or make one: Web: new page (HTML + CSS + JS)")
            return
        if kind == "html":
            for t in self.tabs():
                if getattr(t, "_web_scratch", None) == page:
                    self.notebook.set_current_page(self.notebook.page_num(t))
                    return
            self.open_path(page)
            return
        if getattr(self.cur(), "_web_scratch", None) == page:
            self.flash("Save the page first (Ctrl+S) so it can link a separate .css / .js file")
            return
        files = self.web_assets(page)[kind]
        if not files:
            path = self._web_create_linked(page, kind)
            if path:
                self.open_path(path)
            return
        cur = self.cur().path if self.cur() else None
        nxt = files[(files.index(cur) + 1) % len(files)] if cur in files else files[0]
        if not os.path.exists(nxt) and not any(t.path == nxt for t in self.tabs()):
            os.makedirs(os.path.dirname(nxt), exist_ok=True)
            open(nxt, "a").close()
            self.toast(f"Created {os.path.basename(nxt)} (the page links it)", "ok")
            self.refresh_tree()
        self.open_path(nxt)

    def _web_create_linked(self, page, kind):
        d = os.path.dirname(page)
        base = os.path.splitext(os.path.basename(page))[0]
        cands = (["style.css", "styles.css", f"{base}.css"] if kind == "css" else ["script.js", "main.js", f"{base}.js"])
        name = next((c for c in cands if os.path.exists(os.path.join(d, c))), None)
        name = name or (cands[0] if base == "index" else f"{base}.{kind}")
        path = os.path.join(d, name)
        if not os.path.exists(path):
            starter = ("* {\n  box-sizing: border-box;\n}\n\nbody {\n  margin: 0;\n  font-family: system-ui, sans-serif;\n}\n"
                       if kind == "css" else 'document.addEventListener("DOMContentLoaded", () => {\n  console.log("ready");\n});\n')
            try:
                with open(path, "w") as f:
                    f.write(starter)
            except OSError as e:
                self.flash(f"Couldn't create {name}: {e}")
                return None
        text = self._web_text(page) or ""
        new = webdev.add_link(text, kind, name)
        tab = next((t for t in self.tabs() if t.path == page), None)
        if tab:
            tab.replace_all_text(new)
            tab.save()
        else:
            with open(page, "w") as f:
                f.write(new)
        self.toast(f"Created {name} and linked it from {os.path.basename(page)}", "ok")
        self.refresh_tree()
        return path

    def web_open_tabs(self, page=None):
        """Open the page, its stylesheet(s) and script(s) as neighbouring tabs: HTML, CSS, JS."""
        page = page or self.web_guess_page()
        if not page or getattr(self.cur(), "_web_scratch", None) == page:
            self.flash("Open (and save) an HTML page first — or make one: Web: new page (HTML + CSS + JS)")
            return
        a = self.web_assets(page)
        if not a["css"]:
            p = self._web_create_linked(page, "css")
            a["css"] = [p] if p else []
        if not a["js"]:
            p = self._web_create_linked(page, "js")
            a["js"] = [p] if p else []
        tabs = []
        for p in [page] + a["css"] + a["js"]:
            if not os.path.exists(p):
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "a").close()
            t = self.open_path(p)
            if t:
                tabs.append(t)
        if tabs:                                       # keep them next to each other, in HTML · CSS · JS order
            base = self.notebook.page_num(tabs[0])
            for i, t in enumerate(tabs[1:], 1):
                self.notebook.reorder_child(t, min(base + i, self.notebook.get_n_pages() - 1))
            self.notebook.set_current_page(self.notebook.page_num(tabs[0]))
        self.web_page = page
        self.web_sync()

    # ---------- making things
    def web_new_page(self):
        """HTML + CSS + JS: three linked files, opened as tabs with the live preview."""
        if self.folder:
            Palette(self, f"Name of the new page in {os.path.basename(self.folder)} (e.g. index, about)",
                    on_text=lambda t: self._web_make_page(self.folder, t.strip() or "index"), initial="index").present()
            return
        from .welcome import default_parent
        parent = default_parent()
        n = 1
        while os.path.exists(os.path.join(parent, "web-playground" + ("" if n == 1 else f"-{n}"))):
            n += 1
        root = os.path.join(parent, "web-playground" + ("" if n == 1 else f"-{n}"))
        self._web_make_page(root, "index", open_folder=True)

    def _web_make_page(self, d, name, open_folder=False):
        from . import project
        name = re.sub(r"\.html?$", "", name, flags=re.I)
        name = re.sub(r"[^\w.-]+", "-", name).strip("-") or "index"
        css, js = ("style.css", "script.js") if name == "index" else (f"{name}.css", f"{name}.js")
        html = os.path.join(d, name + ".html")
        if os.path.exists(html):
            self.flash(f"{name}.html already exists — opening it")
            self.web_open_tabs(html)
            self.web_show(html)
            return
        title = os.path.basename(d.rstrip("/")) if name == "index" else name.replace("-", " ").title()
        try:
            os.makedirs(d, exist_ok=True)
            with open(html, "w") as f:
                f.write(project.WEB_HTML.replace("{name}", title).replace("style.css", css).replace("script.js", js)
                        .replace("<code>index.html</code>", f"<code>{name}.html</code>")
                        .replace("<code>style.css</code>", f"<code>{css}</code>").replace("<code>script.js</code>", f"<code>{js}</code>"))
            for fname, body in ((css, project.WEB_CSS), (js, project.WEB_JS.replace("{name}", title))):
                p = os.path.join(d, fname)
                if not os.path.exists(p):
                    with open(p, "w") as f:
                        f.write(body)
        except OSError as e:
            self.flash(f"Couldn't create the page: {e}")
            return
        if open_folder:
            self.open_folder(d)
        else:
            self.refresh_tree()
        self.web_open_tabs(html)
        self.web_show(html)
        self.toast(f"{name}.html + {css} + {js} — edit any of them, the preview follows", "ok", 4500)

    def web_export(self):
        page = self.web_page or self.web_guess_page()
        if not page or not os.path.exists(page):
            self.flash("Open (and save) an HTML page first")
            return
        text = self._web_text(page) or ""
        out, inlined, missing = webdev.bundle(text, page, self.web_root(page), read=self._web_open_text)
        dest = os.path.splitext(page)[0] + ".single.html"
        try:
            with open(dest, "w") as f:
                f.write(out)
        except OSError as e:
            self.flash(f"Couldn't write {dest}: {e}")
            return
        self.refresh_tree()
        msg = f"Wrote {os.path.basename(dest)} with {len(inlined)} file{'s' if len(inlined) != 1 else ''} inlined"
        if missing:
            msg += f" — missing: {', '.join(os.path.basename(m) for m in missing)}"
        self.toast(msg, "ok" if not missing else "info", 5000)
