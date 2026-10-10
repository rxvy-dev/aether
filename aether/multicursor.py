"""Multiple cursors for a GtkSourceView buffer.

GTK has one real cursor, so extra cursors are pairs of text marks (caret + selection anchor).
They are painted on a transparent overlay above the view. Whenever extra cursors exist, the
tab's key handler sends keys here, and every edit is applied at every cursor as one undo step.

  Ctrl+D            select the word / add the next occurrence
  Ctrl+Shift+L      select all occurrences
  Ctrl+Alt+Up/Down  add a cursor on the line above / below
  Alt+Click         add a cursor at the click
  Esc               back to one cursor
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gtk, Gdk, GLib

try:                                     # drawing the extra carets needs PyGObject's cairo bridge
    gi.require_foreign("cairo")
    HAS_CAIRO = True
except (ImportError, TypeError):
    HAS_CAIRO = False


def _isword(ch):
    return bool(ch) and (ch.isalnum() or ch == "_")


class MultiCursor:
    def __init__(self, tab):
        self.tab = tab
        self.b = tab.buffer
        self.extra = []                         # [(caret_mark, anchor_mark)]
        self.sel_tag = self.b.create_tag("aether-mc-sel")
        self.caret_tag = self.b.create_tag("aether-mc-caret")      # fallback when cairo is missing
        self.color = Gdk.RGBA()
        self.color.parse("#7aa2f7")
        self.areas = []
        self.b.connect("changed", lambda *_: self._repaint())
        self.b.connect("mark-set", lambda *_: self._repaint())

    # ------------------------------------------------------------ plumbing
    @property
    def active(self):
        return bool(self.extra)

    def attach(self, view, scrolled):
        """Wrap `scrolled` in an overlay that paints the extra carets; returns the overlay."""
        ov = Gtk.Overlay()
        ov.set_child(scrolled)
        da = Gtk.DrawingArea()
        da.set_can_target(False)
        if HAS_CAIRO:
            da.set_draw_func(self._draw, view)
        ov.add_overlay(da)
        self.areas.append(da)
        for adj in (view.get_vadjustment(), view.get_hadjustment()):
            if adj:
                adj.connect("value-changed", lambda *_: da.queue_draw())
        return ov

    def set_theme(self, accent_hex, sel_bg_hex):
        self.color.parse(accent_hex)
        self.sel_tag.set_property("background", sel_bg_hex)
        self.caret_tag.set_property("background", accent_hex)
        self.caret_tag.set_property("foreground", "#101014")

    def _repaint(self):
        for da in self.areas:
            da.queue_draw()

    def _draw(self, area, cr, w, h, view):
        if not self.extra:
            return
        Gdk.cairo_set_source_rgba(cr, self.color)
        hidden = getattr(self.tab, "folding", None)
        hidden = hidden.hidden if hidden else set()
        for caret, _anchor in self.extra:
            it = self.b.get_iter_at_mark(caret)
            if it.get_line() in hidden:
                continue
            r = view.get_iter_location(it)
            x, y = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, r.x, r.y)
            if -r.height <= y <= h:
                cr.rectangle(x, y, 2, max(r.height, 14))
        cr.fill()

    def _cursors(self):
        """All cursors as (caret_mark, anchor_mark), primary first."""
        return [(self.b.get_insert(), self.b.get_selection_bound())] + self.extra

    def _iters(self, pair):
        return self.b.get_iter_at_mark(pair[0]), self.b.get_iter_at_mark(pair[1])

    def _paint_selections(self):
        b = self.b
        s, e = b.get_bounds()
        b.remove_tag(self.sel_tag, s, e)
        b.remove_tag(self.caret_tag, s, e)
        for caret, anchor in self.extra:
            i1, i2 = b.get_iter_at_mark(caret), b.get_iter_at_mark(anchor)
            if not HAS_CAIRO:
                c2 = i1.copy()
                if c2.forward_char() and not i1.ends_line():
                    b.apply_tag(self.caret_tag, i1, c2)
            if not i1.equal(i2):
                b.apply_tag(self.sel_tag, *sorted((i1, i2), key=lambda i: i.get_offset()))
        self._repaint()
        self.tab.emit("state-changed")

    def _add(self, caret_it, anchor_it=None):
        anchor_it = anchor_it or caret_it
        for pair in self._cursors():
            c, a = self._iters(pair)
            if c.equal(caret_it) and a.equal(anchor_it):
                return False
        self.extra.append((self.b.create_mark(None, caret_it, False), self.b.create_mark(None, anchor_it, False)))
        return True

    def _dedupe(self):
        seen = set()
        keep = []
        for pair in self._cursors():
            c = self.b.get_iter_at_mark(pair[0]).get_offset()
            if c in seen and pair in self.extra:
                self.b.delete_mark(pair[0])
                self.b.delete_mark(pair[1])
                continue
            seen.add(c)
            if pair in self.extra:
                keep.append(pair)
        self.extra = keep

    def clear(self):
        if not self.extra:
            return
        for c, a in self.extra:
            self.b.delete_mark(c)
            self.b.delete_mark(a)
        self.extra = []
        self._paint_selections()

    def count(self):
        return len(self.extra) + 1

    # ------------------------------------------------------------ adding cursors
    def _word_at_cursor(self):
        b = self.b
        it = b.get_iter_at_mark(b.get_insert())
        s, e = it.copy(), it.copy()
        while s.backward_char():
            if not _isword(s.get_char()):
                s.forward_char()
                break
        while _isword(e.get_char()) and e.forward_char():
            pass
        return (s, e) if s.compare(e) < 0 else None

    def add_next_occurrence(self):
        b = self.b
        if not b.get_has_selection() and not self.extra:
            w = self._word_at_cursor()
            if w:
                b.select_range(w[1], w[0])
            return
        s, e = b.get_selection_bounds() if b.get_has_selection() else (None, None)
        if s is None:
            return
        needle = b.get_text(s, e, True)
        if not needle:
            return
        # search after the last cursor added, wrapping around
        last = self.extra[-1] if self.extra else (b.get_insert(), b.get_selection_bound())
        li = max(self._iters(last), key=lambda i: i.get_offset())
        flags = Gtk.TextSearchFlags.TEXT_ONLY
        found = li.forward_search(needle, flags, None) or b.get_start_iter().forward_search(needle, flags, None)
        while found:
            ms, me = found
            if self._add(me, ms):
                self._paint_selections()
                self.tab.active_view.scroll_to_iter(me, 0.1, False, 0, 0)
                return
            # already a cursor there; keep looking (stop after a full lap)
            nxt = me.forward_search(needle, flags, None)
            if nxt is None or nxt[0].equal(found[0]):
                break
            found = nxt
            if found[0].equal(s):
                break
        self.tab.win.flash("No more occurrences", 1500)

    def select_all_occurrences(self):
        b = self.b
        if not b.get_has_selection():
            w = self._word_at_cursor()
            if not w:
                return
            b.select_range(w[1], w[0])
        s, e = b.get_selection_bounds()
        needle = b.get_text(s, e, True)
        if not needle:
            return
        self.clear()
        it = b.get_start_iter()
        n = 0
        while True:
            found = it.forward_search(needle, Gtk.TextSearchFlags.TEXT_ONLY, None)
            if not found:
                break
            ms, me = found
            if not ms.equal(s):
                self._add(me, ms)
                n += 1
            it = me
            if n > 2000:
                break
        self._paint_selections()
        self.tab.win.flash(f"{n + 1} cursors — Esc to go back to one", 2500)

    def add_vertical(self, d):
        """Add a cursor on the line above (d=-1) / below (d=1) the outermost cursor."""
        b = self.b
        carets = [self.b.get_iter_at_mark(p[0]) for p in self._cursors()]
        ref = min(carets, key=lambda i: i.get_offset()) if d < 0 else max(carets, key=lambda i: i.get_offset())
        col = b.get_iter_at_mark(b.get_insert()).get_line_offset()
        line = ref.get_line() + d
        if line < 0 or line >= b.get_line_count():
            return
        ok, it = b.get_iter_at_line(line)
        it.forward_chars(min(col, max(0, it.get_chars_in_line() - (0 if it.ends_line() else 1))))
        if it.get_line() != line:
            ok, it = b.get_iter_at_line(line)
            it.forward_to_line_end()
        self._add(it)
        self._paint_selections()

    def add_at(self, it):
        self._add(it)
        self._paint_selections()

    # ------------------------------------------------------------ editing
    def _edit(self, fn):
        b = self.b
        b.begin_user_action()
        for pair in sorted(self._cursors(), key=lambda p: -self.b.get_iter_at_mark(p[0]).get_offset()):
            fn(pair)
        b.end_user_action()
        self._dedupe()
        self._paint_selections()

    def _delete_sel(self, pair):
        c, a = self._iters(pair)
        if not c.equal(a):
            self.b.delete(c, a)
            return True
        return False

    def insert(self, text):
        def fn(pair):
            self._delete_sel(pair)
            self.b.insert(self.b.get_iter_at_mark(pair[0]), text)
            self._collapse(pair)
        self._edit(fn)

    def _collapse(self, pair):
        it = self.b.get_iter_at_mark(pair[0])
        if pair[0] is self.b.get_insert():
            self.b.place_cursor(it)
        else:
            self.b.move_mark(pair[1], it)

    def backspace(self, word=False):
        def fn(pair):
            if self._delete_sel(pair):
                return
            e = self.b.get_iter_at_mark(pair[0])
            s = e.copy()
            if word:
                while s.backward_char() and s.get_char() in " \t":
                    pass
                if _isword(s.get_char()):
                    while s.backward_char() and _isword(s.get_char()):
                        pass
                    if not _isword(s.get_char()):
                        s.forward_char()
            else:
                s.backward_char()
            if not s.equal(e):
                self.b.delete(s, e)
            self._collapse(pair)
        self._edit(fn)

    def delete(self):
        def fn(pair):
            if self._delete_sel(pair):
                return
            s = self.b.get_iter_at_mark(pair[0])
            e = s.copy()
            if e.forward_char():
                self.b.delete(s, e)
            self._collapse(pair)
        self._edit(fn)

    def newline(self):
        def fn(pair):
            self._delete_sel(pair)
            it = self.b.get_iter_at_mark(pair[0])
            ls = it.copy()
            ls.set_line_offset(0)
            line = self.b.get_text(ls, it, False)
            indent = line[:len(line) - len(line.lstrip(" \t"))]
            if line.rstrip().endswith(("{", "(", "[", ":")):
                indent += self.tab.indent_unit()
            self.b.insert(it, "\n" + indent)
            self._collapse(pair)
        self._edit(fn)

    def move(self, kind, extend=False, word=False):
        b = self.b
        for pair in self._cursors():
            it = b.get_iter_at_mark(pair[0])
            anchor = b.get_iter_at_mark(pair[1])
            if not extend and not it.equal(anchor) and kind in ("left", "right"):
                # collapse the selection to the side we're moving towards
                it = min(it, anchor, key=lambda i: i.get_offset()) if kind == "left" else max(it, anchor, key=lambda i: i.get_offset())
            elif kind == "left":
                (it.backward_word_start() if word else it.backward_char())
            elif kind == "right":
                (it.forward_word_end() if word else it.forward_char())
            elif kind in ("up", "down"):
                col = it.get_line_offset()
                line = it.get_line() + (-1 if kind == "up" else 1)
                if 0 <= line < b.get_line_count():
                    ok, it = b.get_iter_at_line(line)
                    it.forward_chars(min(col, max(0, it.get_chars_in_line() - (0 if it.ends_line() else 1))))
                    if it.get_line() != line:
                        ok, it = b.get_iter_at_line(line)
                        it.forward_to_line_end()
            elif kind == "home":
                it.set_line_offset(0)
                while it.get_char() in " \t" and not it.ends_line():
                    it.forward_char()
            elif kind == "end":
                if not it.ends_line():
                    it.forward_to_line_end()
            if pair[0] is b.get_insert():
                if extend:
                    b.move_mark(b.get_insert(), it)
                else:
                    b.place_cursor(it)
            else:
                b.move_mark(pair[0], it)
                if not extend:
                    b.move_mark(pair[1], it)
        self._dedupe()
        self._paint_selections()

    def copy_text(self):
        parts = []
        for pair in sorted(self._cursors(), key=lambda p: self.b.get_iter_at_mark(p[0]).get_offset()):
            c, a = self._iters(pair)
            parts.append(self.b.get_text(*sorted((c, a), key=lambda i: i.get_offset()), True))
        return "\n".join(parts)

    def paste(self, view):
        clip = view.get_clipboard()

        def done(cb, res):
            try:
                text = cb.read_text_finish(res)
            except GLib.Error:
                return
            if text is None:
                return
            pieces = text.split("\n")
            n = self.count()
            if len(pieces) == n:
                # one line per cursor (e.g. after copying with N cursors)
                order = sorted(self._cursors(), key=lambda p: self.b.get_iter_at_mark(p[0]).get_offset())
                mapping = {id(p): pieces[i] for i, p in enumerate(order)}

                def fn(pair):
                    self._delete_sel(pair)
                    self.b.insert(self.b.get_iter_at_mark(pair[0]), mapping[id(pair)])
                    self._collapse(pair)
                self._edit(fn)
            else:
                self.insert(text)
        clip.read_text_async(None, done)

    # ------------------------------------------------------------ keys
    def on_key(self, view, keyval, state):
        """Handle a key while extra cursors exist. Returns True if consumed."""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        k = keyval
        if k == Gdk.KEY_Escape:
            self.clear()
            return True
        if ctrl and not alt:
            name = Gdk.keyval_name(Gdk.keyval_to_lower(k)) or ""
            if name == "c":
                view.get_clipboard().set(self.copy_text())
                return True
            if name == "x":
                view.get_clipboard().set(self.copy_text())
                self.insert("")
                return True
            if name == "v":
                self.paste(view)
                return True
            if k == Gdk.KEY_BackSpace:
                self.backspace(word=True)
                return True
            if k in (Gdk.KEY_Left, Gdk.KEY_Right):
                self.move("left" if k == Gdk.KEY_Left else "right", extend=shift, word=True)
                return True
            if name in ("z", "a", "y"):
                self.clear()
            return False                         # Ctrl+D etc. go to the window actions
        if alt:
            return False
        if k == Gdk.KEY_BackSpace:
            self.backspace()
            return True
        if k == Gdk.KEY_Delete:
            self.delete()
            return True
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.newline()
            return True
        if k in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.insert(self.tab.indent_unit())
            return True
        moves = {Gdk.KEY_Left: "left", Gdk.KEY_Right: "right", Gdk.KEY_Up: "up", Gdk.KEY_Down: "down",
                 Gdk.KEY_Home: "home", Gdk.KEY_End: "end"}
        if k in moves:
            self.move(moves[k], extend=shift)
            return True
        u = Gdk.keyval_to_unicode(k)
        if u and chr(u).isprintable():
            self.insert(chr(u))
            return True
        return False
