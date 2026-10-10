import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib


def fuzzy(q, s):
    q, s = q.lower(), s.lower()
    i = 0
    for ch in q:
        i = s.find(ch, i)
        if i < 0:
            return False
        i += 1
    return True


class Palette(Gtk.Window):
    """Command palette / quick open / prompt in one small floating window."""

    def __init__(self, win, placeholder, items=None, on_text=None, initial=""):
        super().__init__(transient_for=win, modal=True, decorated=False, resizable=False)
        self.win = win
        self.items = items or []
        self.on_text = on_text
        self.set_default_size(580, 360 if items else 1)
        self.add_css_class("aether-palette")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(8); box.set_margin_bottom(8); box.set_margin_start(8); box.set_margin_end(8)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text(placeholder)
        self.entry.set_text(initial)
        box.append(self.entry)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.set_activate_on_single_click(True)
        if self.items:
            sw = Gtk.ScrolledWindow()
            sw.set_vexpand(True)
            sw.set_child(self.list)
            box.append(sw)
        self.set_child(box)
        for label, sub, cb in self.items:
            row = Gtk.ListBoxRow()
            h = Gtk.Box(spacing=12)
            h.set_margin_top(4); h.set_margin_bottom(4); h.set_margin_start(6); h.set_margin_end(6)
            l1 = Gtk.Label(label=label, xalign=0)
            l1.set_hexpand(True)
            h.append(l1)
            if sub:
                l2 = Gtk.Label(label=sub, xalign=1)
                l2.add_css_class("dim-label")
                h.append(l2)
            row.set_child(h)
            row._label, row._cb = label + " " + (sub or ""), cb
            self.list.append(row)
        self.list.set_filter_func(self._filter)
        self.entry.connect("changed", self._changed)
        self.entry.connect("activate", self._activate)
        self.list.connect("row-activated", lambda _l, row: self._run(row))
        kc = Gtk.EventControllerKey()
        kc.connect("key-pressed", self._key)
        self.entry.add_controller(kc)
        kw = Gtk.EventControllerKey()
        kw.connect("key-pressed", lambda c, k, *a: (self.close(), True)[1] if k == Gdk.KEY_Escape else False)
        self.add_controller(kw)
        self.connect("notify::is-active", lambda w, _p: (not w.is_active()) and GLib.idle_add(w.close))
        self._select_first()

    def _filter(self, row):
        return fuzzy(self.entry.get_text().strip(), row._label)

    def _changed(self, *_):
        self.list.invalidate_filter()
        self._select_first()

    def _visible_rows(self):
        r = self.list.get_first_child()
        while r:
            if r.get_child_visible() and self._filter(r):
                yield r
            r = r.get_next_sibling()

    def _select_first(self):
        for r in self._visible_rows():
            self.list.select_row(r)
            return

    def _key(self, ctl, keyval, kc, st):
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up) and self.items:
            rows = list(self._visible_rows())
            cur = self.list.get_selected_row()
            i = rows.index(cur) if cur in rows else -1
            i = min(len(rows) - 1, i + 1) if keyval == Gdk.KEY_Down else max(0, i - 1)
            if rows:
                self.list.select_row(rows[i])
                rows[i].grab_focus(); self.entry.grab_focus()
            return True
        return False

    def _activate(self, *_):
        if self.on_text:
            txt = self.entry.get_text()
            self.close()
            self.on_text(txt)
            return
        row = self.list.get_selected_row()
        if row:
            self._run(row)

    def _run(self, row):
        cb = row._cb
        self.close()
        GLib.idle_add(lambda: (cb(), False)[1])
