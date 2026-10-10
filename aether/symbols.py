import re

R = lambda p: re.compile(p, re.M)
PATS = {
    "python": [("class", R(r"^\s*class\s+(\w+)")), ("function", R(r"^\s*(?:async\s+)?def\s+(\w+)"))],
    "c": [("struct", R(r"^\s*(?:typedef\s+)?(?:struct|enum|union)\s+(\w+)")),
          ("struct", R(r"^\}\s*(\w+)\s*;")),                       # typedef struct { ... } Name;
          ("define", R(r"^\s*#\s*define\s+(\w+)")),
          ("function", R(r"^[A-Za-z_][\w\s\*]*?[\s\*]+(\w+)\s*\([^;{}]*\)\s*\{?\s*$"))],
    "cpp": [("class", R(r"^\s*(?:template\s*<[^>]*>\s*)?(?:class|struct|enum(?:\s+class)?|namespace)\s+(\w+)")),
            ("function", R(r"^[A-Za-z_][\w\s\*&:<>,~]*?[\s\*&]+((?:\w+::)*~?\w+)\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{?\s*$"))],
    "javascript": [("class", R(r"^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)")),
                   ("function", R(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\*?\s+(\w+)")),
                   ("function", R(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"))],
    "rust": [("struct", R(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union|mod)\s+(\w+)")),
             ("impl", R(r"^\s*impl(?:<[^>]*>)?\s+([\w:<>, ]+?)\s*(?:for\s+[\w:<>, ]+)?\s*\{")),
             ("function", R(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:const\s+)?fn\s+(\w+)"))],
    "go": [("type", R(r"^type\s+(\w+)")), ("function", R(r"^func\s+(?:\([^)]*\)\s*)?(\w+)"))],
    "java": [("class", R(r"^\s*(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+|static\s+)*(?:class|interface|enum|record)\s+(\w+)")),
             ("function", R(r"^\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?[\w<>\[\],\s]+?\s+(\w+)\s*\([^;]*\)\s*(?:throws\s+[\w, ]+)?\s*\{?\s*$"))],
    "csharp": [("class", R(r"^\s*(?:public|internal|private|protected|static|abstract|sealed|partial|\s)*(?:class|interface|struct|enum|record)\s+(\w+)")),
               ("function", R(r"^\s*(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?[\w<>\[\],\?]+\s+(\w+)\s*\([^;]*\)\s*\{?\s*$"))],
    "kotlin": [("class", R(r"^\s*(?:data\s+|sealed\s+|open\s+|abstract\s+)*(?:class|interface|object)\s+(\w+)")), ("function", R(r"^\s*(?:override\s+|private\s+|public\s+|suspend\s+)*fun\s+(?:<[^>]*>\s*)?(?:\w+\.)?(\w+)"))],
    "shellscript": [("function", R(r"^\s*(?:function\s+)?(\w[\w-]*)\s*\(\)\s*\{?"))],
    "lua": [("function", R(r"^\s*(?:local\s+)?function\s+([\w.:]+)"))],
    "ruby": [("class", R(r"^\s*(?:class|module)\s+([\w:]+)")), ("function", R(r"^\s*def\s+([\w.?!]+)"))],
    "php": [("class", R(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait)\s+(\w+)")), ("function", R(r"^\s*(?:public|private|protected|static|\s)*function\s+(\w+)"))],
    "markdown": [("heading", R(r"^(#{1,6}\s+.+)$"))],
    "zig": [("function", R(r"^\s*(?:pub\s+)?fn\s+(\w+)")), ("struct", R(r"^\s*(?:pub\s+)?const\s+(\w+)\s*=\s*(?:struct|enum|union)"))],
    "swift": [("class", R(r"^\s*(?:public\s+|private\s+|final\s+)*(?:class|struct|enum|protocol|extension)\s+(\w+)")), ("function", R(r"^\s*(?:public\s+|private\s+|static\s+)*func\s+(\w+)"))],
    "dart": [("class", R(r"^\s*(?:abstract\s+)?class\s+(\w+)")), ("function", R(r"^\s*[\w<>?]+\s+(\w+)\s*\([^;]*\)\s*(?:async\s*)?\{"))],
    "scala": [("class", R(r"^\s*(?:case\s+)?(?:class|object|trait)\s+(\w+)")), ("function", R(r"^\s*(?:override\s+)?def\s+(\w+)"))],
    "haskell": [("function", R(r"^(\w+)\s*::"))],
    "elixir": [("module", R(r"^\s*defmodule\s+([\w.]+)")), ("function", R(r"^\s*defp?\s+(\w+[?!]?)"))],
}
PATS["typescript"] = PATS["javascriptreact"] = PATS["typescriptreact"] = PATS["javascript"]
KEYWORDS = {"if", "for", "while", "switch", "return", "else", "sizeof", "catch", "do", "case"}


def extract(key, text):
    """-> sorted list of (line_no, kind, name)"""
    out = []
    for kind, pat in PATS.get(key, []):
        for m in pat.finditer(text):
            name = m.group(1).strip()
            if name in KEYWORDS:
                continue
            out.append((text.count("\n", 0, m.start(1)) + 1, kind, name))
    out.sort()
    seen, res = set(), []
    for item in out:
        if (item[0], item[2]) not in seen:
            seen.add((item[0], item[2]))
            res.append(item)
    return res
