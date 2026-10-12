#!/bin/bash
set -e
[ "$EUID" -eq 0 ] || exec sudo "$0" "$@"
cd "$(dirname "$0")"

LIB=/usr/local/lib/risemode-cooler
CONF=/etc/risemode-cooler/config.json
DEFAULT=/etc/default/risemode-cooler

# --- daemon (igual a 1.x)
install -m 755 risemode-cooler.py /usr/local/bin/risemode-cooler
install -m 644 99-risemode-cooler.rules /etc/udev/rules.d/
install -m 644 risemode-cooler.service /etc/systemd/system/
[ -f "$DEFAULT" ] || cat > "$DEFAULT" <<CFG
# Unidade, modo e intervalo ficam em /etc/risemode-cooler/config.json
# (mude pelo painel "Rise Mode Cooler" no menu de aplicativos).
#
# Opcional: forcar sensor de temperatura
# RM_SENSOR=/sys/class/hwmon/hwmon1/temp1_input
# Opcional: forcar dispositivo
# RM_DEVICE=/dev/hidraw5
CFG

# --- helper de configuracao + permissao do polkit
install -d -m 755 "$LIB"
install -m 755 set-config "$LIB/set-config"
install -d -m 755 /usr/share/polkit-1/actions
install -m 644 data/com.github.risemode-cooler.policy /usr/share/polkit-1/actions/

# --- config.json: na primeira vez, traz as preferencias da 1.x (RM_UNIT, RM_MODE, RM_INTERVAL)
if [ ! -f "$CONF" ]; then
    "$LIB/set-config" >/dev/null
    rm_get() { sed -n "s/^[[:space:]]*$1=[\"']\?\([^\"' #]*\).*/\1/p" "$DEFAULT" 2>/dev/null | tail -n 1; }
    for pair in unit:RM_UNIT mode:RM_MODE interval:RM_INTERVAL; do
        key=${pair%%:*}; var=${pair#*:}
        val=$(rm_get "$var")
        [ "$key" != interval ] && val=$(echo "$val" | tr '[:lower:]' '[:upper:]')
        [ -n "$val" ] || continue
        if "$LIB/set-config" "$key=$val" >/dev/null 2>&1; then
            echo "Preferência mantida: $var=$val"
        else
            echo "Aviso: $var=$val não é aceito na 2.0 (usando o padrão)."
        fi
    done
    if [ -f "$DEFAULT" ] && ! grep -q "config.json" "$DEFAULT"; then
        sed -i "1i # Desde a 2.0, RM_UNIT, RM_MODE e RM_INTERVAL ficam em $CONF\n# (mude pelo painel). RM_SENSOR e RM_DEVICE continuam valendo aqui." "$DEFAULT"
    fi
fi

# --- painel grafico (so se o PyGObject existir; nada e instalado automaticamente)
PANEL=0
if python3 -c "
import gi
try:
    gi.require_version('Gtk', '4.0')
except ValueError:
    gi.require_version('Gtk', '3.0')
" 2>/dev/null; then
    install -m 755 risemode-cooler-panel.py /usr/local/bin/risemode-cooler-panel
    install -d -m 755 /usr/share/applications /usr/share/icons/hicolor/scalable/apps
    install -m 644 data/risemode-cooler-panel.desktop /usr/share/applications/
    install -m 644 data/risemode-cooler.svg /usr/share/icons/hicolor/scalable/apps/
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
    PANEL=1
fi

# --- servico
udevadm control --reload-rules && udevadm trigger
systemctl daemon-reload
systemctl enable risemode-cooler
systemctl restart risemode-cooler

echo
echo "Instalado. Status:"
systemctl --no-pager status risemode-cooler | head -n 8
echo
if [ "$PANEL" = 1 ]; then
    echo "Painel: procure \"Rise Mode Cooler\" no menu de aplicativos."
else
    echo "Painel não instalado: falta python3-gi (sudo apt install python3-gi gir1.2-gtk-4.0)"
    echo "O display funciona normalmente sem o painel."
fi
echo "Configuração: $CONF"
