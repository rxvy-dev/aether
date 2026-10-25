"""Serial monitor: a bottom-panel tab that talks to the board (like Arduino IDE's, with ESP-IDF colour support)."""
import re, time
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from . import embedded

LINE_ENDINGS = [("No line ending", ""), ("Newline", "\n"), ("Carriage return", "\r"), ("Both NL & CR", "\r\n")]
COLORS = {30: "#7c7f93", 31: "#f7768e", 32: "#9ece6a", 33: "#e0af68", 34: "#7aa2f7", 35: "#bb9af7", 36: "#7dcfff", 37: "#c0caf5"}
MAX_LINES = 5000
RETRIES = 24                 # native-USB boards (ESP32-S2/S3/C3, Pico) re-appear a moment after a reset


class SerialMonitor(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.sp = None               # embedded.SerialPort while connected
        self.src = 0                 # GLib watch id
        self.retry = 0               # GLib timeout id while waiting for the device to come back
        self.retries_left = 0
        self.ports = []
        self._bol = True
        self._cr = False
        self._esc = ""
        self._scroll_id = 0
        self._history, self._hpos = [], 0
        self._loading = False

        head = Gtk.Box(spacing=6)
        head.add_css_class("aether-build-head")
        self.port_model = Gtk.StringList()
        self.port_dd = Gtk.DropDown(model=self.port_model, tooltip_text="Serial port")
        self.port_dd.connect("notify::selected", self._on_port_changed)
        head.append(self.port_dd)
        refresh = Gtk.Button(label="⟳", tooltip_text="Rescan serial ports")
        refresh.add_css_class("flat")
        refresh.connect("clicked", lambda *_: self.refresh_ports())
        head.append(refresh)
        self.baud_model = Gtk.StringList.new([str(b) for b in embedded.BAUDS])
        self.baud_dd = Gtk.DropDown(model=self.baud_model, tooltip_text="Baud rate — must match Serial.begin() in your code")
        self.baud_dd.set_selected(embedded.BAUDS.index(embedded.DEFAULT_BAUD))
        self.baud_dd.connect("notify::selected", self._on_baud_changed)
        head.append(self.baud_dd)
        self.conn_btn = Gtk.Button(label="Connect")
        self.conn_btn.add_css_class("suggested-action")
        self.conn_btn.connect("clicked", lambda *_: self.disconnect() if self.connected else self.connect_port())
        head.append(self.conn_btn)
        self.reset_btn = Gtk.Button(label="↺ Reset", tooltip_text="Reset the board (pulses DTR, or RTS on ESP boards)")
        self.reset_btn.add_css_class("flat")
        self.reset_btn.connect("clicked", lambda *_: self.reset_board())
        head.append(self.reset_btn)
        self.status = Gtk.Label(label="", xalign=0, hexpand=True)
        self.status.add_css_class("dim-label")
        head.append(self.status)
        self.auto = Gtk.CheckButton(label="Autoscroll", active=True)
        self.ts = Gtk.CheckButton(label="Timestamps")
        head.append(self.auto)
        head.append(self.ts)
        clear = Gtk.Button(label="Clear")
        clear.add_css_class("flat")
        clear.connect("clicked", lambda *_: self.clear())
        head.append(clear)
        self.append(head)

        self.view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(10)
        self.view.set_top_margin(4)
        b = self.view.get_buffer()
        for code, col in COLORS.items():
            b.create_tag(f"c{code}", foreground=col)
            b.create_tag(f"c{code + 60}", foreground=col)
        b.create_tag("ts", foreground="#7c7f93")
        b.create_tag("info", foreground="#7aa2f7", weight=700)
        b.create_tag("error", foreground="#f7768e", weight=700)
        self.sw = Gtk.ScrolledWindow(vexpand=True)
        self.sw.set_child(self.view)
        self.append(self.sw)

        send = Gtk.Box(spacing=6)
        self.entry = Gtk.Entry(hexpand=True, placeholder_text="Type a message and press Enter to send to the board")
        self.entry.add_css_class("aether-dbg-entry")
        self.entry.connect("activate", lambda *_: self.send())
        from gi.repository import Gdk
        kc = Gtk.EventControllerKey()
        kc.connect("key-pressed", self._entry_key)
        self.entry.add_controller(kc)
        send.append(self.entry)
        self.ending_dd = Gtk.DropDown.new_from_strings([n for n, _v in LINE_ENDINGS])
        self.ending_dd.set_selected(1)
        self.ending_dd.set_tooltip_text("Line ending added to what you send")
        send.append(self.ending_dd)
        sb = Gtk.Button(label="Send")
        sb.connect("clicked", lambda *_: self.send())
        send.append(sb)
        self.append(send)
        self._Gdk = Gdk
        self.refresh_ports()
        self._update_ui()

    # ------------------------------------------------------------ state
    @property
    def connected(self):
        return self.sp is not None

    def selected_port(self):
        i = self.port_dd.get_selected()
        return self.ports[i].path if 0 <= i < len(self.ports) else ""

    def selected_baud(self):
        n = self.baud_dd.get_selected_item()
        try:
            return int(n.get_string())
        except (AttributeError, ValueError):
            return embedded.DEFAULT_BAUD

    def _update_ui(self):
        on = self.connected
        self.conn_btn.set_label("Disconnect" if on else "Connect")
        (self.conn_btn.remove_css_class if on else self.conn_btn.add_css_class)("suggested-action")
        self.reset_btn.set_sensitive(on)
        self.entry.set_sensitive(on)
        self.status.set_text(f"{self.sp.path} @ {self.sp.baud}" if on else ("waiting for the device…" if self.retry else "not connected"))
        if hasattr(self.win, "emb_state_changed"):
            self.win.emb_state_changed()

    def _info(self, text, tag="info"):
        self._insert(("\n" if not self._bol else "") + text + "\n", tag)
        self._bol = True

    # ------------------------------------------------------------ ports
    def refresh_ports(self, prefer=None):
        """Rescan /dev and keep (or choose) a sensible selection."""
        self.ports = embedded.list_ports()
        saved = prefer or (self.win.settings["serial"] or {}).get("port", "")
        self._loading = True
        self.port_model.splice(0, self.port_model.get_n_items(), [p.label for p in self.ports] or ["(no device found)"])
        want = embedded.default_port(saved, self.ports) if self.ports else ""
        idx = next((i for i, p in enumerate(self.ports) if p.path == want), 0)
        self.port_dd.set_selected(idx)
        self._loading = False
        return self.selected_port()

    def set_port(self, path):
        if not any(p.path == path for p in self.ports):
            self.refresh_ports(prefer=path)
        for i, p in enumerate(self.ports):
            if p.path == path:
                self._loading = True
                self.port_dd.set_selected(i)
                self._loading = False

    def set_baud(self, baud):
        baud = int(baud)
        for i in range(self.baud_model.get_n_items()):
            if self.baud_model.get_string(i) == str(baud):
                self._loading = True
                self.baud_dd.set_selected(i)
                self._loading = False
                return
        self.baud_model.append(str(baud))
        self._loading = True
        self.baud_dd.set_selected(self.baud_model.get_n_items() - 1)
        self._loading = False

    def _on_port_changed(self, *_):
        if self._loading:
            return
        path = self.selected_port()
        if path:
            self.win.emb_port_chosen(path)
            if self.connected and self.sp.path != path:
                self.connect_port()

    def _on_baud_changed(self, *_):
        if not self._loading and self.connected and self.sp.baud != self.selected_baud():
            self.connect_port()

    # ------------------------------------------------------------ connect / disconnect
    def connect_port(self, path=None, baud=None, quiet=False):
        path = path or self.selected_port()
        if not path:
            self.refresh_ports()
            path = self.selected_port()
        if not path:
            if not quiet:
                self.win.flash("No serial device found — plug in the board (use a data cable, not a charge-only one)", 8000)
                self._info("No serial device found.", "error")
            return False
        if baud:
            self.set_baud(baud)
        self._stop_retry()
        self._close()
        prob = embedded.port_problem(path)
        if prob:
            self._info(prob, "error")
            if not quiet:
                self.win.flash(prob, 14000)
            self._update_ui()
            return False
        try:
            self.sp = embedded.SerialPort(path, self.selected_baud())
        except OSError as e:
            self.sp = None
            self._info(f"Could not open {path}: {e}", "error")
            if not quiet:
                self.win.flash(f"Could not open {path}: {e}", 10000)
            self._update_ui()
            return False
        self.src = GLib.io_add_watch(self.sp.fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._on_io)
        self.set_port(path)
        self._info(f"Connected to {path} at {self.sp.baud} baud", "info")
        s = dict(self.win.settings["serial"] or {})
        s.update(port=path, baud=self.sp.baud)
        self.win.settings["serial"] = s
        self._update_ui()
        return True

    def disconnect(self):
        was = self.connected
        self._stop_retry()
        self._close()
        if was:
            self._info("Disconnected", "info")
        self._update_ui()

    def release(self):
        """Free the port for an upload. Returns what to reconnect to afterwards (or None)."""
        state = (self.sp.path, self.sp.baud) if self.sp else None
        self._stop_retry()
        self._close()
        if state:
            self._info("Port released for upload…", "info")
        self._update_ui()
        return state

    def reconnect_later(self, state, delay_ms=1500):
        """After an upload: open the port again once the board has restarted (retrying for a while)."""
        if not state:
            return
        path, baud = state
        self.retries_left = RETRIES
        self.set_baud(baud)
        self._wanted = path
        self.retry = GLib.timeout_add(delay_ms, self._retry_open)
        self._update_ui()

    def _retry_open(self):
        path = getattr(self, "_wanted", None)
        if not path:
            self.retry = 0
            return False
        self.retries_left -= 1
        ports = [p.path for p in embedded.list_ports()]
        # a native-USB board can come back under another name: take the only port if ours vanished
        target = path if path in ports else (ports[0] if len(ports) == 1 else None)
        if target and embedded.port_problem(target) is None:
            self.retry = 0
            self.connect_port(target, quiet=True)
            return False
        if self.retries_left <= 0:
            self.retry = 0
            self._info("Device did not come back — press Connect when it is ready.", "error")
            self._update_ui()
            return False
        return True

    def _stop_retry(self):
        if self.retry:
            GLib.source_remove(self.retry)
            self.retry = 0
        self._wanted = None

    def _close(self):
        if self.src:
            GLib.source_remove(self.src)
            self.src = 0
        if self.sp:
            self.sp.close()
            self.sp = None

    def _on_io(self, fd, cond):
        if not self.sp:
            self.src = 0
            return False
        gone = False
        if cond & GLib.IO_IN:
            try:
                text = self.sp.read()
                if text:
                    self.feed(text)
            except OSError:
                gone = True
        if gone or cond & (GLib.IO_HUP | GLib.IO_ERR):
            self.src = 0
            path, baud = self.sp.path, self.sp.baud
            self._close()
            self._info("Device disconnected — waiting for it to come back…", "error")
            self.reconnect_later((path, baud), 500)
            return False
        return True

    def reset_board(self):
        if self.sp:
            self.sp.reset(self.win.emb_reset_style())
            self._info("Board reset", "info")

    # ------------------------------------------------------------ output
    def feed(self, text):
        """Text from the board: normalise line ends, split ANSI colours, add timestamps, append."""
        text = self._esc + text
        self._esc = ""
        i = text.rfind("\x1b")
        if i >= 0 and len(text) - i < 16 and not re.match(r"\x1b\[[0-9;?]*[A-Za-z]", text[i:]):
            self._esc, text = text[i:], text[:i]            # an escape sequence split across two reads
        if self._cr and text.startswith("\n"):
            text = text[1:]
        self._cr = text.endswith("\r")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        for seg, color in embedded.split_ansi(text):
            for piece in re.findall(r"[^\n]*\n|[^\n]+", seg):
                if self._bol and self.ts.get_active():
                    now = time.time()
                    self._insert(time.strftime("[%H:%M:%S", time.localtime(now)) + ".%03d] " % (now % 1 * 1000), "ts")
                self._insert(piece, f"c{color}" if color else None)
                self._bol = piece.endswith("\n")
        self._trim()
        if self.auto.get_active() and not self._scroll_id:
            self._scroll_id = GLib.idle_add(self._scroll)

    def _insert(self, text, tag=None):
        b = self.view.get_buffer()
        end = b.get_end_iter()
        if tag:
            b.insert_with_tags_by_name(end, text, tag)
        else:
            b.insert(end, text)

    def _trim(self):
        b = self.view.get_buffer()
        if b.get_line_count() > MAX_LINES:
            ok, e = b.get_iter_at_line(MAX_LINES // 5)
            b.delete(b.get_start_iter(), e)

    def _scroll(self):
        self._scroll_id = 0
        adj = self.sw.get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    def clear(self):
        self.view.get_buffer().set_text("")
        self._bol = True

    # ------------------------------------------------------------ input
    def send(self):
        text = self.entry.get_text()
        if not self.sp:
            self.win.flash("Not connected — press Connect first")
            return
        ending = LINE_ENDINGS[self.ending_dd.get_selected()][1]
        try:
            self.sp.write(text + ending)
        except OSError as e:
            self._info(f"Send failed: {e}", "error")
            return
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._hpos = len(self._history)
        self.entry.set_text("")

    def _entry_key(self, ctl, keyval, kc, st):
        Gdk = self._Gdk
        if keyval == Gdk.KEY_Up and self._history:
            self._hpos = max(0, self._hpos - 1)
            self.entry.set_text(self._history[self._hpos])
            self.entry.set_position(-1)
            return True
        if keyval == Gdk.KEY_Down and self._history:
            self._hpos = min(len(self._history), self._hpos + 1)
            self.entry.set_text(self._history[self._hpos] if self._hpos < len(self._history) else "")
            self.entry.set_position(-1)
            return True
        return False

    def shutdown(self):
        self._stop_retry()
        self._close()
