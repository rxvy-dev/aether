import os

NAME = "Aether"
APP_ID = "io.github.aether.Editor"
VERSION = "3.0.0"
REPO = "rxvy-dev/aether"          # GitHub owner/name — publish.sh updates this


def data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(here, "..", "data"), os.path.join(here, "data"), "/usr/share/aether/data", "/usr/local/share/aether/data",
              os.path.join(os.path.expanduser("~/.local/share"), "aether", "data")):
        d = os.path.normpath(d)
        if os.path.isdir(os.path.join(d, "styles")):
            return d
    return os.path.normpath(os.path.join(here, "..", "data"))
