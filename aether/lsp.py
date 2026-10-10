"""A small Language Server Protocol client (JSON-RPC over stdio). Dispatches everything onto the GTK main loop."""
import json, os, shutil, subprocess, threading
from urllib.parse import quote, unquote, urlparse
from gi.repository import GLib

DEFAULT_SERVERS = {
    "python": ["pyright-langserver", "--stdio"],
    "c": ["clangd", "--background-index"], "cpp": ["clangd", "--background-index"],
    "rust": ["rust-analyzer"], "go": ["gopls"],
    "javascript": ["typescript-language-server", "--stdio"], "typescript": ["typescript-language-server", "--stdio"],
    "javascriptreact": ["typescript-language-server", "--stdio"], "typescriptreact": ["typescript-language-server", "--stdio"],
    "shellscript": ["bash-language-server", "start"], "lua": ["lua-language-server"], "zig": ["zls"],
    "html": ["vscode-html-language-server", "--stdio"], "css": ["vscode-css-language-server", "--stdio"],
    "json": ["vscode-json-language-server", "--stdio"], "yaml": ["yaml-language-server", "--stdio"],
    "java": ["jdtls"], "php": ["intelephense", "--stdio"], "ruby": ["solargraph", "stdio"],
    "kotlin": ["kotlin-language-server"], "csharp": ["csharp-ls"], "markdown": ["marksman", "server"],
    "haskell": ["haskell-language-server-wrapper", "--lsp"], "elixir": ["elixir-ls"],
}
HINTS = {
    "pyright-langserver": "pip install pyright  (or: npm i -g pyright)", "clangd": "pacman -S clangd / apt install clangd",
    "rust-analyzer": "rustup component add rust-analyzer", "gopls": "go install golang.org/x/tools/gopls@latest",
    "typescript-language-server": "npm i -g typescript typescript-language-server",
    "bash-language-server": "npm i -g bash-language-server", "lua-language-server": "pacman -S lua-language-server",
    "zls": "install zls", "yaml-language-server": "npm i -g yaml-language-server",
    "vscode-html-language-server": "npm i -g vscode-langservers-extracted",
    "vscode-css-language-server": "npm i -g vscode-langservers-extracted",
    "vscode-json-language-server": "npm i -g vscode-langservers-extracted",
}
LANG_ID = {"c": "c", "cpp": "cpp", "python": "python", "javascript": "javascript", "typescript": "typescript",
           "javascriptreact": "javascriptreact", "typescriptreact": "typescriptreact", "rust": "rust", "go": "go",
           "shellscript": "shellscript", "lua": "lua", "zig": "zig", "html": "html", "css": "css", "json": "json",
           "yaml": "yaml", "java": "java", "php": "php", "ruby": "ruby", "kotlin": "kotlin", "csharp": "csharp",
           "markdown": "markdown", "haskell": "haskell", "elixir": "elixir"}


def path_to_uri(path):
    return "file://" + quote(os.path.abspath(path))


def uri_to_path(uri):
    u = urlparse(uri)
    return unquote(u.path) if u.scheme == "file" else uri


def server_argv(key, overrides):
    v = (overrides or {}).get(key)
    if isinstance(v, str) and v.strip():
        import shlex
        return shlex.split(v)
    if isinstance(v, list) and v:
        return v
    return DEFAULT_SERVERS.get(key)


class LspClient:
    def __init__(self, name, argv, root, on_diag, on_exit):
        self.name = name
        self.argv = argv
        self.root = root
        self.on_diag, self.on_exit = on_diag, on_exit
        self._id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self.ready = False
        self.dead = False
        self._queue = []
        self.versions = {}
        self.caps = {}
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     cwd=root if os.path.isdir(root) else None, bufsize=0)
        threading.Thread(target=self._reader, daemon=True).start()
        uri = path_to_uri(root)
        self.request("initialize", {
            "processId": os.getpid(), "rootUri": uri, "rootPath": root,
            "workspaceFolders": [{"uri": uri, "name": os.path.basename(root) or "root"}],
            "clientInfo": {"name": "Aether"},
            "capabilities": {
                "workspace": {"configuration": True, "workspaceFolders": True, "applyEdit": True},
                "textDocument": {
                    "synchronization": {"didSave": True},
                    "publishDiagnostics": {"relatedInformation": False},
                    "completion": {"completionItem": {"snippetSupport": False, "documentationFormat": ["plaintext"]}},
                    "hover": {"contentFormat": ["plaintext", "markdown"]},
                    "definition": {"linkSupport": True}, "references": {}, "rename": {"prepareSupport": False},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                },
            }}, self._initialized)

    # ---- transport ----
    def _write(self, obj):
        if self.dead:
            return
        body = json.dumps(obj).encode()
        try:
            with self._lock:
                self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
                self.proc.stdin.flush()
        except (OSError, ValueError):
            self._died()

    def _reader(self):
        out = self.proc.stdout
        try:
            while True:
                length = None
                while True:
                    line = out.readline()
                    if not line:
                        raise EOFError
                    line = line.strip()
                    if not line:
                        break
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":")[1])
                if length is None:
                    continue
                buf = b""
                while len(buf) < length:
                    chunk = out.read(length - len(buf))
                    if not chunk:
                        raise EOFError
                    buf += chunk
                GLib.idle_add(self._dispatch, json.loads(buf.decode("utf-8", errors="replace")))
        except (EOFError, OSError, ValueError):
            GLib.idle_add(self._died)

    def _died(self):
        if not self.dead:
            self.dead = True
            self.ready = False
            self.on_exit(self)
        return False

    def request(self, method, params, cb=None):
        self._id += 1
        if cb:
            self._pending[self._id] = cb
        self._write({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})

    def notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _respond(self, mid, result):
        self._write({"jsonrpc": "2.0", "id": mid, "result": result})

    def _dispatch(self, msg):
        try:
            if "method" in msg and "id" in msg:                       # request from server
                m = msg["method"]
                if m == "workspace/configuration":
                    self._respond(msg["id"], [{} for _ in msg.get("params", {}).get("items", [])])
                else:
                    self._respond(msg["id"], None)
            elif "method" in msg:                                      # notification
                if msg["method"] == "textDocument/publishDiagnostics":
                    p = msg["params"]
                    self.on_diag(p["uri"], p.get("diagnostics", []))
            elif "id" in msg:                                          # response
                cb = self._pending.pop(msg["id"], None)
                if cb:
                    cb(msg.get("result"), msg.get("error"))
        except Exception as e:                                         # never let a server crash the UI loop
            print("lsp dispatch error:", e)
        return False

    def _initialized(self, result, err):
        if err or result is None:
            return
        self.caps = result.get("capabilities", {})
        self.notify("initialized", {})
        self.ready = True
        for fn in self._queue:
            fn()
        self._queue = []

    def when_ready(self, fn):
        if self.ready:
            fn()
        else:
            self._queue.append(fn)

    # ---- documents ----
    def did_open(self, path, lang_id, text):
        uri = path_to_uri(path)
        self.versions[uri] = 1
        self.when_ready(lambda: self.notify("textDocument/didOpen", {
            "textDocument": {"uri": uri, "languageId": lang_id, "version": 1, "text": text}}))

    def did_change(self, path, text):
        uri = path_to_uri(path)
        if uri not in self.versions:
            return
        self.versions[uri] += 1
        v = self.versions[uri]
        self.when_ready(lambda: self.notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": v}, "contentChanges": [{"text": text}]}))

    def did_save(self, path, text):
        uri = path_to_uri(path)
        self.when_ready(lambda: self.notify("textDocument/didSave", {"textDocument": {"uri": uri}, "text": text}))

    def did_close(self, path):
        uri = path_to_uri(path)
        self.versions.pop(uri, None)
        self.when_ready(lambda: self.notify("textDocument/didClose", {"textDocument": {"uri": uri}}))

    def shutdown(self):
        if self.dead:
            return
        try:
            self.request("shutdown", None, lambda *_: (self.notify("exit", None)))
            GLib.timeout_add(1500, lambda: (self.proc.poll() is None and self.proc.kill(), False)[1])
        except Exception:
            pass
