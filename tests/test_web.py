"""Web development: preview server, live reload, console bridge, asset links, bundling, Emmet. No display needed."""
import json, os, shutil, sys, tempfile, threading, time, unittest, urllib.error, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from aether import webdev, emmet, project  # noqa: E402

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # 127.0.0.1 never goes through a proxy


def get(url):
    with OPENER.open(url, timeout=5) as r:
        return r.status, r.headers, r.read().decode("utf-8", errors="replace")


class Server(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aether-web-test-")
        with open(os.path.join(self.root, "index.html"), "w") as f:
            f.write('<!DOCTYPE html>\n<html>\n<head>\n  <link rel="stylesheet" href="style.css">\n</head>\n<body>\n'
                    '  <h1>Hi</h1>\n  <script src="script.js"></script>\n</body>\n</html>\n')
        with open(os.path.join(self.root, "style.css"), "w") as f:
            f.write("h1 { color: red; }\n")
        with open(os.path.join(self.root, "script.js"), "w") as f:
            f.write("console.log('hi');\n")
        os.makedirs(os.path.join(self.root, "docs"))
        with open(os.path.join(self.root, "docs", "a.html"), "w") as f:
            f.write("<p>a</p>")
        self.msgs = []
        self.srv = webdev.PreviewServer(self.root, on_console=self.msgs.append, port=0)
        self.srv.start()

    def tearDown(self):
        self.srv.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_serves_pages_with_bridge(self):
        code, hdr, body = get(self.srv.url_for(os.path.join(self.root, "index.html")))
        self.assertEqual(code, 200)
        self.assertIn("text/html", hdr["Content-Type"])
        self.assertIn("no-store", hdr["Cache-Control"])
        self.assertIn('<head><script src="/__aether__/bridge.js"></script>', body)
        self.assertEqual(get(self.srv.origin + "/")[2], body)            # / -> index.html
        self.assertIn("EventSource", get(self.srv.origin + "/__aether__/bridge.js")[2])

    def test_only_localhost(self):
        self.assertEqual(self.srv._httpd.server_address[0], "127.0.0.1")
        self.assertTrue(self.srv.origin.startswith("http://127.0.0.1:"))

    def test_mime_types(self):
        self.assertIn("text/css", get(self.srv.origin + "/style.css")[1]["Content-Type"])
        self.assertIn("text/javascript", get(self.srv.origin + "/script.js")[1]["Content-Type"])

    def test_overlay_serves_unsaved_text(self):
        css = os.path.join(self.root, "style.css")
        self.srv.set_overlay(css, "h1 { color: blue; }")
        self.assertEqual(get(self.srv.origin + "/style.css")[2], "h1 { color: blue; }")
        self.assertIn("red", open(css).read())                          # disk untouched
        self.srv.clear_overlay(css)
        self.assertIn("red", get(self.srv.origin + "/style.css")[2])

    def test_404_reports_to_console_and_injects(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            get(self.srv.origin + "/img/missing.png")
        self.assertEqual(cm.exception.code, 404)
        self.assertIn("bridge.js", cm.exception.read().decode())         # reloads when the file appears
        self.assertTrue(any("missing.png" in m["text"] for m in self.msgs))

    def test_no_escape_from_root(self):
        for bad in ("/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/docs/../../x"):
            p = self.srv._fs_path(bad)
            self.assertTrue(p is None or p.startswith(self.root + os.sep), (bad, p))     # never outside the folder
        self.assertEqual(self.srv._fs_path("/docs/a.html"), os.path.join(self.root, "docs", "a.html"))

    def test_directory_listing(self):
        os.remove(os.path.join(self.root, "docs", "a.html"))
        with open(os.path.join(self.root, "docs", "b.html"), "w") as f:
            f.write("b")
        body = get(self.srv.origin + "/docs/")[2]
        self.assertIn("b.html", body)

    def test_console_post(self):
        data = json.dumps([{"level": "warn", "text": "careful", "url": self.srv.origin + "/script.js", "line": 3, "col": 2},
                           {"level": "log", "text": "second"}]).encode()
        OPENER.open(urllib.request.Request(self.srv.origin + "/__aether__/console", data=data, method="POST"), timeout=5)
        self.assertEqual([m["text"] for m in self.msgs[-2:]], ["careful", "second"])        # order kept
        self.assertEqual(self.srv.path_for_url(self.msgs[-2]["url"]), os.path.join(self.root, "script.js"))

    def test_live_reload_events(self):
        got = []

        def listen():
            with OPENER.open(self.srv.origin + "/__aether__/events", timeout=10) as r:
                for raw in r:
                    line = raw.decode().strip()
                    got.append(line)
                    if line.startswith("data: {"):
                        return
        th = threading.Thread(target=listen, daemon=True)
        th.start()
        self.assertTrue(webdev.wait_for(lambda: self.srv.clients == 1))
        self.srv.reload_css("/style.css")
        self.srv.reload()
        self.srv.eval("1 + 1", "preview")
        th.join(5)
        self.assertIn("event: css", got)
        self.assertIn("data: /style.css", got)
        self.assertIn("event: reload", got)
        self.assertIn('data: {"code": "1 + 1", "target": "preview"}', got)

    def test_url_paths(self):
        self.assertEqual(self.srv.url_path(os.path.join(self.root, "docs", "a b.html")), "/docs/a%20b.html")
        self.assertIsNone(self.srv.url_path("/somewhere/else.html"))

    def test_stop_and_restart(self):
        self.srv.stop()
        self.assertFalse(self.srv.running)
        self.srv.start()
        self.assertEqual(get(self.srv.origin + "/style.css")[0], 200)


class Pages(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aether-pages-")
        for rel in ("about.html", "index.html", "blog/post.html", "node_modules/x/index.html"):
            p = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_find_pages(self):
        rel = [os.path.relpath(p, self.root) for p in webdev.find_pages(self.root)]
        self.assertEqual(rel, ["index.html", "about.html", os.path.join("blog", "post.html")])
        self.assertEqual(webdev.entry_page(self.root), os.path.join(self.root, "index.html"))

    def test_detected_as_web_project(self):
        self.assertEqual(project.detect(self.root)[0], "Web")

    def test_linked_assets(self):
        page = os.path.join(self.root, "blog", "post.html")
        html = ('<link rel="stylesheet" href="../css/site.css?v=2"><link rel="icon" href="x.ico">'
                '<link rel="stylesheet" href="https://cdn.example.com/x.css"><script src="/js/app.js"></script>'
                '<script type="module" src="./post.js#x"></script><script>inline()</script>')
        a = webdev.linked_assets(html, page, self.root)
        self.assertEqual(a["css"], [os.path.join(self.root, "css", "site.css")])
        self.assertEqual(a["js"], [os.path.join(self.root, "js", "app.js"), os.path.join(self.root, "blog", "post.js")])
        self.assertEqual(a["external"], ["https://cdn.example.com/x.css"])

    def test_pages_linking(self):
        with open(os.path.join(self.root, "index.html"), "w") as f:
            f.write('<link rel="stylesheet" href="style.css">')
        self.assertEqual(webdev.pages_linking(os.path.join(self.root, "style.css"), self.root),
                         [os.path.join(self.root, "index.html")])

    def test_add_link(self):
        html = "<html>\n<head>\n  <title>x</title>\n</head>\n<body>\n  <p>x</p>\n</body>\n</html>\n"
        out = webdev.add_link(html, "css", "style.css")
        self.assertIn('  <title>x</title>\n  <link rel="stylesheet" href="style.css">\n</head>', out)
        out = webdev.add_link(out, "js", "script.js")
        self.assertIn('  <p>x</p>\n  <script src="script.js"></script>\n</body>', out)
        self.assertIn('<script src="a.js"></script>', webdev.add_link("<p>bare</p>", "js", "a.js"))

    def test_bundle(self):
        d = self.root
        with open(os.path.join(d, "s.css"), "w") as f:
            f.write("p{color:red}")
        with open(os.path.join(d, "a.js"), "w") as f:
            f.write("document.write('</script>')")
        html = '<link rel="stylesheet" href="s.css"><script type="module" src="a.js"></script><script src="gone.js"></script>'
        out, inlined, missing = webdev.bundle(html, os.path.join(d, "index.html"), d)
        self.assertIn("<style>\np{color:red}\n</style>", out)
        self.assertIn('<script type="module">', out)
        self.assertIn("<\\/script>", out)                                   # can't end the inline script early
        self.assertEqual(len(inlined), 2)
        self.assertEqual(missing, [os.path.join(d, "gone.js")])

    def test_inject(self):
        self.assertTrue(webdev.inject("<html><head></head></html>").startswith('<html><head><script src="/__aether__/bridge.js">'))
        self.assertTrue(webdev.inject("<p>x</p>").startswith('<script src="/__aether__/bridge.js">'))
        once = webdev.inject("<head></head>")
        self.assertEqual(webdev.inject(once), once)

    def test_web_template(self):
        files = project.TEMPLATES["web"][2]
        self.assertEqual(set(files), {"index.html", "style.css", "script.js"})
        a = webdev.linked_assets(files["index.html"], "/p/index.html")
        self.assertEqual(a["css"], ["/p/style.css"])
        self.assertEqual(a["js"], ["/p/script.js"])


class Emmet(unittest.TestCase):
    def ex(self, a):
        r = emmet.expand(a, "  ")
        return r and r[0]

    def test_basics(self):
        self.assertEqual(self.ex("div#app.dark.big"), '<div id="app" class="dark big"></div>')
        self.assertEqual(self.ex("ul>li.item$*3"), '<ul>\n  <li class="item1"></li>\n  <li class="item2"></li>\n  <li class="item3"></li>\n</ul>')
        self.assertEqual(self.ex("p{Hi}+a[href=#]{Go}"), '<p>Hi</p>\n<a href="#">Go</a>')
        self.assertEqual(self.ex(".card>h2+p"), '<div class="card">\n  <h2></h2>\n  <p></p>\n</div>')
        self.assertEqual(self.ex("ul>.x"), '<ul>\n  <li class="x"></li>\n</ul>')
        self.assertEqual(self.ex("(header>h1)+footer"), "<header>\n  <h1></h1>\n</header>\n<footer></footer>")
        self.assertEqual(self.ex("div>p^span"), "<div>\n  <p></p>\n</div>\n<span></span>")
        self.assertEqual(self.ex("li*2>{Item $$}"), "<li>Item 01</li>\n<li>Item 02</li>")
        self.assertEqual(self.ex("img"), '<img src="" alt="">')
        self.assertEqual(self.ex("input:email"), '<input type="email" name="">')
        self.assertTrue(self.ex("!").startswith("<!DOCTYPE html>"))
        self.assertEqual(len(self.ex("lorem7").split()), 7)

    def test_cursor(self):
        text, cur = emmet.expand("ul>li*2")
        self.assertEqual(text[:cur], "<ul>\n  <li>")
        text, cur = emmet.expand("a")
        self.assertEqual(text[:cur], '<a href="')

    def test_not_abbreviations(self):
        for a in ("hello", "foo bar", ">x", "ul>", "", "x+"):
            self.assertIsNone(emmet.expand(a), a)

    def test_extract(self):
        self.assertEqual(emmet.extract("  <div>ul>li*3"), "ul>li*3")
        self.assertEqual(emmet.extract("text p{Hello world}"), "p{Hello world}")
        self.assertEqual(emmet.extract('<div class="card'), "")
        self.assertEqual(emmet.extract("    .row>.col*2"), ".row>.col*2")


if __name__ == "__main__":
    unittest.main()
