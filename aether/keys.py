"""Default keybindings (action -> accelerators) and labels; users override in settings['keybindings']."""
DEFAULTS = {
    "new": ["<Control>n"], "open": ["<Control>o"], "open_folder": ["<Control><Shift>o"],
    "save": ["<Control>s"], "save_as": ["<Control><Shift>s"], "close_tab": ["<Control>w"],
    "reopen_tab": ["<Control><Shift>t"], "quit": ["<Control>q"], "run": ["F5"],
    "find": ["<Control>f"], "replace": ["<Control>h"], "find_in_files": ["<Control><Shift>f"],
    "goto": ["<Control>g"], "goto_symbol": ["<Control>r"], "palette": ["<Control><Shift>p"],
    "quick_open": ["<Control>p"], "themes": ["<Control>k"], "comment": ["<Control>slash"],
    "dup": ["<Control><Shift>d"], "starter": ["<Control><Shift>m"], "format": ["<Control><Shift>i"],
    "toggle_sidebar": ["<Control>b"], "toggle_panel": ["<Control>grave"], "toggle_wrap": ["<Alt>z"],
    "zoom_in": ["<Control>plus", "<Control>equal"], "zoom_out": ["<Control>minus"], "zoom_reset": ["<Control>0"],
    "next_tab": ["<Control>Page_Down"], "prev_tab": ["<Control>Page_Up"], "split": ["<Control>backslash"],
    "zen": ["F11"], "new_terminal": ["<Control><Shift>grave"], "focus_term": ["<Control><Alt>grave"],
    "show_files": ["<Control><Shift>e"], "show_git": ["<Control><Shift>g"], "preferences": ["<Control>comma"],
    "definition": ["F12"], "hover": ["F1"], "complete": ["<Control>space"], "references": ["<Shift>F12"],
    "rename_symbol": ["F2"], "theme_studio": [],
    "move_up": ["<Alt>Up"], "move_down": ["<Alt>Down"], "delete_line": ["<Control><Shift>k"], "join_lines": ["<Control>j"],
    "sort_lines": [], "sort_lines_desc": [], "upper_case": [], "lower_case": [], "title_case": [], "trim_ws": [],
    "cycle_layout": [], "cycle_theme": ["<Control><Alt>t"], "toggle_statusbar": [], "toggle_line_numbers": [],
    # v3: projects, debugger, folding, multi-cursor
    "build": ["<Control><Shift>b"], "test": [], "clean": [], "configure": [], "tasks": ["<Control><Alt>b"],
    "run_file": ["<Control>F5"], "project_settings": [], "new_project": ["<Control><Alt>n"], "clone": [],
    "debug": ["F6"], "debug_stop": ["<Shift>F6"], "step_over": ["F10"], "step_into": ["F7"], "step_out": ["<Shift>F7"],
    "debug_pause": [], "toggle_breakpoint": ["F9"], "watch_selection": [],
    "show_outline": ["<Control><Alt>o"], "show_debug": ["<Control><Alt>d"],
    "fold": ["<Control><Shift>braceleft", "<Control><Shift>bracketleft"],
    "unfold": ["<Control><Shift>braceright", "<Control><Shift>bracketright"],
    "fold_all": ["<Control><Alt>bracketleft"], "unfold_all": ["<Control><Alt>bracketright"],
    "add_next_occurrence": ["<Control>d"], "select_all_occurrences": ["<Control><Shift>l"],
    "cursor_above": ["<Control><Alt>Up"], "cursor_below": ["<Control><Alt>Down"],
}
LABELS = {
    "new": "New file", "open": "Open file", "open_folder": "Open folder", "save": "Save", "save_as": "Save as",
    "close_tab": "Close tab", "reopen_tab": "Reopen closed tab", "quit": "Quit", "run": "Run file",
    "find": "Find", "replace": "Replace", "find_in_files": "Search in project", "goto": "Go to line",
    "goto_symbol": "Go to symbol", "palette": "Command palette", "quick_open": "Quick open file",
    "themes": "Change theme", "comment": "Toggle comment", "dup": "Duplicate line", "starter": "Insert starter",
    "format": "Format document", "toggle_sidebar": "Toggle sidebar", "toggle_panel": "Toggle bottom panel",
    "toggle_wrap": "Toggle word wrap", "zoom_in": "Zoom in", "zoom_out": "Zoom out", "zoom_reset": "Reset zoom",
    "next_tab": "Next tab", "prev_tab": "Previous tab", "split": "Split editor", "zen": "Zen mode",
    "new_terminal": "New terminal", "focus_term": "Focus terminal", "show_files": "Show files",
    "show_git": "Show source control", "preferences": "Preferences", "definition": "Go to definition",
    "hover": "Show documentation", "complete": "Trigger completion", "references": "Find references",
    "rename_symbol": "Rename symbol", "theme_studio": "Theme studio",
    "move_up": "Move line up", "move_down": "Move line down", "delete_line": "Delete line", "join_lines": "Join lines",
    "sort_lines": "Sort lines (A-Z)", "sort_lines_desc": "Sort lines (Z-A)", "upper_case": "UPPERCASE selection",
    "lower_case": "lowercase selection", "title_case": "Title Case selection", "trim_ws": "Trim trailing whitespace",
    "cycle_layout": "Cycle layout", "cycle_theme": "Next theme", "toggle_statusbar": "Toggle status bar",
    "toggle_line_numbers": "Toggle line numbers",
    "build": "Build project", "test": "Run tests", "clean": "Clean build", "configure": "Configure project",
    "tasks": "Project tasks", "run_file": "Run current file", "project_settings": "Project settings",
    "new_project": "New project", "clone": "Clone repository", "debug": "Debug: start / continue",
    "debug_stop": "Debug: stop", "step_over": "Debug: step over", "step_into": "Debug: step into",
    "step_out": "Debug: step out", "debug_pause": "Debug: pause", "toggle_breakpoint": "Toggle breakpoint",
    "watch_selection": "Debug: watch selection", "show_outline": "Show outline", "show_debug": "Show debugger",
    "fold": "Fold block", "unfold": "Unfold block", "fold_all": "Fold all", "unfold_all": "Unfold all",
    "add_next_occurrence": "Add cursor at next occurrence", "select_all_occurrences": "Select all occurrences",
    "cursor_above": "Add cursor above", "cursor_below": "Add cursor below",
}


def effective(settings):
    out = {k: list(v) for k, v in DEFAULTS.items()}
    for k, v in (settings["keybindings"] or {}).items():
        if k in out and isinstance(v, list):
            out[k] = v
    return out
