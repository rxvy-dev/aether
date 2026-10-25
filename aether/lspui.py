"""Window-side glue for language servers: diagnostics, go to definition, hover, completion, references, rename."""
import os, re
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib

from . import lsp
from .palette import Palette


def _locs(res):
    """Normalise Location | Location[] | LocationLink[] -> [(path, line0, col0)]"""
    if not res:
        return []
    if isinstance(res, dict):
        res = [res]
    out = []
    for r in res:
        uri = r.get("uri") or r.get("targetUri")
        rng = r.get("range") or r.get("targetSelectionRange") or r.get("targetRange")
        if uri and rng:
            out.append((lsp.uri_to_path(uri), rng["start"]["line"], rng["start"]["character"]))
    return out


def _hover_text(c):
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        return c.get("value", "")
    if isinstance(c, list):
        return "\n\n".join(_hover_text(x) for x in c)
    return ""


def _apply_text_edits(text, edits):
    lines = text.split("\n")
    starts, off = [], 0
    for l in lines:
        starts.append(off)
        off += len(l) + 1
    def pos(p):
        ln = min(p["line"], len(lines) - 1)
        return starts[ln] + min(p["character"], len(lines[ln]))
    for e in sorted(edits, key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]), reverse=True):
        a, z = pos(e["range"]["start"]), pos(e["range"]["end"])
        text = text[:a] + e["newText"] + text[z:]
    return text


class LspMixin:
    # ---------------- lifecycle ----------------
    def _lsp_state(self):
        d = self.__dict__
        d.setdefault("_lsp_failed", set())
        d.setdefault("_lsp_warned", set())
        d.setdefault("_lsp_timers", {})

    def lsp_for_tab(self, tab):
        self._lsp_state()
        key = tab.tkey
        if not key or not tab.path or not self.settings["lsp"]:
            return None
        if tab.path.lower().endswith((".ino", ".pde")):
            return None                   # clangd can't resolve Arduino.h for sketches (use PlatformIO + C++ for completion)
        argv = lsp.server_argv(key, self.settings["lsp_servers"])
        if not argv:
            return None
        root = self.folder or os.path.dirname(tab.path)
        ck = (" ".join(argv), root)
        c = self.lsp.get(ck)
        if c and not c.dead:
            return c
        if ck in self._lsp_failed:
            return None
        import shutil
        if shutil.which(argv[0]) is None:
            if key not in self._lsp_warned:
                self._lsp_warned.add(key)
                self.flash(f"Optional: install {argv[0]} for completions, hover and go-to-definition ({lsp.HINTS.get(argv[0], 'see your package manager')})", 9000)
            return None
        try:
            c = lsp.LspClient(argv[0], argv, root, self._lsp_diag, self._lsp_exit)
        except OSError:
            self._lsp_failed.add(ck)
            return None
        self.lsp[ck] = c
        return c

    def lsp_opened(self, tab):
        c = self.lsp_for_tab(tab)
        tab.lsp = c
        tab.lsp_diag_active = False
        if c:
            c.did_open(tab.path, lsp.LANG_ID.get(tab.tkey, tab.tkey), tab.get_text())
            c.when_ready(lambda: self._on_tab_state(self.cur()))
        self._on_tab_state(self.cur())

    def lsp_changed(self, tab):
        c = getattr(tab, "lsp", None)
        if not c or not tab.path:
            return
        self._lsp_state()
        old = self._lsp_timers.pop(id(tab), 0)
        if old:
            GLib.source_remove(old)
        self._lsp_timers[id(tab)] = GLib.timeout_add(250, lambda: (self._lsp_timers.pop(id(tab), None),
                                                                   c.did_change(tab.path, tab.get_text()), False)[2])

    def lsp_saved(self, tab):
        c = getattr(tab, "lsp", None)
        if c and tab.path:
            c.did_save(tab.path, tab.get_text())
        if tab.path and not c and self.settings["lsp"]:
            self.lsp_opened(tab)        # first save of an untitled file

    def lsp_close(self, tab):
        c = getattr(tab, "lsp", None)
        if c and tab.path:
            c.did_close(tab.path)
        tab.lsp = None

    def lsp_shutdown_all(self):
        for c in list(self.lsp.values()):
            c.shutdown()

    def lsp_status(self, tab):
        c = getattr(tab, "lsp", None) if tab else None
        if not c or c.dead:
            return ""
        return f"● {c.name}" if c.ready else f"◌ {c.name} starting"

    def _lsp_diag(self, uri, diags):
        path = lsp.uri_to_path(uri)
        out = []
        for d in diags:
            sev = d.get("severity", 1)
            if sev >= 4:
                continue
            r = d["range"]
            msg = d.get("message", "").strip().splitlines()[0] if d.get("message") else ""
            code = d.get("code")
            if code and not isinstance(code, dict):
                msg += f"  [{code}]"
            out.append({"line": r["start"]["line"] + 1, "col": r["start"]["character"] + 1,
                        "end_line": r["end"]["line"] + 1, "end_col": r["end"]["character"] + 1,
                        "sev": "error" if sev == 1 else "warning", "msg": msg})
        for t in self.tabs():
            if t.path == path:
                t.set_lsp_diags(out)

    def _lsp_exit(self, client):
        for k, v in list(self.lsp.items()):
            if v is client:
                del self.lsp[k]
        for t in self.tabs():
            if getattr(t, "lsp", None) is client:
                t.lsp = None
                t.lsp_diag_active = False
                t.schedule_lint(100)
        self.flash(f"{client.name} stopped", 3000)
        self._on_tab_state(self.cur())

    # ---------------- requests ----------------
    def _lsp_ctx(self):
        t = self.cur()
        c = getattr(t, "lsp", None) if t else None
        if not c or c.dead or not c.ready:
            self.flash("No language server running for this file (see Preferences → Language servers)")
            return None, None
        return t, c

    def _lsp_pos(self, t):
        line, col = t.position()
        return {"line": line - 1, "character": col - 1}

    def _doc(self, t):
        return {"uri": lsp.path_to_uri(t.path)}

    def lsp_definition(self):
        t, c = self._lsp_ctx()
        if not c:
            return
        def cb(res, err):
            locs = _locs(res)
            if not locs:
                self.flash("No definition found", 2000)
            elif len(locs) == 1:
                self.open_path(locs[0][0], locs[0][1] + 1, locs[0][2] + 1)
            else:
                items = [(f"{os.path.relpath(p, self.folder) if self.folder and p.startswith(self.folder) else p}", f":{l + 1}",
                          (lambda p=p, l=l, ch=ch: self.open_path(p, l + 1, ch + 1))) for p, l, ch in locs]
                Palette(self, "Definitions…", items).present()
        c.request("textDocument/definition", {"textDocument": self._doc(t), "position": self._lsp_pos(t)}, cb)

    def lsp_references(self):
        t, c = self._lsp_ctx()
        if not c:
            return
        def cb(res, err):
            locs = _locs(res)
            if not locs:
                self.flash("No references found", 2000)
                return
            def line_text(p, l):
                for tb in self.tabs():
                    if tb.path == p:
                        ok, it = tb.buffer.get_iter_at_line(l)
                        e = it.copy()
                        if not e.ends_line():
                            e.forward_to_line_end()
                        return tb.buffer.get_text(it, e, False).strip()
                try:
                    with open(p, encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f):
                            if i == l:
                                return line.strip()
                except OSError:
                    pass
                return ""
            items = []
            for p, l, ch in locs[:300]:
                rel = os.path.relpath(p, self.folder) if self.folder and p.startswith(self.folder) else p
                items.append((f"{rel}:{l + 1}  {line_text(p, l)[:90]}", "", (lambda p=p, l=l, ch=ch: self.open_path(p, l + 1, ch + 1))))
            Palette(self, f"{len(locs)} references…", items).present()
        c.request("textDocument/references", {"textDocument": self._doc(t), "position": self._lsp_pos(t),
                                              "context": {"includeDeclaration": True}}, cb)

    def lsp_hover(self):
        t, c = self._lsp_ctx()
        if not c:
            return
        def cb(res, err):
            txt = _hover_text((res or {}).get("contents")) if res else ""
            txt = re.sub(r"```\w*\n?", "", txt).strip()
            if not txt:
                self.flash("No documentation here", 1500)
                return
            self._show_popover(t, txt[:3000])
        c.request("textDocument/hover", {"textDocument": self._doc(t), "position": self._lsp_pos(t)}, cb)

    def _show_popover(self, t, text):
        v = t.active_view
        it = t.buffer.get_iter_at_mark(t.buffer.get_insert())
        r = v.get_iter_location(it)
        x, y = v.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, r.x, r.y + r.height)
        pop = Gtk.Popover()
        pop.set_parent(v)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = x, y, 1, 1
        pop.set_pointing_to(rect)
        sw = Gtk.ScrolledWindow()
        sw.set_max_content_height(320)
        sw.set_propagate_natural_height(True)
        sw.set_max_content_width(620)
        sw.set_propagate_natural_width(True)
        lab = Gtk.Label(label=text, xalign=0, selectable=True, wrap=True, max_width_chars=80)
        lab.set_margin_start(10); lab.set_margin_end(10); lab.set_margin_top(8); lab.set_margin_bottom(8)
        lab.add_css_class("aether-hover")
        sw.set_child(lab)
        pop.set_child(sw)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def lsp_complete(self):
        t, c = self._lsp_ctx()
        if not c:
            return
        b = t.buffer
        end = b.get_iter_at_mark(b.get_insert())
        start = end.copy()
        while start.backward_char():
            ch = start.get_char()
            if not (ch.isalnum() or ch == "_"):
                start.forward_char()
                break
        prefix = b.get_text(start, end, False)
        def cb(res, err):
            items = res.get("items", []) if isinstance(res, dict) else (res or [])
            if not items:
                self.flash("No completions", 1500)
                return
            items = sorted(items, key=lambda i: i.get("sortText") or i.get("label", ""))[:300]
            KIND = {2: "method", 3: "function", 4: "constructor", 5: "field", 6: "variable", 7: "class", 8: "interface",
                    9: "module", 10: "property", 14: "keyword", 15: "snippet", 21: "constant", 22: "struct", 23: "event"}
            pal_items = []
            for it in items:
                label = it.get("label", "").strip()
                detail = it.get("detail") or KIND.get(it.get("kind"), "")
                pal_items.append((label, (detail or "")[:48], (lambda it=it: self._insert_completion(t, it, start))))
            Palette(self, "Completions…", pal_items, initial=prefix).present()
        c.request("textDocument/completion", {"textDocument": self._doc(t), "position": self._lsp_pos(t),
                                              "context": {"triggerKind": 1}}, cb)

    def _insert_completion(self, t, item, start):
        b = t.buffer
        end = b.get_iter_at_mark(b.get_insert())
        te = item.get("textEdit")
        text = item.get("insertText") or item.get("label", "")
        b.begin_user_action()
        if te and "range" in te:
            r = te["range"]
            ok, s = b.get_iter_at_line(r["start"]["line"])
            s.forward_chars(r["start"]["character"])
            ok, e = b.get_iter_at_line(r["end"]["line"])
            e.forward_chars(r["end"]["character"])
            b.delete(s, e)
            b.insert(s, te["newText"])
            b.place_cursor(s)
        else:
            s = b.get_iter_at_mark(b.get_insert())
            s = start.copy() if start.compare(end) <= 0 else s
            b.delete(s, end)
            b.insert(s, text)
        b.end_user_action()
        t.active_view.grab_focus()

    def lsp_rename(self):
        t, c = self._lsp_ctx()
        if not c:
            return
        b = t.buffer
        it = b.get_iter_at_mark(b.get_insert())
        s, e = it.copy(), it.copy()
        while s.backward_char():
            if not (s.get_char().isalnum() or s.get_char() == "_"):
                s.forward_char()
                break
        while not e.is_end() and (e.get_char().isalnum() or e.get_char() == "_"):
            e.forward_char()
        word = b.get_text(s, e, False)
        def go(new):
            new = new.strip()
            if not new or new == word:
                return
            def cb(res, err):
                if err or not res:
                    self.flash("Rename failed: " + ((err or {}).get("message", "nothing to rename")), 4000)
                    return
                n = self._apply_workspace_edit(res)
                self.flash(f"Renamed in {n} files", 3000)
            c.request("textDocument/rename", {"textDocument": self._doc(t), "position": self._lsp_pos(t), "newName": new}, cb)
        Palette(self, f"Rename “{word}” to…", on_text=go, initial=word).present()

    def _apply_workspace_edit(self, we):
        changes = dict(we.get("changes") or {})
        for dc in we.get("documentChanges") or []:
            if "textDocument" in dc:
                changes.setdefault(dc["textDocument"]["uri"], []).extend(dc.get("edits", []))
        for uri, edits in changes.items():
            path = lsp.uri_to_path(uri)
            tab = next((t for t in self.tabs() if t.path == path), None)
            if tab:
                tab.replace_all_text(_apply_text_edits(tab.get_text(), edits))
            else:
                try:
                    with open(path, encoding="utf-8") as f:
                        txt = f.read()
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        f.write(_apply_text_edits(txt, edits))
                except OSError:
                    pass
        return len(changes)
