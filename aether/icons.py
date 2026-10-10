"""Vector icons drawn with cairo — no icon theme or SVG loader needed, always crisp, follow the theme colour.

  IconView("files")              a widget that draws an icon in its CSS colour
  file_texture(path, is_dir)     a Gdk.Texture for the file tree / tabs (Seti-style coloured badges)
"""
import math, os
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib

try:
    gi.require_foreign("cairo")
    import cairo
    HAS_CAIRO = True
except (ImportError, TypeError):
    cairo = None
    HAS_CAIRO = False


# ------------------------------------------------------------------ line icons (24×24 grid, stroked)
def _p(cr, pts, close=False):
    cr.move_to(*pts[0])
    for pt in pts[1:]:
        cr.line_to(*pt)
    if close:
        cr.close_path()


def _rrect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


def _files(cr):
    _p(cr, [(14, 3), (7, 3), (7, 17), (19, 17), (19, 8), (14, 3)], True)
    _p(cr, [(14, 3), (14, 8), (19, 8)])
    _p(cr, [(7, 7), (4, 7), (4, 21), (15, 21), (15, 17)])
    cr.stroke()


def _search(cr):
    cr.new_sub_path(); cr.arc(10.5, 10.5, 6.5, 0, 2 * math.pi)
    _p(cr, [(15.5, 15.5), (21, 21)])
    cr.stroke()


def _git(cr):
    for cx, cy in ((6, 5), (6, 19), (18, 7)):
        cr.new_sub_path(); cr.arc(cx, cy, 2.4, 0, 2 * math.pi)
    _p(cr, [(6, 7.4), (6, 16.6)])
    cr.move_to(18, 9.4); cr.curve_to(18, 14, 10, 12, 6.8, 16.8)
    cr.stroke()


def _outline(cr):
    for y in (6, 12, 18):
        cr.new_sub_path(); cr.arc(5, y, 1.2, 0, 2 * math.pi)
        cr.fill()
    _p(cr, [(9, 6), (20, 6)]); _p(cr, [(12, 12), (20, 12)]); _p(cr, [(12, 18), (20, 18)])
    cr.stroke()


def _bug(cr):
    _rrect(cr, 7.5, 8, 9, 12, 4.5)
    _p(cr, [(9.5, 8), (9.5, 6.5)]); cr.arc(12, 6.5, 2.5, math.pi, 2 * math.pi); _p(cr, [(14.5, 6.5), (14.5, 8)])
    for y, dx in ((11, 4), (15, 4.5), (19, 3.5)):
        _p(cr, [(7.5, y), (7.5 - dx, y - 1.5)]); _p(cr, [(16.5, y), (16.5 + dx, y - 1.5)])
    _p(cr, [(12, 11), (12, 19)])
    cr.stroke()


def _debug(cr):
    _p(cr, [(6, 4), (17, 12), (6, 20)], True)
    cr.stroke()
    cr.new_sub_path(); cr.arc(18.5, 18.5, 2.6, 0, 2 * math.pi); cr.fill()


def _gear(cr):
    n, ro, ri = 8, 9.5, 7.2
    for i in range(n * 2):
        a = i * math.pi / n
        r = ro if i % 2 == 0 else ri
        a1, a2 = a - math.pi / (n * 2.6), a + math.pi / (n * 2.6)
        pts = [(12 + r * math.cos(a1), 12 + r * math.sin(a1)), (12 + r * math.cos(a2), 12 + r * math.sin(a2))]
        (cr.move_to if i == 0 else cr.line_to)(*pts[0])
        cr.line_to(*pts[1])
    cr.close_path()
    cr.new_sub_path(); cr.arc(12, 12, 3, 0, 2 * math.pi)
    cr.stroke()


def _hammer(cr):
    _p(cr, [(13, 11), (4.5, 19.5)])
    cr.set_line_width(cr.get_line_width() * 1.25); cr.stroke()
    cr.set_line_width(cr.get_line_width() / 1.25)
    _p(cr, [(10, 6.5), (14.5, 2.5), (21.5, 9.5), (17.5, 13.5)])
    _p(cr, [(10, 6.5), (17.5, 13.5)])
    cr.stroke()


def _play(cr):
    _p(cr, [(7, 4), (19, 12), (7, 20)], True)
    cr.fill_preserve(); cr.stroke()


def _stop(cr):
    _rrect(cr, 6, 6, 12, 12, 2)
    cr.fill_preserve(); cr.stroke()


def _terminal(cr):
    _rrect(cr, 3, 4, 18, 16, 3)
    _p(cr, [(7, 9), (10, 12), (7, 15)]); _p(cr, [(12, 15), (17, 15)])
    cr.stroke()


def _sidebar(cr):
    _rrect(cr, 3, 4, 18, 16, 3)
    _p(cr, [(9, 4), (9, 20)])
    cr.stroke()


def _build_run(cr):
    _p(cr, [(4, 20), (10, 14)]); cr.stroke()
    _p(cr, [(8, 9), (11, 6), (15, 10), (12, 13)], True); cr.stroke()
    _p(cr, [(14, 13), (21, 17.5), (14, 22)], True)
    cr.fill_preserve(); cr.stroke()


ICONS = {"files": _files, "search": _search, "git": _git, "outline": _outline, "debug": _debug, "bug": _bug,
         "settings": _gear, "build": _hammer, "run": _play, "stop": _stop, "terminal": _terminal,
         "sidebar": _sidebar, "build-run": _build_run}


def draw_icon(cr, name, size, rgba):
    fn = ICONS.get(name)
    if not fn:
        return
    cr.save()
    s = size / 24.0
    cr.scale(s, s)
    cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
    cr.set_line_width(1.7)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    fn(cr)
    cr.restore()


class IconView(Gtk.DrawingArea):
    """An icon drawn in the widget's current CSS colour (so :hover / :checked styling applies)."""

    def __init__(self, name, size=20):
        super().__init__()
        self.name = name
        self.size = size
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_can_target(False)
        self.add_css_class("aether-icon")
        if HAS_CAIRO:
            self.set_draw_func(self._draw)

    def set_icon(self, name):
        self.name = name
        self.queue_draw()

    def _draw(self, area, cr, w, h):
        c = self.get_color()
        cr.translate((w - self.size) / 2, (h - self.size) / 2)
        draw_icon(cr, self.name, self.size, c)


def icon_button(name, label=None, tooltip=None, size=16):
    b = Gtk.Button(tooltip_text=tooltip)
    box = Gtk.Box(spacing=7)
    box.append(IconView(name, size))
    if label:
        box.append(Gtk.Label(label=label))
    b.set_child(box)
    return b


# ------------------------------------------------------------------ file-type badges (Seti-style)
FT = {
    ".c": ("C", "#599eff"), ".h": ("H", "#a074c4"), ".cpp": ("C+", "#f34b7d"), ".cc": ("C+", "#f34b7d"),
    ".cxx": ("C+", "#f34b7d"), ".hpp": ("H+", "#a074c4"), ".hh": ("H+", "#a074c4"), ".py": ("Py", "#4b8bbe"),
    ".rs": ("Rs", "#dea584"), ".go": ("Go", "#00add8"), ".js": ("JS", "#e8d44d"), ".mjs": ("JS", "#e8d44d"),
    ".jsx": ("JS", "#61dafb"), ".ts": ("TS", "#3178c6"), ".tsx": ("TS", "#61dafb"), ".json": ("{}", "#cbcb41"),
    ".md": ("M", "#519aba"), ".sh": ("$", "#89e051"), ".bash": ("$", "#89e051"), ".zsh": ("$", "#89e051"),
    ".toml": ("Tm", "#c26b3a"), ".yaml": ("Ym", "#a074c4"), ".yml": ("Ym", "#a074c4"), ".ini": ("Cf", "#6d8086"),
    ".cfg": ("Cf", "#6d8086"), ".conf": ("Cf", "#6d8086"), ".html": ("<>", "#e44d26"), ".htm": ("<>", "#e44d26"),
    ".css": ("#", "#42a5f5"), ".scss": ("#", "#cd6799"), ".java": ("J", "#b07219"), ".kt": ("K", "#a97bff"),
    ".lua": ("Lu", "#51a0cf"), ".rb": ("Rb", "#cc342d"), ".php": ("P", "#8892bf"), ".zig": ("Z", "#f7a41d"),
    ".swift": ("Sw", "#f05138"), ".dart": ("D", "#00b4ab"), ".cs": ("C#", "#68217a"), ".sql": ("Sq", "#e38c00"),
    ".txt": ("Tx", "#8a8a8a"), ".xml": ("<>", "#e37933"), ".svg": ("◇", "#ffb13b"), ".png": ("▣", "#a074c4"),
    ".jpg": ("▣", "#a074c4"), ".gif": ("▣", "#a074c4"), ".o": ("o", "#6d6d6d"), ".a": ("a", "#6d6d6d"),
    ".so": ("so", "#6d6d6d"), ".s": ("as", "#6e4c13"), ".asm": ("as", "#6e4c13"), ".nix": ("❄", "#7eb6ff"),
    ".diff": ("±", "#41b883"), ".patch": ("±", "#41b883"), ".lock": ("lk", "#8a8a8a"),
}
NAMES = {"makefile": ("Mk", "#e37933"), "gnumakefile": ("Mk", "#e37933"), "cmakelists.txt": ("Cm", "#6d8086"),
         "meson.build": ("Me", "#a074c4"), "cargo.toml": ("Rs", "#dea584"), "dockerfile": ("D", "#0db7ed"),
         ".gitignore": ("Gi", "#f14e32"), ".gitmodules": ("Gi", "#f14e32"), "license": ("©", "#cbcb41"),
         "readme.md": ("i", "#519aba"), "package.json": ("np", "#cb3837"), "go.mod": ("Go", "#00add8"),
         "build.zig": ("Z", "#f7a41d"), ".editorconfig": ("Ec", "#6d8086"), ".env": ("En", "#faf743")}

_cache = {}


def _texture_from_surface(surf):
    surf.flush()
    w, h = surf.get_width(), surf.get_height()
    data = GLib.Bytes.new(bytes(surf.get_data()))
    return Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, data, surf.get_stride())


def _hex(c):
    c = c.lstrip("#")
    return int(c[0:2], 16) / 255, int(c[2:4], 16) / 255, int(c[4:6], 16) / 255


def _badge(label, color, px):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    cr = cairo.Context(surf)
    r, g, b = _hex(color)
    cr.set_source_rgb(r, g, b)
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    size = px * (0.86 if len(label) == 1 else 0.66)
    cr.set_font_size(size)
    ext = cr.text_extents(label)
    cr.move_to((px - ext.width) / 2 - ext.x_bearing, (px - ext.height) / 2 - ext.y_bearing)
    cr.show_text(label)
    return surf


def _folder(px, opened, color="#dcb67a"):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    cr = cairo.Context(surf)
    s = px / 16.0
    cr.scale(s, s)
    r, g, b = _hex(color)
    cr.set_source_rgb(r * 0.82, g * 0.82, b * 0.82)
    _p(cr, [(1.5, 3), (6, 3), (7.5, 4.5), (14.5, 4.5), (14.5, 13), (1.5, 13)], True)
    cr.fill()
    cr.set_source_rgb(r, g, b)
    if opened:
        _p(cr, [(3.2, 6.5), (15.5, 6.5), (13.5, 13), (1.5, 13)], True)
    else:
        _p(cr, [(1.5, 6), (14.5, 6), (14.5, 13), (1.5, 13)], True)
    cr.fill()
    return surf


def _doc(px, color="#8a8a8a"):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    cr = cairo.Context(surf)
    cr.scale(px / 16.0, px / 16.0)
    r, g, b = _hex(color)
    cr.set_source_rgb(r, g, b)
    cr.set_line_width(1.2)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    _p(cr, [(3.5, 1.8), (9.5, 1.8), (12.5, 4.8), (12.5, 14.2), (3.5, 14.2)], True)
    cr.stroke()
    _p(cr, [(9.5, 1.8), (9.5, 4.8), (12.5, 4.8)])
    cr.stroke()
    return surf


def file_kind(path, is_dir=False):
    if is_dir:
        return ("dir", None)
    n = os.path.basename(path).lower()
    if n in NAMES:
        return NAMES[n]
    return FT.get(os.path.splitext(n)[1], ("doc", None))


def file_texture(path, is_dir=False, opened=False, px=32):
    """Texture for the file tree / tab labels (rendered at 2× for HiDPI)."""
    if not HAS_CAIRO:
        return None
    kind = file_kind(path, is_dir)
    key = (kind, opened, px)
    t = _cache.get(key)
    if t is None:
        if kind[0] == "dir":
            surf = _folder(px, opened)
        elif kind[0] == "doc":
            surf = _doc(px)
        else:
            surf = _badge(kind[0], kind[1], px)
        t = _cache[key] = _texture_from_surface(surf)
    return t


def file_image(path, size=16):
    """A Gtk.Image with the file-type badge (for tab labels)."""
    tex = file_texture(path or "x.txt")
    img = Gtk.Image.new_from_paintable(tex) if tex else Gtk.Image()
    img.set_pixel_size(size)
    return img
