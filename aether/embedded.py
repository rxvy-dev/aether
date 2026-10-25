"""Embedded development: Arduino, ESP32 / ESP8266, Raspberry Pi Pico and MicroPython.

Plain Python with no GTK, so it can be unit tested. It provides

  * a board table (arduino-cli FQBNs, PlatformIO board ids, chip, reset style)
  * project detection  ->  build / upload / clean / test / configure tasks
        Arduino sketch (arduino-cli) · PlatformIO · ESP-IDF · MicroPython (mpremote)
  * serial port discovery with permission hints
  * a small termios serial port (no pyserial needed) for the serial monitor
"""
import codecs, configparser, glob, os, re, select, shlex, shutil, struct, time
from typing import NamedTuple

try:
    import fcntl, termios
except ImportError:                      # not Linux — the serial monitor is simply unavailable
    fcntl = termios = None

KINDS = ("Arduino", "PlatformIO", "ESP-IDF", "MicroPython")


# ------------------------------------------------------------------ boards
class Board(NamedTuple):
    id: str          # short id stored in .aether/project.json
    name: str
    family: str      # avr | renesas | esp32 | esp8266 | rp2040
    fqbn: str        # arduino-cli fully qualified board name
    pio: str         # PlatformIO board id
    chip: str        # ESP-IDF target / MCU
    reset: str = "dtr"   # how the serial monitor resets it: "dtr" (Arduino) or "rts" (ESP auto-reset)


ESP32_URL = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
ESP8266_URL = "https://arduino.esp8266.com/stable/package_esp8266com_index.json"
RP2040_URL = "https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json"

# family -> (arduino-cli core, board-manager URL, PlatformIO platform, extra platformio.ini lines)
FAMILIES = {
    "avr": ("arduino:avr", "", "atmelavr", []),
    "renesas": ("arduino:renesas_uno", "", "renesas-ra", []),
    "esp32": ("esp32:esp32", ESP32_URL, "espressif32", []),
    "esp8266": ("esp8266:esp8266", ESP8266_URL, "espressif8266", []),
    "rp2040": ("rp2040:rp2040", RP2040_URL, "https://github.com/maxgerhardt/platform-raspberrypi.git",
               ["board_build.core = earlephilhower"]),
}

BOARDS = [
    Board("uno", "Arduino Uno", "avr", "arduino:avr:uno", "uno", "atmega328p"),
    Board("nano", "Arduino Nano", "avr", "arduino:avr:nano:cpu=atmega328", "nanoatmega328new", "atmega328p"),
    Board("nano-old", "Arduino Nano (old bootloader)", "avr", "arduino:avr:nano:cpu=atmega328old", "nanoatmega328", "atmega328p"),
    Board("mega", "Arduino Mega 2560", "avr", "arduino:avr:mega:cpu=atmega2560", "megaatmega2560", "atmega2560"),
    Board("leonardo", "Arduino Leonardo", "avr", "arduino:avr:leonardo", "leonardo", "atmega32u4"),
    Board("micro", "Arduino Micro", "avr", "arduino:avr:micro", "micro", "atmega32u4"),
    Board("uno-r4-minima", "Arduino Uno R4 Minima", "renesas", "arduino:renesas_uno:minima", "uno_r4_minima", "ra4m1"),
    Board("uno-r4-wifi", "Arduino Uno R4 WiFi", "renesas", "arduino:renesas_uno:unor4wifi", "uno_r4_wifi", "ra4m1"),
    Board("esp32", "ESP32 Dev Module", "esp32", "esp32:esp32:esp32", "esp32dev", "esp32", "rts"),
    Board("esp32-wrover", "ESP32 Wrover Module", "esp32", "esp32:esp32:esp32wrover", "esp-wrover-kit", "esp32", "rts"),
    Board("esp32-cam", "ESP32-CAM (AI Thinker)", "esp32", "esp32:esp32:esp32cam", "esp32cam", "esp32", "rts"),
    Board("esp32s2", "ESP32-S2 (Saola)", "esp32", "esp32:esp32:esp32s2", "esp32-s2-saola-1", "esp32s2", "rts"),
    Board("esp32s3", "ESP32-S3 DevKitC", "esp32", "esp32:esp32:esp32s3", "esp32-s3-devkitc-1", "esp32s3", "rts"),
    Board("esp32c3", "ESP32-C3 DevKitM", "esp32", "esp32:esp32:esp32c3", "esp32-c3-devkitm-1", "esp32c3", "rts"),
    Board("esp32c6", "ESP32-C6 DevKitC", "esp32", "esp32:esp32:esp32c6", "esp32-c6-devkitc-1", "esp32c6", "rts"),
    Board("xiao-esp32c3", "Seeed XIAO ESP32C3", "esp32", "esp32:esp32:XIAO_ESP32C3", "seeed_xiao_esp32c3", "esp32c3", "rts"),
    Board("xiao-esp32s3", "Seeed XIAO ESP32S3", "esp32", "esp32:esp32:XIAO_ESP32S3", "seeed_xiao_esp32s3", "esp32s3", "rts"),
    Board("nodemcu", "ESP8266 NodeMCU 1.0", "esp8266", "esp8266:esp8266:nodemcuv2", "nodemcuv2", "esp8266", "rts"),
    Board("d1-mini", "ESP8266 Wemos D1 mini", "esp8266", "esp8266:esp8266:d1_mini", "d1_mini", "esp8266", "rts"),
    Board("esp8266", "ESP8266 Generic", "esp8266", "esp8266:esp8266:generic", "esp01_1m", "esp8266", "rts"),
    Board("pico", "Raspberry Pi Pico", "rp2040", "rp2040:rp2040:rpipico", "pico", "rp2040"),
    Board("pico-w", "Raspberry Pi Pico W", "rp2040", "rp2040:rp2040:rpipicow", "rpipicow", "rp2040"),
    Board("pico2", "Raspberry Pi Pico 2", "rp2040", "rp2040:rp2040:rpipico2", "rpipico2", "rp2350"),
]
IDF_TARGETS = [("esp32", "ESP32"), ("esp32s2", "ESP32-S2"), ("esp32s3", "ESP32-S3"), ("esp32c3", "ESP32-C3"),
               ("esp32c6", "ESP32-C6"), ("esp32h2", "ESP32-H2")]
BAUDS = [300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 74880, 115200, 230400, 250000, 460800, 500000, 921600, 1000000, 2000000]
DEFAULT_BAUD = 115200


def get_board(bid):
    return next((b for b in BOARDS if b.id == bid), None)


def board_by_fqbn(fqbn):
    if not fqbn:
        return None
    key = ":".join(fqbn.split(":")[:3])
    return next((b for b in BOARDS if ":".join(b.fqbn.split(":")[:3]) == key), None)


def board_by_pio(pio):
    return next((b for b in BOARDS if b.pio == pio), None)


def core_of(fqbn):
    return ":".join((fqbn or "").split(":")[:2])


def core_url(fqbn):
    core = core_of(fqbn)
    for c, url, _p, _x in FAMILIES.values():
        if c == core:
            return url
    return ""


def core_install_cmd(fqbn):
    """arduino-cli command that installs the core a board needs."""
    core = core_of(fqbn)
    if core.count(":") != 1:
        return ""
    url = core_url(fqbn)
    u = f" --additional-urls {shlex.quote(url)}" if url else ""
    cli = exe("arduino-cli")
    return f"{cli} core update-index{u} && {cli} core install {shlex.quote(core)}{u}"


# ------------------------------------------------------------------ small readers
def _read(path, limit=200_000):
    try:
        with open(path, errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def read_sketch_yaml(root):
    """default_fqbn / default_port from sketch.yaml (arduino-cli and Arduino IDE 2 share this file)."""
    txt = _read(os.path.join(root, "sketch.yaml"), 20_000)
    out = {}
    for key in ("default_fqbn", "default_port"):
        m = re.search(rf"^\s*{key}\s*:\s*(\S+)\s*$", txt, re.M)
        if m:
            out[key] = m.group(1).strip("'\"")
    return out


def write_sketch_yaml(root, fqbn):
    path = os.path.join(root, "sketch.yaml")
    txt = _read(path, 20_000)
    if re.search(r"^\s*default_fqbn\s*:", txt, re.M):
        txt = re.sub(r"^(\s*default_fqbn\s*:).*$", lambda m: f"{m.group(1)} {fqbn}", txt, flags=re.M)
    else:
        txt = (txt.rstrip("\n") + "\n" if txt.strip() else "") + f"default_fqbn: {fqbn}\n"
    with open(path, "w") as f:
        f.write(txt)


def pio_parse(root):
    """-> {"envs": [names], "default": [names], "env": {name: {board, framework, platform, monitor_speed}}}"""
    cp = configparser.ConfigParser(interpolation=None, strict=False, inline_comment_prefixes=None)
    try:
        cp.read_string(_read(os.path.join(root, "platformio.ini")))
    except configparser.Error:
        return {"envs": [], "default": [], "env": {}}
    common = dict(cp["env"]) if cp.has_section("env") else {}
    envs, info = [], {}
    for sec in cp.sections():
        if sec.startswith("env:"):
            name = sec[4:].strip()
            envs.append(name)
            d = dict(common)
            d.update(dict(cp[sec]))
            info[name] = {k: (d.get(k) or "").strip() for k in ("board", "framework", "platform", "monitor_speed")}
    default = []
    if cp.has_section("platformio"):
        default = [x.strip() for x in re.split(r"[,\s]+", cp["platformio"].get("default_envs", "")) if x.strip()]
    return {"envs": envs, "default": default, "env": info}


def pio_env(root, cfg):
    """The environment commands run against: chosen one, else the first default, else None (PlatformIO decides)."""
    p = pio_parse(root)
    want = (cfg or {}).get("pio_env")
    if want in p["envs"]:
        return want
    if p["default"] and p["default"][0] in p["envs"]:
        return p["default"][0]
    return p["envs"][0] if len(p["envs"]) == 1 else None


def pio_set_board(root, board, env=None):
    """Point an environment of platformio.ini at another board (and its platform, when we know it)."""
    path = os.path.join(root, "platformio.ini")
    lines = _read(path).splitlines()
    start = None
    for i, l in enumerate(lines):
        m = re.match(r"^\s*\[env:([^\]]+)\]", l)
        if m and (env is None or m.group(1).strip() == env):
            start = i
            break
    if start is None:
        return False
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    b = get_board(board) or board_by_pio(board)

    def setkey(key, value):
        nonlocal end
        for i in range(start + 1, end):
            if re.match(rf"^\s*{re.escape(key)}\s*=", lines[i]):
                lines[i] = f"{key} = {value}"
                return
        lines.insert(start + 1, f"{key} = {value}")
        end += 1

    if b:
        for i in range(end - 1, start, -1):          # drop the Pico core line when moving to another family
            if b.family != "rp2040" and re.match(r"^\s*board_build\.core\s*=", lines[i]):
                del lines[i]
                end -= 1
        setkey("board", b.pio)
        setkey("platform", FAMILIES[b.family][2])
        if b.family == "rp2040":
            setkey("board_build.core", "earlephilhower")
    else:
        setkey("board", board)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return True


# ------------------------------------------------------------------ tools
EXTRA_BIN = ("~/.local/bin", "~/bin", "~/.platformio/penv/bin", "/usr/local/bin")


def which(name):
    path = os.pathsep.join([os.environ.get("PATH", "")] + [os.path.expanduser(p) for p in EXTRA_BIN])
    return shutil.which(name, path=path)


def exe(*names):
    """Command word for a tool: its bare name when the login shell can see it, else its full path (e.g. ~/.local/bin)."""
    for n in names:
        if shutil.which(n):
            return n
    for n in names:
        full = which(n)
        if full:
            return shlex.quote(full)
    return names[0]


def pio_exe():
    return exe("pio", "platformio")


def idf_export(cfg=None):
    """Path of ESP-IDF's export.sh (needed to put idf.py on PATH), or None."""
    cands = [(cfg or {}).get("idf_export", ""), os.path.join(os.environ.get("IDF_PATH", "/nonexistent"), "export.sh"),
             "~/esp/esp-idf/export.sh", "~/esp-idf/export.sh", "~/esp/*/esp-idf/export.sh", "~/.espressif/esp-idf/export.sh"]
    for c in cands:
        for p in sorted(glob.glob(os.path.expanduser(c)), reverse=True):
            if os.path.isfile(p):
                return p
    return None


def tool_for(kind, cfg=None):
    """-> (tool name, found?)"""
    if kind == "Arduino":
        return "arduino-cli", which("arduino-cli") is not None
    if kind == "PlatformIO":
        return "pio", (which("pio") or which("platformio")) is not None
    if kind == "ESP-IDF":
        return "idf.py", which("idf.py") is not None or idf_export(cfg) is not None
    if kind == "MicroPython":
        return "mpremote", which("mpremote") is not None
    return "", True


INSTALL_HINTS = {
    "arduino-cli": "arduino-cli not found. Install it:  sudo pacman -S arduino-cli   or   curl -fsSL "
                   "https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=~/.local/bin sh",
    "pio": "PlatformIO not found. Install it:  pipx install platformio   (or: pip install --user platformio)",
    "idf.py": "ESP-IDF not found. Install it into ~/esp/esp-idf (Aether then finds export.sh by itself), or set "
              "\"idf_export\" in .aether/project.json. Guide: docs.espressif.com/projects/esp-idf (Get Started)",
    "mpremote": "mpremote not found. Install it:  pipx install mpremote   (or: pip install --user mpremote)",
}


def install_hint(kind, cfg=None):
    tool, ok = tool_for(kind, cfg)
    return None if ok else INSTALL_HINTS.get(tool, f"'{tool}' not found")


# ------------------------------------------------------------------ project detection
def _is_idf(root):
    cm = _read(os.path.join(root, "CMakeLists.txt"), 8000)
    if not cm:
        return False
    if "IDF_PATH" in cm or "tools/cmake/project.cmake" in cm:
        return True
    return os.path.isfile(os.path.join(root, "sdkconfig")) and "idf_component_register" in _read(os.path.join(root, "main", "CMakeLists.txt"), 4000)


def arduino_fqbn(root, cfg):
    cfg = cfg or {}
    if cfg.get("fqbn"):
        return cfg["fqbn"]
    b = get_board(cfg.get("board", ""))
    if b:
        return b.fqbn
    return read_sketch_yaml(root).get("default_fqbn", "")


def idf_target(root, cfg):
    m = re.search(r'^CONFIG_IDF_TARGET="([^"]+)"', _read(os.path.join(root, "sdkconfig"), 400_000), re.M)
    if m:
        return m.group(1)
    b = get_board((cfg or {}).get("board", ""))
    return b.chip if b and b.family == "esp32" else ""


def detect(root, cfg=None, port=""):
    """-> (kind, {task: shell command}) or (None, {})."""
    cfg = cfg or {}
    j = lambda *p: os.path.join(root, *p)
    ex = lambda *p: os.path.exists(j(*p))
    if ex("platformio.ini"):
        return "PlatformIO", _pio_tasks(root, cfg, port)
    if _is_idf(root):
        return "ESP-IDF", _idf_tasks(root, cfg, port)
    if glob.glob(j("*.ino")) or ex("sketch.yaml") or cfg.get("embedded") == "arduino":
        return "Arduino", _arduino_tasks(root, cfg, port)
    if ex("boot.py") or cfg.get("embedded") == "micropython":
        return "MicroPython", _mpy_tasks(root, cfg, port)
    return None, {}


def _arduino_tasks(root, cfg, port):
    fqbn = arduino_fqbn(root, cfg)
    fq = f" --fqbn {shlex.quote(fqbn)}" if fqbn else ""
    pt = f" --port {shlex.quote(port)}" if port else ""
    base = f"{exe('arduino-cli')} compile{fq} --warnings more --build-path build"
    t = {"build": f"{base} .", "upload": f"{base} --upload{pt} .", "clean": "rm -rf build"}
    inst = core_install_cmd(fqbn)
    if inst:
        t["configure"] = inst
    return t


def _pio_tasks(root, cfg, port):
    pio = pio_exe()
    env = pio_env(root, cfg)
    e = f" -e {shlex.quote(env)}" if env else ""
    up = f" --upload-port {shlex.quote(port)}" if port else ""
    return {"build": f"{pio} run{e}", "upload": f"{pio} run{e} -t upload{up}", "clean": f"{pio} run{e} -t clean",
            "test": f"{pio} test{e}",
            # installs the platform + lib_deps, then writes compile_commands.json so clangd can complete your code
            "configure": f"{pio} pkg install{e} && {pio} run{e} -t compiledb"}


def _idf_prefix(cfg):
    """`. export.sh &&` when idf.py isn't on PATH yet."""
    exp = idf_export(cfg) if not shutil.which("idf.py") else None
    return f". {shlex.quote(exp)} >/dev/null 2>&1 && " if exp else ""


def _idf_tasks(root, cfg, port):
    pre = _idf_prefix(cfg)
    p = f" -p {shlex.quote(port)}" if port else ""
    t = {"build": f"{pre}idf.py build", "upload": f"{pre}idf.py{p} flash", "clean": f"{pre}idf.py fullclean"}
    tgt = (cfg or {}).get("chip") or ""
    if tgt:
        t["configure"] = f"{pre}idf.py set-target {shlex.quote(tgt)}"
    return t


def _mpy_tasks(root, cfg, port):
    dev = shlex.quote(port) if port else "auto"
    mp = exe("mpremote")
    files = sorted(f for f in os.listdir(root) if f.endswith(".py") and os.path.isfile(os.path.join(root, f)))
    dirs = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")
                  and d not in ("__pycache__", "venv", "node_modules", "tests", "build"))
    parts = [f"fs cp {shlex.quote(f)} :" for f in files] + [f"fs cp -r {shlex.quote(d)} :" for d in dirs]
    t = {"upload": f"{mp} connect {dev} " + " + ".join(parts) + " + reset" if parts else "echo 'No .py files to upload'"}
    main = "main.py" if "main.py" in files else (files[0] if files else "main.py")
    t["run"] = f"{mp} connect {dev} run {shlex.quote(main)}"
    return t


def lib_cmd(kind, root, cfg, port, name, search=False):
    """Shell command that installs (or searches for) a library / package, or None when the toolchain has no such command."""
    q = shlex.quote(name)
    if kind == "Arduino":
        return f"{exe('arduino-cli')} lib {'search' if search else 'install'} {q}"
    if kind == "PlatformIO":
        return f"{pio_exe()} pkg search {q}" if search else f"{pio_exe()} pkg install --library {q}"
    if search:
        return None                      # ESP-IDF components: browse components.espressif.com · MicroPython: micropython-lib
    if kind == "ESP-IDF":
        return f"{_idf_prefix(cfg)}idf.py add-dependency {q}"
    if kind == "MicroPython":
        return f"{exe('mpremote')} connect {shlex.quote(port) if port else 'auto'} mip install {q}"
    return None


def missing(kind, root, cfg, port, task):
    """What has to be chosen before `task` can run: a subset of ["board", "port"]."""
    need = []
    if kind == "Arduino":
        if task in ("build", "upload", "configure") and not arduino_fqbn(root, cfg):
            need.append("board")
        if task == "upload" and not port:
            need.append("port")
    return need


# ------------------------------------------------------------------ board / port / baud info for the UI
def board_info(kind, root, cfg):
    """-> (display name, Board or None) for the status chip."""
    cfg = cfg or {}
    if kind == "Arduino":
        fq = arduino_fqbn(root, cfg)
        b = board_by_fqbn(fq)
        return (b.name if b else (fq or ""), b)
    if kind == "PlatformIO":
        p = pio_parse(root)
        env = pio_env(root, cfg) or (p["envs"][0] if p["envs"] else None)
        pb = (p["env"].get(env) or {}).get("board", "") if env else ""
        b = board_by_pio(pb)
        return (b.name if b else pb, b)
    if kind == "ESP-IDF":
        t = idf_target(root, cfg)
        return (dict(IDF_TARGETS).get(t, t), None)
    return ("", None)


def guess_baud(kind, root, cfg, default=DEFAULT_BAUD):
    """Best guess of the serial speed: project.json, platformio.ini, sdkconfig, then Serial.begin(N) in the code."""
    cfg = cfg or {}
    if str(cfg.get("baud", "")).isdigit():
        return int(cfg["baud"])
    if kind == "PlatformIO":
        p = pio_parse(root)
        env = pio_env(root, cfg) or (p["envs"][0] if p["envs"] else None)
        sp = (p["env"].get(env) or {}).get("monitor_speed", "") if env else ""
        if sp.isdigit():
            return int(sp)
    if kind == "ESP-IDF":
        m = re.search(r"^CONFIG_ESP_CONSOLE_UART_BAUDRATE=(\d+)", _read(os.path.join(root, "sdkconfig"), 400_000), re.M)
        return int(m.group(1)) if m else default
    pat = re.compile(r"Serial\d?\.begin\(\s*(\d{3,7})")
    files = []
    for pattern in ("*.ino", "*.cpp", "*.c", "src/*.cpp", "src/*.ino", "src/*.c", "*.pde"):
        files += glob.glob(os.path.join(root, pattern))
    for f in files[:40]:
        m = pat.search(_read(f, 200_000))
        if m:
            return int(m.group(1))
    return default


# ------------------------------------------------------------------ serial ports
class Port(NamedTuple):
    path: str
    label: str


_USB_NAMES = {"10c4:ea60": "CP210x USB-UART", "1a86:7523": "CH340 USB-UART", "1a86:55d4": "CH9102 USB-UART",
              "0403:6001": "FTDI FT232", "303a:1001": "Espressif USB JTAG/serial", "2e8a:0005": "Raspberry Pi Pico (MicroPython)",
              "2341:0043": "Arduino Uno", "2341:0042": "Arduino Mega 2560", "2341:8036": "Arduino Leonardo"}


def _rd(d, name):
    try:
        with open(os.path.join(d, name)) as f:
            return f.read().strip()
    except OSError:
        return ""


def usb_info(dev):
    """-> (vid:pid, "Manufacturer Product") from sysfs, or ("", "")."""
    try:
        d = os.path.realpath(f"/sys/class/tty/{os.path.basename(dev)}/device")
    except OSError:
        return "", ""
    for _ in range(4):
        if os.path.exists(os.path.join(d, "idVendor")):
            return (f"{_rd(d, 'idVendor')}:{_rd(d, 'idProduct')}".lower(),
                    f"{_rd(d, 'manufacturer')} {_rd(d, 'product')}".strip())
        d = os.path.dirname(d)
    return "", ""


def _natkey(path):
    m = re.search(r"(\d+)$", path)
    return (path[:m.start()] if m else path, int(m.group(1)) if m else 0)


def list_ports():
    paths = []
    for pat in ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyAMA*"):
        paths += glob.glob(pat)
    out = []
    for p in sorted(set(paths), key=_natkey):
        vp, desc = usb_info(p)
        name = _USB_NAMES.get(vp) or desc
        out.append(Port(p, f"{os.path.basename(p)}  ·  {name}" if name else os.path.basename(p)))
    return out


def port_problem(path):
    """A human hint when `path` can't be opened (the usual 'add yourself to dialout/uucp' problem), else None."""
    if not path:
        return None
    if not os.path.exists(path):
        return f"{path} is gone — unplug and re-plug the board"
    if os.access(path, os.R_OK | os.W_OK):
        return None
    try:
        import grp
        group = grp.getgrgid(os.stat(path).st_gid).gr_name
    except (ImportError, KeyError, OSError):
        group = "dialout"
    return f"No permission to use {path}. Add yourself to the '{group}' group:  sudo usermod -aG {group} $USER   (then log out and back in)"


def default_port(saved, ports):
    paths = [p.path for p in ports]
    if saved in paths:
        return saved
    return paths[0] if len(paths) == 1 else ""


# ------------------------------------------------------------------ serial port (termios, no dependencies)
_STD = {n: getattr(termios, f"B{n}", None) for n in (300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800,
                                                        500000, 576000, 921600, 1000000, 1152000, 1500000, 2000000, 2500000, 3000000)} if termios else {}
_TCGETS2, _TCSETS2, _BOTHER = 0x802C542A, 0x402C542B, 0o010000      # termios2: any baud rate (x86 / arm / riscv)
_CBAUD = getattr(termios, "CBAUD", 0o010017) if termios else 0


class SerialPort:
    """Non-blocking raw 8N1 serial port. `read()` returns decoded text; `write()` takes str or bytes."""

    def __init__(self, path, baud=DEFAULT_BAUD, reset_on_open=False):
        if termios is None:
            raise OSError("serial ports need Linux (termios)")
        self.path, self.baud = path, int(baud)
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            self._configure(self.baud)
            if not reset_on_open:
                self._modem(dtr=False, rts=False)      # opening asserts both lines, which resets most boards
        except Exception:
            os.close(self.fd)
            raise
        self._dec = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def _configure(self, baud):
        fd = self.fd
        iflag, oflag, cflag, lflag, _is, _os, cc = termios.tcgetattr(fd)
        iflag = oflag = lflag = 0
        cflag = (cflag & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | getattr(termios, "CRTSCTS", 0))) \
            | termios.CS8 | termios.CREAD | termios.CLOCAL
        cc[termios.VMIN], cc[termios.VTIME] = 1, 0
        speed = _STD.get(baud)
        sp = speed if speed is not None else termios.B9600
        termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, sp, sp, cc])
        if speed is None:
            self._custom_baud(baud)
        termios.tcflush(fd, termios.TCIOFLUSH)

    def _custom_baud(self, baud):
        try:
            buf = bytearray(fcntl.ioctl(self.fd, _TCGETS2, b"\0" * 44))
            iflag, oflag, cflag, lflag = struct.unpack_from("4I", buf, 0)
            cflag = (cflag & ~_CBAUD) | _BOTHER
            struct.pack_into("4I", buf, 0, iflag, oflag, cflag, lflag)
            struct.pack_into("2I", buf, 36, baud, baud)
            fcntl.ioctl(self.fd, _TCSETS2, buf)
        except (OSError, AttributeError) as e:
            raise OSError(f"this system can't set {baud} baud ({e})")

    def _modem(self, dtr=None, rts=None):
        for flag, on in ((termios.TIOCM_DTR, dtr), (termios.TIOCM_RTS, rts)):
            if on is None:
                continue
            try:
                fcntl.ioctl(self.fd, termios.TIOCMBIS if on else termios.TIOCMBIC, struct.pack("I", flag))
            except OSError:
                pass                               # not every tty (e.g. a pty) has modem lines

    def reset(self, style="dtr"):
        """Pulse the reset line: "dtr" for Arduino boards, "rts" for ESP32 / ESP8266 auto-reset circuits."""
        if style == "rts":
            self._modem(dtr=False, rts=True)
            time.sleep(0.12)
            self._modem(rts=False)
        else:
            self._modem(dtr=True)
            time.sleep(0.12)
            self._modem(dtr=False)

    def read(self):
        """Text that arrived since the last call ('' if none). Raises OSError once the device is gone."""
        try:
            data = os.read(self.fd, 8192)
        except BlockingIOError:
            return ""
        return self._dec.decode(data) if data else ""

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8", "replace")
        while data:
            try:
                n = os.write(self.fd, data)
                data = data[n:]
            except BlockingIOError:
                select.select([], [self.fd], [], 1.0)

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


ANSI_CSI = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])")


def split_ansi(text):
    """'a\\x1b[0;32mb' -> [("a", None), ("b", "32")]  (only colours are kept; other escape codes are dropped)."""
    out, pos, color = [], 0, None
    for m in ANSI_CSI.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], color))
        pos = m.end()
        if m.group(2) == "m":
            codes = [c for c in m.group(1).split(";") if c]
            if not codes or "0" in codes:
                color = None
            for c in codes:
                if c.isdigit() and (30 <= int(c) <= 37 or 90 <= int(c) <= 97):
                    color = c
    if pos < len(text):
        out.append((text[pos:], color))
    return out


# ------------------------------------------------------------------ new-project templates
ARDUINO_INO = """// {name}
const unsigned long BLINK_MS = 500;

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.println("{name} started");
}

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(BLINK_MS);
  digitalWrite(LED_BUILTIN, LOW);
  delay(BLINK_MS);
  Serial.println("tick");
}
"""
INO_STARTER = """void setup() {
\tSerial.begin(115200);
\tpinMode(LED_BUILTIN, OUTPUT);
\t$0
}

void loop() {
\tdigitalWrite(LED_BUILTIN, HIGH);
\tdelay(500);
\tdigitalWrite(LED_BUILTIN, LOW);
\tdelay(500);
}
"""
ESP32_INO = """// {name} — ESP32 (Arduino core). Wi-Fi example: #include <WiFi.h>  WiFi.begin(SSID, PASSWORD);
#ifndef LED_BUILTIN
#define LED_BUILTIN 2
#endif

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.println("{name} started");
}

void loop() {
  digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  Serial.printf("uptime: %lu ms\\n", millis());
  delay(500);
}
"""
PIO_MAIN = """#include <Arduino.h>

#ifndef LED_BUILTIN
#define LED_BUILTIN 2
#endif

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.println("{name} started");
}

void loop() {
  digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  Serial.printf("uptime: %lu ms\\n", millis());
  delay(500);
}
"""
PIO_ESP32 = """[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
"""
PIO_UNO = """[env:uno]
platform = atmelavr
board = uno
framework = arduino
monitor_speed = 115200
"""
PIO_PICO = """[env:pico]
platform = https://github.com/maxgerhardt/platform-raspberrypi.git
board = pico
framework = arduino
board_build.core = earlephilhower
monitor_speed = 115200
"""
IDF_CMAKE = """cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project({name})
"""
IDF_MAIN_CMAKE = 'idf_component_register(SRCS "main.c" INCLUDE_DIRS ".")\n'
IDF_MAIN = """#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_log.h"

#define BLINK_GPIO GPIO_NUM_2   /* change for your board */

static const char *TAG = "{name}";

void app_main(void)
{
    gpio_reset_pin(BLINK_GPIO);
    gpio_set_direction(BLINK_GPIO, GPIO_MODE_OUTPUT);
    ESP_LOGI(TAG, "started");
    int level = 0;
    for (;;) {
        gpio_set_level(BLINK_GPIO, level = !level);
        ESP_LOGI(TAG, "LED %s", level ? "on" : "off");
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}
"""
MPY_MAIN = """# {name} — MicroPython. F5 runs this file on the board; Ctrl+Alt+U copies the project to it.
import time
from machine import Pin

try:
    led = Pin("LED", Pin.OUT)      # Raspberry Pi Pico / Pico W
except Exception:
    led = Pin(2, Pin.OUT)          # most ESP32 dev boards

while True:
    led.toggle()
    print("tick")
    time.sleep(0.5)
"""
MPY_BOOT = "# boot.py — runs once at power-up, before main.py\n"

TEMPLATES = {
    # key: (label, description, {path: content}, file to open)      "{name}" is replaced in paths and contents
    "arduino": ("Arduino — sketch (Uno, Nano, Mega…)", "Sketch .ino + sketch.yaml, built with arduino-cli",
                {"{name}.ino": ARDUINO_INO, "sketch.yaml": "default_fqbn: arduino:avr:uno\n"}, "{name}.ino"),
    "esp32-arduino": ("ESP32 — Arduino sketch", "Arduino core for ESP32, built with arduino-cli",
                      {"{name}.ino": ESP32_INO, "sketch.yaml": "default_fqbn: esp32:esp32:esp32\n"}, "{name}.ino"),
    "esp32-pio": ("ESP32 — PlatformIO", "platformio.ini + src/main.cpp (Arduino framework)",
                  {"platformio.ini": PIO_ESP32, "src/main.cpp": PIO_MAIN, "include/.keep": "", "lib/.keep": ""}, "src/main.cpp"),
    "uno-pio": ("Arduino Uno — PlatformIO", "platformio.ini + src/main.cpp", {"platformio.ini": PIO_UNO, "src/main.cpp": PIO_MAIN,
                                                                             "include/.keep": "", "lib/.keep": ""}, "src/main.cpp"),
    "pico-pio": ("Raspberry Pi Pico — PlatformIO", "earlephilhower Arduino-Pico core",
                 {"platformio.ini": PIO_PICO, "src/main.cpp": PIO_MAIN,
                  "include/.keep": "", "lib/.keep": ""}, "src/main.cpp"),
    "esp-idf": ("ESP32 — ESP-IDF (C)", "Espressif's native framework: CMakeLists.txt + main/main.c",
                {"CMakeLists.txt": IDF_CMAKE, "main/CMakeLists.txt": IDF_MAIN_CMAKE, "main/main.c": IDF_MAIN}, "main/main.c"),
    "micropython": ("MicroPython (ESP32 / Pico)", "main.py + boot.py, run and uploaded with mpremote",
                    {"main.py": MPY_MAIN, "boot.py": MPY_BOOT}, "main.py"),
}
GITIGNORE = {"arduino": "build/\n", "esp32-arduino": "build/\n", "esp32-pio": ".pio/\ncompile_commands.json\n",
             "uno-pio": ".pio/\ncompile_commands.json\n", "pico-pio": ".pio/\ncompile_commands.json\n",
             "esp-idf": "build/\nsdkconfig.old\n", "micropython": "__pycache__/\n"}
HINTS = {"arduino": "pick a board with the chip in the status bar, then Ctrl+Shift+B builds and F5 uploads",
         "esp32-arduino": "Ctrl+Shift+B builds (the first build downloads the ESP32 core — Project tasks → Configure), F5 uploads",
         "esp32-pio": "Ctrl+Shift+B builds, F5 uploads and opens the serial monitor",
         "uno-pio": "Ctrl+Shift+B builds, F5 uploads and opens the serial monitor",
         "pico-pio": "Ctrl+Shift+B builds, F5 uploads and opens the serial monitor",
         "esp-idf": "Ctrl+Shift+B builds, F5 flashes and opens the serial monitor",
         "micropython": "F5 runs main.py on the board, Ctrl+Alt+U uploads the project"}
