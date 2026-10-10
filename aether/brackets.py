"""Bracket pair colourisation (like VS Code): (), [] and {} are coloured by nesting depth.

Strings and comments are skipped, unmatched closers are marked red. Runs debounced, after typing pauses.
"""
import gi
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Pango

from .folding import LINE_COMMENT, BLOCK_COMMENT_LANGS, SQUOTE_STRINGS

DARK = ["#ffd700", "#da70d6", "#179fff"]
LIGHT = ["#a07800", "#a020a0", "#0062b8"]
SKIP = {None, "", "markdown", "plain", "text"}
MAX_CHARS = 400_000
OPEN, CLOSE = "([{", ")]}"


def scan(text, key):
    """-> list of (offset, depth) and list of offsets of unmatched closers."""
    out, bad, stack = [], [], []
    lc = LINE_COMMENT.get(key, "//" if key not in ("python", "yaml", "ruby", "perl", "r", "julia", "elixir", "nim") else "#")
    if key in ("python", "yaml", "elixir", "nim"):
        lc = "#"
    block = key in BLOCK_COMMENT_LANGS
    squote = key in SQUOTE_STRINGS or key == "python"
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if lc and text.startswith(lc, i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if block and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch == '"' or (ch == "'" and squote) or (ch == "`" and key in ("javascript", "typescript", "go")):
            if key == "python" and text.startswith(ch * 3, i):        # triple-quoted
                j = text.find(ch * 3, i + 3)
                i = n if j < 0 else j + 3
                continue
            q = ch
            i += 1
            while i < n and text[i] != q:
                if text[i] == "\\":
                    i += 1
                elif text[i] == "\n" and q != "`":
                    break
                i += 1
            i += 1
            continue
        if ch in OPEN:
            out.append((i, len(stack)))
            stack.append(ch)
        elif ch in CLOSE:
            if stack and OPEN.index(stack[-1]) == CLOSE.index(ch):
                stack.pop()
                out.append((i, len(stack)))
            else:
                bad.append(i)
        i += 1
    return out, bad


class BracketColors:
    def __init__(self, tab):
        self.tab = tab
        self.b = tab.buffer
        self.tags = [self.b.create_tag(f"aether-bp{i}") for i in range(3)]
        self.bad = self.b.create_tag("aether-bp-bad", foreground="#ff3b5c", underline=Pango.Underline.SINGLE)
        self.enabled = True
        self._timer = 0
        self.b.connect("changed", lambda *_: self.schedule())

    def set_theme(self, dark):
        for t, c in zip(self.tags, DARK if dark else LIGHT):
            t.set_property("foreground", c)
        self.schedule(10)

    def set_enabled(self, on):
        self.enabled = on
        if not on:
            self._clear()
        else:
            self.schedule(10)

    def schedule(self, delay=220):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(delay, self.update)

    def _clear(self):
        s, e = self.b.get_bounds()
        for t in self.tags + [self.bad]:
            self.b.remove_tag(t, s, e)

    def update(self):
        self._timer = 0
        key = self.tab.tkey
        b = self.b
        self._clear()
        if not self.enabled or key in SKIP or b.get_char_count() > MAX_CHARS:
            return False
        # our tags must outrank the syntax-highlighting tags (created later by GtkSourceView)
        top = b.get_tag_table().get_size() - 1
        for t in self.tags + [self.bad]:
            t.set_priority(top)
        text = b.get_text(b.get_start_iter(), b.get_end_iter(), True)
        pairs, bad = scan(text, key)
        for off, depth in pairs:
            s = b.get_iter_at_offset(off)
            e = s.copy()
            e.forward_char()
            b.apply_tag(self.tags[depth % 3], s, e)
        for off in bad[:200]:
            s = b.get_iter_at_offset(off)
            e = s.copy()
            e.forward_char()
            b.apply_tag(self.bad, s, e)
        return False
