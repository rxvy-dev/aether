"""Window features that don't belong in the core: terminals, git glue, symbols, format, zen, themes, preferences."""
import os, shlex, shutil
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gtk, Gdk, GtkSource, GLib, Gio, Pango

try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte
except (ValueError, ImportError):
    Vte = None

from . import gitutil, formatter, symbols, themegen, templates
from .palette import Palette
from .lspui import LspMixin
from .settings import CFG_DIR
from .editor import EditorTab


class ExtrasMixin(LspMixin):
    # ---------------- sidebar / panels ----------------
    def show_sidebar(self, name):
        self.sidebar.set_visible(True)
        self.settings["sidebar"] = True
        self.sidebar.show(name)

    def show_search(self, text=None):
        self.show_sidebar("search")
        if text is None:
            t = self.cur()
            if t and t.buffer.get_has_selection():
                s, e = t.buffer.get_selection_bounds()
                text = t.buffer.get_text(s, e, False)
                if "\n" in text:
                    text = None
        self.sidebar.search.focus(text)

    def toggle_zen(self):
        zen = not getattr(self, "_zen", False)
        self._zen = zen
        if zen:
            self._zen_state = (self.sidebar.get_visible(), self.panel.get_visible())
            self.sidebar.set_visible(False)
            self.panel.set_visible(False)
            self.statusbar.set_visible(False)
            self.crumb.set_visible(False)
            self.get_titlebar().set_visible(False)
            self.fullscreen()
        else:
            sv, pv = getattr(self, "_zen_state", (True, True))
            self.sidebar.set_visible(sv)
            self.panel.set_visible(pv)
            self.statusbar.set_visible(bool(self.settings["show_statusbar"]))
            self.get_titlebar().set_visible(True)
            self.unfullscreen()
            self._on_tab_state(self.cur())

    # ---------------- terminals ----------------
    def new_terminal(self, cwd=None):
        if not Vte:
            self.flash("Terminal support needs VTE for GTK4 (see README)")
            return None
        term = Vte.Terminal()
        term.set_scrollback_lines(10000)
        term.set_hexpand(True)
        term.set_vexpand(True)
        term.set_font(Pango.FontDescription(f"{self.settings['font']} {self.settings['font_size']}"))
        shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
        try:
            term.spawn_async(Vte.PtyFlags.DEFAULT, cwd or self.folder or os.path.expanduser("~"), [shell], None,
                             GLib.SpawnFlags.DEFAULT, None, None, -1, None, None)
        except Exception as e:
            self.flash(f"Terminal failed to start: {e}")
            return None
        self._term_n = getattr(self, "_term_n", 0) + 1
        label = Gtk.Box(spacing=6)
        label.append(Gtk.Label(label=f"Terminal {self._term_n}"))
        close = Gtk.Button(icon_name="window-close-symbolic")
        close.set_has_frame(False)
        label.append(close)
        close.connect("clicked", lambda *_: self._close_term(term))
        idx = self.panel.insert_page(term, label, len(self.terms))
        self.terms.append(term)
        term.connect("child-exited", lambda t, st: self._close_term(t))
        if hasattr(self, "pal"):
            self._theme_term(self.pal["fg"], self.pal["bg"])
        self.panel.set_current_page(idx)
        self.show_panel()
        self._last_term = term
        return term

    def _close_term(self, term):
        idx = self.panel.page_num(term)
        if idx >= 0:
            self.panel.remove_page(idx)
        if term in self.terms:
            self.terms.remove(term)

    def active_term(self):
        i = self.panel.get_current_page()
        w = self.panel.get_nth_page(i) if i >= 0 else None
        if w in self.terms:
            return w
        lt = getattr(self, "_last_term", None)
        if lt in self.terms:
            return lt
        return self.terms[0] if self.terms else None

    def run_in_terminal(self, cmd):
        term = self.active_term() or self.new_terminal()
        if not term:
            self._run_captured(cmd, self.folder or os.path.expanduser("~"))
            return
        self.show_panel(self.panel.page_num(term))
        self._last_term = term
        term.feed_child((cmd + "\n").encode())
        term.grab_focus()

    def focus_terminal(self):
        term = self.active_term() or self.new_terminal()
        if term:
            self.show_panel(self.panel.page_num(term))
            term.grab_focus()

    # ---------------- git glue ----------------
    def set_git_status(self, status, root):
        self.git_status = status
        self.git_root = root
        self.sidebar.files.apply_badges(status)
        b = gitutil.branch(root) if root else None
        self.branch_label.set_text(("⎇ " + b) if b else "")
        for t in self.tabs():
            t.update_git_marks()

    def refresh_git_soon(self):
        if getattr(self, "_git_id", 0):
            GLib.source_remove(self._git_id)
        self._git_id = GLib.timeout_add(500, lambda: (setattr(self, "_git_id", 0), self.sidebar.git.refresh(), False)[2])

    # ---------------- tabs & paths ----------------
    def open_text_tab(self, title, text, lang_id=None):
        tab = EditorTab(self, None)
        tab.untitled_name = title
        tab.tkey = None
        tab.buffer.set_text(text)
        lm = GtkSource.LanguageManager.get_default()
        if lang_id:
            tab.buffer.set_language(lm.get_language(lang_id))
            tab.language = tab.buffer.get_language()
        tab.view.set_editable(False)
        tab.buffer.set_modified(False)
        tab.buffer.place_cursor(tab.buffer.get_start_iter())
        self.add_tab(tab)
        self._on_tab_state(tab)
        return tab

    def reopen_tab(self):
        while self.closed_paths:
            p = self.closed_paths.pop()
            if os.path.exists(p) and not any(t.path == p for t in self.tabs()):
                self.open_path(p)
                return
        self.flash("No closed tabs to reopen")

    def path_renamed(self, old, new):
        for t in self.tabs():
            if t.path and (t.path == old or t.path.startswith(old + os.sep)):
                t.retarget(new + t.path[len(old):])
        self._on_tab_state(self.cur())

    def path_deleted(self, p):
        for t in list(self.tabs()):
            if t.path and (t.path == p or t.path.startswith(p + os.sep)):
                self.close_tab(t, force=True)

    # ---------------- editing helpers ----------------
    def format_document(self, after=None):
        t = self.cur()
        if not t or t.tkey is None:
            self.flash("Nothing to format")
            return
        cmd = formatter.command(t.tkey, t.path, t.view.get_tab_width())
        if cmd is None:
            self.flash(f"No formatter for {t.language.get_name() if t.language else 'this file'}")
            if after:
                after()
            return
        if isinstance(cmd, str):
            self.flash(f"Formatter '{cmd}' not found. Install: {formatter.HINT.get(cmd, cmd)}", 9000)
            if after:
                after()
            return
        text = t.get_text()

        def done(ok, out):
            if not ok:
                self.flash("Format failed: " + out[:140])
            elif out != text:
                t.replace_all_text(out)
                self.flash("Formatted", 1500)
            else:
                self.flash("Already formatted", 1500)
            if after:
                after()
        formatter.run(cmd, text, os.path.dirname(t.path) if t.path else None, done)

    def act_goto_symbol(self):
        t = self.cur()
        if not t or not t.tkey:
            self.flash("No symbols for this file")
            return
        syms = symbols.extract(t.tkey, t.get_text())
        if not syms:
            self.flash("No symbols found")
            return
        items = [(name, f"{kind}  :{ln}", (lambda ln=ln: t.goto(ln))) for ln, kind, name in syms]
        Palette(self, "Go to symbol…", items).present()

    # ---------------- themes / snippets ----------------
    def import_vscode_theme(self):
        self._chooser("Import a VS Code theme (.json)", Gtk.FileChooserAction.OPEN, "Import", self._import_theme_file)

    def _import_theme_file(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                name, pal = themegen.from_vscode(f.read())
        except (OSError, ValueError) as e:
            self.flash(f"Could not read theme: {e}")
            return
        self.install_scheme(name, pal)
        self.flash(f"Imported theme “{name}”")

    def install_scheme(self, name, pal):
        sid = themegen.save_scheme(os.path.join(CFG_DIR, "styles"), name, pal)
        GtkSource.StyleSchemeManager.get_default().force_rescan()
        self.apply_theme(sid)
        return sid

    def open_snippets_dir(self):
        d = os.path.join(CFG_DIR, "snippets")
        os.makedirs(d, exist_ok=True)
        f = os.path.join(d, "my.snippets")
        if not os.path.exists(f):
            with open(f, "w") as fh:
                fh.write('''<?xml version="1.0" encoding="UTF-8"?>
<snippets _group="Mine">
  <!-- Type the trigger in an editor and press Enter on the completion. $1, ${2:default}, $0 = tab stops. -->
  <snippet _name="Print debug (python)" trigger="dbg">
    <text languages="python3;python;"><![CDATA[print(f"${1:value} = {${1:value}!r}")$0]]></text>
  </snippet>
  <snippet _name="Main guard (python)" trigger="ifmain">
    <text languages="python3;python;"><![CDATA[if __name__ == "__main__":
    ${1:main()}]]></text>
  </snippet>
</snippets>
''')
        self.open_path(f)
        self.flash("Edit your snippets here, save, and restart to load them")

    # ---------------- preferences / studio ----------------
    def show_preferences(self, page=None):
        from .prefs import PreferencesWindow
        w = getattr(self, "_prefs", None)
        if w is None or not w.get_visible():
            w = PreferencesWindow(self)
            self._prefs = w
        w.present()
        if page:
            w.show_page(page)

    def show_studio(self):
        from .studio import ThemeStudio
        ThemeStudio(self).present()
