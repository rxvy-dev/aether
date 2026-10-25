"""Unit tests for the embedded-board support (no display needed). Run:  make test"""
import os, select, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aether import embedded, project, templates                  # noqa: E402


def slurp(path):
    with open(path) as f:
        return f.read()


def touch(root, rel, text=""):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)
    return p


class Templates(unittest.TestCase):
    def test_every_embedded_template_is_detected(self):
        expected = {"arduino": "Arduino", "esp32-arduino": "Arduino", "esp32-pio": "PlatformIO", "uno-pio": "PlatformIO",
                    "pico-pio": "PlatformIO", "esp-idf": "ESP-IDF", "micropython": "MicroPython"}
        self.assertEqual(set(expected), set(embedded.TEMPLATES))
        with tempfile.TemporaryDirectory() as d:
            for key, kind in expected.items():
                root, main = project.create(d, f"demo {key}", key, git=False)
                self.assertTrue(os.path.isfile(main), key)
                self.assertEqual(project.detect(root)[0], kind, key)

    def test_sketch_file_is_named_after_its_folder(self):
        with tempfile.TemporaryDirectory() as d:
            root, main = project.create(d, "my sketch", "arduino", git=False)
            self.assertEqual(main, os.path.join(root, "my-sketch.ino"))
            self.assertEqual(os.path.basename(root), "my-sketch")

    def test_plain_python_main_is_not_micropython(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "main.py", "print(1)\n")
            self.assertEqual(project.detect(d)[0], "Python")

    def test_ino_files_are_cpp_with_an_arduino_starter(self):
        self.assertEqual(templates.key_for_path("/x/blink.ino"), "cpp")
        self.assertIn("void setup()", templates.starter_text("cpp", "/x/blink.ino"))


class Boards(unittest.TestCase):
    def test_lookup_ignores_board_options(self):
        self.assertEqual(embedded.board_by_fqbn("arduino:avr:nano:cpu=atmega328").id, "nano")
        self.assertEqual(embedded.board_by_fqbn("esp32:esp32:esp32").id, "esp32")
        self.assertIsNone(embedded.board_by_fqbn("vendor:arch:unknown"))

    def test_ids_and_fqbns_are_unique(self):
        ids = [b.id for b in embedded.BOARDS]
        self.assertEqual(len(ids), len(set(ids)))
        for b in embedded.BOARDS:
            self.assertEqual(b.fqbn.count(":") >= 2, True, b.id)
            self.assertIn(b.family, embedded.FAMILIES, b.id)

    def test_core_install_command_adds_the_board_manager_url(self):
        cmd = embedded.core_install_cmd("esp32:esp32:esp32")
        self.assertIn("core install esp32:esp32", cmd)
        self.assertIn("package_esp32_index.json", cmd)
        self.assertNotIn("--additional-urls", embedded.core_install_cmd("arduino:avr:uno"))
        self.assertEqual(embedded.core_install_cmd(""), "")


class Arduino(unittest.TestCase):
    def test_tasks_use_the_fqbn_from_sketch_yaml_and_the_port(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, f"{os.path.basename(d)}.ino", "void setup(){}\nvoid loop(){}\n")
            touch(d, "sketch.yaml", "default_fqbn: arduino:avr:uno\n")
            kind, t = embedded.detect(d, {}, "/dev/ttyACM0")
            self.assertEqual(kind, "Arduino")
            self.assertIn("--fqbn arduino:avr:uno", t["build"])
            self.assertIn("--upload --port /dev/ttyACM0", t["upload"])
            self.assertEqual(t["clean"], "rm -rf build")
            self.assertIn("core install arduino:avr", t["configure"])

    def test_missing_board_and_port(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "a.ino")
            self.assertEqual(embedded.missing("Arduino", d, {}, "", "build"), ["board"])
            self.assertEqual(embedded.missing("Arduino", d, {}, "", "upload"), ["board", "port"])
            touch(d, "sketch.yaml", "default_fqbn: arduino:avr:uno\n")
            self.assertEqual(embedded.missing("Arduino", d, {}, "/dev/ttyACM0", "upload"), [])
            self.assertEqual(embedded.missing("PlatformIO", d, {}, "", "upload"), [])

    def test_sketch_yaml_roundtrip_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "sketch.yaml", "default_port: /dev/ttyUSB0\ndefault_fqbn: arduino:avr:uno\n")
            embedded.write_sketch_yaml(d, "esp32:esp32:esp32")
            self.assertEqual(embedded.read_sketch_yaml(d), {"default_fqbn": "esp32:esp32:esp32", "default_port": "/dev/ttyUSB0"})
            os.remove(os.path.join(d, "sketch.yaml"))
            embedded.write_sketch_yaml(d, "arduino:avr:mega")
            self.assertEqual(embedded.read_sketch_yaml(d), {"default_fqbn": "arduino:avr:mega"})

    def test_compiler_errors_are_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            src = touch(d, "blink.ino", "x\n")
            loc = project.parse_line("blink.ino:3:5: error: 'foo' was not declared in this scope", d)
            self.assertEqual(loc[:4], (src, 3, 5, "error"))


class PlatformIO(unittest.TestCase):
    INI = """[platformio]
default_envs = esp32dev

[env]
framework = arduino
monitor_speed = 9600

[env:esp32dev]
platform = espressif32
board = esp32dev

[env:uno]
platform = atmelavr
board = uno
monitor_speed = 57600
"""

    def test_parse_envs_and_inheritance(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "platformio.ini", self.INI)
            p = embedded.pio_parse(d)
            self.assertEqual(p["envs"], ["esp32dev", "uno"])
            self.assertEqual(p["default"], ["esp32dev"])
            self.assertEqual(p["env"]["esp32dev"]["framework"], "arduino")
            self.assertEqual(p["env"]["uno"]["monitor_speed"], "57600")
            self.assertEqual(embedded.pio_env(d, {}), "esp32dev")
            self.assertEqual(embedded.pio_env(d, {"pio_env": "uno"}), "uno")
            self.assertEqual(embedded.board_info("PlatformIO", d, {})[0], "ESP32 Dev Module")

    def test_tasks_select_the_environment_and_port(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "platformio.ini", self.INI)
            _k, t = embedded.detect(d, {"pio_env": "uno"}, "/dev/ttyUSB0")
            self.assertIn("run -e uno -t upload --upload-port /dev/ttyUSB0", t["upload"])
            self.assertIn("-t compiledb", t["configure"])

    def test_set_board_changes_board_and_platform_only_in_that_env(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "platformio.ini", self.INI)
            self.assertTrue(embedded.pio_set_board(d, "esp32c3", "esp32dev"))
            p = embedded.pio_parse(d)
            self.assertEqual(p["env"]["esp32dev"]["board"], "esp32-c3-devkitm-1")
            self.assertEqual(p["env"]["esp32dev"]["platform"], "espressif32")
            self.assertEqual(p["env"]["uno"]["board"], "uno")

    def test_set_board_handles_the_pico_core_line(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "platformio.ini", "[env:x]\nplatform = espressif32\nboard = esp32dev\nframework = arduino\n")
            embedded.pio_set_board(d, "pico")
            txt = slurp(os.path.join(d, "platformio.ini"))
            self.assertIn("board = pico", txt)
            self.assertIn("board_build.core = earlephilhower", txt)
            self.assertIn("platform-raspberrypi", txt)
            embedded.pio_set_board(d, "uno")
            txt = slurp(os.path.join(d, "platformio.ini"))
            self.assertNotIn("earlephilhower", txt)
            self.assertIn("platform = atmelavr", txt)

    def test_set_board_without_env_section(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "platformio.ini", "[platformio]\n")
            self.assertFalse(embedded.pio_set_board(d, "uno"))


class IdfAndMicroPython(unittest.TestCase):
    def test_esp_idf_detection_target_and_export(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "CMakeLists.txt", "include($ENV{IDF_PATH}/tools/cmake/project.cmake)\nproject(x)\n")
            touch(d, "sdkconfig", 'CONFIG_IDF_TARGET="esp32s3"\nCONFIG_ESP_CONSOLE_UART_BAUDRATE=74880\n')
            exp = touch(d, "tools/export.sh", "")
            kind, t = embedded.detect(d, {"idf_export": exp, "chip": "esp32c3"}, "/dev/ttyUSB1")
            self.assertEqual(kind, "ESP-IDF")
            if not embedded.shutil.which("idf.py"):
                self.assertTrue(t["build"].startswith(f". {exp} >/dev/null 2>&1 && idf.py build"), t["build"])
            self.assertIn("idf.py -p /dev/ttyUSB1 flash", t["upload"])
            self.assertIn("set-target esp32c3", t["configure"])
            self.assertEqual(embedded.idf_target(d, {}), "esp32s3")
            self.assertEqual(embedded.guess_baud("ESP-IDF", d, {}), 74880)

    def test_plain_cmake_project_is_not_esp_idf(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "CMakeLists.txt", "project(x)\nadd_executable(x main.c)\n")
            self.assertEqual(project.detect(d)[0], "CMake")

    def test_micropython_upload_copies_py_files_and_folders(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "boot.py")
            touch(d, "main.py")
            touch(d, "lib/util.py")
            touch(d, ".aether/project.json", "{}")
            kind, t = embedded.detect(d, {}, "/dev/ttyACM0")
            self.assertEqual(kind, "MicroPython")
            self.assertIn("connect /dev/ttyACM0 fs cp boot.py : + fs cp main.py : + fs cp -r lib : + reset", t["upload"])
            self.assertTrue(t["run"].endswith("connect /dev/ttyACM0 run main.py"))
            self.assertIn("connect auto run", embedded.detect(d, {}, "")[1]["run"])

    def test_library_commands(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("lib install 'Adafruit NeoPixel'", embedded.lib_cmd("Arduino", d, {}, "", "Adafruit NeoPixel"))
            self.assertIn("lib search", embedded.lib_cmd("Arduino", d, {}, "", "x", search=True))
            self.assertIn("pkg install --library", embedded.lib_cmd("PlatformIO", d, {}, "", "x"))
            self.assertIn("mip install aioble", embedded.lib_cmd("MicroPython", d, {}, "/dev/ttyACM0", "aioble"))
            self.assertIsNone(embedded.lib_cmd("MicroPython", d, {}, "", "x", search=True))


class Baud(unittest.TestCase):
    def test_serial_begin_in_the_sketch_wins_over_the_default(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "a.ino", "void setup() {\n  Serial.begin( 9600 );\n}\n")
            self.assertEqual(embedded.guess_baud("Arduino", d, {}), 9600)
            self.assertEqual(embedded.guess_baud("Arduino", d, {"baud": 250000}), 250000)

    def test_defaults_to_115200(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "a.ino", "void setup(){}\n")
            self.assertEqual(embedded.guess_baud("Arduino", d, {}), 115200)

    def test_platformio_monitor_speed(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "platformio.ini", "[env:a]\nboard = uno\nmonitor_speed = 19200\n")
            self.assertEqual(embedded.guess_baud("PlatformIO", d, {}), 19200)


class Ports(unittest.TestCase):
    def test_default_port(self):
        ports = [embedded.Port("/dev/ttyUSB0", "a"), embedded.Port("/dev/ttyUSB1", "b")]
        self.assertEqual(embedded.default_port("/dev/ttyUSB1", ports), "/dev/ttyUSB1")
        self.assertEqual(embedded.default_port("", ports), "")
        self.assertEqual(embedded.default_port("/dev/gone", ports[:1]), "/dev/ttyUSB0")

    def test_port_problems(self):
        self.assertIsNone(embedded.port_problem(""))
        self.assertIn("re-plug", embedded.port_problem("/dev/ttyUSB-does-not-exist"))
        with tempfile.TemporaryDirectory() as d:
            p = touch(d, "tty", "")
            os.chmod(p, 0o644)
            if os.geteuid() != 0:                     # root can open anything
                self.assertIn("usermod -aG", embedded.port_problem(p))

    def test_natural_sort(self):
        names = ["/dev/ttyUSB10", "/dev/ttyUSB2", "/dev/ttyACM0"]
        self.assertEqual(sorted(names, key=embedded._natkey), ["/dev/ttyACM0", "/dev/ttyUSB2", "/dev/ttyUSB10"])


class Ansi(unittest.TestCase):
    def test_colours_are_kept_and_other_codes_dropped(self):
        self.assertEqual(embedded.split_ansi("a\x1b[0;32mI (12) x\x1b[0m b\x1b[2K"), [("a", None), ("I (12) x", "32"), (" b", None)])
        self.assertEqual(embedded.split_ansi("\x1b[1;31mE\x1b[0m"), [("E", "31")])
        self.assertEqual(embedded.split_ansi("plain"), [("plain", None)])


@unittest.skipIf(embedded.termios is None, "needs Linux termios")
class SerialPortOnAPty(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = os.openpty()
        self.path = os.ttyname(self.slave)

    def tearDown(self):
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def wait_readable(self, fd, t=1.0):
        return bool(select.select([fd], [], [], t)[0])

    def test_read_decodes_utf8_split_across_reads(self):
        sp = embedded.SerialPort(self.path, 115200)
        try:
            self.assertEqual(sp.read(), "")                     # nothing yet, and no exception
            data = "temp 21°C\n".encode()
            os.write(self.master, data[:8])
            self.wait_readable(self.slave)
            first = sp.read()
            os.write(self.master, data[8:])
            self.wait_readable(self.slave)
            self.assertEqual(first + sp.read(), "temp 21°C\n")
        finally:
            sp.close()

    def test_write_str_and_bytes(self):
        sp = embedded.SerialPort(self.path, 9600)
        try:
            sp.write("AT\r\n")
            sp.write(b"\x01\x02")
            self.assertTrue(self.wait_readable(self.master))
            self.assertEqual(os.read(self.master, 100), b"AT\r\n\x01\x02")
        finally:
            sp.close()

    def test_unusual_baud_rate_is_accepted_or_refused_cleanly(self):
        try:
            sp = embedded.SerialPort(self.path, 74880)         # ESP8266 boot-loader speed: not a termios constant
        except OSError as e:
            self.assertIn("74880", str(e))
        else:
            sp.close()

    def test_reset_pulse_does_not_fail_on_ttys_without_modem_lines(self):
        sp = embedded.SerialPort(self.path, 115200)
        try:
            sp.reset("rts")
            sp.reset("dtr")
        finally:
            sp.close()

    def test_close_is_idempotent(self):
        sp = embedded.SerialPort(self.path, 115200)
        sp.close()
        sp.close()


if __name__ == "__main__":
    unittest.main()
