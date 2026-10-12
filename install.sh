#!/bin/bash
set -e
[ "$EUID" -eq 0 ] || exec sudo "$0" "$@"
cd "$(dirname "$0")"
install -m 755 risemode-cooler.py /usr/local/bin/risemode-cooler
install -m 644 99-risemode-cooler.rules /etc/udev/rules.d/
install -m 644 risemode-cooler.service /etc/systemd/system/
[ -f /etc/default/risemode-cooler ] || cat > /etc/default/risemode-cooler <<CFG
# Unidade da temperatura: C ou F
RM_UNIT=C
# Segundo valor no display: W (potencia) ou % (uso da CPU)
RM_MODE=W
RM_INTERVAL=1
# Opcional: forcar sensor de temperatura
# RM_SENSOR=/sys/class/hwmon/hwmon1/temp1_input
CFG
udevadm control --reload-rules && udevadm trigger
systemctl daemon-reload
systemctl enable risemode-cooler
systemctl restart risemode-cooler
echo
echo "Instalado. Status:"
systemctl --no-pager status risemode-cooler | head -n 8
echo
echo "Config: /etc/default/risemode-cooler  (depois: sudo systemctl restart risemode-cooler)"
