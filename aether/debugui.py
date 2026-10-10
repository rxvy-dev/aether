"""Debugger UI: the Debug sidebar page (controls, variables, watch, call stack, breakpoints)
and the Debug console in the bottom panel."""
import os
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango

from .debugger import value_children


def _btn(label, tip, cb, css=None):
    b = Gtk.Button(label=label, tooltip_text=tip)
    b.add_css_class("flat")
    b.add_css_class("aether-dbg-btn")
    if css:
        b.add_css_class(css)
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


class DebugPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.win = win
        title = Gtk.Label(label="Debugger", xalign=0)
        title.add_css_class("aether-proj")
        self.append(title)

        bar = Gtk.Box(spacing=2)
        bar.set_margin_start(6)
        bar.set_margin_end(6)
        self.b_go = _btn("▶", "Start / continue (F6)", win.debug_continue, "aether-dbg-go")
        self.b_pause = _btn("⏸", "Pause", win.debug_pause)
        self.b_over = _btn("⤼", "Step over (F10)", win.debug_step_over)
        self.b_in = _btn("↓", "Step into (F7)", win.debug_step_into)
        self.b_out = _btn("↑", "Step out (Shift+F7)", win.debug_step_out)
        self.b_restart = _btn("↻", "Restart", win.debug_restart)
        self.b_stop = _btn("■", "Stop (Shift+F6)", win.debug_stop, "aether-dbg-stop")
        for b in (self.b_go, self.b_pause, self.b_over, self.b_in, self.b_out, self.b_restart, self.b_stop):
            bar.append(b)
        self.append(bar)

        self.status = Gtk.Label(label="Not running — set breakpoints with F9 or by clicking the gutter, then press F6.",
                                xalign=0, wrap=True)
        self.status.add_css_class("aether-hint")
        self.status.set_margin_bottom(4)
        self.append(self.status)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_child(content)
        self.append(sw)

        # variables
        content.append(_section("Variables"))
        self.var_store = Gtk.TreeStore(str, str, str)      # name, value, markup
        self.var_view = self._tree(self.var_store)
        content.append(self.var_view)

        # watch
        wh = Gtk.Box()
        wh.append(_section("Watch"))
        content.append(wh)
        self.watch_entry = Gtk.Entry(placeholder_text="Add expression (e.g. arr[i] * 2)")
        self.watch_entry.set_margin_start(8)
        self.watch_entry.set_margin_end(8)
        self.watch_entry.connect("activate", self._add_watch)
        content.append(self.watch_entry)
        self.watch_box = Gtk.ListBox()
        self.watch_box.add_css_class("aether-dbg-list")
        content.append(self.watch_box)

        # call stack
        content.append(_section("Call stack"))
        self.stack_box = Gtk.ListBox()
        self.stack_box.add_css_class("aether-dbg-list")
        self.stack_box.connect("row-activated", self._on_frame)
        content.append(self.stack_box)

        # breakpoints
        bh = Gtk.Box()
        bh.append(_section("Breakpoints"))
        sp = Gtk.Box(hexpand=True)
        bh.append(sp)
        clr = Gtk.Button(label="clear all", tooltip_text="Remove all breakpoints")
        clr.add_css_class("flat")
        clr.add_css_class("aether-link-small")
        clr.connect("clicked", lambda *_: win.clear_breakpoints())
        bh.append(clr)
        content.append(bh)
        self.bp_box = Gtk.ListBox()
        self.bp_box.add_css_class("aether-dbg-list")
        self.bp_box.connect("row-activated", self._on_bp)
        content.append(self.bp_box)
        self.set_running(False, False)

    def _tree(self, store):
        tv = Gtk.TreeView(model=store)
        tv.set_headers_visible(False)
        tv.add_css_class("aether-dbg-tree")
        r = Gtk.CellRendererText()
        r.set_property("ellipsize", Pango.EllipsizeMode.END)
        col = Gtk.TreeViewColumn("v", r, markup=2)
        col.set_expand(True)
        tv.append_column(col)
        tv.set_tooltip_column(1)
        tv.set_margin_start(4)
        return tv

    # ---------- state ----------
    def set_running(self, active, stopped):
        self.b_go.set_tooltip_text("Continue (F6)" if active else "Start debugging (F6)")
        for b in (self.b_over, self.b_in, self.b_out):
            b.set_sensitive(active and stopped)
        self.b_pause.set_sensitive(active and not stopped)
        self.b_stop.set_sensitive(active)
        self.b_restart.set_sensitive(active)
        self.b_go.set_sensitive(not active or stopped)

    def set_status(self, text):
        self.status.set_text(text)

    # ---------- variables ----------
    def set_vars(self, vars_):
        st = self.var_store
        st.clear()
        if not vars_:
            st.append(None, ["", "", '<span alpha="50%">no variables here</span>'])
            return
        for name, value, kind in vars_:
            self._add_var(None, name, value, kind == "arg")

    def _add_var(self, parent, name, value, is_arg=False, depth=0):
        kids = value_children(value) if depth < 6 else None
        shown = value if kids is None else ("{…}" if len(value) > 60 else value)
        esc = GLib.markup_escape_text
        nm = f'<span foreground="{self.win.accent}">{esc(name)}</span>' if is_arg else f"<b>{esc(name)}</b>"
        it = self.var_store.append(parent, [name, value, f'{nm} = <span font_family="monospace">{esc(shown[:200])}</span>'])
        if kids:
            for kn, kv in kids[:200]:
                self._add_var(it, kn, kv, False, depth + 1)

    # ---------- watch ----------
    def _add_watch(self, entry):
        expr = entry.get_text().strip()
        if expr:
            self.win.debug_add_watch(expr)
            entry.set_text("")

    def set_watches(self, watches):
        _clear(self.watch_box)
        esc = GLib.markup_escape_text
        for i, (expr, val) in enumerate(watches):
            row = Gtk.Box(spacing=6)
            l = Gtk.Label(xalign=0, hexpand=True)
            l.set_ellipsize(Pango.EllipsizeMode.END)
            l.set_markup(f'<b>{esc(expr)}</b> = <span font_family="monospace">{esc(val or "—")}</span>')
            l.set_tooltip_text(f"{expr} = {val}")
            row.append(l)
            x = Gtk.Button(label="×", tooltip_text="Remove")
            x.add_css_class("flat")
            x.connect("clicked", lambda _b, i=i: self.win.debug_remove_watch(i))
            row.append(x)
            self.watch_box.append(row)

    # ---------- call stack ----------
    def set_frames(self, frames, current_level=0):
        _clear(self.stack_box)
        esc = GLib.markup_escape_text
        for f in frames:
            row = Gtk.ListBoxRow()
            row._frame = f
            lvl = int(f.get("level", 0))
            loc = f"{os.path.basename(f.get('file', '') or f.get('from', '??'))}:{f.get('line', '?')}"
            l = Gtk.Label(xalign=0)
            l.set_ellipsize(Pango.EllipsizeMode.END)
            mark = "▶ " if lvl == current_level else "   "
            l.set_markup(f'{mark}<b>{esc(f.get("func", "??"))}</b>  <span alpha="55%">{esc(loc)}</span>')
            row.set_child(l)
            self.stack_box.append(row)

    def _on_frame(self, lb, row):
        f = getattr(row, "_frame", None)
        if f:
            self.win.debug_select_frame(f)

    # ---------- breakpoints ----------
    def set_breakpoints(self, bps):
        _clear(self.bp_box)
        if not bps:
            l = Gtk.Label(label="none", xalign=0)
            l.add_css_class("aether-hint")
            self.bp_box.append(l)
            return
        for path, line0 in bps:
            row = Gtk.ListBoxRow()
            row._bp = (path, line0)
            box = Gtk.Box(spacing=6)
            dot = Gtk.Label(label="●")
            dot.add_css_class("aether-bp-dot")
            box.append(dot)
            l = Gtk.Label(label=f"{os.path.basename(path)}:{line0 + 1}", xalign=0, hexpand=True)
            l.set_tooltip_text(path)
            box.append(l)
            x = Gtk.Button(label="×", tooltip_text="Remove")
            x.add_css_class("flat")
            x.connect("clicked", lambda _b, p=path, ln=line0: self.win.remove_breakpoint(p, ln))
            box.append(x)
            row.set_child(box)
            self.bp_box.append(row)

    def _on_bp(self, lb, row):
        bp = getattr(row, "_bp", None)
        if bp:
            self.win.open_path(bp[0], bp[1] + 1)


class DebugConsole(Gtk.Box):
    """Bottom-panel tab: gdb output + a prompt for raw gdb commands."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(10)
        self.view.set_top_margin(6)
        b = self.view.get_buffer()
        b.create_tag("error", foreground="#f7768e")
        b.create_tag("log", foreground="#7c7f93")
        b.create_tag("info", foreground="#7aa2f7", weight=700)
        b.create_tag("program", foreground="#c0caf5")
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_child(self.view)
        self.sw = sw
        self.append(sw)
        self.entry = Gtk.Entry(placeholder_text="gdb command (e.g.  print arr[3]   info registers   x/8xb ptr)")
        self.entry.add_css_class("aether-dbg-entry")
        self.entry.connect("activate", self._send)
        self.append(self.entry)

    def write(self, text, kind="console"):
        b = self.view.get_buffer()
        end = b.get_end_iter()
        if kind in ("error", "log", "info", "program"):
            b.insert_with_tags_by_name(end, text, kind)
        else:
            b.insert(end, text)
        if b.get_line_count() > 5000:
            s = b.get_start_iter()
            ok, e = b.get_iter_at_line(1000)
            b.delete(s, e)
        GLib.idle_add(self._scroll)

    def _scroll(self):
        adj = self.sw.get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    def clear(self):
        self.view.get_buffer().set_text("")

    def _send(self, entry):
        t = entry.get_text().strip()
        if t:
            self.write(f"(gdb) {t}\n", "info")
            self.win.debug_console_command(t)
            entry.set_text("")
