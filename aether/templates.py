import json, os, re
from . import data_dir

with open(os.path.join(data_dir(), "templates.json")) as _f:
    T = json.load(_f)

EXT = {".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
       ".py": "python", ".js": "javascript", ".mjs": "javascript", ".ts": "typescript", ".jsx": "javascriptreact",
       ".tsx": "typescriptreact", ".rs": "rust", ".go": "go", ".java": "java", ".cs": "csharp", ".kt": "kotlin",
       ".swift": "swift", ".dart": "dart", ".scala": "scala", ".sh": "shellscript", ".bash": "shellscript",
       ".lua": "lua", ".pl": "perl", ".rb": "ruby", ".php": "php", ".hs": "haskell", ".zig": "zig",
       ".ex": "elixir", ".exs": "elixir", ".r": "r", ".jl": "julia", ".html": "html", ".htm": "html",
       ".css": "css", ".sql": "sql", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".md": "markdown",
       ".json": "json"}
NAMES = {"makefile": "makefile", "dockerfile": "dockerfile"}
KEY_EXT = {"c": ".c", "cpp": ".cpp", "python": ".py", "javascript": ".js", "typescript": ".ts",
           "javascriptreact": ".jsx", "typescriptreact": ".tsx", "rust": ".rs", "go": ".go", "java": ".java",
           "csharp": ".cs", "kotlin": ".kt", "swift": ".swift", "dart": ".dart", "scala": ".scala",
           "shellscript": ".sh", "lua": ".lua", "perl": ".pl", "ruby": ".rb", "php": ".php", "haskell": ".hs",
           "zig": ".zig", "elixir": ".ex", "r": ".r", "julia": ".jl", "html": ".html", "css": ".css",
           "sql": ".sql", "makefile": "Makefile", "dockerfile": "Dockerfile", "toml": ".toml", "yaml": ".yaml",
           "markdown": ".md", "json": ".json"}
PRETTY = {"c": "C", "cpp": "C++", "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
          "javascriptreact": "JSX", "typescriptreact": "TSX", "rust": "Rust", "go": "Go", "java": "Java",
          "csharp": "C#", "kotlin": "Kotlin", "swift": "Swift", "dart": "Dart", "scala": "Scala",
          "shellscript": "Shell (bash)", "lua": "Lua", "perl": "Perl", "ruby": "Ruby", "php": "PHP",
          "haskell": "Haskell", "zig": "Zig", "elixir": "Elixir", "r": "R", "julia": "Julia", "html": "HTML",
          "css": "CSS", "sql": "SQL", "makefile": "Makefile", "dockerfile": "Dockerfile", "toml": "TOML",
          "yaml": "YAML", "markdown": "Markdown", "json": "JSON"}
# languages where an automatic starter makes no sense (data / prose)
NO_AUTO = {"markdown", "json", "yaml", "toml", "css", "sql"}


def key_for_path(path):
    if not path:
        return None
    base = os.path.basename(path)
    if base.lower() in NAMES:
        return NAMES[base.lower()]
    return EXT.get(os.path.splitext(base)[1].lower())


def header_starter(path):
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1].lower()
    guard = re.sub(r"\W", "_", os.path.splitext(base)[0]).upper() + "_" + ext[1:].upper()
    if ext == ".h":
        return f"#ifndef {guard}\n#define {guard}\n\n$0\n\n#endif /* {guard} */\n"
    if ext in (".hpp", ".hh"):
        return "#pragma once\n\n$0\n"
    return None


def number_final(text):
    """GtkSourceView ignores default text in ${0:..}; turn it into the last numbered tab stop so it is pre-selected."""
    if "${0:" not in text:
        return text
    nums = [int(n) for n in re.findall(r"\$\{(\d+):", text) if n != "0"]
    return text.replace("${0:", "${%d:" % (max(nums, default=0) + 1))


def starter_text(key, path=None):
    if path:
        h = header_starter(path)
        if h:
            return h
    d = T.get(key)
    if not d:
        return None
    base = os.path.splitext(os.path.basename(path))[0] if path else "Main"
    base = re.sub(r"\W", "_", base) or "Main"
    text = number_final(d["main"])
    text = text.replace("${TM_FILENAME_BASE:Main}", base).replace("${TM_FILENAME_BASE}", base)
    text = re.sub(r"\$TM_FILENAME_BASE\b", base, text)
    return text
