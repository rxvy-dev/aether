"""A small Emmet: type an abbreviation in HTML and press Tab.

    !                     HTML5 page          ul>li.item$*3      list with item1..item3
    div#app.dark          <div id="app" class="dark"></div>
    nav>a[href=#]*2       links               p{Hello}+button.btn{Go}
    .card>h2+p            implicit <div>      (header>h1)+main+footer   groups
    lorem / lorem10       placeholder text

expand(abbr, indent_unit) -> (text, cursor_offset) or None when `abbr` isn't an abbreviation.
"""
import re

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
INLINE = {"a", "abbr", "b", "bdi", "bdo", "br", "cite", "code", "data", "dfn", "em", "i", "img", "input", "kbd", "label",
          "mark", "q", "s", "samp", "small", "span", "strong", "sub", "sup", "time", "u", "var", "button", "select",
          "textarea", "option", "td", "th", "li", "h1", "h2", "h3", "h4", "h5", "h6", "p", "title", "dt", "dd",
          "figcaption", "legend", "summary", "caption", "script", "style"}
TAGS = VOID | INLINE | {
    "html", "head", "body", "div", "section", "article", "aside", "header", "footer", "main", "nav", "ul", "ol", "dl",
    "table", "thead", "tbody", "tfoot", "tr", "form", "fieldset", "figure", "blockquote", "pre", "details", "dialog",
    "canvas", "svg", "video", "audio", "picture", "iframe", "noscript", "template", "address", "hgroup", "menu", "object",
    "optgroup", "datalist", "output", "progress", "meter", "slot", "colgroup", "map", "search"}
DEFAULT_ATTRS = {"a": [("href", "")], "img": [("src", ""), ("alt", "")], "link": [("rel", "stylesheet"), ("href", "")],
                 "input": [("type", "text"), ("name", "")], "form": [("action", "")], "label": [("for", "")],
                 "iframe": [("src", "")], "source": [("src", ""), ("type", "")], "video": [("src", "")],
                 "audio": [("src", "")], "script": [("src", "")], "option": [("value", "")], "textarea": [("name", "")],
                 "select": [("name", "")], "button": [("type", "button")], "meta": [("name", ""), ("content", "")]}
ALIASES = {"link:css": ("link", [("rel", "stylesheet"), ("href", "style.css")]), "script:src": ("script", [("src", "")]),
           "input:text": ("input", [("type", "text"), ("name", "")]), "input:email": ("input", [("type", "email"), ("name", "")]),
           "input:password": ("input", [("type", "password"), ("name", "")]),
           "input:checkbox": ("input", [("type", "checkbox"), ("name", "")]),
           "input:submit": ("input", [("type", "submit"), ("value", "")]), "btn": ("button", [("type", "button")]),
           "a:link": ("a", [("href", "https://")]), "img:alt": ("img", [("src", ""), ("alt", "")])}
IMPLICIT = {"ul": "li", "ol": "li", "menu": "li", "table": "tr", "tbody": "tr", "thead": "tr", "tfoot": "tr", "tr": "td",
            "select": "option", "optgroup": "option", "dl": "dt", "colgroup": "col", "map": "area", "audio": "source",
            "video": "source", "picture": "source"}
LOREM = ("Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore "
         "magna aliqua ut enim ad minim veniam quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo "
         "consequat duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur").split()

CURSOR = "\x00"
BOILERPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
{i}<meta charset="UTF-8">
{i}<meta name="viewport" content="width=device-width, initial-scale=1.0">
{i}<title>Document</title>
{i}<link rel="stylesheet" href="style.css">
</head>
<body>
{i}\x00
{i}<script src="script.js"></script>
</body>
</html>"""

ABBR_CHARS = re.compile(r"[\w.#>+^*$!:()\[\]{}=\"'@%/ -]")


class _Node:
    def __init__(self, tag=None):
        self.tag, self.id, self.classes, self.attrs, self.text = tag, None, [], [], None
        self.children, self.count, self.group = [], 1, False


class _Parser:
    def __init__(self, s):
        self.s, self.i = s, 0

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def take(self, n=1):
        t = self.s[self.i:self.i + n]
        self.i += n
        return t

    def until(self, close):
        start = self.i
        depth = 0
        opener = {"]": "[", "}": "{", ")": "("}[close]
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == opener:
                depth += 1
            elif c == close:
                if depth == 0:
                    out = self.s[start:self.i]
                    self.i += 1
                    return out
                depth -= 1
            self.i += 1
        raise ValueError("unclosed " + opener)

    def parse(self):
        root = _Node()
        self._seq(root)
        if self.i != len(self.s):
            raise ValueError("junk at %d" % self.i)
        return root

    def _seq(self, parent):
        """sibling list, with > and ^ moving down / up."""
        stack = [parent]
        cur = stack[-1]
        last = None
        while True:
            node = self._elem()
            cur.children.append(node)
            last = node
            c = self.peek()
            if c == "+":
                self.take()
            elif c == ">":
                self.take()
                stack.append(last)
                cur = last
            elif c == "^":
                while self.peek() == "^":
                    self.take()
                    if len(stack) > 1:
                        stack.pop()
                cur = stack[-1]
            else:
                return

    def _elem(self):
        if self.peek() == "(":
            self.take()
            inner = self.until(")")
            node = _Node()
            node.group = True
            _Parser(inner)._seq(node)
        else:
            node = _Node()
            m = re.match(r"[A-Za-z][\w:-]*!?", self.s[self.i:])
            if m:
                node.tag = self.take(len(m.group(0))).rstrip("!")
            got = bool(m)
            while True:
                c = self.peek()
                if c == "#":
                    self.take()
                    node.id = self._name()
                elif c == ".":
                    self.take()
                    node.classes.append(self._name())
                elif c == "[":
                    self.take()
                    node.attrs += _attrs(self.until("]"))
                elif c == "{":
                    self.take()
                    node.text = self.until("}")
                else:
                    break
                got = True
            if not got:
                raise ValueError("expected an element at %d" % self.i)
        if self.peek() == "*":
            self.take()
            m = re.match(r"\d+", self.s[self.i:])
            if not m:
                raise ValueError("expected a number after *")
            node.count = max(1, min(500, int(self.take(len(m.group(0))))))
        return node

    def _name(self):
        m = re.match(r"[\w$@-]+", self.s[self.i:])
        if not m:
            raise ValueError("expected a name")
        return self.take(len(m.group(0)))


def _attrs(s):
    out = []
    for m in re.finditer(r'([\w:@.-]+)(?:=("[^"]*"|\'[^\']*\'|[^\s]*))?', s):
        v = m.group(2)
        if v and v[0] in "\"'":
            v = v[1:-1]
        out.append((m.group(1), v if v is not None else ""))
    return out


def _num(s, n, total):
    def rep(m):
        w = len(m.group(1))
        rev = m.group(2) == "@-"
        v = (total - n + 1) if rev else n
        return str(v).zfill(w)
    return re.sub(r"(\$+)(@-)?", rep, s) if s else s


def _lorem(n):
    words = [LOREM[i % len(LOREM)] for i in range(n)]
    words[0] = words[0].capitalize()
    return " ".join(words) + "."


def _render(nodes, parent_tag, unit, depth, out, pn=1, ptotal=1):
    for node in nodes:
        if node.count == 1:                      # un-repeated children number like their parent: li*3>{Item $}
            _render_one(node, pn, ptotal, parent_tag, unit, depth, out)
        else:
            for n in range(1, node.count + 1):
                _render_one(node, n, node.count, parent_tag, unit, depth, out)


def _render_one(node, n, total, parent_tag, unit, depth, out):
    pad = unit * depth
    if node.group:
        _render(node.children, parent_tag, unit, depth, out, n, total)
        return
    if node.tag is None and node.text is not None and node.id is None and not node.classes and not node.attrs \
            and not node.children:
        out.append(pad + _num(node.text, n, total))          # a bare {text} node
        return
    tag = node.tag
    attrs = []
    if tag and tag.lower() in ALIASES:
        tag, attrs = ALIASES[tag.lower()][0], list(ALIASES[tag.lower()][1])
    m = re.fullmatch(r"lorem(?:ipsum)?(\d*)", tag or "")
    if m and not node.children and not node.classes and node.id is None:
        out.append(pad + _lorem(int(m.group(1) or 30)))
        return
    if not tag:
        tag = IMPLICIT.get((parent_tag or "").lower(), "span" if (parent_tag or "").lower() in INLINE - {"li", "td", "th"} else "div")
    if not attrs and not node.attrs:
        attrs = list(DEFAULT_ATTRS.get(tag.lower(), []))
    for k, v in node.attrs:
        attrs = [(a, b) for a, b in attrs if a != k] + [(k, v)]
    parts = []
    if node.id is not None:
        parts.append(f'id="{_num(node.id, n, total)}"')
    if node.classes:
        parts.append(f'class="{" ".join(_num(c, n, total) for c in node.classes)}"')
    for k, v in attrs:
        parts.append(f'{k}="{_num(v, n, total) if v else CURSOR}"')
    open_tag = "<" + tag + ("" if not parts else " " + " ".join(parts)) + ">"
    text = _num(node.text, n, total) if node.text is not None else None
    if tag.lower() in VOID:
        out.append(pad + open_tag)
        return
    close = f"</{tag}>"
    if not node.children:
        out.append(pad + open_tag + (text if text is not None else CURSOR) + close)
        return
    if text is None and all(not c.children for c in node.children) and tag.lower() in INLINE and len(node.children) == 1 \
            and node.children[0].count == 1:
        inner = []
        _render(node.children, tag, unit, 0, inner, n, total)
        out.append(pad + open_tag + inner[0] + close)
        return
    out.append(pad + open_tag + (text or ""))
    _render(node.children, tag, unit, depth + 1, out, n, total)
    out.append(pad + close)


def looks_like(abbr):
    """Is this worth expanding? (Bare words only when they are HTML tags, so Tab still indents prose.)"""
    if not abbr or abbr[0] in ">+^*)]}" or abbr.endswith((">", "+")):
        return False
    if abbr == "!" or re.fullmatch(r"lorem(?:ipsum)?\d*", abbr):
        return True
    if re.fullmatch(r"[A-Za-z][\w-]*", abbr):
        return abbr.lower() in TAGS
    if re.fullmatch(r"[A-Za-z][\w-]*:[\w-]+", abbr):
        return abbr.lower() in ALIASES
    return bool(re.search(r"[.#>+*\[{(^]", abbr))


def expand(abbr, unit="  "):
    abbr = abbr.strip()
    if not looks_like(abbr):
        return None
    if abbr in ("!", "html:5"):
        text = BOILERPLATE.replace("{i}", unit)
    else:
        try:
            tree = _Parser(abbr).parse()
        except (ValueError, IndexError, KeyError):
            return None
        lines = []
        _render(tree.children, None, unit, 0, lines)
        text = "\n".join(lines)
    cur = text.find(CURSOR)
    text = text.replace(CURSOR, "")
    return text, (cur if cur >= 0 else len(text))


def extract(line_before):
    """The abbreviation right before the cursor on this line (or "")."""
    i = len(line_before)
    depth = 0
    while i > 0:
        c = line_before[i - 1]
        if c in "]})":
            depth += 1
        elif c in "[{(":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and (c.isspace() or c in "<;,`"):
            break
        elif depth == 0 and c == ">" and i >= 2 and (line_before[i - 2] in "\"'/" or re.search(r"<[^<>]*$", line_before[:i - 1])):
            break                                   # the end of a real tag:  <div>ul>li
        elif depth == 0 and not ABBR_CHARS.match(c):
            break
        i -= 1
    s = line_before[i:]
    tail = line_before[:i]
    if re.search(r"<[^<>]*$", tail):                # inside an open tag:  <div class="x  — don't touch
        return ""
    return s
