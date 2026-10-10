"""Code folding: fold regions, a fold gutter, and line numbers that skip folded lines.

Folded text is hidden with an invisible GtkTextTag, so the file on disk is never touched.
Regions come from braces (C-like languages), indentation (Python, YAML…), headings (Markdown)
and multi-line /* comments */.
"""
import re
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gtk, GtkSource, GLib, Pango

INDENT_LANGS = {"python", "yaml", "nim", "coffeescript", "haskell", "elixir"}
LINE_COMMENT = {"c": "//", "cpp": "//", "javascript": "//", "typescript": "//", "javascriptreact": "//",
                "typescriptreact": "//", "rust": "//", "go": "//", "java": "//", "csharp": "//", "kotlin": "//",
                "swift": "//", "dart": "//", "scala": "//", "php": "//", "zig": "//", "json": None,
                "css": None, "shellscript": "#", "ruby": "#", "perl": "#", "r": "#", "julia": "#",
                "makefile": "#", "toml": "#", "lua": "--", "sql": "--"}
BLOCK_COMMENT_LANGS = {"c", "cpp", "javascript", "typescript", "javascriptreact", "typescriptreact", "rust", "go",
                       "java", "csharp", "kotlin", "swift", "dart", "scala", "php", "css", "zig"}
SQUOTE_STRINGS = {"c", "cpp", "javascript", "typescript", "javascriptreact", "typescriptreact", "go", "java",
                  "csharp", "kotlin", "dart", "scala", "php", "shellscript", "ruby", "perl", "lua", "css", "sql", "json"}
MAX_CHARS = 600_000


def brace_regions(text, key):
    """{header_line: last_hidden_line} for {...} blocks, [...] arrays and /* */ comments."""
    out = {}
    stack = []
    lc = LINE_COMMENT.get(key, "//")
    block = key in BLOCK_COMMENT_LANGS
    squote = key in SQUOTE_STRINGS
    i, n, line = 0, len(text), 0
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
        elif lc and text.startswith(lc, i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif block and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            end_line = line + text.count("\n", i, j)
            if end_line - line >= 2:
                out.setdefault(line, end_line - 1)          # keep the "*/" line visible
            line = end_line
            i = j
            continue
        elif ch == '"' or (ch == "'" and squote) or (ch == "`" and key in ("javascript", "typescript", "go")):
            q = ch
            i += 1
            while i < n and text[i] != q:
                if text[i] == "\\":
                    i += 1
                elif text[i] == "\n":
                    if q != "`":
                        break                       # unterminated string: stop at line end
                    line += 1
                i += 1
        elif ch in "{[":
            stack.append(line)
        elif ch in "}]":
            if stack:
                start = stack.pop()
                if line - start >= 2:
                    # keep the header and the closing line visible
                    if start not in out or out[start] < line - 1:
                        out[start] = line - 1
        i += 1
    return out


def indent_regions(text):
    lines = text.split("\n")
    ind = []
    for ln in lines:
        x = ln.expandtabs(4)
        ind.append(len(x) - len(x.lstrip()) if x.strip() else None)
    out = {}
    for i, n in enumerate(ind):
        if n is None:
            continue
        last = None
        for j in range(i + 1, len(lines)):
            if ind[j] is None:
                continue
            if ind[j] > n:
                last = j
            else:
                break
        if last is not None and last > i:
            out[i] = last
    return out


def heading_regions(text):
    lines = text.split("\n")
    heads = [(i, len(m.group(1))) for i, l in enumerate(lines) for m in [re.match(r"^(#{1,6})\s", l)] if m]
    out = {}
    for k, (i, lvl) in enumerate(heads):
        end = len(lines) - 1
        for j, l2 in heads[k + 1:]:
            if l2 <= lvl:
                end = j - 1
                break
        while end > i and not lines[end].strip():
            end -= 1
        if end > i:
            out[i] = end
    return out


def compute_regions(text, key):
    if len(text) > MAX_CHARS:
        return {}
    if key in INDENT_LANGS:
        return indent_regions(text)
    if key == "markdown":
        return heading_regions(text)
    return brace_regions(text, key)


class LineNumbers(GtkSource.GutterRendererText):
    """Line numbers that leave folded (hidden) lines blank and bold the cursor line."""

    def __init__(self, folding):
        super().__init__()
        self.folding = folding
        self.set_xalign(1.0)
        self.set_xpad(8)
        self._digits = 0

    def update_width(self, view):
        d = max(2, len(str(view.get_buffer().get_line_count())))
        if d != self._digits:
            self._digits = d
            lay = view.create_pango_layout("9" * d)
            w, _h = lay.get_pixel_size()
            self.set_size_request(w + 18, -1)

    def do_query_data(self, lines, line):
        if line in self.folding.hidden:
            self.set_text("", -1)
            return
        t = str(line + 1)
        self.set_markup(f"<b>{t}</b>" if lines.is_cursor(line) else t, -1)


class FoldGutter(GtkSource.GutterRendererText):
    """▾ / ▸ arrows; click to fold or unfold."""

    def __init__(self, folding):
        super().__init__()
        self.folding = folding
        self.set_xalign(0.5)
        self.set_size_request(16, -1)

    def do_query_data(self, lines, line):
        f = self.folding
        if line in f.hidden:
            self.set_text("", -1)
        elif line in f.folded_heads():
            self.set_markup(f'<span foreground="{f.accent}">▸</span>', -1)
        elif line in f.regions:
            self.set_markup('<span alpha="45%">▾</span>', -1)
        else:
            self.set_text("", -1)

    def do_query_activatable(self, it, area):
        return it.get_line() in self.folding.regions or it.get_line() in self.folding.folded_heads()

    def do_activate(self, it, area, button, state, n_presses):
        self.folding.toggle(it.get_line())


class Folding:
    def __init__(self, tab):
        self.tab = tab
        self.buffer = tab.buffer
        self.regions = {}
        self.entries = []        # [(head_mark, start_mark, end_mark)]
        self.hidden = set()
        self.accent = "#7aa2f7"
        self._timer = 0
        self.tag = self.buffer.create_tag("aether-fold", invisible=True)
        self.head_tag = self.buffer.create_tag("aether-fold-head")
        self.renderers = []
        self.buffer.connect("changed", self._on_changed)
        self.buffer.connect("mark-set", self._on_mark_set)

    # ------------------------------------------------------------ gutter
    def attach(self, view):
        view.set_show_line_numbers(False)
        g = view.get_gutter(Gtk.TextWindowType.LEFT)
        nums = LineNumbers(self)
        fold = FoldGutter(self)
        g.insert(nums, -30)
        g.insert(fold, 5)
        nums.update_width(view)
        self.renderers.append((view, nums, fold))
        return nums

    def set_numbers_visible(self, on):
        for _v, nums, _f in self.renderers:
            nums.set_visible(on)

    def set_theme(self, accent, head_bg):
        self.accent = accent
        self.head_tag.set_property("paragraph-background", head_bg)
        self.redraw()

    def refresh_metrics(self):
        for _v, nums, _f in self.renderers:
            nums._digits = 0
        self.redraw()

    def redraw(self):
        for view, nums, fold in self.renderers:
            nums.update_width(view)
            nums.queue_draw()
            fold.queue_draw()
            view.get_gutter(Gtk.TextWindowType.LEFT).queue_draw()

    # ------------------------------------------------------------ regions
    def _on_changed(self, *_):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(350, self.recompute)
        self._rebuild_hidden()

    def recompute(self):
        self._timer = 0
        b = self.buffer
        self.regions = compute_regions(b.get_text(b.get_start_iter(), b.get_end_iter(), True), self.tab.tkey or "")
        self.redraw()
        return False

    def folded_heads(self):
        out = set()
        for head, _s, _e in self.entries:
            out.add(self.buffer.get_iter_at_mark(head).get_line())
        return out

    def _rebuild_hidden(self):
        b = self.buffer
        keep, hidden = [], set()
        for ent in self.entries:
            head, s, e = ent
            si, ei = b.get_iter_at_mark(s), b.get_iter_at_mark(e)
            if si.compare(ei) >= 0:
                for m in ent:
                    b.delete_mark(m)
                continue
            keep.append(ent)
            last = ei.get_line() - (1 if ei.starts_line() and not ei.is_end() else 0)
            hidden.update(range(si.get_line(), last + 1))
        self.entries = keep
        self.hidden = hidden

    # ------------------------------------------------------------ fold ops
    def fold(self, line):
        if line not in self.regions or line in self.folded_heads():
            return False
        b = self.buffer
        last = self.regions[line]
        ok, s = b.get_iter_at_line(line + 1)
        ok2, e = b.get_iter_at_line(last + 1)
        if not ok2 or last + 1 >= b.get_line_count():
            e = b.get_end_iter()
        if s.compare(e) >= 0:
            return False
        # don't hide the cursor: move it to the header line first
        cur = b.get_iter_at_mark(b.get_insert())
        if s.compare(cur) <= 0 and cur.compare(e) < 0:
            ok, h = b.get_iter_at_line(line)
            h.forward_to_line_end()
            b.place_cursor(h)
        b.apply_tag(self.tag, s, e)
        ok, h = b.get_iter_at_line(line)
        he = h.copy()
        he.forward_to_line_end()
        b.apply_tag(self.head_tag, h, he)
        self.entries.append((b.create_mark(None, h, True), b.create_mark(None, s, True), b.create_mark(None, e, False)))
        self._rebuild_hidden()
        self.redraw()
        return True

    def unfold(self, line):
        b = self.buffer
        done = False
        for ent in list(self.entries):
            head, s, e = ent
            if b.get_iter_at_mark(head).get_line() == line:
                self._remove(ent)
                done = True
        if done:
            self._rebuild_hidden()
            self.redraw()
        return done

    def _remove(self, ent):
        b = self.buffer
        head, s, e = ent
        b.remove_tag(self.tag, b.get_iter_at_mark(s), b.get_iter_at_mark(e))
        h = b.get_iter_at_mark(head)
        he = h.copy()
        he.forward_to_line_end()
        b.remove_tag(self.head_tag, h, he)
        for m in ent:
            b.delete_mark(m)
        self.entries.remove(ent)
        # re-apply nested folds that are still folded
        for head2, s2, e2 in self.entries:
            b.apply_tag(self.tag, b.get_iter_at_mark(s2), b.get_iter_at_mark(e2))

    def toggle(self, line):
        if not self.unfold(line):
            if self._timer:              # regions are stale: refresh first
                GLib.source_remove(self._timer)
                self.recompute()
            self.fold(line)

    def enclosing(self, line):
        """The innermost region whose header is at/above `line` and covers it."""
        best = None
        for h, last in self.regions.items():
            if h <= line <= last and (best is None or h > best):
                best = h
        return best

    def fold_at_cursor(self):
        b = self.buffer
        line = b.get_iter_at_mark(b.get_insert()).get_line()
        h = line if line in self.regions else self.enclosing(line)
        if h is not None:
            self.fold(h)

    def unfold_at_cursor(self):
        b = self.buffer
        line = b.get_iter_at_mark(b.get_insert()).get_line()
        if not self.unfold(line):
            h = self.enclosing(line)
            if h is not None:
                self.unfold(h)

    def fold_all(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self.recompute()
        # outermost first so nested regions stay hidden inside them
        for h in sorted(self.regions):
            if h not in self.hidden:
                self.fold(h)

    def unfold_all(self):
        for ent in list(self.entries):
            self._remove(ent)
        self._rebuild_hidden()
        self.redraw()

    def reveal_line(self, line):
        """Unfold whatever hides `line` (used by go-to, search, debugger)."""
        b = self.buffer
        changed = True
        while changed and line in self.hidden:
            changed = False
            for ent in list(self.entries):
                head, s, e = ent
                si, ei = b.get_iter_at_mark(s), b.get_iter_at_mark(e)
                if si.get_line() <= line <= ei.get_line():
                    self._remove(ent)
                    changed = True
                    break
            self._rebuild_hidden()
        self.redraw()

    def _on_mark_set(self, buf, it, mark):
        if mark is buf.get_insert() and self.hidden and it.get_line() in self.hidden:
            line = it.get_line()
            GLib.idle_add(lambda: (self.reveal_line(line), False)[1])
