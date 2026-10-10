#!/usr/bin/env python3
"""Turn data/templates.json into GtkSourceView .snippets files (trigger 'main' + extras)."""
import json, os, re
D = os.path.join(os.path.dirname(__file__), "..", "data")
T = json.load(open(os.path.join(D, "templates.json")))
# template key -> GtkSourceView language ids
LANG = {"c":"c;chdr","cpp":"cpp;cpphdr","python":"python;python3","javascript":"js","typescript":"typescript","javascriptreact":"jsx",
 "typescriptreact":"typescript-jsx","rust":"rust","go":"go","java":"java","csharp":"c-sharp","kotlin":"kotlin","swift":"swift","dart":"dart",
 "scala":"scala","shellscript":"sh","lua":"lua","perl":"perl","ruby":"ruby","php":"php","haskell":"haskell","elixir":"elixir","r":"r","julia":"julia",
 "html":"html","css":"css","sql":"sql","makefile":"makefile","dockerfile":"docker","toml":"toml","yaml":"yaml","markdown":"markdown","json":"json"}
def number_final(text):
    if "${0:" not in text:
        return text
    nums = [int(n) for n in re.findall(r"\$\{(\d+):", text) if n != "0"]
    return text.replace("${0:", "${%d:" % (max(nums, default=0) + 1))
def fix(body):
    body = number_final(body)
    body = re.sub(r"\$\{TM_FILENAME_BASE/\(\.\*\)/\$\{1:/upcase\}/\}", "${TM_FILENAME_BASE}", body)
    body = body.replace("${TM_FILENAME_BASE:Main}", "$TM_FILENAME_BASE")
    return body
def block(trigger, desc, langs, body):
    return (f'  <snippet _name="{desc}" trigger="{trigger}" _description="{desc}">\n'
            f'    <text languages="{langs};"><![CDATA[{fix(body)}]]></text>\n  </snippet>\n')
out = ['<?xml version="1.0" encoding="UTF-8"?>\n<snippets _group="Aether">\n']
for k, v in T.items():
    if k not in LANG: continue
    out.append(block("main", f"{k}: starter (main)", LANG[k], v["main"].rstrip("\n")))
    for name, (prefix, body) in v.get("extras", {}).items():
        out.append(block(prefix, f"{k}: {name}", LANG[k], body))
# extra universal helpers
out.append('  <snippet _name="TODO comment" trigger="todo"><text><![CDATA[TODO: ${1:what}]]></text></snippet>\n')
out.append("</snippets>\n")
os.makedirs(os.path.join(D, "snippets"), exist_ok=True)
open(os.path.join(D, "snippets", "aether.snippets"), "w").write("".join(out))
print("snippets written")
