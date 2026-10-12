# Changelog

## 1.2 (2026-10-12)

- **Display volta mais rápido quando trava.** No `Broken pipe` (EPIPE), o reset USB agora acontece já na primeira falha, sem esperar 3. Depois do reset, o adaptador tenta reabrir o cooler a cada 0,5 s (por até 5 s) em vez de esperar um tempo fixo. O display fica parado por uns 2 a 4 s, contra ~12 s na 1.1.
- Os outros erros de travamento (`EPROTO`, `ETIMEDOUT`, `EIO`) continuam esperando 3 falhas seguidas. O limite de um reset a cada 30 s continua valendo.
- Erros na leitura do sensor de temperatura não disparam mais o reset USB.
- Testes automáticos da recuperação em `tests/` (rodam sem o cooler).

## 1.1 (2026-10-12)

- **Recuperação automática:** o chip do display às vezes trava e passa a recusar os pacotes (`Broken pipe` / EPIPE). Depois de 3 falhas seguidas, o adaptador faz um reset USB do cooler (`USBDEVFS_RESET`) e volta a enviar. No máximo um reset a cada 30 s.
- Logs mais limpos: "Conectado" só aparece uma vez por conexão, erros repetidos são resumidos e existe a mensagem `[ok]` quando o cooler volta.
- `install.sh` agora reinicia o serviço, então rodar de novo atualiza na hora e mantém a configuração.
- Novas opções no `/etc/default/risemode-cooler`: `RM_SENSOR` e `RM_DEVICE`.

## 1.0 (2026-10-12)

- Primeira versão: temperatura da CPU (°C/°F) e potência (W) ou uso (%) no display do Rise Mode Air Cooler Temp 6 (`1A2C:4984`).
- Serviço systemd, regra udev, instalador e desinstalador.
