"""Outline sidebar page: the symbols of the current file.

Uses the language server's documentSymbol when one is running (nested, with ranges),
otherwise the built-in regex scanner. Follows the cursor and filters as you type.
"""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango

from . import symbols, lsp

# LSP SymbolKind -> (glyph, colour)
KIND = {
    1: ("F", "#a9b1d6"), 2: ("M", "#7dcfff"), 3: ("N", "#7dcfff"), 4: ("P", "#7dcfff"), 5: ("C", "#e0af68"),
    6: ("m", "#bb9af7"), 7: ("p", "#73daca"), 8: ("f", "#73daca"), 9: ("c", "#bb9af7"), 10: ("E", "#e0af68"),
    11: ("I", "#e0af68"), 12: ("ƒ", "#7aa2f7"), 13: ("v", "#9ece6a"), 14: ("K", "#ff9e64"), 15: ("s", "#9ece6a"),
    16: ("#", "#ff9e64"), 17: ("b", "#ff9e64"), 18: ("[]", "#9ece6a"), 19: ("{}", "#9ece6a"), 20: ("k", "#9ece6a"),
    21: ("∅", "#9ece6a"), 22: ("e", "#e0af68"), 23: ("S", "#e0af68"), 24: ("!", "#f7768e"), 25: ("o", "#89ddff"),
    26: ("T", "#e0af68"),
}
REGEX_KIND = {"function": 12, "class": 5, "struct": 23, "define": 14, "type": 26, "impl": 11, "module": 2,
              "heading": 15}


def _esc(s):
    return GLib.markup_escape_text(s or "")


class OutlinePage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.tab = None
        self._timer = 0
        self._gen = 0
        self.items = []          # flat [(depth, kind, name, detail, line0, end_line0, col0)]
        self.title = Gtk.Label(label="No file", xalign=0)
        self.title.add_css_class("aether-proj")
        self.title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.append(self.title)
        self.entry = Gtk.SearchEntry(placeholder_text="Filter symbols")
        self.entry.set_margin_start(8)
        self.entry.set_margin_end(8)
        self.entry.set_margin_bottom(6)
        self.entry.connect("search-changed", lambda *_: self._fill())
        self.entry.connect("activate", lambda *_: self._activate_first())
        self.append(self.entry)
        self.source = Gtk.Label(label="", xalign=0)
        self.source.add_css_class("aether-hint")
        self.append(self.source)
        self.list = Gtk.ListBox()
        self.list.add_css_class("aether-outline")
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", self._on_row)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_child(self.list)
        self.append(sw)

    # ------------------------------------------------------------ data
    def set_tab(self, tab):
        if tab is not self.tab:
            self.tab = tab
            self.items = []
        self.schedule(50)

    def schedule(self, delay=600):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(delay, self.refresh)

    def refresh(self):
        self._timer = 0
        t = self.tab
        if t is None or not self.get_mapped():
            self.title.set_text(t.title if t else "No file")
            if t is None:
                self.items = []
                self._fill()
            return False
        self.title.set_text(t.title)
        self._gen += 1
        gen = self._gen
        c = getattr(t, "lsp", None)
        if c and not c.dead and not c.ready:
            # language server still starting: show the quick scan now, upgrade when it's ready
            self._from_regex(t)
            self._timer = GLib.timeout_add(1000, self.refresh)
            return False
        if c and not c.dead and c.ready and c.caps.get("documentSymbolProvider") and t.path:
            def cb(res, err):
                if gen != self._gen or t is not self.tab:
                    return
                if err or res is None:
                    self._from_regex(t)
                else:
                    self._from_lsp(res)
            c.request("textDocument/documentSymbol", {"textDocument": {"uri": lsp.path_to_uri(t.path)}}, cb)
        else:
            self._from_regex(t)
        return False

    def _from_regex(self, t):
        self.items = []
        for line, kind, name in symbols.extract(t.tkey or "", t.get_text()):
            self.items.append((0, REGEX_KIND.get(kind, 12), name, "", line - 1, line - 1, 0))
        self.source.set_text("  from a quick scan" if self.items else "  no symbols found")
        self._fill()

    def _from_lsp(self, res):
        out = []

        def walk(syms, depth):
            for s in sorted(syms, key=lambda x: (x.get("range") or x.get("location", {}).get("range", {})).get("start", {}).get("line", 0)):
                rng = s.get("selectionRange") or s.get("range") or s.get("location", {}).get("range") or {}
                full = s.get("range") or s.get("location", {}).get("range") or rng
                st = rng.get("start", {})
                out.append((depth, s.get("kind", 12), s.get("name", "?"), s.get("detail") or "",
                            st.get("line", 0), full.get("end", {}).get("line", st.get("line", 0)), st.get("character", 0)))
                walk(s.get("children") or [], depth + 1)
        walk(res, 0)
        self.items = out
        self.source.set_text(f"  from {self.tab.lsp.name}" if out else "  no symbols found")
        self._fill()

    # ------------------------------------------------------------ view
    def _fill(self):
        q = self.entry.get_text().strip().lower()
        c = self.list.get_first_child()
        while c:
            n = c.get_next_sibling()
            self.list.remove(c)
            c = n
        for it in self.items:
            depth, kind, name, detail, line, end, col = it
            if q and q not in name.lower():
                continue
            glyph, colour = KIND.get(kind, ("•", "#a9b1d6"))
            row = Gtk.ListBoxRow()
            row._item = it
            lbl = Gtk.Label(xalign=0)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            pad = "    " * (0 if q else depth)
            det = f'  <span alpha="45%">{_esc(detail[:60])}</span>' if detail else ""
            lbl.set_markup(f'{pad}<span foreground="{colour}" weight="bold">{_esc(glyph)}</span>  {_esc(name)}{det}')
            lbl.set_tooltip_text(f"{name}  — line {line + 1}")
            row.set_child(lbl)
            self.list.append(row)
        self.follow_cursor()

    def follow_cursor(self):
        t = self.tab
        if not t or not self.items:
            return
        ln = t.position()[0] - 1
        best, best_row = None, None
        row = self.list.get_first_child()
        while row:
            it = getattr(row, "_item", None)
            if it:
                _d, _k, _n, _det, line, end, _c = it
                inside = line <= ln <= max(end, line)
                if inside or (end == line and line <= ln):
                    if best is None or line >= best:
                        best, best_row = line, row
            row = row.get_next_sibling()
        if best_row is not None and best_row is not self.list.get_selected_row():
            self.list.select_row(best_row)

    def _on_row(self, lb, row):
        it = getattr(row, "_item", None)
        if it and self.tab:
            self.tab.goto(it[4] + 1, it[6] + 1)

    def _activate_first(self):
        row = self.list.get_row_at_index(0)
        if row:
            self._on_row(self.list, row)
