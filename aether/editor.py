import os, re
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gtk, Gdk, GtkSource, GLib, Gio, Pango, GObject

from . import templates, lint, gitutil
from .folding import Folding
from .multicursor import MultiCursor
from .brackets import BracketColors

PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'", "`": "`"}
CLOSERS = set(")]}\"'`")
QUOTE_OK = {"'": {"c", "cpp", "python", "javascript", "typescript", "javascriptreact", "typescriptreact", "rust",
                   "go", "java", "csharp", "kotlin", "swift", "dart", "scala", "shellscript", "lua", "perl", "ruby",
                   "php", "haskell", "zig", "elixir", "r", "julia", "html", "css", "sql", "json", "toml", "yaml"},
            "`": {"markdown", "javascript", "typescript", "javascriptreact", "typescriptreact", "shellscript", "go"}}
COMMENT = {"c": "//", "cpp": "//", "python": "#", "javascript": "//", "typescript": "//", "javascriptreact": "//",
           "typescriptreact": "//", "rust": "//", "go": "//", "java": "//", "csharp": "//", "kotlin": "//",
           "swift": "//", "dart": "//", "scala": "//", "shellscript": "#", "lua": "--", "perl": "#", "ruby": "#",
           "php": "//", "haskell": "--", "zig": "//", "elixir": "#", "r": "#", "julia": "#", "makefile": "#",
           "dockerfile": "#", "toml": "#", "yaml": "#", "sql": "--"}
WORD_OPENERS = {"lua": ("then", "do", "else", "repeat"), "shellscript": ("then", "do", "else"),
                "ruby": ("then", "do", "else")}
DEDENT_AFTER = {"python": ("return", "break", "continue", "pass", "raise")}


def _icon(attrs, name):
    """Use our bundled SVG directly (icon-theme lookup of app-private icons is unreliable)."""
    from . import data_dir
    for d in (os.path.join(data_dir(), "icons"), "/usr/share/icons", "/usr/local/share/icons",
              os.path.expanduser("~/.local/share/icons")):
        for sub, ext in (("32x32", ".png"), ("scalable", ".svg")):     # PNG first: no SVG loader needed
            p = os.path.join(d, "hicolor", sub, "actions", name + ext)
            if os.path.isfile(p):
                attrs.set_gicon(Gio.FileIcon.new(Gio.File.new_for_path(p)))
                return
    attrs.set_icon_name(name)


def _isword(ch):
    return ch.isalnum() or ch == "_"


class EditorTab(Gtk.Box):
    __gsignals__ = {"state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
                    "diagnostics": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, win, path=None, suggest_key=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.win = win
        self.settings = win.settings
        self.path = path
        self.suggest_key = suggest_key          # key for untitled files
        self.tkey = templates.key_for_path(path) or suggest_key
        self.diags = []
        self._lint_id = 0
        self._lint_gen = 0
        self._lint_proc = None
        self._marks = {}
        self.untitled_name = None

        self.buffer = GtkSource.Buffer()
        self.view = None
        self.view2 = None
        self.active_view = None
        self.buffer.set_highlight_matching_brackets(True)
        self.buffer.set_implicit_trailing_newline(True)
        rgba = Gdk.RGBA()
        rgba.parse("#f7768e")
        self.buffer.create_tag("diag-error", underline=Pango.Underline.ERROR, underline_rgba=rgba)
        rgba2 = Gdk.RGBA()
        rgba2.parse("#e0af68")
        self.buffer.create_tag("diag-warning", underline=Pango.Underline.ERROR, underline_rgba=rgba2)
        self.folding = Folding(self)
        self.mc = MultiCursor(self)
        self.brackets = BracketColors(self)

        self.view, self.sw, self.box = self._make_view()
        self.active_view = self.view
        self.add_css_class("aether-editor")
        self.set_vexpand(True)
        self.split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.split.set_wide_handle(True)
        self.split.set_hexpand(True)
        self.split.set_shrink_start_child(False)
        self.split.set_start_child(self.box)
        self.append(self.split)
        self.map = GtkSource.Map()
        self.map.set_view(self.view)
        self.map.set_size_request(76, -1)
        self.map.add_css_class("aether-map")
        self.map.set_visible(self.settings["minimap"])
        self.append(self.map)

        self.buffer.connect("modified-changed", lambda *_: self.emit("state-changed"))
        self.buffer.connect("changed", self._on_changed)
        self.buffer.connect("notify::cursor-position", lambda *_: self.emit("state-changed"))

        self.apply_language()
        self.apply_indent()
        self.apply_prefs()

    def _make_view(self):
        v = GtkSource.View.new_with_buffer(self.buffer)
        v.add_css_class("aether-code")
        v.set_show_line_numbers(False)        # our own renderer (skips folded lines)
        v.set_auto_indent(False)           # we do our own, language-aware
        v.set_indent_on_tab(True)
        v.set_smart_home_end(GtkSource.SmartHomeEndType.BEFORE)
        v.set_show_line_marks(True)
        v.set_monospace(True)
        v.set_left_margin(14)
        v.set_right_margin(14)
        v.set_top_margin(10)
        v.set_bottom_margin(200)
        v.set_hexpand(True)
        v.set_vexpand(True)
        sw = Gtk.ScrolledWindow()
        sw.set_child(v)
        sw.set_hexpand(True)
        sw.set_vexpand(True)
        comp = v.get_completion()
        words = GtkSource.CompletionWords.new(None)
        words.register(self.buffer)
        comp.add_provider(words)
        try:
            comp.add_provider(GtkSource.CompletionSnippets.new())
        except Exception:
            pass
        icons = (("error", "dialog-error-symbolic", 10), ("warning", "dialog-warning-symbolic", 5))
        for cat, icon, prio in icons:
            at = GtkSource.MarkAttributes()
            at.set_icon_name(icon)
            at.connect("query-tooltip-text", self._mark_tooltip)
            v.set_mark_attributes(cat, at, prio)
        for cat, col in (("git-add", "rgba(115,218,138,0.16)"), ("git-mod", "rgba(224,175,104,0.16)"), ("git-del", "rgba(247,118,142,0.22)")):
            at = GtkSource.MarkAttributes()
            c = Gdk.RGBA()
            c.parse(col)
            at.set_background(c)
            v.set_mark_attributes(cat, at, 1)
        # debugger: breakpoints and the current execution line
        at = GtkSource.MarkAttributes()
        _icon(at, "aether-breakpoint")
        c = Gdk.RGBA()
        c.parse("rgba(247,118,142,0.10)")
        at.set_background(c)
        at.connect("query-tooltip-text", lambda *_: "Breakpoint (F9 / click to remove)")
        v.set_mark_attributes("breakpoint", at, 20)
        at = GtkSource.MarkAttributes()
        _icon(at, "aether-debug-pc")
        c = Gdk.RGBA()
        c.parse("rgba(224,175,104,0.28)")
        at.set_background(c)
        v.set_mark_attributes("debug-pc", at, 30)
        v.connect("line-mark-activated", self._on_mark_gutter)
        self.folding.attach(v)
        kc = Gtk.EventControllerKey()
        kc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        kc.connect("key-pressed", self._on_key)
        v.add_controller(kc)
        fc = Gtk.EventControllerFocus()
        fc.connect("enter", lambda *_: setattr(self, "active_view", v))
        v.add_controller(fc)
        # ctrl+click -> go to definition
        gc = Gtk.GestureClick()
        gc.set_button(1)
        gc.connect("pressed", lambda g, n, x, y: self._ctrl_click(g, v, x, y))
        gc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        v.add_controller(gc)
        box = self.mc.attach(v, sw)
        return v, sw, box

    def _on_mark_gutter(self, view, it, button, state, n_presses):
        if button == 1 and self.path:
            self.win.toggle_breakpoint(self, it.get_line())

    def _ctrl_click(self, gesture, view, x, y):
        st = gesture.get_current_event_state()
        if st & Gdk.ModifierType.ALT_MASK:          # Alt+click: add a cursor
            bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
            ok, it = view.get_iter_at_location(bx, by)
            if ok:
                self.mc.add_at(it)
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            return
        if self.mc.active and not (st & Gdk.ModifierType.CONTROL_MASK):
            self.mc.clear()
        if st & Gdk.ModifierType.CONTROL_MASK:
            bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
            ok, it = view.get_iter_at_location(bx, by)
            if ok:
                self.buffer.place_cursor(it)
                GLib.idle_add(lambda: (self.win.lsp_definition(), False)[1])

    def views(self):
        return [v for v in (self.view, self.view2) if v is not None]

    def toggle_split(self):
        if self.view2 is None:
            self.view2, self.sw2, self.box2 = self._make_view()
            self.split.set_end_child(self.box2)
            w = max(400, self.split.get_allocated_width())
            self.split.set_position(w // 2)
            self.apply_prefs()
            self.apply_indent()
            self.view2.grab_focus()
        else:
            self.split.set_end_child(None)
            self.view2 = None
            self.active_view = self.view
            self.view.grab_focus()

    # ---------- configuration ----------
    def apply_prefs(self):
        s = self.settings
        ls = int(s["line_spacing"])
        for v in self.views():
            v.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if s["word_wrap"] else Gtk.WrapMode.NONE)
            v.set_show_right_margin(bool(s["show_ruler"]))
            v.set_right_margin_position(int(s["right_margin"]))
            v.set_highlight_current_line(bool(s["highlight_line"]))
            v.set_pixels_above_lines(max(0, ls // 2))
            v.set_pixels_below_lines(max(0, ls - ls // 2))
            sd = v.get_space_drawer()
            sd.set_enable_matrix(bool(s["show_whitespace"]))
            if s["show_whitespace"]:
                sd.set_types_for_locations(GtkSource.SpaceLocationFlags.ALL,
                                           GtkSource.SpaceTypeFlags.SPACE | GtkSource.SpaceTypeFlags.TAB)
            v.set_smart_home_end(GtkSource.SmartHomeEndType.BEFORE if s["smart_home_end"] else GtkSource.SmartHomeEndType.DISABLED)
            v.set_bottom_margin(260 if s["scroll_past_end"] else 4)
        self.folding.set_numbers_visible(bool(s["show_line_numbers"]))
        pal = getattr(self.win, "pal", None)
        if pal:
            self.folding.set_theme(pal["accent"], pal["hover"])
            self.mc.set_theme(pal["accent"], pal["sel"])
            self.brackets.set_theme(pal["dark"])
        self.brackets.set_enabled(bool(s["bracket_colors"]))
        self.buffer.set_highlight_matching_brackets(bool(s["bracket_match"]))
        self.map.set_visible(bool(s["minimap"]))
        if not s["git_marks"]:
            self._clear_git_marks()

    def apply_language(self):
        lm = GtkSource.LanguageManager.get_default()
        name = os.path.basename(self.path) if self.path else (self.untitled_name or "")
        lang = lm.guess_language(name, None) if name else None
        if lang is None and self.tkey:
            ids = {"c": "c", "cpp": "cpp", "python": "python3", "javascript": "js", "typescript": "typescript",
                   "rust": "rust", "go": "go", "java": "java", "csharp": "c-sharp", "shellscript": "sh",
                   "makefile": "makefile", "dockerfile": "docker", "markdown": "markdown", "json": "json",
                   "yaml": "yaml", "html": "html", "css": "css", "sql": "sql", "lua": "lua", "ruby": "ruby",
                   "php": "php", "perl": "perl", "toml": "toml", "kotlin": "kotlin", "swift": "swift",
                   "dart": "dart", "scala": "scala", "haskell": "haskell", "elixir": "elixir", "r": "r",
                   "julia": "julia", "javascriptreact": "jsx", "typescriptreact": "typescript-jsx"}
            lang = lm.get_language(ids.get(self.tkey, self.tkey))
        self.buffer.set_language(lang)
        self.language = lang

    def apply_indent(self, style=None, width=None):
        cfg = self.settings.indent_for(self.tkey)
        style = style or cfg["style"]
        width = width or cfg["width"]
        for v in self.views():
            v.set_insert_spaces_instead_of_tabs(style == "spaces")
            v.set_tab_width(width)
            v.set_indent_width(width if style == "spaces" else -1)
        self.emit("state-changed")

    def indent_unit(self):
        if self.view.get_insert_spaces_instead_of_tabs():
            w = self.view.get_indent_width()
            return " " * (w if w > 0 else self.view.get_tab_width())
        return "\t"

    def detect_indent(self, text):
        tabs = spaces = 0
        steps = {}
        prev = 0
        for line in text.splitlines()[:600]:
            if not line.strip():
                continue
            if line.startswith("\t"):
                tabs += 1
            elif line.startswith("  "):
                n = len(line) - len(line.lstrip(" "))
                spaces += 1
                d = abs(n - prev)
                if d in (2, 3, 4, 8):
                    steps[d] = steps.get(d, 0) + 1
                prev = n
            else:
                prev = 0
        if tabs > spaces and tabs > 3:
            self.apply_indent("tabs", self.view.get_tab_width())
        elif spaces > 3 and steps:
            self.apply_indent("spaces", max(steps, key=steps.get))

    # ---------- file io ----------
    @property
    def title(self):
        if self.path:
            return os.path.basename(self.path)
        return self.untitled_name or "untitled"

    def load(self, path):
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8", errors="replace")
        self.crlf = "\r\n" in text[:20000]
        if self.crlf:
            text = text.replace("\r\n", "\n")
        self.path = path
        self.tkey = templates.key_for_path(path)
        self.buffer.begin_irreversible_action()
        self.buffer.set_text(text)
        self.buffer.end_irreversible_action()
        self.buffer.set_modified(False)
        self.buffer.place_cursor(self.buffer.get_start_iter())
        self.apply_language()
        self.apply_indent()
        self.detect_indent(text)
        self.schedule_lint(100)
        self.update_git_marks()
        self.win.lsp_opened(self)

    def get_text(self):
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)

    def save(self, path=None):
        path = path or self.path
        if not path:
            return False
        if self.settings["format_on_save"] and self.tkey != "markdown":
            self.trim_whitespace()
        text = self.get_text()
        if text and not text.endswith("\n") and self.settings["format_on_save"]:
            text += "\n"
        if getattr(self, "crlf", False):
            text = text.replace("\n", "\r\n")
        try:
            tmp = path + ".aether-tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            if os.path.exists(path):
                try:
                    os.chmod(tmp, os.stat(path).st_mode)
                except OSError:
                    pass
            os.replace(tmp, path)
        except OSError as e:
            self.win.flash(f"Could not save: {e}")
            return False
        changed = path != self.path
        self.path = path
        if changed:
            self.tkey = templates.key_for_path(path) or self.tkey
            self.apply_language()
            self.apply_indent()
        self.buffer.set_modified(False)
        self.schedule_lint(50)
        self.update_git_marks()
        self.win.lsp_saved(self)
        return True

    def trim_whitespace(self):
        b = self.buffer
        b.begin_user_action()
        it = b.get_start_iter()
        while True:
            end = it.copy()
            if not end.ends_line():
                end.forward_to_line_end()
            s = end.copy()
            while s.backward_char():
                if s.get_char() not in (" ", "\t"):
                    s.forward_char()
                    break
            if not s.equal(end) and (s.get_line() == end.get_line()):
                # keep the cursor line untouched while typing? only on save, so trim everywhere
                b.delete(s, end)
                end = s
            if not end.forward_line():
                break
            it = end
        b.end_user_action()

    # ---------- starter ----------
    def insert_starter(self, key=None):
        key = key or self.tkey
        text = templates.starter_text(key, self.path)
        if not text:
            self.win.flash("No starter template for this language")
            return False
        self.buffer.set_text("")
        try:
            snip = GtkSource.Snippet.new_parsed(text)
            self.active_view.push_snippet(snip, None)
        except Exception:
            plain = re.sub(r"\$\{\d+:([^}]*)\}", r"\1", text)
            plain = re.sub(r"\$\d+", "", plain).replace("\\\\", "\\")
            self.buffer.set_text(plain)
        return True

    # ---------- keys / smart editing ----------
    def _line_info(self, it=None):
        b = self.buffer
        it = it or b.get_iter_at_mark(b.get_insert())
        start = it.copy()
        start.set_line_offset(0)
        before = b.get_text(start, it, False)
        end = it.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        after = b.get_text(it, end, False)
        return before, after

    def _char_at(self, it, off):
        c = it.copy()
        if off < 0:
            if not c.backward_chars(-off):
                return ""
        elif off > 0:
            if not c.forward_chars(off):
                return ""
        return c.get_char() if not c.is_end() else ""

    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def _on_key(self, ctl, keyval, keycode, state):
        w = ctl.get_widget() if ctl else None
        if w is not None:
            self.active_view = w
        if self.mc.active and self.mc.on_key(self.active_view, keyval, state):
            return True
        mods = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK)
        if mods:
            return False
        b = self.buffer
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (state & Gdk.ModifierType.SHIFT_MASK):
            return self._smart_enter()
        if keyval == Gdk.KEY_BackSpace and self.settings["auto_pairs"] and not b.get_has_selection():
            it = b.get_iter_at_mark(b.get_insert())
            prev, nxt = self._char_at(it, -1), self._char_at(it, 0)
            if prev in PAIRS and PAIRS[prev] == nxt:
                s = it.copy()
                s.backward_char()
                e = it.copy()
                e.forward_char()
                b.begin_user_action()
                b.delete(s, e)
                b.end_user_action()
                return True
            return False
        ch = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
        if not ch or not ch.isprintable():
            return False
        it = b.get_iter_at_mark(b.get_insert())
        nxt = self._char_at(it, 0)
        if self.settings["auto_pairs"]:
            if ch in CLOSERS and nxt == ch and not b.get_has_selection():
                it.forward_char()
                b.place_cursor(it)
                return True
            if ch in PAIRS:
                if ch in QUOTE_OK and self.tkey not in QUOTE_OK[ch]:
                    return False
                close = PAIRS[ch]
                if b.get_has_selection():
                    s, e = b.get_selection_bounds()
                    txt = b.get_text(s, e, True)
                    b.begin_user_action()
                    b.delete(s, e)
                    b.insert_at_cursor(ch + txt + close)
                    b.end_user_action()
                    return True
                prev = self._char_at(it, -1)
                if ch == close:  # quotes
                    if _isword(prev) or _isword(nxt) or prev == ch:
                        return False
                elif nxt and not nxt.isspace() and nxt not in ")]}>,;":
                    return False
                b.begin_user_action()
                b.insert_at_cursor(ch + close)
                it = b.get_iter_at_mark(b.get_insert())
                it.backward_char()
                b.place_cursor(it)
                b.end_user_action()
                return True
        if ch == ">" and self.tkey in ("html", "javascriptreact", "typescriptreact") and self.settings["auto_pairs"]:
            before, _after = self._line_info(it)
            m = re.search(r"<([A-Za-z][\w.:-]*)(?:\s[^<>]*)?$", before)
            if m and not before.endswith("/") and m.group(1).lower() not in self.VOID_TAGS:
                b.begin_user_action()
                b.insert_at_cursor("></" + m.group(1) + ">")
                it = b.get_iter_at_mark(b.get_insert())
                it.backward_chars(len(m.group(1)) + 3)
                b.place_cursor(it)
                b.end_user_action()
                return True
        if ch in "}])":
            before, _after = self._line_info(it)
            unit = self.indent_unit()
            if before and not before.strip() and before.endswith(unit):
                s = it.copy()
                s.backward_chars(len(unit))
                b.begin_user_action()
                b.delete(s, it)
                b.end_user_action()
        return False

    def _smart_enter(self):
        b = self.buffer
        b.begin_user_action()
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            b.delete(s, e)
        it = b.get_iter_at_mark(b.get_insert())
        before, after = self._line_info(it)
        indent = re.match(r"[ \t]*", before).group(0)
        stripped = before.rstrip()
        unit = self.indent_unit()
        extra = ""
        last = stripped[-1:] if stripped else ""
        if last in ("{", "(", "["):
            extra = unit
        elif last == ":" and self.tkey in ("python", "yaml"):
            extra = unit
        elif self.tkey in WORD_OPENERS and re.search(r"\b(" + "|".join(WORD_OPENERS[self.tkey]) + r")$", stripped):
            extra = unit
        elif self.tkey == "python" and stripped.lstrip().split(" ")[0] in DEDENT_AFTER["python"] and indent.endswith(unit):
            indent = indent[:-len(unit)]
        elif self.tkey == "markdown":
            m = re.match(r"^(\s*)([-*+] |\d+\. )", before)
            if m and before.strip() not in ("-", "*", "+"):
                extra = ""
                indent = m.group(1) + (m.group(2) if not m.group(2)[0].isdigit() else str(int(m.group(2)[:-2]) + 1) + ". ")
        close_next = after.lstrip()[:1]
        if last in PAIRS and PAIRS.get(last) == close_next and last in "{[(":
            b.insert_at_cursor("\n" + indent + extra + "\n" + indent)
            it = b.get_iter_at_mark(b.get_insert())
            it.backward_line()
            it.forward_to_line_end()
            b.place_cursor(it)
        else:
            if after.strip() == "" and before.strip() == "":
                # blank line: drop whitespace-only indentation carried on empty lines
                pass
            b.insert_at_cursor("\n" + indent + extra)
        b.end_user_action()
        self.active_view.scroll_mark_onscreen(b.get_insert())
        return True

    # ---------- actions ----------
    def toggle_comment(self):
        prefix = COMMENT.get(self.tkey)
        if not prefix:
            self.win.flash("No line-comment syntax for this language")
            return
        b = self.buffer
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            l1, l2 = s.get_line(), e.get_line() - (1 if e.starts_line() and e.get_line() > s.get_line() else 0)
        else:
            l1 = l2 = b.get_iter_at_mark(b.get_insert()).get_line()
        lines = []
        for ln in range(l1, l2 + 1):
            ok, it = b.get_iter_at_line(ln)
            e = it.copy()
            if not e.ends_line():
                e.forward_to_line_end()
            lines.append((ln, b.get_text(it, e, False)))
        nonblank = [t for _, t in lines if t.strip()]
        uncomment = bool(nonblank) and all(t.lstrip().startswith(prefix) for t in nonblank)
        minind = min((len(t) - len(t.lstrip()) for t in nonblank), default=0)
        b.begin_user_action()
        for ln, t in lines:
            if not t.strip():
                continue
            ok, it = b.get_iter_at_line(ln)
            if uncomment:
                idx = len(t) - len(t.lstrip())
                s = it.copy()
                s.forward_chars(idx)
                e = s.copy()
                n = len(prefix) + (1 if t.lstrip()[len(prefix):len(prefix) + 1] == " " else 0)
                e.forward_chars(n)
                b.delete(s, e)
            else:
                it.forward_chars(minind)
                b.insert(it, prefix + " ")
        b.end_user_action()

    def duplicate_line(self):
        b = self.buffer
        it = b.get_iter_at_mark(b.get_insert())
        ok, s = b.get_iter_at_line(it.get_line())
        e = s.copy()
        if not e.ends_line():
            e.forward_to_line_end()
        txt = b.get_text(s, e, False)
        b.begin_user_action()
        b.insert(e, "\n" + txt)
        b.end_user_action()

    # ---- line / text operations ----
    def _line_range(self):
        """(start_line, end_line) covered by the selection (or the caret line)."""
        b = self.buffer
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            el = e.get_line() - (1 if e.starts_line() and e.get_line() > s.get_line() else 0)
            return s.get_line(), el
        l = b.get_iter_at_mark(b.get_insert()).get_line()
        return l, l

    def _lines_iters(self, l1, l2):
        b = self.buffer
        ok, s = b.get_iter_at_line(l1)
        ok, e = b.get_iter_at_line(l2)
        if not e.ends_line():
            e.forward_to_line_end()
        return s, e

    def move_lines(self, d):
        b = self.buffer
        l1, l2 = self._line_range()
        n = b.get_line_count()
        if (d < 0 and l1 == 0) or (d > 0 and l2 >= n - 1):
            return
        s, e = self._lines_iters(l1, l2)
        block = b.get_text(s, e, False)
        other = l1 - 1 if d < 0 else l2 + 1
        os_, oe = self._lines_iters(other, other)
        otxt = b.get_text(os_, oe, False)
        b.begin_user_action()
        if d < 0:
            rs, re_ = self._lines_iters(l1 - 1, l2)
            b.delete(rs, re_)
            b.insert(rs, block + "\n" + otxt)
            nl1 = l1 - 1
        else:
            rs, re_ = self._lines_iters(l1, l2 + 1)
            b.delete(rs, re_)
            b.insert(rs, otxt + "\n" + block)
            nl1 = l1 + 1
        b.end_user_action()
        ok, a = b.get_iter_at_line(nl1)
        ok, z = b.get_iter_at_line(nl1 + (l2 - l1))
        if not z.ends_line():
            z.forward_to_line_end()
        b.select_range(z, a) if l2 != l1 else b.place_cursor(a)

    def delete_lines(self):
        b = self.buffer
        l1, l2 = self._line_range()
        s, e = self._lines_iters(l1, l2)
        if not e.is_end():
            e.forward_char()
        elif l1 > 0:
            s.backward_char()
        b.begin_user_action()
        b.delete(s, e)
        b.end_user_action()

    def join_lines(self):
        b = self.buffer
        l1, l2 = self._line_range()
        if l2 == l1:
            l2 = min(l1 + 1, b.get_line_count() - 1)
        if l2 == l1:
            return
        s, e = self._lines_iters(l1, l2)
        parts = [x.strip() if i else x.rstrip() for i, x in enumerate(b.get_text(s, e, False).split("\n"))]
        b.begin_user_action()
        b.delete(s, e)
        b.insert(s, " ".join(parts))
        b.end_user_action()

    def sort_lines(self, reverse=False):
        b = self.buffer
        l1, l2 = self._line_range()
        if l1 == l2:
            l1, l2 = 0, b.get_line_count() - 1
        s, e = self._lines_iters(l1, l2)
        lines = b.get_text(s, e, False).split("\n")
        tail = [lines.pop()] if lines and lines[-1] == "" and l2 == b.get_line_count() - 1 else []
        b.begin_user_action()
        b.delete(s, e)
        b.insert(s, "\n".join(sorted(lines, key=str.lower, reverse=reverse) + tail))
        b.end_user_action()

    def change_case(self, kind):
        b = self.buffer
        if not b.get_has_selection():
            it = b.get_iter_at_mark(b.get_insert())
            s = it.copy()
            e = it.copy()
            if not s.starts_word():
                s.backward_word_start()
            if not e.ends_word():
                e.forward_word_end()
        else:
            s, e = b.get_selection_bounds()
        t = b.get_text(s, e, False)
        f = {"upper": str.upper, "lower": str.lower, "title": str.title}[kind]
        b.begin_user_action()
        off = s.get_offset()
        b.delete(s, e)
        ins = b.get_iter_at_offset(off)
        b.insert(ins, f(t))
        b.end_user_action()

    def trim_whitespace(self):
        b = self.buffer
        b.begin_user_action()
        for i in range(b.get_line_count()):
            ok, s = b.get_iter_at_line(i)
            e = s.copy()
            if not e.ends_line():
                e.forward_to_line_end()
            t = b.get_text(s, e, False)
            if t != t.rstrip():
                s.forward_chars(len(t.rstrip()))
                b.delete(s, e)
        b.end_user_action()

    def goto_line(self, n):
        b = self.buffer
        n = max(1, min(n, b.get_line_count()))
        self.folding.reveal_line(n - 1)
        ok, it = b.get_iter_at_line(n - 1)
        b.place_cursor(it)
        self.active_view.scroll_to_iter(it, 0.2, True, 0.5, 0.4)
        self.active_view.grab_focus()

    def goto(self, line, col=None):
        b = self.buffer
        self.folding.reveal_line(max(0, line - 1))
        ok, it = b.get_iter_at_line(max(0, line - 1))
        if col:
            it.forward_chars(min(col - 1, it.get_chars_in_line() - 1 if it.get_chars_in_line() > 0 else 0))
        b.place_cursor(it)
        self.active_view.scroll_to_iter(it, 0.2, True, 0.5, 0.4)
        self.active_view.grab_focus()

    def position(self):
        it = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        return it.get_line() + 1, it.get_line_offset() + 1

    def set_lsp_diags(self, diags):
        self.lsp_diag_active = True
        self._set_diags(diags)

    # ---------- misc editing ----------
    def replace_all_text(self, new):
        b = self.buffer
        line, col = self.position()
        vadj = self.sw.get_vadjustment().get_value()
        b.begin_user_action()
        b.set_text(new)
        b.end_user_action()
        ok, it = b.get_iter_at_line(min(line - 1, b.get_line_count() - 1))
        it.forward_chars(min(col - 1, max(0, it.get_chars_in_line() - 1)))
        b.place_cursor(it)
        GLib.idle_add(lambda: (self.sw.get_vadjustment().set_value(vadj), False)[1])

    def retarget(self, new_path):
        self.path = new_path
        self.tkey = templates.key_for_path(new_path) or self.tkey
        self.apply_language()
        self.apply_indent()
        self.schedule_lint(100)

    # ---------- git diff marks ----------
    def _clear_git_marks(self):
        s, e = self.buffer.get_bounds()
        for cat in ("git-add", "git-mod", "git-del"):
            self.buffer.remove_source_marks(s, e, cat)

    def update_git_marks(self):
        if not self.path or not self.settings["git_marks"] or self.buffer.get_modified():
            if not self.settings["git_marks"]:
                self._clear_git_marks()
            return
        root = gitutil.repo_root(self.path)
        if not root:
            self._clear_git_marks()
            return
        rel = os.path.relpath(self.path, root)

        def done(st, out):
            self._clear_git_marks()
            if st != 0:
                return
            b = self.buffer
            for kind, a, z in gitutil.parse_hunks(out):
                for ln in range(a, min(z, b.get_line_count()) + 1):
                    ok, it = b.get_iter_at_line(ln - 1)
                    if ok:
                        b.create_source_mark(None, "git-" + kind, it)
        gitutil.run(["git", "diff", "-U0", "--no-color", "--", rel], root, done)

    # ---------- diagnostics ----------
    def _on_changed(self, *_):
        self.schedule_lint(700)
        self.win.lsp_changed(self)

    def schedule_lint(self, delay=700):
        if self._lint_id:
            GLib.source_remove(self._lint_id)
            self._lint_id = 0
        if not self.settings["lint"] or not self.tkey:
            self._set_diags([])
            return
        self._lint_id = GLib.timeout_add(delay, self._do_lint)

    def _do_lint(self):
        self._lint_id = 0
        if getattr(self, "lsp_diag_active", False):
            return False
        self._lint_gen += 1
        gen = self._lint_gen

        def cb(res):
            if gen != self._lint_gen:
                return
            self._set_diags(res or [])
        lint.run(self.tkey, self.path, self.get_text(), cb)
        return False

    def _set_diags(self, diags):
        b = self.buffer
        s, e = b.get_bounds()
        b.remove_tag_by_name("diag-error", s, e)
        b.remove_tag_by_name("diag-warning", s, e)
        b.remove_source_marks(s, e, "error")       # leave git / breakpoint marks alone
        b.remove_source_marks(s, e, "warning")
        self._marks = {}
        self.diags = diags
        seen = set()
        for i, d in enumerate(diags):
            ok, it = b.get_iter_at_line(min(d["line"], b.get_line_count()) - 1)
            line_end = it.copy()
            if not line_end.ends_line():
                line_end.forward_to_line_end()
            start = it.copy()
            if d["col"]:
                start.forward_chars(min(d["col"] - 1, max(0, it.get_chars_in_line() - 1)))
                end = start.copy()
                if d.get("end_line"):
                    ok2, end = b.get_iter_at_line(min(d["end_line"], b.get_line_count()) - 1)
                    end.forward_chars(min(max(0, d.get("end_col", 1) - 1), max(0, end.get_chars_in_line() - 1)))
                elif not end.ends_line():
                    end.forward_word_end()
                if end.compare(start) <= 0:
                    end = line_end
            else:
                end = line_end
                while start.get_char() in (" ", "\t") and start.compare(end) < 0:
                    start.forward_char()
            b.apply_tag_by_name("diag-" + d["sev"], start, end)
            key = (d["line"], d["sev"])
            name = f"diag-{i}"
            self._marks[name] = d["msg"]
            if key not in seen:
                seen.add(key)
                b.create_source_mark(name, d["sev"], it)
        self.emit("diagnostics")

    def _mark_tooltip(self, attrs, mark):
        name = mark.get_name()
        msgs = [m for n, m in self._marks.items()]
        line = self.buffer.get_iter_at_mark(mark).get_line() + 1
        here = [d["msg"] for d in self.diags if d["line"] == line]
        return "\n".join(here) if here else (self._marks.get(name) or None)
