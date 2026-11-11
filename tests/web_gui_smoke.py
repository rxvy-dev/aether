"""Headless GUI test of the web features.   Run:  xvfb-run -a python3 tests/web_gui_smoke.py

Drives the real window: new HTML + CSS + JS page, live preview (real WebKitGTK when installed), live typing,
CSS hot swap, console capture + eval, device sizes, HTML/CSS/JS switcher, Emmet and HTML/CSS/JS auto-indent.
Not named test_*.py on purpose: `make test` stays display-free.
"""
import os, shutil, sys, tempfile, time

TMP = tempfile.mkdtemp(prefix="aether-web-")
for var, sub in (("XDG_CONFIG_HOME", "cfg"), ("XDG_CACHE_HOME", "cache"), ("HOME", "home")):
    os.environ[var] = os.path.join(TMP, sub)
    os.makedirs(os.environ[var])
os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import gi                                                                   # noqa: E402
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Gdk                                    # noqa: E402

from aether import webui, webdev                                            # noqa: E402
from aether.app import AetherApp                                            # noqa: E402

FAILS = []
SHOTS = os.environ.get("AETHER_SHOTS")          # folder: save screenshots there


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def pump(ms=100, until=None, timeout=15000):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + (timeout if until else ms) / 1000.0
    while time.monotonic() < end:
        while ctx.iteration(False):
            pass
        if until and until():
            return True
        time.sleep(0.01)
    return until() if until else True


def console_texts(win):
    out = []
    r = win.web_console.list.get_first_child()
    while r:
        lbl = r.get_child().get_first_child().get_next_sibling()
        out.append((getattr(r, "_level", ""), lbl.get_text()))
        r = r.get_next_sibling()
    return out


def page_js(win, expr):
    """Evaluate JS in the preview and return the result as a string (WebKit only)."""
    view = win.web_preview.view
    box = {}

    def done(v, res):
        try:
            box["v"] = v.evaluate_javascript_finish(res).to_string()
        except Exception as e:
            box["v"] = "ERR " + str(e)
    view.evaluate_javascript(expr, -1, None, None, None, done)
    pump(until=lambda: "v" in box, timeout=5000)
    return box.get("v")


def type_text(tab, text):
    """Send key presses through the editor's own key handler (auto-indent, Emmet, auto-close)."""
    for ch in text:
        kv = {"\n": Gdk.KEY_Return, "\t": Gdk.KEY_Tab}.get(ch) or Gdk.unicode_to_keyval(ord(ch))
        if not tab._on_key(None, kv, 0, Gdk.ModifierType(0)):
            if ch == "\t":
                tab.buffer.insert_at_cursor("\t")
            else:
                tab.buffer.insert_at_cursor(ch)


def shot(win, name):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    pump(400)
    paintable = Gtk.WidgetPaintable.new(win)
    w, h = win.get_width(), win.get_height()
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, w, h)
    node = snap.to_node()
    if node is None:
        return
    renderer = win.get_native().get_renderer()
    tex = renderer.render_texture(node, None)
    tex.save_to_png(os.path.join(SHOTS, name + ".png"))


def run(app):
    win = app._window()
    win.set_default_size(1500, 900)
    win.present()
    pump(400)
    has_wk = webui.webkit() is not None
    print(f"WebKitGTK: {'yes' if has_wk else 'no (browser fallback)'}")
    launched = []
    win._web_launch = lambda url: launched.append(url)          # never open a real browser from a test

    print("New page — HTML + CSS + JS")
    parent = os.path.join(TMP, "home", "Projects")
    os.makedirs(parent)
    win.web_new_page()
    pump(until=lambda: win.web_srv is not None and win.web_srv.running, timeout=5000)
    root = os.path.join(parent, "web-playground")
    html, css, js = (os.path.join(root, f) for f in ("index.html", "style.css", "script.js"))
    check(all(os.path.isfile(p) for p in (html, css, js)), "index.html + style.css + script.js created")
    titles = [t.title for t in win.tabs()]
    check(titles[:3] == ["index.html", "style.css", "script.js"], f"three tabs side by side, in order ({titles})")
    check(win.project and win.project.kind == "Web", f"folder detected as a Web project ({win.project and win.project.kind})")
    check(win.web_preview is not None and win.web_preview.get_visible(), "preview pane is showing")
    check(win.web_chip.get_visible() and str(win.web_srv.port) in win.web_chip.get_label(), "status bar shows the live server")
    check(win.web_srv.url_for(html).startswith("http://127.0.0.1:"), "served from 127.0.0.1 only (offline)")

    if has_wk:
        ok = pump(until=lambda: page_js(win, "document.readyState") == "complete", timeout=10000)
        check(ok, "page loaded in WebKit")
        check(pump(until=lambda: win.web_srv.clients >= 1, timeout=8000), "page connected for live reload")
        check(pump(until=lambda: any("loaded" in t for _l, t in console_texts(win)), timeout=6000),
              f"console.log from script.js shows in the Console ({console_texts(win)[-3:]})")
        rows = [r for r in console_texts(win)]
        shot(win, "1-new-page")

        print("Live typing")
        win.web_goto("html")
        pump(100)
        t = win.cur()
        check(t.path == html, "HTML button jumps to the page")
        b = t.buffer
        text = t.get_text().replace("<h1>web-playground</h1>", "<h1 id='t'>Typed live</h1>")
        b.set_text(text)
        check(pump(until=lambda: page_js(win, "(document.getElementById('t')||{}).textContent") == "Typed live", timeout=8000),
              "unsaved HTML edit shows up in the preview")
        check(b.get_modified() and "Typed live" not in open(html).read(), "…without touching the file on disk")

        print("CSS hot swap")
        win.web_goto("css")
        pump(100)
        t = win.cur()
        check(t.path == css, "CSS button jumps to style.css")
        page_js(win, "window.__keep = 42")
        t.buffer.insert(t.buffer.get_end_iter(), "\nh1 { color: rgb(0, 200, 0); }\n")
        check(pump(until=lambda: page_js(win, "getComputedStyle(document.querySelector('h1')).color") == "rgb(0, 200, 0)", timeout=8000),
              "new CSS applied")
        check(page_js(win, "String(window.__keep)") == "42", "…without reloading the page (state kept)")

        print("JS + console")
        win.web_goto("js")
        pump(100)
        t = win.cur()
        check(t.path == js, "JS button jumps to script.js")
        t.buffer.insert(t.buffer.get_end_iter(), '\nconsole.warn("careful");\nnotDefined();\n')
        check(pump(until=lambda: any(l == "warn" and "careful" in x for l, x in console_texts(win)), timeout=8000), "console.warn captured")
        check(pump(until=lambda: any(l == "error" and "notDefined" in x for l, x in console_texts(win)), timeout=8000),
              "uncaught error captured")
        err = next((r for r in iter_rows(win) if getattr(r, "_level", "") == "error"), None)
        check(err is not None and getattr(err, "_loc", (None,))[0] == js, f"error row links to script.js ({getattr(err, '_loc', None)})")
        check("✖" in win.web_console_label.get_text(), f"Console tab counts errors ({win.web_console_label.get_text()!r})")
        if err is not None:
            win.web_console._activated(None, err)
            pump(100)
            check(win.cur().path == js and win.cur().position()[0] == err._loc[1], "clicking it opens the line")
        win.web_console.entry.set_text("6 * 7")
        win.web_console._run()
        check(pump(until=lambda: any(l == "result" and x == "42" for l, x in console_texts(win)), timeout=6000),
              "console prompt runs JS in the page")

        print("Save")
        t.save()
        pump(400)
        check(win.web_srv.overlay(js) is None, "saving drops the in-memory copy")

        print("Devices")
        pane = win.web_preview
        pane.set_device("Phone · 390")
        pump(700)
        check(page_js(win, "String(window.innerWidth)") == "390", f"phone: page is 390px wide ({page_js(win, 'String(window.innerWidth)')})")
        shot(win, "2-phone")
        pane.rotate()
        pump(700)
        rw = page_js(win, "String(window.innerWidth)")
        check(rw == "844", f"rotated: 844px ({rw}, zoom {pane.view.get_zoom_level():.2f})")
        pane.set_device("Desktop · 1920")
        pump(900)
        print("     stage", pane.stage.get_width(), "view", pane.view.get_width(), "frame", pane.frame.dev, "zoom", pane.view.get_zoom_level())
        w = page_js(win, "String(window.innerWidth)")
        check(w == "1920", f"desktop: page is 1920px wide, scaled to fit ({w}, zoom {pane.view.get_zoom_level():.2f})")
        check(pane.view.get_zoom_level() < 1.0, "desktop scaled down to fit the pane")
        shot(win, "3-desktop")
        pane.set_device("Desktop · 1920")          # clicking the active size again -> responsive
        pump(500)
        check(pane.device == "Responsive", "click again: back to responsive")
    else:
        check(bool(launched), "without WebKit: opens in the browser")

    print("HTML auto-indent + Emmet")
    win.new_untitled("html")
    pump(100)
    t = win.cur()
    t.buffer.set_text("")
    type_text(t, "<div>\nx")
    check(t.get_text() == "<div>\n  x\n</div>", f"Enter inside <div></div> indents ({t.get_text()!r})")
    t.buffer.set_text("")
    type_text(t, "<ul>\n<li>a</")
    check(t.get_text() == "<ul>\n  <li>a</li>\n</ul>" and t.position() == (2, 13),
          f"</ steps over the auto-closed tag ({t.get_text()!r} {t.position()})")
    t.buffer.set_text("<section>\n  <p>hi</p>\n  ")
    t.buffer.place_cursor(t.buffer.get_end_iter())
    type_text(t, "</")
    check(t.get_text() == "<section>\n  <p>hi</p>\n</section>", f"</ closes the open tag and lines it up ({t.get_text()!r})")
    t.buffer.set_text("")
    type_text(t, "ul>li.item$*3\t")
    check(t.get_text() == '<ul>\n  <li class="item1"></li>\n  <li class="item2"></li>\n  <li class="item3"></li>\n</ul>',
          f"Emmet ul>li.item$*3 ({t.get_text()!r})")
    line, col = t.position()
    check((line, col) == (2, 21), f"cursor lands in the first <li> ({line},{col})")
    t.buffer.set_text("")
    type_text(t, "hello\t")
    check(t.get_text() == "hello\t", "plain words are not expanded")

    print("CSS / JS auto-indent")
    win.new_untitled("css")
    t = win.cur()
    t.buffer.set_text("")
    type_text(t, "body {\ncolor: red;")
    check(t.get_text() == "body {\n  color: red;\n}", f"CSS block indents ({t.get_text()!r})")
    win.new_untitled("javascript")
    t = win.cur()
    t.buffer.set_text("")
    type_text(t, "function f() {\nif (x) {\nreturn 1;")
    check(t.get_text() == "function f() {\n  if (x) {\n    return 1;\n  }\n}", f"JS blocks indent ({t.get_text()!r})")

    print("Unsaved HTML tab previews too")
    win.new_untitled("html")
    t = win.cur()
    t.buffer.set_text("<!doctype html><html><head></head><body><p id=s>scratch</p></body></html>")
    win.act_run()
    pump(500)
    check(win.web_page and win.web_page.endswith("index.html") and "web-scratch" in win.web_page, "F5 on an untitled HTML tab previews it")
    if has_wk:
        check(pump(until=lambda: page_js(win, "(document.getElementById('s')||{}).textContent") == "scratch", timeout=8000),
              "scratch page rendered")

    print("Language picker")
    win.act_new()
    pump(200)
    ps = [w for w in Gtk.Window.list_toplevels() if type(w).__name__ == "Palette"]
    check(ps and ps[0].items[0][0].startswith("Web page — HTML + CSS + JS"), "first choice is Web page — HTML + CSS + JS")
    check(ps and all(len(i) == 4 and i[3] is not None for i in ps[0].items), "every language has an icon")
    for p in ps:
        p.close()

    print("Export")
    win.web_show(html)
    pump(300)
    win.web_export()
    single = os.path.join(root, "index.single.html")
    check(os.path.isfile(single) and "<style>" in open(single).read() and "careful" in open(single).read(),
          "export inlines CSS and JS into one file")
    win.web_stop()
    check(not win.web_srv.running, "server stops")
    for tb in win.tabs():
        tb.buffer.set_modified(False)
    app.quit()


def iter_rows(win):
    r = win.web_console.list.get_first_child()
    while r:
        yield r
        r = r.get_next_sibling()


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
