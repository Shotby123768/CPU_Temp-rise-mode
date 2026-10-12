#!/bin/bash
[ "$EUID" -eq 0 ] || exec sudo "$0" "$@"
systemctl disable --now risemode-cooler 2>/dev/null
rm -f /usr/local/bin/risemode-cooler /etc/systemd/system/risemode-cooler.service \
      /etc/udev/rules.d/99-risemode-cooler.rules /etc/default/risemode-cooler \
      /usr/local/bin/risemode-cooler-panel \
      /usr/share/applications/risemode-cooler-panel.desktop \
      /usr/share/icons/hicolor/scalable/apps/risemode-cooler.svg \
      /usr/share/polkit-1/actions/com.github.risemode-cooler.policy
rm -rf /usr/local/lib/risemode-cooler /etc/risemode-cooler /run/risemode-cooler
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null
update-desktop-database -q /usr/share/applications 2>/dev/null
systemctl daemon-reload; udevadm control --reload-rules
echo "Removido."
