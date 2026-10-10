"""Toast notifications: small cards that slide up in the bottom-right corner and fade out."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango

ICONS = {"ok": "✓", "error": "✗", "info": "●", "debug": "◆", "warn": "!"}


class Toaster:
    def __init__(self, overlay):
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                           halign=Gtk.Align.END, valign=Gtk.Align.END)
        self.box.set_margin_end(22)
        self.box.set_margin_bottom(44)
        self.box.set_can_target(True)
        overlay.add_overlay(self.box)
        overlay.set_clip_overlay(self.box, False)
        self.live = []

    def show(self, text, kind="info", ms=3800, action=None):
        """action: optional (label, callback) shown as a button on the toast."""
        rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=220)
        card = Gtk.Box(spacing=10)
        card.add_css_class("aether-toast")
        card.add_css_class(f"aether-toast-{kind}")
        ic = Gtk.Label(label=ICONS.get(kind, "●"))
        ic.add_css_class("aether-toast-icon")
        card.append(ic)
        lbl = Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=48)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        card.append(lbl)
        if action:
            b = Gtk.Button(label=action[0])
            b.add_css_class("aether-toast-btn")
            b.connect("clicked", lambda *_: (action[1](), self._close(rev)))
            card.append(b)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self._close(rev))
        card.add_controller(click)
        rev.set_child(card)
        self.box.append(rev)
        self.live.append(rev)
        while len(self.live) > 4:
            self._close(self.live[0])
        GLib.idle_add(lambda: (rev.set_reveal_child(True), False)[1])
        GLib.timeout_add(ms, lambda: (self._close(rev), False)[1])

    def _close(self, rev):
        if rev not in self.live:
            return
        self.live.remove(rev)
        rev.set_reveal_child(False)
        GLib.timeout_add(260, lambda: (rev.get_parent() is self.box and self.box.remove(rev), False)[1])
