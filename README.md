# cpu temp rise mode - Adaptador Linux

![versão](https://img.shields.io/badge/versão-1.2-ffb547) ![licença](https://img.shields.io/badge/licença-MIT-2b5c8a) ![python](https://img.shields.io/badge/python-3.6%2B-1b2531) ![dependências](https://img.shields.io/badge/dependências-zero-2f7d4f)

🌐 **Site com passo a passo para iniciantes:** https://SEU-SITE.netlify.app

Driver não oficial para Linux do **display digital do Rise Mode Air Cooler Temp 6** (e outros coolers Rise Mode com o mesmo display — USB `1A2C:4984`).

O software oficial ("CPU TEMP Monitor") só existe para Windows. Sem ele, o display do cooler fica apagado ou parado no Linux. Este projeto reimplementa o protocolo em **um único script Python, sem dependências**, que roda como serviço do sistema e mostra no display:

- 🌡️ **Temperatura da CPU** em °C ou °F
- ⚡ **Consumo da CPU em Watts** ou 📊 **uso da CPU em %**

> ⚠️ Projeto independente, feito por engenharia reversa para interoperabilidade. **Não é afiliado, endossado ou suportado pela Rise Mode.** Use por sua conta e risco.

---

## Sumário

1. [Compatibilidade](#compatibilidade)
2. [Requisitos](#requisitos)
3. [Instalação rápida](#instalação-rápida)
4. [Instalação passo a passo](#instalação-passo-a-passo)
5. [Atualização](#atualização)
6. [Uso no dia a dia](#uso-no-dia-a-dia)
7. [Configuração](#configuração)
8. [Comandos do script](#comandos-do-script)
9. [Solução de problemas](#solução-de-problemas)
10. [Desinstalação](#desinstalação)
11. [Como funciona (protocolo)](#como-funciona-protocolo)
12. [Arquivos do projeto](#arquivos-do-projeto)
13. [Contribuindo](#contribuindo)
14. [Versões](#versões)

---

## Compatibilidade

| Item | Status |
|---|---|
| Rise Mode Air Cooler Temp 6 (Black) | ✅ Testado |
| Outros coolers Rise Mode com display `1A2C:4984` | 🟡 Deve funcionar (mesmo software oficial) |
| CPU Intel (sensor `coretemp`) | ✅ Testado |
| CPU AMD Ryzen (sensor `k10temp` / `zenpower`) | 🟡 Suportado, não testado ainda |
| Zorin OS 17 | ✅ Testado |
| Ubuntu, Linux Mint, Pop!_OS, Debian, Fedora, Arch… | 🟡 Deve funcionar (qualquer distro com systemd) |

Testou em outro hardware ou distro? [Abra uma issue](../../issues) contando o resultado.

**Como saber se o seu cooler é compatível:** com ele conectado, rode

```bash
lsusb | grep -i 1a2c:4984
```

Se aparecer uma linha, o display usa este protocolo.

---

## Requisitos

- Linux com **systemd** (praticamente todas as distros atuais)
- **Python 3.6+** (já vem instalado em quase todas as distros)
- Cooler conectado em um **header USB interno** da placa-mãe (o cabo USB 9 pinos que acompanha o cooler)

Não precisa instalar nenhuma biblioteca. O script fala direto com o kernel via `/dev/hidraw` e lê os sensores em `/sys`.

---

## Instalação rápida

1. Baixe o `risemode-cooler-linux.tar.gz` na [página de releases](../../releases) ou no site.
2. Abra o terminal (`Ctrl+Alt+T`) e cole:

```bash
cd ~ && rm -rf risemode-cooler-linux && tar xzf "$(find ~ -maxdepth 3 -name 'risemode-cooler-linux*.tar.gz' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)" && cd risemode-cooler-linux && sudo ./install.sh
```

3. Digite sua senha quando pedir (ela não aparece enquanto você digita, é normal).

Pronto. O display passa a mostrar a temperatura em poucos segundos, e o serviço liga sozinho toda vez que o PC iniciar. Pode fechar o terminal.

O comando acha o arquivo baixado mais recente em qualquer pasta (`Downloads`, `Transferências`…), extrai e instala.

---

## Instalação passo a passo

Para quem prefere fazer manualmente ou quer conferir cada etapa.

### 1. Extraia

```bash
cd ~/Downloads        # ou ~/Transferências, dependendo do idioma do sistema
tar xzf risemode-cooler-linux.tar.gz
cd risemode-cooler-linux
```

### 2. Verifique se o cooler e o sensor foram encontrados

```bash
sudo python3 risemode-cooler.py --info
```

Saída esperada (os números de `hidraw` e `hwmon` mudam de PC para PC):

```
Dispositivo HID : /dev/hidraw5
Sensor de temp  : /sys/class/hwmon/hwmon1/temp1_input
RAPL (potencia) : /sys/class/powercap/intel-rapl:0/energy_uj
Firmware        : 0x...
```

### 3. Teste o display (opcional)

```bash
sudo python3 risemode-cooler.py --test 42 65
```

O display deve mostrar **42** e **65**. O comando fica rodando até você apertar `Ctrl+C`. Ele não travou.

### 4. Instale o serviço

```bash
sudo ./install.sh
```

O instalador:

- copia o script para `/usr/local/bin/risemode-cooler`
- cria uma regra udev (`/etc/udev/rules.d/99-risemode-cooler.rules`) que libera o acesso ao cooler
- cria o arquivo de configuração `/etc/default/risemode-cooler` (se ainda não existir)
- registra, ativa e (re)inicia o serviço systemd `risemode-cooler`

Se aparecer `Active: active (running)`, está funcionando.

---

## Atualização

Baixe o arquivo novo e rode **o mesmo comando da instalação rápida**. Sua configuração em `/etc/default/risemode-cooler` é mantida e o serviço é reiniciado automaticamente.

Para conferir a versão instalada:

```bash
grep -m1 Versao /usr/local/bin/risemode-cooler
```

---

## Uso no dia a dia

**Você não precisa fazer nada.** Depois de instalado:

- o serviço inicia sozinho no boot, em segundo plano
- não precisa deixar terminal aberto
- se o cooler for desconectado e reconectado, ele reconecta sozinho em ~3 segundos
- se o chip do display travar e parar de aceitar dados, ele reinicia o USB do cooler sozinho, e o display volta em poucos segundos (v1.1+)

Comandos úteis:

```bash
systemctl status risemode-cooler           # ver se está rodando
journalctl -u risemode-cooler -n 20        # ver os últimos logs
sudo systemctl restart risemode-cooler     # reiniciar (após mudar a config)
sudo systemctl stop risemode-cooler        # parar temporariamente
sudo systemctl disable --now risemode-cooler  # parar e não iniciar mais no boot
```

---

## Configuração

Edite o arquivo de configuração:

```bash
sudo nano /etc/default/risemode-cooler
```

```bash
# Unidade da temperatura: C ou F
RM_UNIT=C
# Segundo valor no display: W (potência) ou % (uso da CPU)
RM_MODE=W
# Intervalo de atualização em segundos
RM_INTERVAL=1
# (opcional) forçar sensor de temperatura
# RM_SENSOR=/sys/class/hwmon/hwmon1/temp1_input
```

Salve (`Ctrl+O`, `Enter`, `Ctrl+X`) e aplique:

```bash
sudo systemctl restart risemode-cooler
```

| Opção | Valores | Padrão | O que faz |
|---|---|---|---|
| `RM_UNIT` | `C`, `F` | `C` | Temperatura em Celsius ou Fahrenheit (acende o ícone correspondente no display) |
| `RM_MODE` | `W`, `%` | `W` | Mostra a potência da CPU em Watts ou o uso em porcentagem |
| `RM_INTERVAL` | número | `1` | Segundos entre cada atualização |
| `RM_SENSOR` | caminho | automático | Força um sensor de temperatura específico |
| `RM_DEVICE` | `/dev/hidrawN` | automático | Força um dispositivo específico |

> **Sobre o modo W:** a potência é lida via RAPL (`/sys/class/powercap`), disponível em CPUs Intel e AMD Zen. Se sua CPU não suportar, o script muda automaticamente para `%` e avisa no log.

---

## Comandos do script

O script também pode ser usado manualmente (útil para testes e diagnóstico):

```bash
sudo risemode-cooler [opções]
# ou, de dentro da pasta extraída:
sudo python3 risemode-cooler.py [opções]
```

| Opção | Descrição |
|---|---|
| `--info` | Mostra o dispositivo, o sensor, o RAPL e a versão do firmware, e sai |
| `--test TEMP VALOR` | Envia valores fixos para testar o display (ex.: `--test 42 65`) |
| `--dry-run` | Lê os sensores e mostra os pacotes, mas não envia nada ao cooler |
| `-v`, `--verbose` | Mostra cada leitura enviada |
| `--unit C\|F` | Unidade da temperatura |
| `--mode W\|%` | Potência ou uso da CPU |
| `--interval N` | Intervalo em segundos |
| `--device /dev/hidrawN` | Força um dispositivo específico |
| `--sensor CAMINHO` | Força um sensor de temperatura específico |

Antes de rodar manualmente, pare o serviço para os dois não brigarem pelo display:

```bash
sudo systemctl stop risemode-cooler
sudo risemode-cooler -v
```

---

## Solução de problemas

### O display apagou ou congelou depois de um tempo

O chip do display às vezes trava e passa a recusar os dados (no log aparece `Broken pipe`). O adaptador detecta isso, faz um reset USB do cooler e volta a enviar sozinho. Na **v1.2** isso acontece já na primeira falha, e o display fica parado só uns 2 a 4 segundos. No log aparece:

```
[recuperacao] cooler travado, reset USB em /dev/bus/usb/001/007
[ok] cooler voltou a responder apos reset em /dev/hidraw5
```

Se você está numa versão mais antiga, [atualize](#atualização). Para destravar na hora:

```bash
sudo usbreset 1a2c:4984 && sudo systemctl restart risemode-cooler
```

### `Arquivo ou diretório inexistente` ao extrair

O arquivo não está onde o comando procurou. Confira se o download terminou (o nome termina em `.tar.gz`) e use o comando da [instalação rápida](#instalação-rápida), que procura em todas as pastas.

### `Dispositivo HID : NAO ENCONTRADO`

- Confira se o cooler aparece no USB: `lsusb | grep -i 1a2c`
- Verifique se o cabo USB do cooler está bem encaixado no header USB 2.0 da placa-mãe
- Alguns headers USB ficam desligados na BIOS — confira as opções de USB

### `Permission denied: '/dev/hidrawN'`

Normal se rodar sem `sudo` antes de instalar. A regra udev do `install.sh` resolve. Se instalou e o erro continua, desconecte e reconecte o cooler (ou reinicie o PC) e rode:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### `RAPL indisponivel ... Usando modo %`

- Se rodou sem `sudo`: normal. A leitura de energia exige root, e o serviço já roda como root.
- Se aparece mesmo no serviço: sua CPU ou kernel não expõe RAPL. Use `RM_MODE=%`.

### A temperatura no display não bate com a da CPU

Veja qual sensor foi escolhido e quais existem:

```bash
sudo risemode-cooler --info
sensors
```

O certo é `coretemp` → `Package id 0` (Intel) ou `k10temp` → `Tctl` (AMD). Se o script pegou outro (por exemplo, do SSD `nvme`), force o correto. Descubra o caminho:

```bash
for f in /sys/class/hwmon/hwmon*/temp*_label; do echo "$f: $(cat $f)"; done
```

E adicione ao `/etc/default/risemode-cooler` (trocando pelo seu caminho, com `_input` no lugar de `_label`):

```bash
RM_SENSOR=/sys/class/hwmon/hwmon1/temp1_input
```

E reinicie: `sudo systemctl restart risemode-cooler`.

> Atenção: a numeração `hwmonN` pode mudar entre reinicializações em alguns PCs. Só force o sensor se a detecção automática errar.

### Display apagado ou com números estranhos

1. Pare o serviço: `sudo systemctl stop risemode-cooler`
2. Teste: `sudo risemode-cooler --test 42 65 -v`
3. Se o teste não aparecer no display, abra uma issue com a saída de `--info` e de `lsusb -v -d 1a2c:4984`

### Ver erros do serviço

```bash
journalctl -u risemode-cooler -b --no-pager
```

---

## Desinstalação

De dentro da pasta extraída:

```bash
sudo ./uninstall.sh
```

Isso remove o script, o serviço, a regra udev e o arquivo de configuração.

---

## Como funciona (protocolo)

Descoberto por engenharia reversa do `DeviceDriver.exe` do software oficial "CPU TEMP Monitor".

- **Dispositivo:** USB HID, VID `0x1A2C`, PID `0x4984`, interface com usage page `0xFF01`
- **Transporte:** *feature report* HID (`HidD_SetFeature` no Windows, `HIDIOCSFEATURE` no Linux)
- **Frequência:** 1 pacote por segundo
- **Pacote:** 64 bytes, report ID `0x07`, valores enviados **dígito a dígito**

| Byte | Conteúdo |
|---|---|
| 0 | `0x07` (report ID) |
| 1 | temperatura — centena |
| 2 | temperatura — dezena |
| 3 | temperatura — unidade |
| 4 | flags: bit 0 = °F, bit 4 (`0x10`) = modo % (desligado = W) |
| 5 | W ou % — centena |
| 6 | W ou % — dezena |
| 7 | W ou % — unidade |
| 8–63 | `0x00` |

Exemplo: 47 °C e 65 W → `07 00 04 07 00 00 06 05 00 …`

Consulta de firmware: envia `07 FD 00 …` e lê o report 7 (bytes 1–2 = versão).

O software oficial usa o LibreHardwareMonitor para ler temperatura, potência e uso. Aqui isso vem direto do kernel:

| Dado | Fonte no Linux |
|---|---|
| Temperatura | `/sys/class/hwmon` (`coretemp`, `k10temp`, `zenpower`) |
| Potência | `/sys/class/powercap/*rapl*` (energia do pacote ÷ tempo) |
| Uso | `/proc/stat` |

---

## Arquivos do projeto

```
risemode-cooler-linux/
├── risemode-cooler.py         # o driver (Python puro, sem dependências)
├── risemode-cooler.service    # unidade systemd
├── 99-risemode-cooler.rules   # regra udev de permissão
├── install.sh                 # instalador
├── uninstall.sh               # desinstalador
├── LICENSE                    # MIT
├── CHANGELOG.md               # histórico de versões
├── README.md                  # este manual
└── tests/                     # testes automáticos (rodam sem o cooler)
```

---

## Contribuindo

Contribuições são bem-vindas, principalmente:

- testes em **CPUs AMD** e em outras distros
- outros modelos Rise Mode com display
- suporte à temperatura da **GPU** (o software oficial tem os ícones, mas o protocolo de GPU ainda não foi mapeado)

Para rodar os testes (não precisa do cooler):

```bash
python3 -m unittest discover -s tests -v
```

Ao abrir uma issue, inclua a saída de:

```bash
sudo risemode-cooler --info
lsusb | grep -i 1a2c
sensors
uname -r && cat /etc/os-release | head -2
```

---

## Versões

Veja o [CHANGELOG](CHANGELOG.md). Resumo:

- **1.2:** o display volta em 2 a 4 s quando trava (reset USB já na primeira falha e reabertura rápida).
- **1.1:** recuperação automática quando o display trava (reset USB), logs mais limpos, instalador reinicia o serviço ao atualizar, opções `RM_SENSOR` e `RM_DEVICE`.
- **1.0:** primeira versão.

---

## Licença

MIT. Rise Mode é marca de seus respectivos donos. Este projeto não distribui nenhum arquivo do software oficial.
