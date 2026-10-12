#!/usr/bin/python3
"""
Painel grafico do cpu temp rise mode - Adaptador Linux (versao 2.0).

Roda como usuario comum. Le /run/risemode-cooler/status.json (gravado pelo
daemon a cada segundo) e, para mudar a configuracao, chama o helper
/usr/local/lib/risemode-cooler/set-config via pkexec.

Depende so de PyGObject: GTK 4, ou GTK 3 se o 4 nao existir.
"""
import argparse
import json
import math
import os
import shutil
import sys
import time

import gi

try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    GTK4 = True
except ValueError:
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    GTK4 = False
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

APP_ID = "io.github.risemode_cooler.Panel"
STATUS_PATH = "/run/risemode-cooler/status.json"
HELPER = "/usr/local/lib/risemode-cooler/set-config"
STALE_AFTER = 5.0      # s sem atualizar o status.json = servico parado
APPLY_TIMEOUT = 10.0   # s esperando o daemon aplicar uma mudanca salva
FLASH_SECONDS = 6.0

AMBER = (1.0, 0xB5 / 255, 0x47 / 255)
SEG_OFF = (0x22 / 255, 0x2B / 255, 0x35 / 255)

MSG = {
    "ok": "Conectado ao cooler",
    "dry": "Modo de teste: nada é enviado ao cooler",
    "recovering": "Display travou, recuperando…",
    "not_found": "Cooler não encontrado. Confira o cabo USB interno.",
    "error": "Problema na comunicação com o cooler. Tentando de novo…",
    "stopped": "Serviço parado",
    "saving": "Salvando…",
    "restarting": "Reiniciando o serviço…",
}

CSS = """
.rm-unit {
  background-image: linear-gradient(180deg, #2a333d, #171e26);
  border-radius: 22px;
  padding: 16px;
}
.rm-screen {
  background-color: #10171f;
  border-radius: 12px;
  padding: 20px 18px 16px 18px;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.05), inset 0 10px 30px rgba(0,0,0,0.6);
}
.rm-suffix { color: #ffb547; font-weight: 600; font-size: 18px; }
.rm-pill {
  background-color: #0b1015;
  border-radius: 999px;
  padding: 4px;
  box-shadow: inset 0 0 0 1px #2b3540;
}
.rm-pill button {
  background: none;
  border: none;
  box-shadow: none;
  text-shadow: none;
  -gtk-icon-shadow: none;
  outline-color: #ffb547;
  color: #8a96a3;
  border-radius: 999px;
  min-height: 0;
  padding: 7px 0;
  font-weight: 600;
}
.rm-pill button:hover { color: #e3e8ee; }
.rm-pill button:checked { background-color: #ffb547; color: #1b1206; }
.rm-pill button:disabled { opacity: 0.55; }
.rm-status { font-size: 15px; }
"""

# ---------------------------------------------------------------- 7 segmentos (Cairo)
# Mesma geometria do site e do icone: cada digito num quadro de 36x50.
SEGS = {
    "a": [(7, 2), (29, 2), (25, 6), (11, 6)],
    "b": [(30, 3), (26, 7), (26, 20), (30, 23)],
    "c": [(30, 27), (26, 30), (26, 43), (30, 47)],
    "d": [(7, 48), (29, 48), (25, 44), (11, 44)],
    "e": [(6, 27), (10, 30), (10, 43), (6, 47)],
    "f": [(6, 3), (10, 7), (10, 20), (6, 23)],
    "g": [(8, 25), (11, 22.5), (25, 22.5), (28, 25), (25, 27.5), (11, 27.5)],
}
DIGIT_MAP = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
    "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", " ": "",
}
DIGIT_W, DIGIT_H, DIGIT_GAP = 36, 50, 4
ICON_W, ICON_GAP = 22, 6
ROW_W = ICON_W + ICON_GAP + 3 * DIGIT_W + 2 * DIGIT_GAP
ROW_H = DIGIT_H


def _poly(cr, pts):
    cr.move_to(*pts[0])
    for p in pts[1:]:
        cr.line_to(*p)
    cr.close_path()


def draw_digit(cr, ch):
    lit = DIGIT_MAP.get(ch, "")
    for name, pts in SEGS.items():
        if name in lit:
            # brilho leve em volta do segmento aceso
            _poly(cr, pts)
            cr.set_source_rgba(*AMBER, 0.28)
            cr.set_line_width(2.6)
            cr.stroke()
            _poly(cr, pts)
            cr.set_source_rgb(*AMBER)
        else:
            _poly(cr, pts)
            cr.set_source_rgb(*SEG_OFF)
        cr.fill()


def draw_thermometer(cr):
    # viewBox 22x30, mesmo desenho do site
    cr.set_line_width(1.8)
    cr.new_path()
    cr.arc(11, 4, 3, math.pi, 2 * math.pi)
    cr.line_to(14, 17.5)
    cy = 17.5 + math.sqrt(5.5 ** 2 - 3 ** 2)
    cr.arc(11, cy, 5.5, math.atan2(17.5 - cy, 3), math.atan2(17.5 - cy, -3) + 2 * math.pi)
    cr.close_path()
    cr.stroke()
    cr.arc(11, 22.5, 2.4, 0, 2 * math.pi)
    cr.fill()
    cr.move_to(11, 20)
    cr.line_to(11, 9)
    cr.stroke()


def draw_chip(cr):
    cr.set_line_width(1.8)
    x, y, w, h, r = 4, 8, 14, 14, 2
    cr.new_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()
    cr.stroke()
    cr.rectangle(8, 12, 6, 6)
    cr.fill()
    for x1, y1, x2, y2 in ((8, 5, 8, 8), (14, 5, 14, 8), (8, 22, 8, 25), (14, 22, 14, 25),
                           (1, 12, 4, 12), (1, 18, 4, 18), (18, 12, 21, 12), (18, 18, 21, 18)):
        cr.move_to(x1, y1)
        cr.line_to(x2, y2)
    cr.stroke()


class Readout:
    """Icone + 3 digitos de 7 segmentos, desenhados com Cairo numa DrawingArea."""

    def __init__(self, icon):
        self.icon = icon
        self.text = "---"
        self.area = Gtk.DrawingArea()
        if GTK4:
            self.area.set_content_width(ROW_W)
            self.area.set_content_height(ROW_H)
            self.area.set_draw_func(lambda a, cr, w, h: self.draw(cr, w, h))
        else:
            self.area.set_size_request(ROW_W, ROW_H)
            self.area.connect("draw", lambda a, cr: self.draw(
                cr, a.get_allocated_width(), a.get_allocated_height()))
        self.area.set_valign(Gtk.Align.END)

    def set_text(self, text):
        text = text.rjust(3)[-3:]
        if text != self.text:
            self.text = text
            self.area.queue_draw()

    def draw(self, cr, w, h):
        s = min(w / ROW_W, h / ROW_H)
        cr.scale(s, s)
        cr.save()
        cr.translate(0, ROW_H - 30)  # icone alinhado embaixo, como no display
        cr.set_source_rgba(*AMBER, 0.95)
        self.icon(cr)
        cr.restore()
        x = ICON_W + ICON_GAP
        for ch in self.text:
            cr.save()
            cr.translate(x, 0)
            draw_digit(cr, ch)
            cr.restore()
            x += DIGIT_W + DIGIT_GAP
        return False


def fmt3(v):
    if v is None:
        return "---"
    return str(max(0, min(999, int(v))))


# ---------------------------------------------------------------- GTK 3/4

def add_class(widget, name):
    if GTK4:
        widget.add_css_class(name)
    else:
        widget.get_style_context().add_class(name)


def append(box, child, expand=False):
    if GTK4:
        if expand:
            child.set_hexpand(True)
        box.append(child)
    else:
        box.pack_start(child, expand, expand, 0)


def load_css():
    prov = Gtk.CssProvider()
    if hasattr(prov, "load_from_string"):  # GTK >= 4.12
        prov.load_from_string(CSS)
    elif GTK4:
        prov.load_from_data(CSS, -1)
    else:
        prov.load_from_data(CSS.encode())
    prio = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    if GTK4:
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, prio)
    else:
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, prio)


def follow_system_dark_mode():
    """GTK sem libadwaita nao segue sozinho o 'modo escuro' do GNOME/Zorin."""
    try:
        src = Gio.SettingsSchemaSource.get_default()
        schema = src.lookup("org.gnome.desktop.interface", True) if src else None
        if not schema or not schema.has_key("color-scheme"):
            return
        gs = Gio.Settings.new("org.gnome.desktop.interface")
    except GLib.Error:
        return

    def apply(*_):
        Gtk.Settings.get_default().set_property(
            "gtk-application-prefer-dark-theme", gs.get_string("color-scheme") == "prefer-dark")

    gs.connect("changed::color-scheme", apply)
    apply()
    follow_system_dark_mode.settings = gs  # mantem a referencia viva


class Pill:
    """Seletor tipo pilula com duas opcoes (ex: °C | °F)."""

    def __init__(self, key, options, on_pick):
        self.key = key
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.box.set_homogeneous(True)
        add_class(self.box, "rm-pill")
        self.buttons = {}
        self.syncing = False
        self.on_pick = on_pick
        for value, label in options:
            b = Gtk.ToggleButton(label=label)
            b.set_can_focus(True)
            b.connect("toggled", self._toggled, value)
            append(self.box, b, expand=True)
            self.buttons[value] = b

    def _toggled(self, btn, value):
        if self.syncing:
            return
        # comporta como radio: so uma opcao marcada, e clicar na atual nao desmarca
        self.set(value)
        if btn.get_active():
            self.on_pick(self.key, value)

    def set(self, value):
        self.syncing = True
        for v, b in self.buttons.items():
            b.set_active(v == value)
        self.syncing = False

    def set_sensitive(self, on):
        self.box.set_sensitive(on)


# ---------------------------------------------------------------- Janela

class Panel:
    def __init__(self, app, status_path):
        self.status_path = status_path
        self.status = None
        self.pending = None          # mudanca sendo salva/aplicada
        self.flash = None            # (texto, ate quando)
        self.busy_restart = False

        win = Gtk.ApplicationWindow(application=app, title="Rise Mode Cooler")
        win.set_resizable(False)
        win.set_icon_name("risemode-cooler")
        self.win = win

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for side in ("start", "end", "top", "bottom"):
            getattr(outer, "set_margin_" + side)(18)

        unit = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        add_class(unit, "rm-unit")
        screen = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        add_class(screen, "rm-screen")

        readouts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        readouts.set_homogeneous(True)
        self.temp = Readout(draw_thermometer)
        self.value = Readout(draw_chip)
        self.temp_suffix = Gtk.Label(label="°C")
        self.value_suffix = Gtk.Label(label="W")
        for ro, suffix in ((self.temp, self.temp_suffix), (self.value, self.value_suffix)):
            cell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            add_class(suffix, "rm-suffix")
            suffix.set_valign(Gtk.Align.END)
            suffix.set_width_chars(2)
            suffix.set_xalign(0)
            append(cell, ro.area)
            append(cell, suffix)
            append(readouts, cell)
        append(screen, readouts)

        pills = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        pills.set_homogeneous(True)
        self.pills = {
            "unit": Pill("unit", (("C", "°C"), ("F", "°F")), self.pick),
            "mode": Pill("mode", (("W", "W"), ("%", "%")), self.pick),
        }
        self.pills["unit"].box.set_tooltip_text("Unidade da temperatura no display")
        self.pills["mode"].box.set_tooltip_text("Consumo da CPU em watts (W) ou uso em porcentagem (%)")
        append(pills, self.pills["unit"].box)
        append(pills, self.pills["mode"].box)
        append(screen, pills)
        append(unit, screen)
        append(outer, unit)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.dot = Gtk.DrawingArea()
        self.dot_color = (0.5, 0.5, 0.5)
        if GTK4:
            self.dot.set_content_width(10)
            self.dot.set_content_height(10)
            self.dot.set_draw_func(lambda a, cr, w, h: self._draw_dot(cr, w, h))
        else:
            self.dot.set_size_request(10, 10)
            self.dot.connect("draw", lambda a, cr: self._draw_dot(
                cr, a.get_allocated_width(), a.get_allocated_height()))
        self.dot.set_valign(Gtk.Align.CENTER)
        self.status_label = Gtk.Label(label="")
        add_class(self.status_label, "rm-status")
        self.status_label.set_xalign(0)
        if GTK4:
            self.status_label.set_wrap(True)
        else:
            self.status_label.set_line_wrap(True)
        self.status_label.set_max_width_chars(40)
        append(status_row, self.dot)
        append(status_row, self.status_label, expand=True)
        self.restart_btn = Gtk.Button(label="Reiniciar serviço")
        self.restart_btn.set_tooltip_text("Use se o display parou e não voltou sozinho")
        self.restart_btn.connect("clicked", self.restart_service)
        self.restart_btn.set_valign(Gtk.Align.CENTER)
        append(status_row, self.restart_btn)
        append(outer, status_row)

        if GTK4:
            win.set_child(outer)
        else:
            win.add(outer)

        self.refresh()
        GLib.timeout_add_seconds(1, self.refresh)

    def _draw_dot(self, cr, w, h):
        cr.arc(w / 2, h / 2, min(w, h) / 2, 0, 2 * math.pi)
        cr.set_source_rgb(*self.dot_color)
        cr.fill()
        return False

    def present(self):
        if not GTK4:
            self.win.show_all()
        self.win.present()

    # --- leitura do status

    def read_status(self):
        try:
            with open(self.status_path) as f:
                st = json.load(f)
        except (OSError, ValueError):
            return None
        if not isinstance(st, dict) or not isinstance(st.get("updated"), (int, float)):
            return None
        if time.time() - st["updated"] > STALE_AFTER:
            return None
        return st

    def refresh(self):
        st = self.status = self.read_status()
        now = time.monotonic()

        if self.pending and self.pending["saved"]:
            p = self.pending
            if st is None:
                self.pending = None  # ficou salvo; o servico aplica quando voltar
            elif st.get(p["key"]) == p["value"]:
                self.pending = None
            elif p["key"] == "mode" and p["value"] == "W" and st.get("rapl") is False:
                self.pending = None
                self.show_flash("Sua CPU não informa o consumo em watts. Mostrando o uso em %.")
            elif now - p["since"] > APPLY_TIMEOUT:
                self.pending = None
                self.show_flash("A mudança foi salva, mas o serviço não respondeu. "
                                "Tente “Reiniciar serviço”.")

        if st is None:
            self.temp.set_text("---")
            self.value.set_text("---")
        else:
            self.temp.set_text(fmt3(st.get("temp")))
            self.value.set_text(fmt3(st.get("value")))
            self.temp_suffix.set_label("°F" if st.get("unit") == "F" else "°C")
            self.value_suffix.set_label("%" if st.get("mode") == "%" else "W")
            if not self.pending:
                self.pills["unit"].set(st.get("unit"))
                self.pills["mode"].set(st.get("mode"))

        for pill in self.pills.values():
            pill.set_sensitive(self.pending is None and not self.busy_restart)
        self.update_status_line(st)
        return True

    def show_flash(self, text):
        self.flash = (text, time.monotonic() + FLASH_SECONDS)

    def update_status_line(self, st):
        green, amber, red, grey = (0.30, 0.75, 0.47), AMBER, (0.89, 0.36, 0.33), (0.55, 0.59, 0.64)
        if self.busy_restart:
            text, color = MSG["restarting"], amber
        elif self.pending:
            text, color = MSG["saving"], amber
        elif self.flash and time.monotonic() < self.flash[1]:
            text, color = self.flash[0], amber
        elif st is None:
            text, color = MSG["stopped"], grey
        else:
            state = st.get("state")
            if state == "ok":
                text, color = (MSG["ok"] if st.get("device") else MSG["dry"]), green
            elif state == "recovering":
                text, color = MSG["recovering"], amber
            elif state == "not_found":
                text, color = MSG["not_found"], red
            else:
                text, color = MSG["error"], red
        if self.status_label.get_label() != text:
            self.status_label.set_label(text)
        if color != self.dot_color:
            self.dot_color = color
            self.dot.queue_draw()

    # --- acoes

    def run_privileged(self, argv, done):
        pkexec = shutil.which("pkexec")
        if not pkexec:
            done(None, "O pkexec não está instalado. Instale o pacote policykit-1.")
            return
        try:
            proc = Gio.Subprocess.new([pkexec] + argv, Gio.SubprocessFlags.STDOUT_SILENCE
                                      | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as e:
            done(None, f"Não foi possível pedir a senha: {e.message}")
            return

        def finished(p, res):
            try:
                p.wait_finish(res)
                code = p.get_exit_status() if p.get_if_exited() else -1
            except GLib.Error:
                code = -1
            done(code, None)

        proc.wait_async(None, finished)

    def pick(self, key, value):
        st = self.status
        current = st.get(key) if st else None
        if self.pending or value == current:
            if not self.pending:
                self.pills[key].set(current)
            return
        if not os.path.exists(HELPER):
            self.pills[key].set(current)
            self.show_flash("O painel não foi instalado direito. Rode o install.sh de novo.")
            self.refresh()
            return
        self.pending = {"key": key, "value": value, "prev": current,
                        "saved": False, "since": time.monotonic()}
        self.refresh()

        def done(code, err):
            p = self.pending
            if code == 0:
                p["saved"] = True
                p["since"] = time.monotonic()
                # le o status mais vezes ate o daemon aplicar, para a resposta ser rapida
                GLib.timeout_add(250, lambda: self.refresh() and self.pending is p)
            else:
                self.pending = None
                self.pills[key].set(p["prev"])
                if err:
                    self.show_flash(err)
                elif code not in (126, 127):  # 126/127 = senha cancelada ou negada
                    self.show_flash("Não foi possível salvar a configuração.")
            self.refresh()

        self.run_privileged([HELPER, f"{key}={value}"], done)

    def restart_service(self, _btn):
        if self.busy_restart:
            return
        self.busy_restart = True
        self.restart_btn.set_sensitive(False)
        self.refresh()
        systemctl = shutil.which("systemctl") or "/usr/bin/systemctl"

        def done(code, err):
            self.busy_restart = False
            self.restart_btn.set_sensitive(True)
            if err:
                self.show_flash(err)
            elif code not in (0, 126, 127):
                self.show_flash("Não foi possível reiniciar o serviço.")
            self.refresh()

        self.run_privileged([systemctl, "restart", "risemode-cooler"], done)


# ---------------------------------------------------------------- Main

def save_screenshot(panel, path):
    """Grava um PNG do conteudo da janela (usado para o print do README)."""
    if not GTK4:
        print("--screenshot precisa de GTK 4", file=sys.stderr)
        return False
    w = panel.win.get_width()
    h = panel.win.get_height()
    paint = Gtk.WidgetPaintable.new(panel.win)
    snap = Gtk.Snapshot()
    paint.snapshot(snap, w, h)
    node = snap.to_node()
    tex = panel.win.get_renderer().render_texture(node, None)
    tex.save_to_png(path)
    return False


def main():
    ap = argparse.ArgumentParser(description="Painel do cpu temp rise mode")
    ap.add_argument("--status", default=STATUS_PATH, help=argparse.SUPPRESS)
    ap.add_argument("--screenshot", metavar="PNG", help=argparse.SUPPRESS)
    args = ap.parse_args()

    GLib.set_prgname(APP_ID)
    GLib.set_application_name("Rise Mode Cooler")
    flags = getattr(Gio.ApplicationFlags, "DEFAULT_FLAGS", Gio.ApplicationFlags.FLAGS_NONE)
    app = Gtk.Application(application_id=APP_ID, flags=flags)
    state = {}

    def activate(app):
        if "panel" in state:
            state["panel"].present()
            return
        load_css()
        follow_system_dark_mode()
        panel = state["panel"] = Panel(app, args.status)
        panel.present()
        if args.screenshot:
            def shoot():
                save_screenshot(panel, args.screenshot)
                app.quit()
                return False
            GLib.timeout_add(800, shoot)

    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
