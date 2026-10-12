#!/bin/bash
[ "$EUID" -eq 0 ] || exec sudo "$0" "$@"
systemctl disable --now risemode-cooler 2>/dev/null
rm -f /usr/local/bin/risemode-cooler /etc/systemd/system/risemode-cooler.service \
      /etc/udev/rules.d/99-risemode-cooler.rules /etc/default/risemode-cooler
systemctl daemon-reload; udevadm control --reload-rules
echo "Removido."
