"""All window CSS lives here: one function, driven by the theme colours + user settings."""
from gi.repository import Gdk

UI_FONT = "Inter, Cantarell, Noto Sans, sans-serif"
RADII = {"sharp": 3, "soft": 10, "round": 16}
DENSITY = {"compact": (2, 28, 12), "comfortable": (4, 32, 13), "spacious": (7, 38, 14)}   # row pad, tab height, ui font px


def lum(hexcolor):
    c = Gdk.RGBA()
    c.parse(hexcolor)
    return 0.2126 * c.red + 0.7152 * c.green + 0.0722 * c.blue


def mix(a, b, t):
    ca, cb = Gdk.RGBA(), Gdk.RGBA()
    ca.parse(a)
    cb.parse(b)
    return "#%02x%02x%02x" % tuple(int((x * (1 - t) + y * t) * 255) for x, y in
                                   ((ca.red, cb.red), (ca.green, cb.green), (ca.blue, cb.blue)))


def rgba(hexcolor, a):
    c = Gdk.RGBA()
    c.parse(hexcolor)
    return "rgba(%d,%d,%d,%.2f)" % (int(c.red * 255), int(c.green * 255), int(c.blue * 255), a)


def families(font):
    names = [f.strip().strip("'\"") for f in font.split(",") if f.strip()]
    return ", ".join('"%s"' % n if n.lower() not in ("monospace", "sans-serif", "serif") else n for n in names)


def palette(bg, fg, dark, accent_hint, s):
    op = max(0.35, min(1.0, float(s["opacity"])))
    backdrop = mix(bg, "#000000", 0.44 if dark else 0.075)
    p = dict(
        bg=bg, fg=fg, dark=dark, op=op,
        backdrop=backdrop,
        side=mix(bg, "#000000", 0.15 if dark else 0.03),
        gut=mix(bg, fg, 0.52),
        border=mix(bg, fg, 0.06),
        hover=mix(bg, fg, 0.07),
        sel=mix(bg, fg, 0.14),
        accent=s["accent"] or accent_hint,
    )
    p["on_accent"] = "#101014" if lum(p["accent"]) > 0.45 else "#ffffff"
    return p


def build_css(p, s):
    radius = RADII.get(s["corner_style"], 10)
    inner = max(3, radius - 4)
    rowpad, tabh, uipx = DENSITY.get(s["density"], DENSITY["comfortable"])
    op = p["op"]
    bd = rgba(p["backdrop"], op)
    isl = rgba(p["bg"], op)
    side = rgba(p["side"], op)
    lay = s["layout"]
    ir, gap, bodypad, shadow = radius, 8, "0 8px 2px 8px", "none"
    if lay == "classic":
        ir, gap, bodypad = 0, 1, "0"
    elif lay == "flat":
        ir, gap, bodypad = 0, 1, "0"
        bd = isl
    elif lay == "floating":
        ir, gap, bodypad, shadow = radius + 4, 14, "2px 14px 6px 14px", "0 6px 22px rgba(0,0,0,0.32)"
    sepbg = "transparent" if lay in ("islands", "floating") else (p["border"] if lay == "classic" else "transparent")
    a, fg, gut, border, hover, sel, bg = p["accent"], p["fg"], p["gut"], p["border"], p["hover"], p["sel"], p["bg"]
    ts = s["tab_style"]
    if ts == "pill":
        tabcss = (f"notebook > header.top > tabs > tab {{{{ min-height: {tabh - 8}px; padding: 0 12px; margin: 2px 3px 4px 0; border: none; border-radius: {inner + 4}px; background: transparent; color: {gut}; box-shadow: none; outline: none; }}}}\n"
                  f"notebook > header.top > tabs > tab:hover {{{{ background: {hover}; color: {fg}; }}}}\n"
                  f"notebook > header.top > tabs > tab:checked {{{{ background: {rgba(a, 0.20)}; color: {fg}; box-shadow: none; }}}}")
    elif ts == "box":
        tabcss = (f"notebook > header.top > tabs > tab {{{{ min-height: {tabh - 6}px; padding: 0 14px; margin: 0; border: none; border-radius: 0; background: transparent; color: {gut}; box-shadow: none; outline: none; }}}}\n"
                  f"notebook > header.top > tabs > tab:hover {{{{ background: {hover}; color: {fg}; }}}}\n"
                  f"notebook > header.top > tabs > tab:checked {{{{ background: {sel}; color: {fg}; box-shadow: inset 0 2px {a}; }}}}")
    else:
        tabcss = (f"notebook > header.top > tabs > tab {{{{ min-height: {tabh - 6}px; padding: 0 12px; margin: 0 2px 0 0; border: none; border-radius: {inner + 2}px {inner + 2}px 0 0; background: transparent; color: {gut}; box-shadow: none; outline: none; }}}}\n"
                  f"notebook > header.top > tabs > tab:hover {{{{ background: {hover}; color: {fg}; }}}}\n"
                  f"notebook > header.top > tabs > tab:checked {{{{ background: {hover}; color: {fg}; box-shadow: inset 0 -2px {a}; }}}}")
    tabcss = tabcss.replace("{{", "{").replace("}}", "}")
    if lay == "classic":
        statuscss = f".aether-status {{ background: {a}; color: {p['on_accent']}; }} .aether-status label {{ color: {p['on_accent']}; }} .aether-chip {{ background: rgba(0,0,0,0.18); color: {p['on_accent']}; }}"
        headcss = f"headerbar {{ background: {p['side']}; }}"
    else:
        statuscss = headcss = ""
    return f"""
window, .background {{ background: {bd}; color: {fg}; font-family: {families(s['ui_font'])}; font-size: {uipx}px; }}
headerbar {{ background: {bd}; color: {fg}; border: none; box-shadow: none; min-height: 44px; padding: 0 8px; }}
headerbar button {{ background: transparent; color: {gut}; border: none; box-shadow: none; border-radius: {inner}px; min-height: 28px; padding: 0 10px; }}
headerbar button:hover {{ background: {hover}; color: {fg}; }}
headerbar button.aether-run {{ background: {rgba(a, 0.16)}; color: {a}; font-weight: 600; padding: 0 14px; margin-left: 6px; }}
headerbar button.aether-run:hover {{ background: {rgba(a, 0.28)}; }}
headerbar button.aether-pill {{ background: {hover}; color: {gut}; border-radius: {radius + 6}px; min-width: 320px; padding: 0 14px; min-height: 30px; }}
headerbar button.aether-pill:hover {{ background: {sel}; color: {fg}; }}
.aether-key {{ background: transparent; color: {gut}; border-radius: {inner}px; padding: 0 7px; font-size: 11px; }}
.aether-body {{ background: {bd}; padding: {bodypad}; }}
.aether-island {{ background: {isl}; border: none; border-radius: {ir}px; box-shadow: {shadow}; }}
.aether-island.side {{ background: {side}; }}
paned > separator, paned > separator.wide {{ background: {sepbg}; min-width: {gap}px; min-height: {gap}px; border: none; box-shadow: none; }}
.aether-switch {{ margin: 10px 10px 6px 10px; }}
.aether-switch button {{ background: transparent; color: {gut}; border: none; box-shadow: none; border-radius: {inner}px; padding: 3px 12px; min-height: 22px; font-weight: 600; }}
.aether-switch button:hover {{ background: {hover}; color: {fg}; }}
.aether-switch button:checked {{ background: {sel}; color: {fg}; }}
.aether-proj {{ font-weight: 700; font-size: {uipx + 1}px; padding: 8px 14px 4px 14px; }}
.aether-hint {{ color: {gut}; font-size: 12px; padding: 4px 14px; }}
.aether-island.side treeview, .aether-island.side treeview.view, .aether-island.side list, .aether-island.side row, .aether-island.side scrolledwindow, .aether-island.side viewport, .aether-bottom scrolledwindow, .aether-bottom viewport {{ background: transparent; color: {fg}; }}
.aether-island.side treeview.view {{ padding: 2px 6px; background-color: transparent; background-image: none; }}
.aether-island.side treeview.view:not(:selected):not(:hover) {{ background-color: transparent; }}
.aether-island.side treeview {{ background-color: transparent; }}
.aether-island.side treeview.view:hover {{ background: {hover}; }}
.aether-island.side treeview.view:selected {{ background: {rgba(a, 0.20)}; color: {fg}; }}
.aether-island.side entry, .aether-island.side textview, .aether-island.side textview text {{ background: {rgba(p['backdrop'], 0.55)}; color: {fg}; border: 1px solid {border}; border-radius: {inner}px; min-height: 24px; box-shadow: none; padding: 0 6px; }}
.aether-island.side entry:focus-within, .aether-island.side textview:focus-within {{ border-color: {a}; }}
.aether-island.side button.flat, .aether-island.side .tool {{ background: transparent; color: {gut}; border: none; box-shadow: none; border-radius: {inner}px; min-height: 22px; min-width: 22px; padding: 0 6px; }}
.aether-island.side button.flat:hover, .aether-island.side .tool:hover {{ background: {hover}; color: {fg}; }}
.aether-island.side button.tool:checked {{ background: {rgba(a, 0.25)}; color: {fg}; }}
.aether-island.side button.primary {{ background: {a}; color: {p['on_accent']}; border-radius: {inner}px; border: none; font-weight: 700; min-height: 26px; }}
.aether-island.side row {{ padding: {rowpad}px 8px; border-radius: {inner}px; margin: 0 6px; }}
.aether-island.side row:hover {{ background: {hover}; }}
.aether-island.side row:selected {{ background: {rgba(a, 0.20)}; }}
.aether-island.side .file-head {{ font-weight: 700; padding-top: {rowpad + 4}px; color: {fg}; }}
.aether-island.side .match {{ font-family: {families(s['font'])}; font-size: 12px; color: {gut}; }}
.aether-island.side .badge {{ font-weight: 700; font-size: 11px; min-width: 14px; }}
.aether-crumb {{ background: transparent; color: {gut}; font-size: 12px; padding: 7px 18px 3px 18px; }}
.aether-bottom, .aether-bottom textview, .aether-bottom list, .aether-bottom row, .aether-bottom text {{ background: transparent; color: {fg}; }}
.aether-bottom row {{ padding: {rowpad}px 8px; border-radius: {inner}px; margin: 0 6px; }}
.aether-bottom row:hover, .aether-bottom row:selected {{ background: {hover}; }}
.aether-bottom button {{ background: transparent; border: none; box-shadow: none; color: {gut}; min-height: 22px; min-width: 22px; }}
.aether-bottom button:hover {{ color: {fg}; background: {hover}; }}
.aether-status {{ background: transparent; color: {gut}; font-size: 12px; padding: 0 14px; min-height: 28px; }}
.aether-status label {{ margin: 0 2px; }}
.aether-chip {{ background: {rgba(a, 0.18)}; color: {a}; font-weight: 700; padding: 0 10px; border-radius: {inner}px; margin: 4px 8px 4px 0; min-height: 18px; }}
.aether-welcome {{ background: transparent; color: {fg}; }}
.aether-welcome .title {{ font-size: 44px; font-weight: 800; letter-spacing: -1.5px; }}
.aether-welcome .sub {{ color: {gut}; font-size: 15px; }}
.aether-welcome .section {{ color: {fg}; font-size: 14px; font-weight: 700; margin-bottom: 6px; }}
.aether-welcome .dim-label {{ color: {gut}; }}
.aether-welcome button.link {{ text-decoration: none; color: {a}; padding: 3px 0; font-size: 14px; }}
.aether-welcome button.link:hover {{ color: {fg}; }}
.aether-editor {{ background: transparent; }}
.aether-map {{ opacity: 0.5; }}
.aether-map:hover {{ opacity: 0.9; }}
notebook > header {{ background: transparent; border: none; padding: 6px 8px 0 8px; margin: 0; min-height: 0; box-shadow: none; }}
{tabcss}
notebook > header.top > tabs > tab button {{ min-width: 18px; min-height: 18px; padding: 0; border-radius: {inner}px; opacity: 0; background: transparent; }}
notebook > header.top > tabs > tab:hover button, notebook > header.top > tabs > tab:checked button {{ opacity: 0.8; }}
notebook > header.top > tabs > tab button:hover {{ background: {sel}; opacity: 1; }}
notebook > stack {{ background: transparent; }}
scrollbar {{ background: transparent; }}
scrollbar slider {{ min-width: 7px; min-height: 7px; border-radius: 4px; background: {rgba(gut, 0.35)}; border: 2px solid transparent; }}
scrollbar slider:hover {{ background: {rgba(gut, 0.7)}; }}
.aether-palette {{ background: {p['side']}; color: {fg}; border: 1px solid {border}; border-radius: {radius + 2}px; box-shadow: 0 16px 48px rgba(0,0,0,0.5); }}
.aether-palette entry {{ background: {bg}; color: {fg}; border: 1px solid {border}; border-radius: {radius - 2}px; padding: 8px 12px; font-size: 15px; min-height: 22px; box-shadow: none; }}
.aether-palette entry:focus-within {{ border-color: {a}; }}
.aether-palette list, .aether-palette row {{ background: transparent; color: {fg}; }}
.aether-palette row {{ border-radius: {inner}px; margin: 1px 0; }}
.aether-palette row:selected {{ background: {rgba(a, 0.22)}; }}
.aether-palette .dim-label {{ color: {gut}; font-size: 12px; }}
searchbar > revealer > box {{ background: transparent; border: none; }}
searchbar entry, searchbar button {{ border-radius: {inner}px; }}
popover > contents {{ border-radius: {radius - 2}px; }}
.aether-prefs {{ background: {p['side']}; color: {fg}; }}
.aether-prefs .heading {{ font-weight: 700; font-size: {uipx + 3}px; margin: 4px 0 8px 0; }}
{statuscss}
{headcss}
headerbar button.aether-pill.plain {{ background: transparent; min-width: 0; font-weight: 600; }}
.aether-prefs .group {{ background: {isl}; border: 1px solid {border}; border-radius: {radius}px; padding: 4px 14px; }}
.aether-prefs .swatch {{ border-radius: {radius - 2}px; border: 2px solid transparent; padding: 2px; }}
.aether-prefs .swatch.current {{ border-color: {a}; }}
.aether-prefs .dim-label {{ color: {gut}; }}
.aether-prefs stacksidebar row {{ border-radius: {inner}px; margin: 1px 6px; padding: 6px 10px; }}
.aether-prefs stacksidebar row:selected {{ background: {rgba(a, 0.22)}; color: {fg}; }}
""" + ide_css(p, s, a, fg, gut, border, hover, sel, bg, inner, radius, uipx, rowpad, side, ir, gap)


def ide_css(p, s, a, fg, gut, border, hover, sel, bg, inner, radius, uipx, rowpad, side="", ir=8, gap=8):
    """Styles for the v3 IDE widgets: welcome cards, debugger, build panel, outline."""
    card = rgba(mix(bg, fg, 0.04), 1)
    return f"""
.aether-switch {{ margin: 10px 6px 6px 6px; }}
.aether-switch button {{ padding: 3px 7px; font-size: {uipx - 1}px; }}
.aether-section {{ color: {gut}; font-size: 10.5px; font-weight: 700; letter-spacing: 1.2px; padding: 10px 14px 4px 14px; }}
.aether-welcome .aether-section {{ padding: 0 0 4px 0; }}
.aether-version {{ color: {gut}; font-size: 13px; font-weight: 600; margin-bottom: 9px; }}
button.aether-action {{ background: {card}; border: 1px solid {border}; border-radius: {radius}px; padding: 14px 16px; box-shadow: none; min-width: 150px; }}
button.aether-action:hover {{ background: {hover}; border-color: {rgba(a, 0.55)}; }}
.aether-action-icon {{ color: {a}; font-size: 20px; font-weight: 700; }}
.aether-action-title {{ font-weight: 700; font-size: {uipx + 1}px; color: {fg}; }}
.aether-action-desc {{ color: {gut}; font-size: 12px; }}
button.aether-card {{ background: {card}; border: 1px solid {border}; border-radius: {radius}px; padding: 10px 14px; box-shadow: none; }}
button.aether-card:hover {{ background: {hover}; border-color: {rgba(a, 0.55)}; }}
.aether-card-title {{ font-weight: 700; color: {fg}; }}
.aether-card-meta {{ color: {gut}; font-size: 12px; }}
.aether-welcome .aether-chip {{ margin: 0; font-size: 11px; }}
.aether-island.side button.aether-dbg-btn {{ font-size: 15px; min-width: 28px; min-height: 28px; padding: 0 4px; }}
.aether-island.side button.aether-dbg-go {{ color: #9ece6a; }}
.aether-island.side button.aether-dbg-stop {{ color: #f7768e; }}
.aether-island.side button.aether-dbg-btn:disabled {{ opacity: 0.35; }}
.aether-island.side .aether-dbg-list, .aether-island.side .aether-dbg-tree {{ background: transparent; font-size: 12.5px; }}
.aether-island.side .aether-dbg-list row {{ padding: 2px 8px; }}
.aether-island.side button.aether-link-small {{ font-size: 11px; color: {gut}; margin-right: 8px; }}
.aether-bp-dot {{ color: #f7768e; }}
.aether-island.side .aether-outline row {{ padding: {max(1, rowpad - 1)}px 8px; font-size: 13px; }}
.aether-build-head {{ padding: 4px 12px; color: {gut}; font-size: 12px; }}
.aether-bottom entry.aether-dbg-entry {{ background: {rgba(p['backdrop'], 0.5)}; color: {fg}; border: none; border-top: 1px solid {border}; border-radius: 0; font-family: {families(s['font'])}; min-height: 28px; }}
.aether-status button.aether-status-btn {{ background: transparent; color: {gut}; border: none; box-shadow: none; min-height: 20px; padding: 0 6px; font-size: 12px; }}
.aether-status button.aether-status-btn:hover {{ color: {fg}; background: {hover}; }}
.aether-prefs list.group row:selected {{ background: {rgba(a, 0.22)}; color: {fg}; }}
.aether-prefs list.group row:selected label {{ color: {fg}; }}
.aether-prefs button.suggested-action {{ background: {a}; color: {p['on_accent']}; border: none; }}
.aether-prefs .error {{ color: #f7768e; }}
@keyframes aether-glow {{ 0% {{ text-shadow: 0 0 14px {rgba(a, 0.18)}; }} 50% {{ text-shadow: 0 0 30px {rgba(a, 0.55)}; }} 100% {{ text-shadow: 0 0 14px {rgba(a, 0.18)}; }} }}
@keyframes aether-pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.25; }} 100% {{ opacity: 1; }} }}
.aether-welcome .title {{ animation: aether-glow 4.5s ease-in-out infinite; }}
.aether-welcome image {{ -gtk-icon-shadow: 0 0 26px {rgba(a, 0.45)}; }}
.aether-tip {{ color: {fg}; font-size: 13px; padding: 9px 14px; border-radius: {radius}px; background: {rgba(a, 0.07)}; border: 1px solid {rgba(a, 0.18)}; }}
headerbar button.aether-run {{ box-shadow: 0 0 0 1px {rgba(a, 0.35)}, 0 0 16px {rgba(a, 0.22)}; }}
headerbar button.aether-run:hover {{ box-shadow: 0 0 0 1px {rgba(a, 0.6)}, 0 0 22px {rgba(a, 0.4)}; }}
.aether-activity {{ color: {a}; font-weight: 600; font-size: 12px; margin: 0 6px; }}
.aether-activity .dot {{ color: {a}; animation: aether-pulse 1.1s ease-in-out infinite; }}
.aether-toast {{ background: {p['side']}; color: {fg}; border: 1px solid {border}; border-left: 3px solid {a}; border-radius: {radius}px; padding: 10px 16px 10px 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.45); font-weight: 600; }}
.aether-toast .icon {{ color: {a}; font-size: 15px; font-weight: 800; }}
.aether-toast.ok {{ border-left-color: #9ece6a; }} .aether-toast.ok .icon {{ color: #9ece6a; }}
.aether-toast.bad {{ border-left-color: #f7768e; }} .aether-toast.bad .icon {{ color: #f7768e; }}
.aether-island.side .aether-switch button:checked {{ box-shadow: inset 0 -2px {a}; }}
notebook > header.top > tabs > tab:checked {{ color: {fg}; }}
.aether-activity-bar {{ background: {side}; border-radius: {ir}px; padding: 6px 0; margin-right: {gap}px; min-width: 50px; }}
button.aether-act {{ background: transparent; border: none; box-shadow: none; border-radius: 0; min-height: 46px; min-width: 50px; padding: 0; color: {rgba(fg, 0.42)}; border-left: 2px solid transparent; }}
button.aether-act:hover {{ color: {rgba(fg, 0.85)}; }}
button.aether-act.active {{ color: {fg}; border-left-color: {a}; }}
button.aether-act.running {{ color: {a}; }}
button.aether-act.running .aether-icon {{ animation: aether-pulse 1.3s ease-in-out infinite; }}
.aether-act-badge {{ background: {a}; color: {p['on_accent']}; font-size: 9px; font-weight: 800; border-radius: 9px; min-width: 15px; min-height: 15px; padding: 0 3px; margin: 0 -4px -3px 0; }}
headerbar button.aether-tool {{ color: {fg}; padding: 0 10px; }}
headerbar button.aether-tool:hover {{ background: {hover}; }}
headerbar button.aether-stop {{ color: #f7768e; }}
headerbar button.aether-stop:disabled {{ color: {rgba(gut, 0.35)}; }}
headerbar dropdown.aether-config > button {{ background: {hover}; color: {fg}; border-radius: {inner}px; font-weight: 600; min-height: 28px; padding: 0 8px 0 12px; }}
.aether-status.debugging {{ background: {a}; }}
.aether-status.debugging label, .aether-status.debugging button {{ color: {p['on_accent']}; }}
.aether-status.debugging .aether-activity .dot {{ color: {p['on_accent']}; }}
.aether-status.debugging .aether-chip {{ background: rgba(0,0,0,0.2); color: {p['on_accent']}; }}
notebook.aether-bottom > header.top > tabs > tab {{ font-size: {uipx - 1}px; letter-spacing: 0.4px; }}
"""
