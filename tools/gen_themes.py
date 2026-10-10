#!/usr/bin/env python3
"""Generate GtkSourceView style schemes (themes) for Aether."""
import os
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "styles")

# name, id, dark?, palette
P = [
 ("Aether Crimson", "aether-crimson", True, dict(bg="#0a0a0c", fg="#e9e4e6", sel="#46121b", line="#130c0f", gut="#5a474d", cur="#ff2e43",
   comment="#5c4a50", string="#e3c49a", keyword="#ff2e43", type="#ff8591", number="#ff9466", func="#ff5468", pre="#d4243a", const="#ff9466", err="#ff2e43", warn="#ffb454", special="#e0a8b3", op="#a08a90")),
 ("Obsidian", "aether-obsidian", True, dict(bg="#08080a", fg="#dcdce4", sel="#2a2a36", line="#101014", gut="#4a4a58", cur="#a78bfa",
   comment="#4f4f5e", string="#a5e3b8", keyword="#a78bfa", type="#7dd3fc", number="#fca5a5", func="#c4b5fd", pre="#f0abfc", const="#fca5a5", err="#f87171", warn="#fcd34d", special="#67e8f9", op="#9ca3af")),
 ("Synthwave", "aether-synthwave", True, dict(bg="#1a1033", fg="#f5e9ff", sel="#3d2667", line="#22164a", gut="#7a64a8", cur="#ff3df2",
   comment="#7a64a8", string="#fffb96", keyword="#ff3df2", type="#36f9f6", number="#ff8b39", func="#72f1b8", pre="#fe4450", const="#ff8b39", err="#fe4450", warn="#fffb96", special="#36f9f6", op="#d7b8ff")),
 ("Cyberpunk", "aether-cyberpunk", True, dict(bg="#0b0f14", fg="#e6f7ff", sel="#1f3b4d", line="#101820", gut="#3e6a80", cur="#fcee0a",
   comment="#3e6a80", string="#00ff9c", keyword="#fcee0a", type="#00d9ff", number="#ff2a6d", func="#05d9e8", pre="#ff2a6d", const="#ff2a6d", err="#ff2a6d", warn="#fcee0a", special="#d1f7ff", op="#7fa7b8")),
 ("Aether Abyss", "aether-abyss", True, dict(bg="#0b0a0d", fg="#e8e2e4", sel="#4a141c", line="#140d10", gut="#5e4a50", cur="#ff2e43",
   comment="#5f4c52", string="#d9bf98", keyword="#ff2e43", type="#ff7a85", number="#ff9466", func="#ff4d5e", pre="#c21d34", const="#ff9466", err="#ff2e43", warn="#ffb454", special="#d7a7b0", op="#9a8388")),
 ("Aether Night", "aether-night", True, dict(bg="#1a1b26", fg="#c0caf5", sel="#33467c", line="#202233", gut="#565f89", cur="#c0caf5",
   comment="#565f89", string="#9ece6a", keyword="#bb9af7", type="#2ac3de", number="#ff9e64", func="#7aa2f7", pre="#e0af68", const="#ff9e64", err="#f7768e", warn="#e0af68", special="#73daca", op="#89ddff")),
 ("Aether Dawn", "aether-dawn", False, dict(bg="#faf4ed", fg="#575279", sel="#dfdad9", line="#f2e9e1", gut="#9893a5", cur="#575279",
   comment="#9893a5", string="#286983", keyword="#907aa9", type="#56949f", number="#d7827e", func="#31748f", pre="#ea9d34", const="#d7827e", err="#b4637a", warn="#ea9d34", special="#56949f", op="#797593")),
 ("Aether Ember", "aether-ember", True, dict(bg="#1c1917", fg="#e7e0d8", sel="#4a3b2f", line="#26211e", gut="#7d7268", cur="#ffb454",
   comment="#7d7268", string="#a9d17b", keyword="#ff7b54", type="#ffc857", number="#f4a261", func="#ffb454", pre="#e76f51", const="#f4a261", err="#ff5c57", warn="#ffc857", special="#5ad4c4", op="#d9c8b6")),
 ("Aether Forest", "aether-forest", True, dict(bg="#1b2420", fg="#d3e0d5", sel="#35503f", line="#222d28", gut="#6b8574", cur="#a7e9a0",
   comment="#6b8574", string="#e6c07b", keyword="#7fdbca", type="#82aaff", number="#f78c6c", func="#a7e9a0", pre="#c792ea", const="#f78c6c", err="#ff6b6b", warn="#e6c07b", special="#7fdbca", op="#b4c9b9")),
 ("Aether Ocean", "aether-ocean", True, dict(bg="#0d1b2a", fg="#d6e4f0", sel="#274060", line="#14263a", gut="#5b7a99", cur="#6cd4ff",
   comment="#5b7a99", string="#95e6a4", keyword="#6cd4ff", type="#b9a2ff", number="#ffb86b", func="#82b1ff", pre="#ff9ac1", const="#ffb86b", err="#ff6b81", warn="#ffd479", special="#5eead4", op="#9fc2e0")),
 ("Aether Paper", "aether-paper", False, dict(bg="#ffffff", fg="#24292f", sel="#cfe3ff", line="#f4f6f8", gut="#8c959f", cur="#0969da",
   comment="#6e7781", string="#0a3069", keyword="#cf222e", type="#8250df", number="#0550ae", func="#6639ba", pre="#953800", const="#0550ae", err="#cf222e", warn="#9a6700", special="#116329", op="#24292f")),
 ("Aether Mono", "aether-mono", True, dict(bg="#101010", fg="#d0d0d0", sel="#3a3a3a", line="#181818", gut="#666666", cur="#ffffff",
   comment="#6a6a6a", string="#b5b5b5", keyword="#ffffff", type="#e0e0e0", number="#c8c8c8", func="#f0f0f0", pre="#9a9a9a", const="#c8c8c8", err="#ff6b6b", warn="#e6c07b", special="#a0a0a0", op="#8c8c8c")),
 ("Vampire", "aether-vampire", True, dict(bg="#1e1f29", fg="#f2f2f0", sel="#44475a", line="#282a36", gut="#6272a4", cur="#f8f8f2",
   comment="#6272a4", string="#f1fa8c", keyword="#ff79c6", type="#8be9fd", number="#bd93f9", func="#50fa7b", pre="#ffb86c", const="#bd93f9", err="#ff5555", warn="#ffb86c", special="#8be9fd", op="#ff79c6")),
 ("Fjord", "aether-fjord", True, dict(bg="#2e3440", fg="#d8dee9", sel="#434c5e", line="#3b4252", gut="#616e88", cur="#d8dee9",
   comment="#616e88", string="#a3be8c", keyword="#81a1c1", type="#8fbcbb", number="#b48ead", func="#88c0d0", pre="#d08770", const="#b48ead", err="#bf616a", warn="#ebcb8b", special="#8fbcbb", op="#81a1c1")),
 ("Fjord Light", "aether-fjord-light", False, dict(bg="#eceff4", fg="#2e3440", sel="#d8dee9", line="#e5e9f0", gut="#8f9bb3", cur="#2e3440",
   comment="#8f9bb3", string="#5f8a49", keyword="#5e81ac", type="#4c8a8d", number="#8f6a9c", func="#3b7f98", pre="#b8694e", const="#8f6a9c", err="#bf616a", warn="#a67c1a", special="#4c8a8d", op="#5e81ac")),
 ("Sandstone", "aether-sandstone", True, dict(bg="#282828", fg="#ebdbb2", sel="#504945", line="#32302f", gut="#7c6f64", cur="#ebdbb2",
   comment="#928374", string="#b8bb26", keyword="#fb4934", type="#fabd2f", number="#d3869b", func="#8ec07c", pre="#fe8019", const="#d3869b", err="#fb4934", warn="#fabd2f", special="#83a598", op="#fe8019")),
 ("Sandstone Light", "aether-sandstone-light", False, dict(bg="#fbf1c7", fg="#3c3836", sel="#d5c4a1", line="#f2e5bc", gut="#a89984", cur="#3c3836",
   comment="#928374", string="#79740e", keyword="#9d0006", type="#b57614", number="#8f3f71", func="#427b58", pre="#af3a03", const="#8f3f71", err="#9d0006", warn="#b57614", special="#076678", op="#af3a03")),
 ("Mocha", "aether-mocha", True, dict(bg="#1e1e2e", fg="#cdd6f4", sel="#45475a", line="#313244", gut="#6c7086", cur="#f5e0dc",
   comment="#6c7086", string="#a6e3a1", keyword="#cba6f7", type="#f9e2af", number="#fab387", func="#89b4fa", pre="#f5c2e7", const="#fab387", err="#f38ba8", warn="#f9e2af", special="#94e2d5", op="#89dceb")),
 ("Latte", "aether-latte", False, dict(bg="#eff1f5", fg="#4c4f69", sel="#ccd0da", line="#e6e9ef", gut="#9ca0b0", cur="#dc8a78",
   comment="#9ca0b0", string="#40a02b", keyword="#8839ef", type="#df8e1d", number="#fe640b", func="#1e66f5", pre="#ea76cb", const="#fe640b", err="#d20f39", warn="#df8e1d", special="#179299", op="#04a5e5")),
 ("Sunburst", "aether-sunburst", True, dict(bg="#002b36", fg="#93a1a1", sel="#073642", line="#06323d", gut="#586e75", cur="#93a1a1",
   comment="#586e75", string="#2aa198", keyword="#859900", type="#b58900", number="#d33682", func="#268bd2", pre="#cb4b16", const="#d33682", err="#dc322f", warn="#b58900", special="#2aa198", op="#839496")),
 ("Dayglow", "aether-dayglow", False, dict(bg="#fdf6e3", fg="#586e75", sel="#eee8d5", line="#f5eedb", gut="#93a1a1", cur="#586e75",
   comment="#93a1a1", string="#2aa198", keyword="#859900", type="#b58900", number="#d33682", func="#268bd2", pre="#cb4b16", const="#d33682", err="#dc322f", warn="#b58900", special="#2aa198", op="#657b83")),
 ("Neon", "aether-neon", True, dict(bg="#0b0b14", fg="#e6e6ff", sel="#2b2b55", line="#13132a", gut="#4b4b8a", cur="#ff2bd6",
   comment="#4b4b8a", string="#00ffa3", keyword="#ff2bd6", type="#00e5ff", number="#ffe600", func="#7c5cff", pre="#ff8a00", const="#ffe600", err="#ff3860", warn="#ffe600", special="#00e5ff", op="#a0a0ff")),
 ("Rosewood", "aether-rosewood", True, dict(bg="#1f1d2e", fg="#e0def4", sel="#403d52", line="#26233a", gut="#6e6a86", cur="#e0def4",
   comment="#6e6a86", string="#f6c177", keyword="#c4a7e7", type="#9ccfd8", number="#eb6f92", func="#ebbcba", pre="#f6c177", const="#eb6f92", err="#eb6f92", warn="#f6c177", special="#31748f", op="#908caa")),
 ("Slate", "aether-slate", True, dict(bg="#22272e", fg="#adbac7", sel="#2d4a6b", line="#2b313a", gut="#636e7b", cur="#adbac7",
   comment="#636e7b", string="#96d0ff", keyword="#f47067", type="#f69d50", number="#6cb6ff", func="#dcbdfb", pre="#6bc46d", const="#6cb6ff", err="#ff938a", warn="#c69026", special="#6bc46d", op="#adbac7")),
 ("Midnight", "aether-midnight", True, dict(bg="#000000", fg="#e4e4e7", sel="#27272a", line="#0c0c0f", gut="#52525b", cur="#e4e4e7",
   comment="#52525b", string="#86efac", keyword="#c4b5fd", type="#7dd3fc", number="#fdba74", func="#93c5fd", pre="#f0abfc", const="#fdba74", err="#fca5a5", warn="#fde047", special="#5eead4", op="#a1a1aa")),
 ("Matcha", "aether-matcha", False, dict(bg="#f4f8f1", fg="#2f3e34", sel="#cfe3c9", line="#eaf1e5", gut="#8aa08f", cur="#2f3e34",
   comment="#8aa08f", string="#a05a2c", keyword="#2f7d4f", type="#1d6b8a", number="#9a4d8a", func="#2a6f97", pre="#b0701a", const="#9a4d8a", err="#c0392b", warn="#a67c1a", special="#1d7a6e", op="#4d6455")),
 ("Terminal Green", "aether-terminal", True, dict(bg="#050805", fg="#33ff66", sel="#0f3d1c", line="#0a120b", gut="#1f7a3a", cur="#66ff99",
   comment="#1f7a3a", string="#b6ff6a", keyword="#33ff66", type="#7dffb0", number="#ffd24a", func="#66ff99", pre="#33ff66", const="#ffd24a", err="#ff5555", warn="#ffd24a", special="#7dffb0", op="#22cc55")),
 ("Amber CRT", "aether-amber", True, dict(bg="#140d02", fg="#ffb000", sel="#4a3000", line="#1c1204", gut="#7a5200", cur="#ffcc4d",
   comment="#7a5200", string="#ffd27a", keyword="#ff8c00", type="#ffcc4d", number="#ff9e3d", func="#ffc14d", pre="#ff8c00", const="#ff9e3d", err="#ff5a3d", warn="#ffd27a", special="#ffb000", op="#cc8a00")),
]

import sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from aether.themegen import scheme_xml

def gen(name, sid, dark, c):
    return scheme_xml(sid, name, c)

os.makedirs(OUT, exist_ok=True)
for name, sid, dark, c in P:
    open(os.path.join(OUT, sid + ".xml"), "w").write(gen(name, sid, dark, c))
    print("theme", sid)
