# Changelog

## 1.1 (2026-10-12)

- **Recuperação automática:** o chip do display às vezes trava e passa a recusar os pacotes (`Broken pipe` / EPIPE). Depois de 3 falhas seguidas, o adaptador faz um reset USB do cooler (`USBDEVFS_RESET`) e volta a enviar. No máximo um reset a cada 30 s.
- Logs mais limpos: "Conectado" só aparece uma vez por conexão, erros repetidos são resumidos e existe a mensagem `[ok]` quando o cooler volta.
- `install.sh` agora reinicia o serviço, então rodar de novo atualiza na hora e mantém a configuração.
- Novas opções no `/etc/default/risemode-cooler`: `RM_SENSOR` e `RM_DEVICE`.

## 1.0 (2026-10-12)

- Primeira versão: temperatura da CPU (°C/°F) e potência (W) ou uso (%) no display do Rise Mode Air Cooler Temp 6 (`1A2C:4984`).
- Serviço systemd, regra udev, instalador e desinstalador.
