"""Build GtkSourceView style schemes from a small palette; import VS Code themes."""
import json, os, re

KEYS = ["bg", "fg", "sel", "line", "gut", "cur", "comment", "string", "keyword", "type", "number", "func",
        "pre", "const", "err", "warn", "special", "op"]
LABELS = {"bg": "Background", "fg": "Text", "sel": "Selection", "line": "Current line", "gut": "Line numbers",
          "cur": "Cursor", "comment": "Comments", "string": "Strings", "keyword": "Keywords", "type": "Types",
          "number": "Numbers", "func": "Functions (accent)", "pre": "Preprocessor", "const": "Constants",
          "err": "Errors", "warn": "Warnings", "special": "Escapes / specials", "op": "Operators"}


def _style(name, fg=None, bg=None, italic=False, bold=False, underline=None):
    a = [f'name="{name}"']
    if fg:
        a.append(f'foreground="{fg}"')
    if bg:
        a.append(f'background="{bg}"')
    if italic:
        a.append('italic="true"')
    if bold:
        a.append('bold="true"')
    if underline:
        a.append(f'underline="{underline}"')
    return "  <style " + " ".join(a) + "/>"


def scheme_xml(sid, name, c):
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<style-scheme id="{sid}" name="{name}" version="1.0">',
         '  <author>Aether</author>', f'  <description>{name}</description>',
         _style("text", c["fg"], c["bg"]), _style("selection", None, c["sel"]), _style("cursor", c["cur"]),
         _style("secondary-cursor", c["gut"]), _style("current-line", None, c["line"]),
         _style("line-numbers", c["gut"], c["bg"]), _style("current-line-number", c["fg"], c["line"], bold=True),
         _style("bracket-match", c["cur"], c["sel"], bold=True), _style("bracket-mismatch", c["err"], None, underline="error"),
         _style("right-margin", c["gut"], c["line"]), _style("draw-spaces", c["sel"]), _style("search-match", None, c["sel"]),
         _style("map-overlay", None, c["sel"]),
         _style("def:comment", c["comment"], italic=True), _style("def:shebang", c["comment"], bold=True),
         _style("def:doc-comment-element", c["comment"], italic=True, bold=True),
         _style("def:string", c["string"]), _style("def:special-char", c["special"]),
         _style("def:special-constant", c["const"]), _style("def:character", c["string"]),
         _style("def:keyword", c["keyword"]), _style("def:statement", c["keyword"]), _style("def:builtin", c["func"]),
         _style("def:type", c["type"]), _style("def:function", c["func"]), _style("def:identifier", c["fg"]),
         _style("def:variable", c["fg"]), _style("def:operator", c["op"]), _style("def:constant", c["const"]),
         _style("def:boolean", c["const"]), _style("def:number", c["number"]), _style("def:decimal", c["number"]),
         _style("def:base-n-integer", c["number"]), _style("def:floating-point", c["number"]),
         _style("def:complex", c["number"]), _style("def:preprocessor", c["pre"]),
         _style("def:note", c["warn"], bold=True), _style("def:warning", c["warn"], underline="error"),
         _style("def:error", c["err"], underline="error"), _style("def:underlined", None, underline="single"),
         _style("def:link-symbol", c["func"], underline="single"), _style("def:link-destination", c["func"], underline="single"),
         _style("def:heading", c["keyword"], bold=True), _style("def:emphasis", None, italic=True),
         _style("def:strong-emphasis", None, bold=True), _style("def:inline-code", c["string"]),
         _style("def:net-address", c["func"], underline="single"), _style("def:reserved", c["keyword"]),
         _style("diff:added-line", "#6bd36b"), _style("diff:removed-line", c["err"]),
         _style("diff:changed-line", c["warn"]), _style("diff:special-case", c["pre"]),
         _style("diff:location", c["func"]), _style("diff:diff-file", c["type"]),
         "</style-scheme>"]
    return "\n".join(L) + "\n"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "theme"


def save_scheme(dirpath, name, c):
    os.makedirs(dirpath, exist_ok=True)
    sid = "user-" + slug(name)
    with open(os.path.join(dirpath, sid + ".xml"), "w") as f:
        f.write(scheme_xml(sid, name, c))
    return sid


# ---------------- palette helpers ----------------
def _hex(c, default):
    if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", c):
        return c[:7].lower()
    return default


def scheme_to_palette(scheme):
    """Read a Gtk.Source style scheme into our palette dict (best effort)."""
    def fg(n, d):
        s = scheme.get_style(n)
        return (s.props.foreground if s and s.props.foreground_set else None) or d
    def bgc(n, d):
        s = scheme.get_style(n)
        return (s.props.background if s and s.props.background_set else None) or d
    t = scheme.get_style("text")
    bg = (t.props.background if t and t.props.background_set else "#1e1e1e")
    f = (t.props.foreground if t and t.props.foreground_set else "#d4d4d4")
    return dict(bg=bg, fg=f, sel=bgc("selection", "#264f78"), line=bgc("current-line", bg), gut=fg("line-numbers", "#858585"),
                cur=fg("cursor", f), comment=fg("def:comment", "#6a9955"), string=fg("def:string", "#ce9178"),
                keyword=fg("def:keyword", "#569cd6"), type=fg("def:type", "#4ec9b0"), number=fg("def:number", "#b5cea8"),
                func=fg("def:function", "#dcdcaa"), pre=fg("def:preprocessor", "#c586c0"), const=fg("def:constant", "#4fc1ff"),
                err=fg("def:error", "#f44747"), warn=fg("def:warning", "#cca700"), special=fg("def:special-char", "#d7ba7d"),
                op=fg("def:operator", f))


def _strip_jsonc(text):
    """Remove // and /* */ comments (outside strings) and trailing commas."""
    out, i, n, instr = [], 0, len(text), False
    while i < n:
        c = text[i]
        if instr:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 1
            elif c == '"':
                instr = False
        elif c == '"':
            instr = True; out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 1
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


SCOPES = {
    "comment": ["comment"], "string": ["string"], "keyword": ["keyword", "storage.type", "storage.modifier"],
    "type": ["entity.name.type", "entity.name.class", "support.type", "support.class", "storage.type.class"],
    "number": ["constant.numeric"], "func": ["entity.name.function", "support.function", "meta.function-call"],
    "pre": ["meta.preprocessor", "keyword.control.directive", "entity.name.tag"], "const": ["constant.language", "constant"],
    "err": ["invalid"], "special": ["constant.character.escape", "string.regexp"], "op": ["keyword.operator"],
}


def from_vscode(text):
    """Convert a VS Code color theme (JSON/JSONC) into a palette dict. Raises ValueError on garbage."""
    try:
        data = json.loads(text)
    except ValueError:
        data = json.loads(_strip_jsonc(text))
    colors = data.get("colors", {}) or {}
    toks = data.get("tokenColors", []) or data.get("settings", [])
    dark = "light" not in str(data.get("type", "dark")).lower()
    bg = _hex(colors.get("editor.background"), "#1e1e1e" if dark else "#ffffff")
    fg = _hex(colors.get("editor.foreground") or colors.get("foreground"), "#d4d4d4" if dark else "#333333")
    for t in toks:                                  # legacy "settings" style global entry
        s = t.get("settings", {}) if isinstance(t, dict) else {}
        if isinstance(t, dict) and not t.get("scope"):
            bg = _hex(s.get("background"), bg)
            fg = _hex(s.get("foreground"), fg)

    def find(key, default):
        wanted = SCOPES[key]
        best = None
        for t in toks:
            if not isinstance(t, dict):
                continue
            sc = t.get("scope", [])
            sc = [x.strip() for x in (sc.split(",") if isinstance(sc, str) else sc)]
            for s in sc:
                for w in wanted:
                    if s == w or s.startswith(w + "."):
                        col = _hex((t.get("settings") or {}).get("foreground"), None)
                        if col and (best is None or s == w):
                            best = col
        return best or default

    mixfg = lambda a: fg
    pal = dict(
        bg=bg, fg=fg,
        sel=_hex(colors.get("editor.selectionBackground"), "#264f78" if dark else "#add6ff"),
        line=_hex(colors.get("editor.lineHighlightBackground"), bg),
        gut=_hex(colors.get("editorLineNumber.foreground"), "#858585"),
        cur=_hex(colors.get("editorCursor.foreground"), fg),
        comment=find("comment", "#6a9955"), string=find("string", "#ce9178"), keyword=find("keyword", "#569cd6"),
        type=find("type", "#4ec9b0"), number=find("number", "#b5cea8"), func=find("func", "#dcdcaa"),
        pre=find("pre", "#c586c0"), const=find("const", "#4fc1ff"), err=find("err", "#f44747"),
        warn=_hex(colors.get("editorWarning.foreground"), "#cca700"), special=find("special", "#d7ba7d"),
        op=find("op", fg),
    )
    return data.get("name") or "Imported theme", pal
