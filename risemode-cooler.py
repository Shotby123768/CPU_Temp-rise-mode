#!/usr/bin/env python3
"""
Rise Mode Air Cooler Temp 6 (display digital) - driver para Linux.

Versao 2.0

Reimplementa o protocolo do "CPU TEMP Monitor" (DeviceDriver.exe) do Windows:
  - Dispositivo USB HID 1A2C:4984, interface com usage page 0xFF01
  - A cada 1s envia um feature report de 64 bytes (report ID 7):
      [0] 0x07
      [1] temperatura - centena
      [2] temperatura - dezena
      [3] temperatura - unidade
      [4] flags: bit0 = Fahrenheit, bit4 (0x10) = modo % (senao Watts)
      [5] valor (W ou %) - centena
      [6] valor - dezena
      [7] valor - unidade
      [8..63] 0

Sem dependencias: usa /dev/hidraw via ioctl e le sensores do /sys.

Desde a 2.0 conversa com o painel grafico por dois arquivos:
  - /run/risemode-cooler/status.json   (daemon -> painel, gravado a cada envio)
  - /etc/risemode-cooler/config.json   (painel -> daemon, relido sem restart)
"""
import argparse
import errno
import fcntl
import glob
import json
import os
import signal
import sys
import tempfile
import time

VERSION = "2.0"

VID = 0x1A2C
PID = 0x4984
REPORT_ID = 0x07
REPORT_LEN = 64  # bytes, incluindo o report ID


# ---------------------------------------------------------------- HID / hidraw

def _ioc(direction, type_, nr, size):
    return (direction << 30) | (size << 16) | (ord(type_) << 8) | nr


def HIDIOCSFEATURE(size):
    return _ioc(3, "H", 0x06, size)


def HIDIOCGFEATURE(size):
    return _ioc(3, "H", 0x07, size)


def find_hidraw():
    """Acha o /dev/hidrawN do cooler (preferindo a interface vendor 0xFF01)."""
    want = f"{VID:08X}:{PID:08X}"
    candidates = []
    for sysdir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sysdir, "device", "uevent")) as f:
                uevent = f.read().upper()
        except OSError:
            continue
        if want not in uevent:
            continue
        node = "/dev/" + os.path.basename(sysdir)
        vendor_page = False
        try:
            with open(os.path.join(sysdir, "device", "report_descriptor"), "rb") as f:
                desc = f.read()
            # Usage Page (Vendor 0xFF01) => 06 01 FF
            vendor_page = b"\x06\x01\xff" in desc
        except OSError:
            pass
        candidates.append((not vendor_page, node))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


USBDEVFS_RESET = 0x5514  # _IO('U', 20)


def usb_node_for(hidraw_path):
    """De /dev/hidrawN acha o /dev/bus/usb/BBB/DDD do dispositivo USB pai."""
    if not hidraw_path:
        return None
    p = os.path.realpath(f"/sys/class/hidraw/{os.path.basename(hidraw_path)}/device")
    while p and p != "/":
        try:
            bus = int(_read(os.path.join(p, "busnum")))
            dev = int(_read(os.path.join(p, "devnum")))
            return f"/dev/bus/usb/{bus:03d}/{dev:03d}"
        except (OSError, ValueError):
            p = os.path.dirname(p)
    return None


def usb_reset(node):
    fd = os.open(node, os.O_WRONLY)
    try:
        fcntl.ioctl(fd, USBDEVFS_RESET, 0)
    finally:
        os.close(fd)


# Erros que indicam firmware do display travado (so um reset USB resolve).
STALL_ERRNOS = (errno.EPIPE, errno.EPROTO, errno.ETIMEDOUT, errno.EIO)
RESET_MIN_GAP = 30.0   # segundos minimos entre dois resets USB
REOPEN_STEP = 0.5      # apos o reset, tenta reabrir a cada 0,5 s...
REOPEN_TIMEOUT = 5.0   # ...por ate 5 s


def should_reset(err, fails, since_last_reset):
    """Decide se vale resetar o USB agora.

    EPIPE (STALL do firmware) reseta ja na 1a falha; os outros erros de
    travamento esperam 3 falhas seguidas. Nunca mais de um reset a cada 30 s.
    """
    if not isinstance(err, OSError) or err.errno not in STALL_ERRNOS:
        return False
    if since_last_reset <= RESET_MIN_GAP:
        return False
    return fails >= (1 if err.errno == errno.EPIPE else 3)


def reopen_after_reset(device, pkt):
    """Depois do reset, reabre o hidraw e reenvia o pacote assim que der.

    O dispositivo some e reaparece em ~1-2 s, as vezes com outro numero de
    hidraw, por isso chama find_hidraw() a cada tentativa. Retorna o Cooler
    ja aberto (com o pacote enviado) ou None se nao voltou dentro do prazo.
    """
    deadline = time.monotonic() + REOPEN_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(REOPEN_STEP)
        path = device or find_hidraw()
        if not path:
            continue
        try:
            c = Cooler(path)
        except OSError:
            continue
        try:
            c.send_feature(pkt)
            return c
        except OSError:
            c.close()
    return None


class Cooler:
    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDWR)
        self.send_len = REPORT_LEN + 1  # igual ao Windows (65); cai p/ 64 se falhar

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    def send_feature(self, payload):
        buf = bytearray(payload[:REPORT_LEN].ljust(REPORT_LEN, b"\x00"))
        for size in (self.send_len, REPORT_LEN):
            data = bytearray(buf.ljust(size, b"\x00"))
            try:
                fcntl.ioctl(self.fd, HIDIOCSFEATURE(size), data)
                self.send_len = size
                return
            except OSError as e:
                last = e
        raise last

    def firmware_version(self):
        """Mesma consulta que o software oficial faz: envia 07 FD e le o report 7."""
        self.send_feature(bytes([REPORT_ID, 0xFD]))
        time.sleep(0.016)
        buf = bytearray(REPORT_LEN + 1)
        buf[0] = REPORT_ID
        fcntl.ioctl(self.fd, HIDIOCGFEATURE(len(buf)), buf)
        if buf[0] != REPORT_ID:
            return None
        return (buf[1] << 8) | buf[2]


def build_packet(temp, value, fahrenheit=False, percent=False):
    temp = max(0, min(999, int(temp)))
    value = max(0, min(999, int(value)))
    flags = (0x01 if fahrenheit else 0) | (0x10 if percent else 0)
    pkt = bytearray(REPORT_LEN)
    pkt[0] = REPORT_ID
    pkt[1], pkt[2], pkt[3] = temp // 100 % 10, temp // 10 % 10, temp % 10
    pkt[4] = flags
    pkt[5], pkt[6], pkt[7] = value // 100 % 10, value // 10 % 10, value % 10
    return bytes(pkt)


# ---------------------------------------------------------------- Sensores

def _read(path):
    with open(path) as f:
        return f.read().strip()


def find_cpu_temp_sensor():
    """Retorna o caminho do tempN_input mais adequado pra CPU."""
    prefs = [
        ("k10temp", ("Tctl", "Tdie")),     # AMD
        ("zenpower", ("Tdie", "Tctl")),    # AMD (modulo zenpower)
        ("coretemp", ("Package id 0",)),   # Intel
        ("cpu_thermal", ()),               # ARM / outros
    ]
    hwmons = {}
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            hwmons.setdefault(_read(os.path.join(d, "name")), []).append(d)
        except OSError:
            pass
    for name, labels in prefs:
        for d in hwmons.get(name, []):
            inputs = sorted(glob.glob(os.path.join(d, "temp*_input")))
            for lbl in labels:
                for inp in inputs:
                    lf = inp.replace("_input", "_label")
                    try:
                        if _read(lf) == lbl:
                            return inp
                    except OSError:
                        pass
            if inputs:
                return inputs[0]
    # fallback: thermal zones
    for z in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            if _read(os.path.join(z, "type")) in ("x86_pkg_temp", "cpu-thermal", "acpitz"):
                return os.path.join(z, "temp")
        except OSError:
            pass
    return None


class CpuUsage:
    def __init__(self):
        self.prev = self._snap()

    @staticmethod
    def _snap():
        with open("/proc/stat") as f:
            vals = [int(x) for x in f.readline().split()[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return idle, sum(vals)

    def read(self):
        idle, total = self._snap()
        pidle, ptotal = self.prev
        self.prev = (idle, total)
        dt = total - ptotal
        if dt <= 0:
            return 0.0
        return 100.0 * (1.0 - (idle - pidle) / dt)


class CpuPower:
    """Potencia do pacote da CPU via RAPL (Intel e AMD Zen). Precisa de root."""

    def __init__(self):
        self.path = None
        self.max_range = None
        for d in sorted(glob.glob("/sys/class/powercap/*rapl*:[0-9]")):
            try:
                if _read(os.path.join(d, "name")).startswith("package"):
                    _read(os.path.join(d, "energy_uj"))  # testa permissao
                    self.path = os.path.join(d, "energy_uj")
                    try:
                        self.max_range = int(_read(os.path.join(d, "max_energy_range_uj")))
                    except OSError:
                        pass
                    break
            except OSError:
                continue
        self.prev = self._snap() if self.path else None

    @property
    def available(self):
        return self.path is not None

    def _snap(self):
        return int(_read(self.path)), time.monotonic()

    def read(self):
        if not self.path:
            return None
        e, t = self._snap()
        pe, pt = self.prev
        self.prev = (e, t)
        de = e - pe
        if de < 0 and self.max_range:
            de += self.max_range
        dt = t - pt
        if dt <= 0 or de < 0:
            return 0.0
        return de / dt / 1e6


# ---------------------------------------------------------------- Configuracao e status

CONFIG_PATH = "/etc/risemode-cooler/config.json"
STATUS_PATH = "/run/risemode-cooler/status.json"
DEFAULTS = {"unit": "C", "mode": "W", "interval": 1.0}


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def read_config_json(path):
    """Le o config.json do painel. Retorna so as chaves validas ({} se nao existir).

    Mesmas regras do helper set-config: unit C/F, mode W/%, interval de 1 a 10.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        _log(f"[config] ignorando {path}: {e}")
        return {}
    if not isinstance(data, dict):
        _log(f"[config] ignorando {path}: formato invalido")
        return {}
    out = {}
    if data.get("unit") in ("C", "F"):
        out["unit"] = data["unit"]
    if data.get("mode") in ("W", "%"):
        out["mode"] = data["mode"]
    iv = data.get("interval")
    if isinstance(iv, (int, float)) and not isinstance(iv, bool) and 1 <= iv <= 10:
        out["interval"] = float(iv)
    bad = sorted(k for k in data if k not in out)
    if bad:
        _log(f"[config] valores invalidos ignorados em {path}: {', '.join(bad)}")
    return out


def env_settings(environ):
    """Variaveis RM_* do /etc/default/risemode-cooler (formato da 1.x)."""
    out = {}
    unit = environ.get("RM_UNIT", "").strip().upper()
    if unit in ("C", "F"):
        out["unit"] = unit
    mode = environ.get("RM_MODE", "").strip().upper()
    if mode in ("W", "%"):
        out["mode"] = mode
    try:
        iv = float(environ["RM_INTERVAL"])
        if iv > 0:
            out["interval"] = iv
    except (KeyError, ValueError):
        pass
    return out


def resolve_settings(cli, from_json, from_env):
    """Prioridade: linha de comando > config.json > RM_* > padrao."""
    out = dict(DEFAULTS)
    for src in (from_env, from_json, cli):
        out.update({k: v for k, v in src.items() if v is not None})
    return out


class StatusFile:
    """Grava o status.json de forma atomica (temporario + os.replace)."""

    def __init__(self, path):
        self.path = path
        self.warned = False

    def write(self, data):
        if not self.path:
            return
        d = os.path.dirname(self.path) or "."
        try:
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
                os.chmod(d, 0o755)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".status-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f)
                os.chmod(tmp, 0o644)
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            self.warned = False
        except OSError as e:
            if not self.warned:
                _log(f"[status] nao consegui gravar {self.path}: {e}")
                self.warned = True


def classify_error(err):
    """Estado do status.json para um erro de envio/leitura."""
    if isinstance(err, OSError):
        if err.errno in STALL_ERRNOS:
            return "recovering"
        if isinstance(err, FileNotFoundError) or err.errno in (errno.ENOENT, errno.ENODEV):
            return "not_found"
    return "error"


# ---------------------------------------------------------------- Daemon

class Daemon:
    def __init__(self, args, sensor, power, usage):
        self.args = args
        self.sensor = sensor
        self.power = power
        self.usage = usage
        self.status = StatusFile(args.status_file)
        self.cli = {"unit": args.unit, "mode": args.mode, "interval": args.interval}
        self.env = env_settings(os.environ)
        self.config_sig = None
        self.rapl_warned = False
        self.cooler = None
        self.fails = 0           # falhas seguidas de envio
        self.last_reset = 0.0    # momento do ultimo reset USB
        self.resets = 0
        self.connected_msg = False
        self.running = True
        self.state = "ok"
        self.last_error = None
        self.reading = (None, None)
        self.last_publish = 0.0
        self.reload_config(force=True)

    # --- configuracao

    def _config_signature(self):
        try:
            st = os.stat(self.args.config)
            return (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return None

    def reload_config(self, force=False):
        """Rele o config.json se ele mudou. Retorna True se algo foi recarregado."""
        sig = self._config_signature()
        if not force and sig == self.config_sig:
            return False
        self.config_sig = sig
        from_json = read_config_json(self.args.config) if sig else {}
        s = resolve_settings(self.cli, from_json, self.env)
        self.fahrenheit = s["unit"] == "F"
        self.percent = s["mode"] == "%"
        if not self.percent and not self.power.available:
            if not self.rapl_warned:
                _log("[aviso] RAPL indisponivel (rode como root ou sem suporte). Usando modo %.")
                self.rapl_warned = True
            self.percent = True
        self.interval = s["interval"]
        if not force:
            print(f"[config] unidade={'F' if self.fahrenheit else 'C'} "
                  f"modo={'%' if self.percent else 'W'} intervalo={self.interval:g}s", flush=True)
        return True

    # --- status para o painel

    def publish(self):
        t, v = self.reading
        self.status.write({
            "version": VERSION,
            "state": self.state,
            "device": self.cooler.path if self.cooler else None,
            "temp": round(t, 1) if t is not None else None,
            "unit": "F" if self.fahrenheit else "C",
            "value": round(v, 1) if v is not None else None,
            "mode": "%" if self.percent else "W",
            "rapl": self.power.available,
            "last_error": self.last_error,
            "resets": self.resets,
            "updated": time.time(),
        })
        self.last_publish = time.monotonic()

    # --- loop

    def read_values(self):
        # Le uso e potencia todo ciclo, assim trocar W/% mostra um valor certo na hora.
        use = self.usage.read()
        pw = self.power.read() if self.power.available else None
        if self.args.test:
            return self.args.test
        t = int(_read(self.sensor)) / 1000.0
        if self.fahrenheit:
            t = t * 1.8 + 32
        return t, (use if self.percent else (pw or 0.0))

    def step(self):
        """Le os sensores e envia um pacote. Retorna True se o display recebeu."""
        args = self.args
        pkt = None  # so fica preenchido se o erro vier do envio ao cooler
        try:
            t, val = self.read_values()
            self.reading = (t, val)
            pkt = build_packet(t, val, self.fahrenheit, self.percent)
            if args.verbose or args.dry_run:
                unit = "F" if self.fahrenheit else "C"
                print(f"temp={t:.1f}{unit}  {'uso' if self.percent else 'pot'}={val:.1f}"
                      f"{'%' if self.percent else 'W'}  pkt={' '.join(f'{b:02x}' for b in pkt[:8])}", flush=True)

            if not args.dry_run:
                if self.cooler is None:
                    path = args.device or find_hidraw()
                    if not path:
                        raise FileNotFoundError(errno.ENOENT, "cooler 1A2C:4984 nao conectado")
                    self.cooler = Cooler(path)
                    if not self.connected_msg:
                        print(f"Conectado em {path}", flush=True)
                        self.connected_msg = True
                self.cooler.send_feature(pkt)
                if self.fails:
                    print(f"[ok] cooler voltou a responder apos {self.fails} falha(s)", flush=True)
                self.fails = 0
            self.state, self.last_error = "ok", None
            self.publish()
            return True
        except (OSError, ValueError) as e:
            return self.handle_error(e, pkt)

    def handle_error(self, e, pkt):
        args = self.args
        self.fails += 1
        if self.fails <= 3 or self.fails % 20 == 0:
            _log(f"[erro] {e} (falha {self.fails}) - tentando de novo")
        dev_for_reset = self.cooler.path if self.cooler else None
        if self.cooler:
            self.cooler.close()
            self.cooler = None
        self.connected_msg = False
        self.state = classify_error(e) if pkt is not None else "error"
        self.last_error = str(e)
        self.publish()
        # O firmware do display as vezes trava e passa a recusar os
        # pacotes (EPIPE/EPROTO). Um reset USB destrava sem desligar o PC.
        if (pkt is not None and not args.dry_run
                and should_reset(e, self.fails, time.monotonic() - self.last_reset)):
            self.last_reset = time.monotonic()
            node = usb_node_for(dev_for_reset or args.device or find_hidraw())
            if node:
                try:
                    usb_reset(node)
                    self.resets += 1
                    _log(f"[recuperacao] cooler travado, reset USB em {node}")
                    self.cooler = reopen_after_reset(args.device, pkt)
                except OSError as re_err:
                    _log(f"[recuperacao] falhou o reset USB ({re_err})")
            if self.cooler:
                print(f"[ok] cooler voltou a responder apos reset em {self.cooler.path}",
                      flush=True)
                self.connected_msg = True
                self.fails = 0
                self.state, self.last_error = "ok", None
                self.publish()
                return True
        return False

    def wait(self, seconds):
        """Espera em passos de ate 1 s, aplicando mudancas do config.json na hora
        e mantendo o 'updated' do status.json fresco para o painel."""
        end = time.monotonic() + seconds
        while self.running:
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(1.0, left))
            if self.reload_config():
                return
            if time.monotonic() - self.last_publish >= 1.0:
                self.publish()

    def run(self):
        time.sleep(0.5)  # primeira janela p/ uso/potencia
        while self.running:
            if self.step():
                self.wait(self.interval)
            else:
                self.wait(3 if self.fails < 10 else 5)
        if self.cooler:
            self.cooler.close()


# ---------------------------------------------------------------- Main

def main():
    ap = argparse.ArgumentParser(description="Driver Linux do display do Rise Mode Air Cooler Temp 6")
    ap.add_argument("--unit", choices=["C", "F"], type=str.upper, default=None,
                    help="Unidade de temperatura (padrao C)")
    ap.add_argument("--mode", choices=["W", "%"], type=str.upper, default=None,
                    help="Segundo valor: potencia (W) ou uso (%%). Sem RAPL cai pra %%")
    ap.add_argument("--interval", type=float, default=None, help="Segundos entre envios (padrao 1)")
    ap.add_argument("--device", default=os.environ.get("RM_DEVICE") or None,
                    help="Forcar /dev/hidrawN")
    ap.add_argument("--sensor", default=os.environ.get("RM_SENSOR") or None,
                    help="Forcar caminho do tempN_input")
    ap.add_argument("--config", default=CONFIG_PATH,
                    help=f"Arquivo de configuracao do painel (padrao {CONFIG_PATH})")
    ap.add_argument("--status-file", default=STATUS_PATH,
                    help=f"Onde gravar o status para o painel (padrao {STATUS_PATH}, '' desliga)")
    ap.add_argument("--dry-run", action="store_true", help="So mostra leituras, nao envia")
    ap.add_argument("--info", action="store_true", help="Mostra dispositivo, sensores e firmware e sai")
    ap.add_argument("--test", nargs=2, type=int, metavar=("TEMP", "VALOR"),
                    help="Envia valores fixos (ex: --test 42 65) para testar o display")
    ap.add_argument("--version", action="version", version=f"risemode-cooler {VERSION}")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    sensor = args.sensor or find_cpu_temp_sensor()
    usage = CpuUsage()
    power = CpuPower()

    if args.info:
        dev_path = args.device or find_hidraw()
        s = resolve_settings({"unit": args.unit, "mode": args.mode, "interval": args.interval},
                             read_config_json(args.config), env_settings(os.environ))
        print(f"Versao          : {VERSION}")
        print(f"Dispositivo HID : {dev_path or 'NAO ENCONTRADO (VID 1A2C PID 4984)'}")
        print(f"Sensor de temp  : {sensor or 'NAO ENCONTRADO'}")
        print(f"RAPL (potencia) : {power.path or 'indisponivel'}")
        print(f"Configuracao    : unidade {s['unit']}, modo {s['mode']}, "
              f"intervalo {s['interval']:g}s")
        if dev_path:
            try:
                c = Cooler(dev_path)
                v = c.firmware_version()
                print(f"Firmware        : {hex(v) if v is not None else 'sem resposta'}")
                c.close()
            except OSError as e:
                print(f"Erro abrindo {dev_path}: {e}")
        return 0

    if not sensor and not args.test:
        print("Nao achei sensor de temperatura da CPU. Use --sensor.", file=sys.stderr)
        return 1

    daemon = Daemon(args, sensor, power, usage)

    def stop(*_):
        daemon.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
