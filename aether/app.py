import os, sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gtk, Gio, GLib, GtkSource

from . import APP_ID, NAME
from .settings import Settings
from .window import AetherWindow


class AetherApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        GLib.set_application_name(NAME)
        GLib.set_prgname("aether")
        self.win = None
        self.settings = None

    def _window(self):
        if not self.win:
            GtkSource.init()
            self.settings = Settings()
            self.win = AetherWindow(self, self.settings)
            self.win._fresh = True
        return self.win

    def do_activate(self):
        w = self._window()
        if getattr(w, "_fresh", False):
            w._fresh = False
            s = self.settings["session"] or {}
            if s.get("folder") and os.path.isdir(s["folder"]):
                w.open_folder(s["folder"])
            for p in s.get("files", []):
                if os.path.isfile(p):
                    w.open_path(p)
            if w.notebook.get_n_pages():
                w.notebook.set_current_page(min(s.get("active", 0), w.notebook.get_n_pages() - 1))
        w.present()

    def do_open(self, files, n_files, hint):
        w = self._window()
        w._fresh = False
        for f in files:
            w.open_path(f.get_path())
        w.present()


def main(argv=None):
    return AetherApp().run(argv if argv is not None else sys.argv)
