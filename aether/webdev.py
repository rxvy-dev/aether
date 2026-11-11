"""Web development without GTK: the offline preview server, live reload, the console bridge,
finding a page's CSS / JS, and bundling a page into one file.

Everything runs on this machine — the server listens on 127.0.0.1 only and needs no internet.

    srv = PreviewServer("/path/to/site", on_console=print)
    srv.start()                       # http://127.0.0.1:5500/
    srv.set_overlay(path, text)       # serve unsaved editor text instead of the file on disk
    srv.reload() / srv.reload_css("/style.css") / srv.eval("1 + 1")
    srv.stop()

Every HTML page the server sends gets one extra <script> (the "bridge") that
  * forwards console.log / warn / error, uncaught errors and promise rejections to Aether,
  * reloads the page when a file changes (CSS is swapped in place, keeping the page state),
  * runs code typed into Aether's web console.
Files on disk are never changed by the server.
"""
import json, os, posixpath, queue, re, socket, threading, time
import http.server
import urllib.parse
from html.parser import HTMLParser

BRIDGE = "/__aether__/"
PAGE_EXT = (".html", ".htm", ".xhtml")
WEB_EXT = PAGE_EXT + (".css", ".js", ".mjs", ".cjs", ".json", ".svg", ".xml", ".txt", ".md", ".webmanifest")
IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", ".cache", ".idea", ".aether", "dist", "build"}
FIRST_PORT = 5500                         # the same default as VS Code's Live Server, so muscle memory works
DEVICES = [("Responsive", 0, 0), ("Laptop · 1366", 1366, 768), ("Desktop · 1920", 1920, 1080),
           ("Tablet · 768", 768, 1024), ("Phone · 390", 390, 844), ("Small phone · 360", 360, 640)]

MIME = {".html": "text/html", ".htm": "text/html", ".xhtml": "application/xhtml+xml", ".css": "text/css",
        ".js": "text/javascript", ".mjs": "text/javascript", ".cjs": "text/javascript", ".json": "application/json",
        ".map": "application/json", ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
        ".avif": "image/avif", ".ico": "image/x-icon", ".bmp": "image/bmp", ".wasm": "application/wasm",
        ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
        ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav", ".mp4": "video/mp4", ".webm": "video/webm",
        ".txt": "text/plain", ".md": "text/markdown", ".xml": "application/xml", ".csv": "text/csv", ".pdf": "application/pdf"}

BRIDGE_JS = r"""/* Aether live preview bridge — injected by the editor's local server, never written to your files. */
(function () {
  if (window.__aether) return;
  var A = window.__aether = {};
  var from = /AetherPreview/.test(navigator.userAgent) ? "preview" : "browser";
  var base = "/__aether__/";
  var q = [], busy = false, timer = 0;

  function ser(v, d) {
    try {
      if (v === undefined) return "undefined";
      if (v === null) return "null";
      var t = typeof v;
      if (t === "string") return d ? JSON.stringify(v) : v;
      if (t === "number" || t === "boolean" || t === "bigint" || t === "symbol") return String(v);
      if (t === "function") return "ƒ " + (v.name || "anonymous") + "()";
      if (v instanceof Error) return (v.name || "Error") + ": " + v.message + (v.stack ? "\n" + v.stack : "");
      if (typeof Element !== "undefined" && v instanceof Element) {
        var h = v.outerHTML || ""; return h.length > 300 ? h.slice(0, 300) + "…" : h;
      }
      if (d > 2) return Array.isArray(v) ? "[…]" : "{…}";
      if (Array.isArray(v))
        return "[" + v.slice(0, 100).map(function (x) { return ser(x, d + 1); }).join(", ") + (v.length > 100 ? ", …" : "") + "]";
      if (typeof Map !== "undefined" && v instanceof Map) {
        var m = []; v.forEach(function (val, k) { if (m.length < 50) m.push(ser(k, d + 1) + " => " + ser(val, d + 1)); });
        return "Map(" + v.size + ") {" + m.join(", ") + "}";
      }
      if (typeof Set !== "undefined" && v instanceof Set) {
        var s = []; v.forEach(function (val) { if (s.length < 50) s.push(ser(val, d + 1)); });
        return "Set(" + v.size + ") {" + s.join(", ") + "}";
      }
      var keys = Object.keys(v).slice(0, 50);
      var name = v.constructor && v.constructor.name && v.constructor.name !== "Object" ? v.constructor.name + " " : "";
      return name + "{" + keys.map(function (k) { return k + ": " + ser(v[k], d + 1); }).join(", ") + "}";
    } catch (e) { try { return String(v); } catch (e2) { return "?"; } }
  }

  function where() {
    var st = "";
    try { throw new Error(); } catch (e) { st = e.stack || ""; }
    var lines = st.split("\n");
    for (var i = 0; i < lines.length; i++) {
      var m = /((?:https?|file):\/\/[^\s()]+?):(\d+):(\d+)/.exec(lines[i]);
      if (m && m[1].indexOf(base) < 0) return { url: m[1], line: +m[2], col: +m[3] };
    }
    return null;
  }

  function flush() {
    timer = 0;
    if (busy || !q.length) return;
    var batch = q.splice(0, q.length);
    busy = true;
    try {
      var x = new XMLHttpRequest();
      x.open("POST", base + "console", true);
      x.onloadend = function () { busy = false; if (q.length) flush(); };
      x.send(JSON.stringify(batch));
    } catch (e) { busy = false; }
  }

  function push(level, args, loc, quote) {
    var parts = [];
    for (var i = 0; i < args.length; i++) parts.push(ser(args[i], quote ? 1 : 0));
    q.push({ level: level, text: parts.join(" ").slice(0, 8000), url: loc && loc.url, line: loc && loc.line,
             col: loc && loc.col, from: from });
    if (q.length > 500) q.splice(0, q.length - 500);
    if (!timer) timer = setTimeout(flush, 25);
  }
  A.push = push;

  var levels = { log: "log", info: "info", warn: "warn", error: "error", debug: "debug", table: "log", dir: "log" };
  Object.keys(levels).forEach(function (m) {
    var orig = console[m] ? console[m].bind(console) : function () {};
    console[m] = function () { orig.apply(null, arguments); push(levels[m], arguments, where()); };
  });
  var oAssert = console.assert ? console.assert.bind(console) : function () {};
  console.assert = function (ok) {
    oAssert.apply(null, arguments);
    if (!ok) push("error", ["Assertion failed:"].concat([].slice.call(arguments, 1)), where());
  };
  var oClear = console.clear ? console.clear.bind(console) : function () {};
  console.clear = function () { oClear(); push("clear", [], null); };
  var oTrace = console.trace ? console.trace.bind(console) : function () {};
  console.trace = function () {
    oTrace.apply(null, arguments);
    var st = ""; try { throw new Error(); } catch (e) { st = e.stack || ""; }
    push("log", ["Trace:"].concat([].slice.call(arguments)).concat(["\n" + st.split("\n").slice(2).join("\n")]), where());
  };

  window.addEventListener("error", function (e) {
    var msg = e.message || "Error";
    if (e.error && e.error.stack && msg.indexOf(e.error.stack) < 0) msg += "\n" + e.error.stack;
    push("error", ["Uncaught " + msg.replace(/^Uncaught /, "")], { url: e.filename, line: e.lineno, col: e.colno });
  });
  window.addEventListener("unhandledrejection", function (e) {
    push("error", ["Uncaught (in promise)", e.reason], null);
  });
  window.addEventListener("pagehide", function () {
    if (q.length && navigator.sendBeacon) {
      try { navigator.sendBeacon(base + "console", new Blob([JSON.stringify(q.splice(0, q.length))], { type: "text/plain" })); }
      catch (e) {}
    }
  });

  function reloadKeepScroll() {
    try { sessionStorage.setItem("__aether_scroll", JSON.stringify([location.pathname, scrollX, scrollY])); } catch (e) {}
    location.reload();
  }
  try {
    var s = JSON.parse(sessionStorage.getItem("__aether_scroll") || "null");
    if (s && s[0] === location.pathname) {
      sessionStorage.removeItem("__aether_scroll");
      window.addEventListener("load", function () { window.scrollTo(s[1], s[2]); });
    }
  } catch (e) {}

  function swapCss(path) {
    var found = false, links = document.querySelectorAll('link[rel~="stylesheet"]');
    for (var i = 0; i < links.length; i++) {
      try {
        var u = new URL(links[i].getAttribute("href"), location.href);
        if (u.origin === location.origin && (path === "*" || decodeURIComponent(u.pathname) === path)) {
          u.searchParams.set("__aether", Date.now());
          links[i].href = u.href;
          found = true;
        }
      } catch (e) {}
    }
    if (!found) reloadKeepScroll();
  }

  if (window.EventSource) {
    var es = new EventSource(base + "events");
    es.addEventListener("reload", reloadKeepScroll);
    es.addEventListener("css", function (ev) { swapCss(ev.data); });
    es.addEventListener("eval", function (ev) {
      var d = JSON.parse(ev.data);
      if (d.target && d.target !== "*" && d.target !== from) return;
      try { push("result", [(0, eval)(d.code)], null, true); }
      catch (e) { push("error", ["Uncaught " + ser(e, 0)], null); }
    });
  }
  push("page", [location.pathname], null);
})();
"""

_TAG = '<script src="/__aether__/bridge.js"></script>'


# ------------------------------------------------------------------ pages and their CSS / JS
def is_page(path):
    return bool(path) and path.lower().endswith(PAGE_EXT)


def is_web_file(path):
    return bool(path) and path.lower().endswith(WEB_EXT)


def find_pages(root, limit=400):
    """HTML pages under root (absolute paths): index.html first, then shallow before deep, then by name."""
    out = []
    root = os.path.abspath(root)
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in IGNORE and not x.startswith("."))
        for f in files:
            if f.lower().endswith(PAGE_EXT):
                out.append(os.path.join(d, f))
                if len(out) >= limit:
                    break
        if len(out) >= limit:
            break

    def key(p):
        rel = os.path.relpath(p, root)
        return (rel.count(os.sep), os.path.basename(p).lower() not in ("index.html", "index.htm"), rel.lower())
    return sorted(out, key=key)


def entry_page(root):
    for name in ("index.html", "index.htm", "public/index.html", "src/index.html", "docs/index.html"):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            return p
    pages = find_pages(root, 50)
    return pages[0] if pages else None


def is_external(url):
    return bool(re.match(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)", url or ""))


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.css, self.js = [], []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "link" and "stylesheet" in a.get("rel", "").lower().split() and a.get("href"):
            self.css.append(a["href"])
        elif tag == "script" and a.get("src"):
            self.js.append(a["src"])


def resolve(href, page_path, root=None):
    """Local file an href / src points at (absolute path), or None for external URLs."""
    if not href or is_external(href) or href.startswith(("#", "data:")):
        return None
    href = urllib.parse.unquote(href.split("#", 1)[0].split("?", 1)[0])
    if not href:
        return None
    if href.startswith("/"):
        base = root or os.path.dirname(page_path)
        return os.path.normpath(os.path.join(base, href.lstrip("/")))
    return os.path.normpath(os.path.join(os.path.dirname(page_path), href))


def linked_assets(html_text, page_path, root=None):
    """-> {"css": [paths], "js": [paths], "external": [urls]} for the stylesheets / scripts a page loads."""
    p = _Links()
    try:
        p.feed(html_text or "")
        p.close()
    except Exception:            # malformed HTML: keep what we got
        pass
    out = {"css": [], "js": [], "external": []}
    for kind, hrefs in (("css", p.css), ("js", p.js)):
        for h in hrefs:
            r = resolve(h, page_path, root)
            if r is None:
                if is_external(h):
                    out["external"].append(h)
            elif r not in out[kind]:
                out[kind].append(r)
    return out


def pages_linking(path, root, read=None):
    """HTML pages under root that load `path` (a CSS or JS file)."""
    path = os.path.normpath(path)
    hits = []
    for page in find_pages(root, 200):
        try:
            text = read(page) if read else None
            if text is None:
                with open(page, errors="replace") as f:
                    text = f.read()
        except OSError:
            continue
        a = linked_assets(text, page, root)
        if path in a["css"] or path in a["js"]:
            hits.append(page)
    return hits


def _indent_before(text, idx):
    line_start = text.rfind("\n", 0, idx) + 1
    return re.match(r"[ \t]*", text[line_start:idx]).group(0)


def add_link(html_text, kind, href):
    """Return html_text with a <link rel=stylesheet> (kind "css") or <script src> (kind "js") added in the usual place."""
    tag = f'<link rel="stylesheet" href="{href}">' if kind == "css" else f'<script src="{href}"></script>'
    close = re.search(r"</head\s*>", html_text, re.I) if kind == "css" else None
    if kind == "js":
        closes = list(re.finditer(r"</body\s*>", html_text, re.I))
        close = closes[-1] if closes else None
    if close:
        inner = _indent_before(html_text, close.start()) + "  "
        line_start = html_text.rfind("\n", 0, close.start()) + 1
        if html_text[line_start:close.start()].strip():          # </head> shares a line with other markup
            return html_text[:close.start()] + tag + html_text[close.start():]
        return html_text[:line_start] + inner + tag + "\n" + html_text[line_start:]
    if kind == "css":
        m = re.search(r"<head\b[^>]*>", html_text, re.I)
        if m:
            return html_text[:m.end()] + "\n  " + tag + html_text[m.end():]
    sep = "" if html_text.endswith("\n") or not html_text else "\n"
    return html_text + sep + tag + "\n"


# ------------------------------------------------------------------ single-file export
_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_SCRIPT_RE = re.compile(r"<script\b([^>]*)>\s*</script\s*>", re.I)


def _attrs(tag_text):
    p = _Links()
    a = {}

    def grab(tag, attrs):
        a.update({k.lower(): (v or "") for k, v in attrs})
    p.handle_starttag = grab
    try:
        p.feed(tag_text)
    except Exception:
        pass
    return a


def bundle(html_text, page_path, root=None, read=None):
    """Inline the page's local stylesheets and scripts. -> (single_file_html, [inlined paths], [missing paths])."""
    inlined, missing = [], []

    def load(path):
        if read:
            t = read(path)
            if t is not None:
                return t
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def link(m):
        a = _attrs(m.group(0))
        if "stylesheet" not in a.get("rel", "").lower().split():
            return m.group(0)
        path = resolve(a.get("href", ""), page_path, root)
        if not path:
            return m.group(0)
        try:
            css = load(path)
        except OSError:
            missing.append(path)
            return m.group(0)
        inlined.append(path)
        media = f' media="{a["media"]}"' if a.get("media") else ""
        return f"<style{media}>\n{css.rstrip()}\n</style>"

    def script(m):
        a = _attrs("<script" + m.group(1) + ">")
        path = resolve(a.get("src", ""), page_path, root)
        if not path:
            return m.group(0)
        try:
            js = load(path)
        except OSError:
            missing.append(path)
            return m.group(0)
        inlined.append(path)
        keep = "".join(f' {k}="{v}"' if v else f" {k}" for k, v in a.items() if k in ("type", "defer", "async", "nomodule"))
        js = re.sub(r"</(script)", r"<\\/\1", js, flags=re.I)
        return f"<script{keep}>\n{js.rstrip()}\n</script>"

    out = _LINK_RE.sub(link, html_text)
    out = _SCRIPT_RE.sub(script, out)
    return out, inlined, missing


# ------------------------------------------------------------------ injection
def inject(html_text):
    """Add the bridge <script> as early as possible, so it sees every console call."""
    if BRIDGE + "bridge.js" in html_text:
        return html_text
    for pat in (r"<head\b[^>]*>", r"<html\b[^>]*>", r"<!doctype[^>]*>"):
        m = re.search(pat, html_text, re.I)
        if m:
            return html_text[:m.end()] + _TAG + html_text[m.end():]
    return _TAG + html_text


def _page(title, body):
    return ("<!doctype html><html><head><meta charset=utf-8><title>" + title + "</title><style>"
            "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0d0d10;color:#e8e8ea;"
            "font:15px/1.6 system-ui,sans-serif}main{max-width:640px;padding:32px}h1{color:#e53935;font-weight:600}"
            "a{color:#ff6b6b}code{background:#1c1c22;padding:2px 6px;border-radius:4px}ul{padding-left:20px}"
            "</style></head><body><main>" + body + "</main></body></html>")


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ------------------------------------------------------------------ server
class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class PreviewServer:
    """Serves one folder on 127.0.0.1 with live reload. Thread-safe; callbacks run on the server's threads."""

    def __init__(self, root, on_console=None, port=FIRST_PORT):
        self.root = os.path.abspath(root)
        self.on_console = on_console
        self.want_port = port
        self.port = 0
        self._httpd = None
        self._thread = None
        self._lock = threading.Lock()
        self._overlay = {}
        self._clients = []
        self._stopping = False

    # ---------- lifecycle
    @property
    def running(self):
        return self._httpd is not None

    def start(self):
        if self._httpd:
            return self.port
        handler = _make_handler(self)
        httpd = None
        for port in list(range(self.want_port, self.want_port + 40)) + [0] if self.want_port else [0]:
            try:
                httpd = _Server(("127.0.0.1", port), handler)
                break
            except OSError:
                continue
        if httpd is None:
            raise OSError("no free port on 127.0.0.1")
        self._stopping = False
        self._httpd = httpd
        self.port = httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="aether-web", daemon=True)
        self._thread.start()
        return self.port

    def stop(self):
        httpd, self._httpd = self._httpd, None
        if not httpd:
            return
        self._stopping = True
        with self._lock:
            for c in self._clients:
                c.put(None)
        httpd.shutdown()
        httpd.server_close()
        self.port = 0

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"

    def set_root(self, root):
        root = os.path.abspath(root)
        if root != self.root:
            self.root = root
            self.reload()

    # ---------- urls
    def url_path(self, path):
        """'/sub/page.html' for a file under the root, or None."""
        path = os.path.abspath(path)
        if path != self.root and not path.startswith(self.root.rstrip(os.sep) + os.sep):
            return None
        rel = os.path.relpath(path, self.root).replace(os.sep, "/")
        return "/" if rel == "." else "/" + urllib.parse.quote(rel)

    def url_for(self, path=None):
        up = self.url_path(path) if path else "/"
        return self.origin + (up or "/")

    def path_for_url(self, url):
        """Local file for a URL served by us (for clickable console locations)."""
        if not url:
            return None
        u = urllib.parse.urlparse(url)
        if u.scheme == "file":
            return urllib.parse.unquote(u.path)
        if u.netloc and u.netloc not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return None
        return self._fs_path(u.path)

    def _fs_path(self, url_path):
        rel = posixpath.normpath(urllib.parse.unquote(url_path or "/")).lstrip("/")
        if rel in (".", ""):
            return self.root
        full = os.path.normpath(os.path.join(self.root, *rel.split("/")))
        if full != self.root and not full.startswith(self.root.rstrip(os.sep) + os.sep):
            return None                             # ../ outside the served folder
        return full

    # ---------- unsaved editor text
    def set_overlay(self, path, text):
        with self._lock:
            self._overlay[os.path.abspath(path)] = text

    def clear_overlay(self, path=None):
        with self._lock:
            if path is None:
                self._overlay.clear()
            else:
                self._overlay.pop(os.path.abspath(path), None)

    def overlay(self, path):
        with self._lock:
            return self._overlay.get(os.path.abspath(path))

    # ---------- pushing to pages
    def _broadcast(self, event, data=""):
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            c.put((event, data))
        return len(clients)

    def reload(self):
        return self._broadcast("reload", "1")

    def reload_css(self, url_path="*"):
        return self._broadcast("css", url_path or "*")

    def eval(self, code, target="*"):
        return self._broadcast("eval", json.dumps({"code": code, "target": target}))

    @property
    def clients(self):
        with self._lock:
            return len(self._clients)

    def _console(self, msg):
        if self.on_console:
            try:
                self.on_console(msg)
            except Exception:
                pass


def _make_handler(srv):
    class H(http.server.BaseHTTPRequestHandler):
        server_version = "AetherPreview"
        sys_version = ""

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype, extra=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == BRIDGE + "bridge.js":
                return self._send(200, BRIDGE_JS, "text/javascript; charset=utf-8")
            if path == BRIDGE + "events":
                return self._events()
            if path == BRIDGE + "ping":
                return self._send(200, json.dumps({"root": srv.root, "clients": srv.clients}), "application/json")
            fs = srv._fs_path(path)
            if fs is None:
                return self._send(403, "Forbidden", "text/plain")
            if os.path.isdir(fs):
                if not path.endswith("/"):
                    return self._send(301, "", "text/plain", {"Location": path + "/"})
                for idx in ("index.html", "index.htm"):
                    if os.path.isfile(os.path.join(fs, idx)) or srv.overlay(os.path.join(fs, idx)) is not None:
                        fs = os.path.join(fs, idx)
                        break
                else:
                    return self._listing(fs, path)
            text = srv.overlay(fs)
            ext = os.path.splitext(fs)[1].lower()
            ctype = MIME.get(ext, "application/octet-stream")
            if ctype.startswith("text/") or ctype in ("application/json", "application/xml", "image/svg+xml",
                                                       "application/manifest+json", "application/xhtml+xml"):
                ctype += "; charset=utf-8"
            if text is not None:
                body = text.encode("utf-8")
            else:
                try:
                    with open(fs, "rb") as f:
                        body = f.read()
                except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
                    if not path.endswith("favicon.ico"):
                        srv._console({"level": "warn", "text": f"404 Not Found: {urllib.parse.unquote(path)}", "from": "server",
                                      "url": "", "line": 0})
                    return self._send(404, inject(_page("Not found", f"<h1>404</h1><p><code>{_esc(urllib.parse.unquote(path))}</code> "
                                                                   "doesn't exist (yet). Create it and this page reloads.</p>")),
                                      "text/html; charset=utf-8")
                except OSError as e:
                    return self._send(500, str(e), "text/plain")
            if ext in PAGE_EXT:
                body = inject(body.decode("utf-8", errors="replace")).encode("utf-8")
            self._send(200, body, ctype)

        def _listing(self, fs, url_path):
            items = []
            try:
                names = sorted(os.listdir(fs), key=str.lower)
            except OSError:
                names = []
            for n in names:
                if n.startswith(".") or n in IGNORE:
                    continue
                full = os.path.join(fs, n)
                if os.path.isdir(full):
                    items.append(f'<li><a href="{urllib.parse.quote(n)}/">{_esc(n)}/</a></li>')
                elif n.lower().endswith(PAGE_EXT):
                    items.append(f'<li><a href="{urllib.parse.quote(n)}">{_esc(n)}</a></li>')
            body = (f"<h1>{_esc(urllib.parse.unquote(url_path))}</h1><p>No <code>index.html</code> here. Pages:</p>"
                    + ("<ul>" + "".join(items) + "</ul>" if items else "<p>none yet</p>"))
            self._send(200, inject(_page("Index", body)), "text/html; charset=utf-8")

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = queue.Queue()
            with srv._lock:
                srv._clients.append(q)
            try:
                self.wfile.write(b"retry: 700\n\n")
                self.wfile.flush()
                while not srv._stopping:
                    try:
                        item = q.get(timeout=10)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    if item is None:
                        break
                    ev, data = item
                    payload = "".join(f"data: {line}\n" for line in str(data).split("\n"))
                    self.wfile.write(f"event: {ev}\n{payload}\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
                pass
            finally:
                with srv._lock:
                    if q in srv._clients:
                        srv._clients.remove(q)

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path != BRIDGE + "console":
                return self._send(404, "", "text/plain")
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 4 << 20)
                data = json.loads(self.rfile.read(n).decode("utf-8", errors="replace") or "[]")
            except (ValueError, OSError):
                return self._send(400, "", "text/plain")
            for msg in data if isinstance(data, list) else [data]:
                if isinstance(msg, dict):
                    srv._console({"level": str(msg.get("level") or "log"), "text": str(msg.get("text") or ""),
                                  "url": str(msg.get("url") or ""), "line": int(msg.get("line") or 0),
                                  "col": int(msg.get("col") or 0), "from": str(msg.get("from") or "browser")})
            self._send(204, b"", "text/plain")

        def do_OPTIONS(self):
            self._send(204, b"", "text/plain", {"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                                                 "Access-Control-Allow-Headers": "Content-Type"})
    return H


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()
