# Changelog

## 2.0 (2026-10-12)

- **Painel gráfico** (`risemode-cooler-panel`, no menu como "Rise Mode Cooler"). Mostra a temperatura e o consumo com dígitos de 7 segmentos iguais aos do display, e tem seletores °C/°F e W/%. A mudança chega ao cooler em 1 a 2 s, sem reiniciar o serviço. Funciona com GTK 4 ou GTK 3 e segue o tema claro ou escuro do sistema.
- **Status para o painel:** o daemon grava `/run/risemode-cooler/status.json` a cada segundo, de forma atômica. Estados: `ok`, `recovering`, `not_found`, `error`.
- **Nova configuração** em `/etc/risemode-cooler/config.json`, relida a cada segundo. Prioridade: linha de comando > `config.json` > `RM_*` > padrão. As variáveis `RM_*` da 1.x continuam funcionando.
- **Helper `set-config`** (`/usr/local/lib/risemode-cooler/`), chamado pelo painel via `pkexec`, com policy polkit `auth_admin_keep`. Aceita só `unit`, `mode` e `interval` (1 a 10).
- O instalador migra `RM_UNIT`, `RM_MODE` e `RM_INTERVAL` para o `config.json` na primeira vez. O painel só é instalado se o PyGObject existir. Sem ele, o daemon funciona igual.
- Novas opções: `--config`, `--status-file`, `--version`. O `--info` mostra a versão e a configuração em uso.
- Trocar W/% mostra um valor certo na hora, porque uso e potência são lidos a cada ciclo.
- Corrigido: o `-v` e o `--dry-run` usavam `bytes.hex(sep)`, que só existe no Python 3.8+.

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
