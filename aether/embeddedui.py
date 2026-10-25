"""Embedded boards in the main window: board / port pickers, upload, serial monitor, library install,
the *Device* sidebar page and the status-bar chip.  Logic that needs no GTK lives in embedded.py."""
import os, re, shlex
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango

from . import embedded, project
from .palette import Palette
from .serialmon import SerialMonitor

SKETCH_EXT = (".ino", ".pde")


def _section(title):
    l = Gtk.Label(label=title.upper(), xalign=0)
    l.add_css_class("aether-section")
    return l


def _btn(label, tip, cb, wide=False):
    b = Gtk.Button(label=label, tooltip_text=tip)
    b.add_css_class("flat")
    b.connect("clicked", lambda *_: cb())
    if wide:
        b.set_hexpand(True)
        b.get_child().set_xalign(0)
    return b


class DevicePage(Gtk.Box):
    """Sidebar page: the board, the port, one-click actions, libraries, board support and attached devices."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.win = win
        title = Gtk.Label(label="Boards & serial", xalign=0)
        title.add_css_class("aether-proj")
        self.append(title)
        self.info = Gtk.Label(label="", xalign=0, wrap=True)
        self.info.add_css_class("aether-hint")
        self.append(self.info)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_child(box)
        self.append(sw)

        box.append(_section("Board"))
        self.board_b = _btn("Select board…", "Choose the board you are building for", win.emb_pick_board, True)
        self.port_b = _btn("Select port…", "Choose the serial port of the board", win.emb_pick_port, True)
        box.append(self.board_b)
        box.append(self.port_b)

        box.append(_section("Actions"))
        grid = Gtk.Grid(column_spacing=2, row_spacing=2, column_homogeneous=True)
        grid.set_margin_start(6)
        grid.set_margin_end(6)
        for i, (label, tip, cb) in enumerate([
                ("Build", "Compile (Ctrl+Shift+B)", win.act_build), ("Upload", "Build and upload (Ctrl+Alt+U)", lambda: win.emb_upload(False)),
                ("Monitor", "Open the serial monitor (Ctrl+Alt+M)", win.emb_monitor), ("Upload + monitor", "Upload, then watch the output (F5)", win.act_run)]):
            b = Gtk.Button(label=label, tooltip_text=tip)
            b.connect("clicked", lambda _b, cb=cb: cb())
            grid.attach(b, i % 2, i // 2, 1, 1)
        box.append(grid)

        box.append(_section("Libraries"))
        row = Gtk.Box(spacing=4)
        row.set_margin_start(8)
        row.set_margin_end(8)
        self.lib = Gtk.Entry(hexpand=True, placeholder_text="Library / package name")
        self.lib.connect("activate", lambda *_: self._lib(False))
        row.append(self.lib)
        row.append(_btn("Install", "Install the library into this project / toolchain", lambda: self._lib(False)))
        row.append(_btn("Search", "Search the library index", lambda: self._lib(True)))
        box.append(row)

        box.append(_section("Setup"))
        box.append(_btn("Install board support", "Download the compiler / core for the selected board", win.emb_board_setup, True))
        self.tools = Gtk.Label(label="", xalign=0, wrap=True, selectable=True)
        self.tools.add_css_class("aether-hint")
        box.append(self.tools)

        head = Gtk.Box()
        head.append(_section("Devices"))
        sp = Gtk.Box(hexpand=True)
        head.append(sp)
        rescan = Gtk.Button(label="rescan", tooltip_text="Look for serial devices again")
        rescan.add_css_class("flat")
        rescan.add_css_class("aether-link-small")
        rescan.connect("clicked", lambda *_: win.emb_refresh(True))
        head.append(rescan)
        box.append(head)
        self.devices = Gtk.ListBox()
        self.devices.add_css_class("aether-dbg-list")
        self.devices.connect("row-activated", self._on_device)
        box.append(self.devices)

    def _lib(self, search):
        name = self.lib.get_text().strip()
        if not name:
            self.win.flash("Type the name of a library first")
            return
        self.win.emb_lib(name, search)

    def _on_device(self, lb, row):
        path = getattr(row, "_path", None)
        if path:
            self.win.emb_port_chosen(path)

    def update(self, proj, ports, port, board_name, baud):
        if proj is None:
            self.info.set_text("Open an Arduino sketch (.ino), a PlatformIO or ESP-IDF project, or a MicroPython folder "
                               "— or create one with New project (Ctrl+Alt+N).")
            self.board_b.get_child().set_label("Select board…")
            self.tools.set_text("")
        else:
            self.info.set_text(f"{proj.name} — {proj.kind}" + (f", {baud} baud" if baud else ""))
            self.board_b.get_child().set_label(f"Board: {board_name}" if board_name else "Select board…")
            self.tools.set_text(embedded.install_hint(proj.kind, proj.cfg) or "")
        self.port_b.get_child().set_label(f"Port: {os.path.basename(port)}" if port else "Select port…")
        c = self.devices.get_first_child()
        while c:
            n = c.get_next_sibling()
            self.devices.remove(c)
            c = n
        if not ports:
            l = Gtk.Label(label="no serial device found", xalign=0)
            l.add_css_class("aether-hint")
            self.devices.append(l)
        for p in ports:
            row = Gtk.ListBoxRow()
            row._path = p.path
            lab = Gtk.Label(label=("● " if p.path == port else "   ") + p.label, xalign=0)
            lab.set_ellipsize(Pango.EllipsizeMode.END)
            lab.set_margin_start(8)
            lab.set_margin_top(3)
            lab.set_margin_bottom(3)
            row.set_child(lab)
            self.devices.append(row)


class EmbeddedMixin:
    """Mixed into AetherWindow. Everything is prefixed emb_ / _emb_ to stay out of the way."""

    _sketch_proj = None
    _emb_sig = None

    EMB_COMMANDS = [
        ("Embedded: upload to board", "upload"), ("Embedded: open serial monitor", "serial_monitor"),
        ("Embedded: select board…", "select_board"), ("Embedded: select serial port…", "select_port"),
        ("Embedded: reset board", "reset_board"), ("Embedded: install library / package…", "install_library"),
        ("Embedded: search libraries…", "search_library"), ("Embedded: install board support", "board_setup"),
        ("Embedded: show boards & serial", "show_device"),
    ]

    # ================================================================ setup
    def _emb_setup(self):
        self._sketch_proj = None
        self._emb_sig = None
        self.serial = SerialMonitor(self)
        self.panel.append_page(self.serial, Gtk.Label(label="Serial"))
        self.board_btn = Gtk.Button(label="", tooltip_text="Board and serial port")
        self.board_btn.add_css_class("flat")
        self.board_btn.add_css_class("aether-status-btn")
        self.board_btn.connect("clicked", lambda *_: self.emb_menu())
        self.board_btn.set_visible(False)
        self.statusbar.insert_child_after(self.board_btn, self.project_label)
        self.emb_refresh(True)

    def _emb_callbacks(self):
        return {
            "upload": lambda *_: self.emb_upload(False), "serial_monitor": lambda *_: self.emb_monitor(),
            "select_board": lambda *_: self.emb_pick_board(), "select_port": lambda *_: self.emb_pick_port(),
            "reset_board": lambda *_: self.serial.reset_board() if self.serial.connected else self.flash("Open the serial monitor first (Ctrl+Alt+M)"),
            "install_library": lambda *_: Palette(self, "Library / package to install (e.g. Adafruit NeoPixel)",
                                                  on_text=lambda t: t.strip() and self.emb_lib(t.strip(), False)).present(),
            "search_library": lambda *_: Palette(self, "Search libraries for…",
                                                 on_text=lambda t: t.strip() and self.emb_lib(t.strip(), True)).present(),
            "board_setup": lambda *_: self.emb_board_setup(), "show_device": lambda *_: self.show_sidebar("device"),
        }

    # ================================================================ which project?
    def _emb_port(self):
        return (self.settings["serial"] or {}).get("port", "")

    def emb_project(self, fresh=False):
        """The embedded project actions apply to: the open folder's, or the folder of the open .ino sketch."""
        p = self.project
        t = self.cur()
        ino = t.path if (t and t.path and t.path.lower().endswith(SKETCH_EXT)) else None
        if ino and not (p and p.embedded and ino.startswith(p.root + os.sep)):
            folder = os.path.dirname(ino)
            sp = self._sketch_proj
            if sp is None or sp.root != folder:
                sp = self._sketch_proj = project.Project(folder, port=self._emb_port())
            elif fresh:
                sp.port = self._emb_port()
                sp.cfg = project.read_cfg(sp.root)
                sp.refresh()
            return sp if sp.embedded else None
        if p and p.embedded:
            if fresh:
                p.port = self._emb_port()
                p.cfg = project.read_cfg(p.root)
                p.refresh()
            return p
        return None

    # ================================================================ status chip, toolbar button, sidebar page
    def emb_refresh(self, force=False):
        if getattr(self, "board_btn", None) is None:
            return
        p = self.emb_project(fresh=force)
        sig = (p.root if p else None, id(p))
        if not force and sig == self._emb_sig:
            return
        self._emb_sig = sig
        ports = embedded.list_ports()
        port = embedded.default_port(self._emb_port(), ports)
        name, _b = embedded.board_info(p.kind, p.root, p.cfg) if p else ("", None)
        baud = embedded.guess_baud(p.kind, p.root, p.cfg, self.serial.selected_baud()) if p else 0
        self.board_btn.set_visible(p is not None)
        self.upload_btn.set_visible(p is not None)
        if p:
            self.board_btn.set_label(f"◆ {name or 'no board'}  ·  {os.path.basename(port) if port else 'no port'}")
        self.sidebar.device.update(p, ports, port, name, baud)

    def emb_state_changed(self):
        self.emb_refresh(True)

    def emb_reset_style(self):
        p = self.emb_project()
        if p:
            _n, b = embedded.board_info(p.kind, p.root, p.cfg)
            if b:
                return b.reset
            if p.kind == "ESP-IDF":
                return "rts"
        return "dtr"

    def emb_menu(self):
        items = [("Select board…", "", self.emb_pick_board), ("Select serial port…", "", self.emb_pick_port),
                 ("Upload", "Ctrl+Alt+U", lambda: self.emb_upload(False)), ("Upload and open serial monitor", "F5", lambda: self.emb_upload(True)),
                 ("Open serial monitor", "Ctrl+Alt+M", self.emb_monitor), ("Install board support", "", self.emb_board_setup),
                 ("Show boards & serial", "", lambda: self.show_sidebar("device"))]
        Palette(self, "Board and serial port", items).present()

    # ================================================================ pickers
    def emb_pick_port(self, after=None):
        ports = embedded.list_ports()
        if not ports:
            self.flash("No serial device found — plug in the board (use a data cable, not a charge-only one)", 8000)
            return
        items = [(p.label, "", (lambda p=p: (self.emb_port_chosen(p.path), after and after()))) for p in ports]
        Palette(self, "Choose the serial port of your board", items).present()

    def emb_port_chosen(self, path):
        s = dict(self.settings["serial"] or {})
        s["port"] = path
        self.settings["serial"] = s
        for p in (self.project, self._sketch_proj):
            if p:
                p.port = path
                p.refresh()
        self.serial.set_port(path)
        self.emb_refresh(True)

    def emb_pick_board(self, after=None, proj=None):
        proj = proj or self.emb_project(fresh=True)
        if not proj:
            self.flash("Open an Arduino / PlatformIO / ESP-IDF project (or a .ino sketch) first")
            return
        items = []
        if proj.kind == "ESP-IDF":
            items = [(name, chip, (lambda c=chip: self._emb_set_idf_target(proj, c, after))) for chip, name in embedded.IDF_TARGETS]
            prompt = "Choose the ESP32 chip (runs idf.py set-target)"
        elif proj.kind in ("Arduino", "PlatformIO"):
            ard = proj.kind == "Arduino"
            items = [(b.name, b.fqbn if ard else b.pio, (lambda b=b: self._emb_set_board(proj, b, after))) for b in embedded.BOARDS]
            what = "FQBN, e.g. arduino:avr:uno" if ard else "PlatformIO board id, e.g. nodemcuv2"
            items.append((f"Other… (type a {what})", "", lambda: Palette(
                self, f"Board {what}", on_text=lambda t: t.strip() and self._emb_set_custom(proj, t.strip(), after)).present()))
            prompt = "Choose your board"
        else:
            self.flash("MicroPython projects don't need a board — just pick the serial port")
            return
        Palette(self, prompt, items).present()

    def _emb_reload(self, path):
        for t in self.tabs():
            if t.path == path and not t.buffer.get_modified():
                t.load(path)

    def _emb_board_done(self, proj, name, after):
        proj.refresh()
        self._emb_sig = None
        self.emb_refresh(True)
        hint = "  —  first time with this board? Install board support in the Device panel" if proj.kind == "Arduino" else ""
        self.toast(f"Board: {name}{hint}", "info", 4500)
        if after:
            after()

    def _emb_set_board(self, proj, b, after=None):
        self.save_all()
        if proj.kind == "Arduino":
            embedded.write_sketch_yaml(proj.root, b.fqbn)          # sketch.yaml is the one source of truth (also used by arduino-cli / IDE 2)
            if proj.cfg.get("board") or proj.cfg.get("fqbn"):
                proj.save_cfg(board=None, fqbn=None)
            self._emb_reload(os.path.join(proj.root, "sketch.yaml"))
        else:
            if not embedded.pio_set_board(proj.root, b.id, embedded.pio_env(proj.root, proj.cfg)):
                self.flash("No [env:…] section found in platformio.ini")
                return
            self._emb_reload(os.path.join(proj.root, "platformio.ini"))
        self._emb_board_done(proj, b.name, after)

    def _emb_set_custom(self, proj, text, after=None):
        self.save_all()
        if proj.kind == "Arduino":
            embedded.write_sketch_yaml(proj.root, text)
            if proj.cfg.get("board") or proj.cfg.get("fqbn"):
                proj.save_cfg(board=None, fqbn=None)
            self._emb_reload(os.path.join(proj.root, "sketch.yaml"))
        elif not embedded.pio_set_board(proj.root, text, embedded.pio_env(proj.root, proj.cfg)):
            self.flash("No [env:…] section found in platformio.ini")
            return
        self._emb_board_done(proj, text, after)

    def _emb_set_idf_target(self, proj, chip, after=None):
        proj.save_cfg(chip=chip, board=None)
        self.show_build_panel()
        self._emb_run(proj, "configure", f"Set target {chip}", lambda ok: ok and self._emb_board_done(proj, chip, after))

    # ================================================================ running tasks
    def _emb_missing_tool(self, hint):
        self.flash(hint, 15000)
        self._write_output(hint + "\n")
        self.show_panel(self.panel.page_num(self.output_sw))

    def _emb_build_text(self):
        b = self.build.view.get_buffer()
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def _emb_prepare(self, proj, task, cb, need_port=False):
        """Check the toolchain, pick a port / board if needed, then call cb(proj)."""
        hint = embedded.install_hint(proj.kind, proj.cfg)
        if hint:
            self._emb_missing_tool(hint)
            return
        if need_port and not proj.cfg.get("upload"):
            ports = embedded.list_ports()
            port = embedded.default_port(self._emb_port(), ports)
            if not port:
                if not ports:
                    self.flash("No serial device found — plug in the board (use a data cable, not a charge-only one)", 9000)
                    self.show_panel(self.panel.page_num(self.serial))
                    self.serial._info("No serial device found. Plug in the board and try again.", "error")
                else:
                    self.emb_pick_port(lambda: self._emb_prepare(proj, task, cb, need_port))
                return
            problem = embedded.port_problem(port)
            if problem:
                self.flash(problem, 15000)
                self.show_panel(self.panel.page_num(self.serial))
                self.serial._info(problem, "error")
                return
            if port != proj.port:
                self.emb_port_chosen(port)
                proj.port = port
                proj.refresh()
        need = embedded.missing(proj.kind, proj.root, proj.cfg, proj.port, task)
        if "board" in need:
            self.emb_pick_board(lambda: self._emb_prepare(proj, task, cb, need_port), proj)
            return
        cb(proj)

    def _emb_run(self, proj, task, label, done=None, retry=True):
        cmd = proj.tasks.get(task)
        if not cmd:
            self.flash(f"This {proj.kind} project has no '{task}' task — add one in Project settings")
            return
        self.show_build_panel()

        def finished(ok):
            if not ok and retry and proj.kind == "Arduino" and proj.tasks.get("configure") and re.search(
                    r"platform[^\n]*not (installed|found)|not installed[^\n]*platform|core[^\n]*not installed",
                    self._emb_build_text(), re.I):
                self.toast("Board support is missing — installing it first…", "info", 4000)
                self.build.run("Install board support", proj.tasks["configure"], proj.root,
                               lambda ok2: ok2 and self._emb_run(proj, task, label, done, retry=False))
                return
            if done:
                done(ok)
        self.build.run(label, cmd, proj.root, finished)

    def emb_build(self, done=None, proj=None):
        proj = proj or self.emb_project(fresh=True)
        self.save_all()
        self._emb_prepare(proj, "build", lambda p: self._emb_run(p, "build", "Build", done))
        return True

    def emb_task(self, name, proj=None):
        proj = proj or self.emb_project(fresh=True)
        self.save_all()
        self._emb_prepare(proj, name, lambda p: self._emb_run(p, name, name.title()), need_port=(name == "upload"))

    def emb_board_setup(self):
        proj = self.emb_project(fresh=True)
        if not proj:
            self.flash("Open an embedded project first")
            return
        if not proj.tasks.get("configure"):
            self.flash("Nothing to install — pick a board first" if proj.kind == "Arduino" else f"{proj.kind} installs what it needs by itself")
            return
        self._emb_prepare(proj, "configure", lambda p: self._emb_run(p, "configure", "Install board support" if p.kind == "Arduino" else "Configure"))

    def emb_upload(self, monitor=True, proj=None):
        proj = proj or self.emb_project(fresh=True)
        if not proj:
            self.flash("Open an Arduino sketch, PlatformIO / ESP-IDF project or MicroPython folder first")
            return
        if self.build.running:
            self.flash("A task is still running — stop it first")
            return
        self.save_all()
        self._emb_prepare(proj, "upload", lambda p: self._emb_do_upload(p, monitor), need_port=True)

    def _emb_do_upload(self, proj, monitor):
        before = self.serial.release()                 # the port must be free for the uploader

        def after(ok):
            baud = embedded.guess_baud(proj.kind, proj.root, proj.cfg, before[1] if before else self.serial.selected_baud())
            if ok and (monitor or before):
                self.show_panel(self.panel.page_num(self.serial))
                self.serial.reconnect_later((proj.port, baud), 1800)
            elif before:
                self.serial.reconnect_later(before, 400)
        label = "Flash" if proj.kind == "ESP-IDF" else "Upload"
        self._emb_run(proj, "upload", label, after)

    def emb_run(self, proj=None):
        """F5 on an embedded project: MicroPython runs the script on the board; others upload and watch the output."""
        proj = proj or self.emb_project(fresh=True)
        if not proj:
            return False
        if proj.kind == "MicroPython":
            self.save_all()

            def go(p):
                self.serial.release()
                self.show_panel()
                self.run_in_terminal(f"clear; cd {shlex.quote(p.root)} && {p.tasks['run']}")
            self._emb_prepare(proj, "run", go, need_port=True)
            return True
        self.emb_upload(True, proj)
        return True

    def emb_monitor(self):
        proj = self.emb_project(fresh=True)
        self.show_panel(self.panel.page_num(self.serial))
        if proj:
            self.serial.set_baud(embedded.guess_baud(proj.kind, proj.root, proj.cfg, self.serial.selected_baud()))
        port = self.serial.refresh_ports()
        if not port:
            self.flash("No serial device found — plug in the board (use a data cable, not a charge-only one)", 8000)
            self.serial._info("No serial device found.", "error")
            return
        if not self.serial.connected:
            self.serial.connect_port(port)

    def emb_lib(self, name, search):
        proj = self.emb_project(fresh=True)
        if not proj:
            self.flash("Open an embedded project first")
            return
        hint = embedded.install_hint(proj.kind, proj.cfg)
        if hint:
            self._emb_missing_tool(hint)
            return
        cmd = embedded.lib_cmd(proj.kind, proj.root, proj.cfg, proj.port, name, search)
        if not cmd:
            self.flash("There is no library search for this toolchain — browse components.espressif.com / micropython-lib" if search
                       else "Can't install libraries for this project type")
            return
        self.show_build_panel()
        self.build.run(f"{'Search' if search else 'Install'} {name}", cmd, proj.root)

    def emb_active_guard(self, what):
        """True (after telling the user) when `what` isn't possible for the embedded project in front of us."""
        if self.emb_project():
            self.flash(f"{what} isn't available for boards yet — use the serial monitor (Ctrl+Alt+M) and Serial.print()", 8000)
            return True
        return False

    def emb_shutdown(self):
        self.serial.shutdown()
