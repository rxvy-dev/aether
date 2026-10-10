"""`aether --doctor`: check that everything Aether needs is installed, on any distro."""
import os, shutil, sys

if sys.stdout.isatty():
    OK, BAD, OPT = "\033[32m✔\033[0m", "\033[31m✖\033[0m", "\033[33m•\033[0m"
else:
    OK, BAD, OPT = "✔", "✖", "•"


def _typelib(ns, ver):
    try:
        import gi
        gi.require_version(ns, ver)
        mod = __import__("gi.repository", fromlist=[ns])
        return getattr(mod, ns)
    except Exception:
        return None


def check():
    """Returns (problems, report_lines). problems = number of missing *required* things."""
    lines, problems = [], 0

    def row(ok, required, name, detail=""):
        nonlocal problems
        mark = OK if ok else (BAD if required else OPT)
        if not ok and required:
            problems += 1
        lines.append(f"  {mark} {name}{('  — ' + detail) if detail else ''}")

    lines.append("Required")
    row(sys.version_info >= (3, 9), True, f"Python {sys.version.split()[0]}", "" if sys.version_info >= (3, 9) else "need 3.9+")
    try:
        import gi  # noqa: F401
        row(True, True, "PyGObject (python gi bindings)")
    except ImportError:
        row(False, True, "PyGObject (python gi bindings)", "not found for " + sys.executable)
        return problems, lines
    try:
        gi.require_foreign("cairo")
        row(True, True, "PyGObject cairo bridge")
    except Exception:
        row(False, True, "PyGObject cairo bridge", "needed to draw extra cursors (python3-gi-cairo / python-cairo)")
    Gtk = _typelib("Gtk", "4.0")
    if Gtk:
        v = (Gtk.get_major_version(), Gtk.get_minor_version())
        row(v >= (4, 8), True, f"GTK {v[0]}.{v[1]}", "" if v >= (4, 8) else "need 4.8+")
    else:
        row(False, True, "GTK 4", "typelib Gtk-4.0 not found")
    Src = _typelib("GtkSource", "5")
    if Src:
        v = (Src.get_major_version(), Src.get_minor_version())
        row(v >= (5, 6), True, f"GtkSourceView {v[0]}.{v[1]}", "" if v >= (5, 6) else "need 5.6+")
    else:
        row(False, True, "GtkSourceView 5", "typelib GtkSource-5 not found")

    lines.append("Recommended")
    row(_typelib("Vte", "3.91") is not None, False, "VTE for GTK 4", "integrated terminal + debugger program tab")
    row(shutil.which("gdb") is not None, False, "gdb", "debugger (F6)")
    row(shutil.which("git") is not None, False, "git", "source control, clone, new projects")
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    row(cc is not None, False, "C compiler (gcc / clang)", "build & run C/C++")
    row(shutil.which("make") is not None, False, "make", "Makefile projects")

    lines.append("Optional (language servers & tools)")
    for tool, why in (("clangd", "C/C++ completion, go-to-definition, outline"), ("pyright-langserver", "Python intelligence"),
                      ("rust-analyzer", "Rust intelligence"), ("gopls", "Go intelligence"), ("cmake", "CMake projects"),
                      ("meson", "Meson projects"), ("clang-format", "format C/C++"), ("shellcheck", "shell diagnostics")):
        row(shutil.which(tool) is not None, False, tool, why)
    return problems, lines


def main():
    problems, lines = check()
    print("Aether doctor\n")
    print("\n".join(lines))
    print()
    if problems:
        print(f"{problems} required component(s) missing. Run:  ./install.sh --deps   (from the source folder)")
    else:
        print("Everything required is installed. Missing extras are optional.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
