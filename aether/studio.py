"""Theme studio: edit every colour of a theme with a live preview, save it, or import from VS Code."""
import os
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gtk, Gdk, GLib, GtkSource

from . import themegen
from .prefs import hexof
from .settings import CFG_DIR

SAMPLE = '''#include <stdio.h>
#define LIMIT 10

/* Print a countdown. */
static int countdown(int from) {
    for (int i = from; i > 0; --i) {
        printf("T-minus %d\\n", i);   // launch soon
    }
    return from > LIMIT ? -1 : 0;
}

int main(void) {
    const char *name = "Aether";
    printf("Hello, %s! 0x2A %.2f\\n", name, 3.14);
    return countdown(3);
}
'''


class ThemeStudio(Gtk.Window):
    def __init__(self, win):
        super().__init__(title="Theme studio", transient_for=win, default_width=1000, default_height=640)
        self.win = win
        self.add_css_class("aether-prefs")
        self.mgr = GtkSource.StyleSchemeManager.get_default()
        self.pal = themegen.scheme_to_palette(self.mgr.get_scheme(win.settings["theme"]))
        self.buttons = {}
        self._deb = 0
        self.preview_dir = os.path.join(CFG_DIR, "styles")
        box = Gtk.Box(spacing=0)
        self.set_child(box)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(left, f"set_margin_{m}")(18)
        left.set_size_request(340, -1)
        box.append(left)
        h = Gtk.Label(label="Start from", xalign=0)
        h.add_css_class("heading")
        left.append(h)
        ids = win.theme_ids()
        names = [self.mgr.get_scheme(i).get_name() for i in ids]
        self.ids = ids
        self.dd = Gtk.DropDown.new_from_strings(names)
        self.dd.set_selected(ids.index(win.settings["theme"]) if win.settings["theme"] in ids else 0)
        self.dd.connect("notify::selected", self._from_scheme)
        left.append(self.dd)
        self.name = Gtk.Entry()
        self.name.set_placeholder_text("Name of your theme")
        self.name.set_text("My theme")
        left.append(self.name)
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        for i, k in enumerate(themegen.KEYS):
            grid.attach(Gtk.Label(label=themegen.LABELS[k], xalign=0, hexpand=True), 0, i, 1, 1)
            b = Gtk.ColorButton()
            b.connect("color-set", lambda btn, k=k: self._color_set(k, btn))
            grid.attach(b, 1, i, 1, 1)
            self.buttons[k] = b
        sw.set_child(grid)
        left.append(sw)
        row = Gtk.Box(spacing=8)
        imp = Gtk.Button(label="Import VS Code…")
        imp.connect("clicked", lambda *_: self.win.import_vscode_theme())
        save = Gtk.Button(label="Save and use")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._save)
        row.append(imp)
        row.append(save)
        left.append(row)

        self.buf = GtkSource.Buffer()
        lm = GtkSource.LanguageManager.get_default()
        self.buf.set_language(lm.get_language("c"))
        self.buf.set_text(SAMPLE)
        self.view = GtkSource.View.new_with_buffer(self.buf)
        self.view.set_show_line_numbers(True)
        self.view.set_highlight_current_line(True)
        self.view.set_editable(False)
        self.view.set_monospace(True)
        self.view.add_css_class("aether-code")
        self.view.set_left_margin(14)
        self.view.set_top_margin(12)
        psw = Gtk.ScrolledWindow()
        psw.set_hexpand(True)
        psw.set_child(self.view)
        box.append(psw)
        self.connect("close-request", self._on_close)
        self._sync_buttons()
        self._render()

    def _sync_buttons(self):
        for k, b in self.buttons.items():
            c = Gdk.RGBA()
            c.parse(self.pal[k])
            b.set_rgba(c)

    def _from_scheme(self, *_):
        sc = self.mgr.get_scheme(self.ids[self.dd.get_selected()])
        self.pal = themegen.scheme_to_palette(sc)
        self.name.set_text(sc.get_name() + " (custom)")
        self._sync_buttons()
        self._render()

    def _color_set(self, k, btn):
        self.pal[k] = hexof(btn.get_rgba())
        if self._deb:
            GLib.source_remove(self._deb)
        self._deb = GLib.timeout_add(150, lambda: (setattr(self, "_deb", 0), self._render(), False)[2])

    def _render(self):
        os.makedirs(self.preview_dir, exist_ok=True)
        with open(os.path.join(self.preview_dir, "studio-preview.xml"), "w") as f:
            f.write(themegen.scheme_xml("studio-preview", "Preview", self.pal))
        self.mgr.force_rescan()
        sc = self.mgr.get_scheme("studio-preview")
        if sc:
            self.buf.set_style_scheme(sc)

    def _save(self, *_):
        name = self.name.get_text().strip() or "My theme"
        self.win.install_scheme(name, dict(self.pal))
        self.win.flash(f"Saved theme “{name}”")
        self.close()

    def _on_close(self, *_):
        try:
            os.remove(os.path.join(self.preview_dir, "studio-preview.xml"))
            self.mgr.force_rescan()
        except OSError:
            pass
        return False
