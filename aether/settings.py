import json, os

CFG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "aether")
CFG_FILE = os.path.join(CFG_DIR, "settings.json")

DEFAULTS = {
    "theme": "aether-crimson",
    "version": 3,
    "font": "JetBrains Mono, Fira Code, Cascadia Code, Hack, Source Code Pro, DejaVu Sans Mono, monospace",
    "show_ruler": False,
    "accent": "",                    # "" = use the theme's accent
    "layout": "islands",             # islands | classic | flat | floating
    "tab_style": "underline",        # underline | pill | box
    "sidebar_side": "left",          # left | right
    "panel_position": "bottom",      # bottom | right
    "header_style": "command bar",   # command bar | title
    "show_statusbar": True,
    "breadcrumbs": True,
    "show_line_numbers": True,
    "bracket_match": True,
    "smart_home_end": True,
    "cursor_blink": True,
    "scroll_past_end": False,
    "corner_style": "soft",          # sharp | soft | round
    "density": "comfortable",        # compact | comfortable | spacious
    "opacity": 1.0,                  # <1 = translucent window (blur it in your compositor)
    "ui_font": "Inter, Cantarell, Noto Sans, sans-serif",
    "line_spacing": 2,
    "ligatures": True,
    "git_marks": True,
    "keybindings": {},
    "run_commands": {},
    "format_on_save_tool": False,
    "lsp": True,
    "lsp_servers": {},
    "highlight_line": True,
    "recent": [],
    "font_size": 12,
    "minimap": True,
    "word_wrap": False,
    "show_whitespace": False,
    "auto_save": False,
    "format_on_save": True,          # trim trailing whitespace + final newline
    "auto_pairs": True,
    "lint": True,
    "starter_on_new_file": True,     # insert `main` skeleton into new empty files
    "right_margin": 100,
    "terminal": True,
    "sidebar": True,
    "indent_default": {"style": "spaces", "width": 4},
    "indent_by_language": {
        "go": {"style": "tabs", "width": 4}, "makefile": {"style": "tabs", "width": 4},
        "javascript": {"style": "spaces", "width": 2}, "typescript": {"style": "spaces", "width": 2},
        "javascriptreact": {"style": "spaces", "width": 2}, "typescriptreact": {"style": "spaces", "width": 2},
        "html": {"style": "spaces", "width": 2}, "css": {"style": "spaces", "width": 2},
        "json": {"style": "spaces", "width": 2}, "yaml": {"style": "spaces", "width": 2},
        "lua": {"style": "spaces", "width": 2}, "ruby": {"style": "spaces", "width": 2},
        "markdown": {"style": "spaces", "width": 2}, "toml": {"style": "spaces", "width": 2},
    },
    "session": {"folder": None, "files": [], "active": 0},
    "breakpoints": {},               # path -> [0-based lines]
    "bracket_colors": True,          # colour (), [], {} by depth
    "activity_bar": True,            # VS Code-style icon bar on the left
    "build_config": "Debug",         # Debug | Release
    "panel_pos": 0,                  # editor/panel split (0 = default)
    "serial": {"port": "", "baud": 115200},   # last used serial port / speed (embedded boards)
}


class Settings:
    def __init__(self):
        self.d = json.loads(json.dumps(DEFAULTS))
        try:
            with open(CFG_FILE) as f:
                user = json.load(f)
            if user.get("version", 1) < 3:      # old defaults: let the new look take over
                for k in ("minimap", "font", "right_margin"):
                    user.pop(k, None)
            for k, v in user.items():
                self.d[k] = v
            self.d["version"] = 3
        except (OSError, ValueError):
            pass

    def __getitem__(self, k):
        return self.d.get(k, DEFAULTS.get(k))

    def __setitem__(self, k, v):
        self.d[k] = v
        self.save()

    def save(self):
        try:
            os.makedirs(CFG_DIR, exist_ok=True)
            tmp = CFG_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.d, f, indent=2)
            os.replace(tmp, CFG_FILE)
        except OSError:
            pass

    def indent_for(self, tkey):
        return self.d["indent_by_language"].get(tkey) or self.d["indent_default"]
