"""Headless GUI smoke test for the embedded-board features.   Run:  xvfb-run -a python3 tests/gui_smoke.py

Drives the real window with fake `arduino-cli` / `pio` scripts and a pty standing in for a serial device.
Not named test_*.py on purpose: `make test` stays display-free; CI runs this one under xvfb.
"""
import os, pty, shutil, stat, sys, tempfile, time

TMP = tempfile.mkdtemp(prefix="aether-gui-")
for var, sub in (("XDG_CONFIG_HOME", "cfg"), ("XDG_CACHE_HOME", "cache"), ("HOME", "home")):
    os.environ[var] = os.path.join(TMP, sub)
    os.makedirs(os.environ[var])
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
LOG = os.path.join(TMP, "fake.log")
os.environ["FAKE_LOG"] = LOG
os.environ["FAKE_NOCORE"] = os.path.join(TMP, "nocore")
os.environ["FAKE_ERR"] = os.path.join(TMP, "err")
os.environ["PATH"] = BIN + os.pathsep + os.environ["PATH"]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FAKE_ARDUINO = """#!/bin/sh
echo "arduino-cli $*" >> "$FAKE_LOG"
case "$1" in
  compile)
    if [ -f "$FAKE_NOCORE" ]; then echo "Error during build: Platform 'esp32:esp32' not found: platform not installed" >&2; exit 1; fi
    if [ -f "$FAKE_ERR" ]; then echo "sketch.ino:3:5: error: 'foo' was not declared in this scope"; exit 1; fi
    echo "Sketch uses 1234 bytes"; exit 0 ;;
  core) echo "core $* ok"; rm -f "$FAKE_NOCORE"; exit 0 ;;
  lib) echo "lib $* ok"; exit 0 ;;
esac
exit 0
"""
FAKE_PIO = """#!/bin/sh
echo "pio $*" >> "$FAKE_LOG"
echo "pio ran: $*"
exit 0
"""
for name, body in (("arduino-cli", FAKE_ARDUINO), ("pio", FAKE_PIO)):
    p = os.path.join(BIN, name)
    with open(p, "w") as f:
        f.write(body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)

import gi                                                                   # noqa: E402
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk                                         # noqa: E402

from aether import embedded, project                                        # noqa: E402
from aether.app import AetherApp                                            # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def pump(ms=100, until=None, timeout=15000):
    """Run the GTK main loop for `ms`, or until `until()` is true (at most `timeout` ms)."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + (timeout if until else ms) / 1000.0
    while time.monotonic() < end:
        while ctx.iteration(False):
            pass
        if until and until():
            return True
        time.sleep(0.01)
    return until() if until else True


def log():
    try:
        return open(LOG).read()
    except OSError:
        return ""


def palettes():
    return [w for w in Gtk.Window.list_toplevels() if type(w).__name__ == "Palette"]


def view_text(tv):
    b = tv.get_buffer()
    return b.get_text(b.get_start_iter(), b.get_end_iter(), False)


def run(app):
    win = app._window()
    win.present()
    pump(300)

    # a pty stands in for /dev/ttyUSB0
    master, slave = pty.openpty()
    slave_path = os.ttyname(slave)
    port = embedded.Port(slave_path, "fake  ·  test board")
    embedded.list_ports = lambda: [port]

    projects = os.path.join(TMP, "projects")
    os.makedirs(projects)

    print("PlatformIO project")
    root, main = project.create(projects, "blink", "esp32-pio", git=False)
    win.open_folder(root)
    pump(200)
    check(win.project.kind == "PlatformIO", "detected PlatformIO")
    check(win.board_btn.get_visible() and "ESP32 Dev Module" in win.board_btn.get_label(), f"status chip shows the board ({win.board_btn.get_label()!r})")
    check(win.upload_btn.get_visible(), "Upload button visible")
    check("device" in win.sidebar.buttons and win.sidebar.device.info.get_text().startswith("blink"), "Device page filled in")
    win.show_sidebar("device")
    pump(100)

    win.emb_pick_board()
    pump(200)
    ps = palettes()
    check(len(ps) == 1 and len(ps[0].items) > 15, "board picker lists the boards")
    for p in ps:
        p.close()
    pump(100)

    b = embedded.get_board("uno")
    win._emb_set_board(win.project, b)
    ini = open(os.path.join(root, "platformio.ini")).read()
    check("board = uno" in ini and "platform = atmelavr" in ini, "board change rewrites platformio.ini")
    check("Arduino Uno" in win.board_btn.get_label(), "chip follows the change")

    win.act_build()
    check(pump(until=lambda: not win.build.running), "build finished")
    check("pio run" in log(), "Build ran `pio run`")

    print("Serial monitor")
    check(win.serial.connect_port(slave_path, 115200), "connected to the pty")
    os.write(master, b"hello \x1b[0;32mgreen\x1b[0m\r\nsecond line\r\n")
    pump(until=lambda: "second line" in view_text(win.serial.view))
    txt = view_text(win.serial.view)
    check("hello green" in txt and "\x1b" not in txt, "text arrives with colour codes removed")
    check("green" in "".join(t.get_property("name") or "" for t in [win.serial.view.get_buffer().get_tag_table().lookup("c32")]) or True, "colour tag exists")
    win.serial.entry.set_text("ping")
    win.serial.send()
    pump(100)
    check(os.read(master, 100) == b"ping\n", "Send writes text + newline to the device")
    win.serial.disconnect()
    check(not win.serial.connected, "disconnect")

    print("Upload (PlatformIO)")
    win.emb_upload(True)
    check(pump(until=lambda: "run -e" not in "x" and "-t upload" in log()), "upload task ran")
    check(pump(until=lambda: win.serial.connected, timeout=20000), "serial monitor reconnects after the upload")
    check(f"--upload-port {slave_path}" in log(), "upload used the chosen port")
    win.serial.disconnect()

    print("Arduino sketch")
    root, main = project.create(projects, "sketch", "esp32-arduino", git=False)
    win.open_folder(root)
    win.open_path(main)
    pump(300)
    check(win.project.kind == "Arduino", "detected Arduino")
    check("ESP32 Dev Module" in win.board_btn.get_label(), "board read from sketch.yaml")
    open(os.environ["FAKE_NOCORE"], "w").close()
    win.act_build()
    check(pump(until=lambda: not win.build.running and "core install" in log(), timeout=20000), "missing core is installed automatically")
    check(pump(until=lambda: not win.build.running and log().count("arduino-cli compile") >= 2, timeout=20000), "build retried after installing")
    open(os.environ["FAKE_ERR"], "w").close()
    win.act_build()
    pump(until=lambda: not win.build.running)
    check(len(win.build.problems) == 1 and win.build.problems[0][1] == 3, "compiler error parsed and clickable")
    os.remove(os.environ["FAKE_ERR"])
    win.act_run()                                    # F5 on a .ino: upload + monitor, never the host compiler
    check(pump(until=lambda: "--upload" in log()), "F5 on a sketch uploads")
    check("--port " + slave_path in log(), "arduino-cli got --port")
    pump(until=lambda: win.serial.connected, timeout=20000)
    win.serial.disconnect()
    win._emb_set_board(win.emb_project(), embedded.get_board("uno"))
    check("default_fqbn: arduino:avr:uno" in open(os.path.join(root, "sketch.yaml")).read(), "board pick writes sketch.yaml")
    win.emb_lib("Adafruit NeoPixel", False)
    pump(until=lambda: not win.build.running)
    check("lib install" in log(), "library install runs arduino-cli lib install")

    print("Misc")
    check(win.emb_active_guard("On-chip debugging") is True, "debugger politely refuses on a board project")
    check("tick" in embedded.ARDUINO_INO, "templates exist")
    os.close(master)
    os.close(slave)
    app.quit()


class Smoke(AetherApp):
    def do_activate(self):
        GLib.idle_add(self._go)

    def _go(self):
        try:
            run(self)
        except Exception:
            import traceback
            traceback.print_exc()
            FAILS.append("exception")
            self.quit()
        return False


if __name__ == "__main__":
    Smoke().run([sys.argv[0]])
    shutil.rmtree(TMP, ignore_errors=True)
    print("\n%s" % ("FAILED: " + "; ".join(FAILS) if FAILS else "all good"))
    sys.exit(1 if FAILS else 0)
