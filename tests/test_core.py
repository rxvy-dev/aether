"""Unit tests for the non-GUI parts. Run:  make test"""
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aether import folding, project, symbols                     # noqa: E402
from aether.debugger import parse_record, value_children         # noqa: E402

C = """#include <stdio.h>
/* multi
 * line
 */
int main(void) {
    char *s = "}{";
    if (1) {
        puts("x"); // }
        puts("y");
    }
    return 0;
}
"""


class Folding(unittest.TestCase):
    def test_c_braces_ignore_strings_and_comments(self):
        self.assertEqual(folding.compute_regions(C, "c"), {1: 2, 6: 8, 4: 10})

    def test_python_indent(self):
        src = "def a():\n    x = 1\n    if x:\n        y()\n\n    z()\nprint()\n"
        self.assertEqual(folding.compute_regions(src, "python"), {0: 5, 2: 3})

    def test_markdown_headings(self):
        self.assertEqual(folding.compute_regions("# A\ntext\n## B\nmore\n# C\nx\n", "markdown"), {0: 3, 2: 3, 4: 5})


class Debugger(unittest.TestCase):
    def test_result_record(self):
        kind, tok, cls, p = parse_record('7^done,bkpt={number="1",line="12",fullname="/x/main.c"}')
        self.assertEqual((kind, tok, cls), ("^", 7, "done"))
        self.assertEqual(p["bkpt"]["line"], "12")

    def test_stopped_record_with_list(self):
        _k, _t, cls, p = parse_record('*stopped,reason="breakpoint-hit",frame={func="main",args=[{name="argc",value="1"}],line="5"}')
        self.assertEqual(cls, "stopped")
        self.assertEqual(p["frame"]["args"][0]["value"], "1")

    def test_stream_record_escapes(self):
        self.assertEqual(parse_record('~"hello\\n\\"q\\""')[3], 'hello\n"q"')

    def test_value_children(self):
        self.assertEqual(value_children('{x = 1, y = {a = 2, b = "h,i"}, 0x0}'),
                         [("x", "1"), ("y", '{a = 2, b = "h,i"}'), ("[2]", "0x0")])
        self.assertIsNone(value_children("42"))


class Projects(unittest.TestCase):
    def test_create_and_detect_every_template(self):
        expected = {"c": "Makefile", "c-meson": "Meson", "cpp": "CMake", "python": "Python", "rust": "Cargo",
                    "go": "Go", "web": None, "bash": None}
        with tempfile.TemporaryDirectory() as d:
            for key, kind in expected.items():
                root, main = project.create(d, f"demo {key}", key, git=False)
                self.assertTrue(os.path.isfile(main), key)
                self.assertEqual(project.detect(root)[0], kind, key)

    def test_makefile_run_target(self):
        with tempfile.TemporaryDirectory() as d:
            root, _ = project.create(d, "m", "c", git=False)
            self.assertEqual(project.detect(root)[1]["run"], "make run")

    def test_parse_gcc_and_rust_and_python(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "main.c")
            with open(src, "w") as fh:
                fh.write("int main(){}\n")
            loc = project.parse_line("main.c:3:5: error: 'oops' undeclared", d)
            self.assertEqual(loc[:4], (src, 3, 5, "error"))
            self.assertEqual(project.parse_line("  --> src/main.rs:2:9", d)[1:3], (2, 9))
            self.assertEqual(project.parse_line('  File "/tmp/x.py", line 12, in f', d)[:2], ("/tmp/x.py", 12))
            self.assertIsNone(project.parse_line("gcc -o main main.c", d))


class Symbols(unittest.TestCase):
    def test_c_typedef_struct(self):
        src = "typedef struct {\n    int x;\n} Point;\n\nint main(void) {\n}\n"
        names = [s[2] for s in symbols.extract("c", src)]
        self.assertIn("Point", names)
        self.assertIn("main", names)


if __name__ == "__main__":
    unittest.main()
