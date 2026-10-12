#!/usr/bin/env python3
"""
Rise Mode Air Cooler Temp 6 (display digital) - driver para Linux.

Versao 1.1

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
"""
import argparse
import errno
import fcntl
import glob
import os
import signal
import sys
import time

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


# ---------------------------------------------------------------- Main

def main():
    ap = argparse.ArgumentParser(description="Driver Linux do display do Rise Mode Air Cooler Temp 6")
    ap.add_argument("--unit", choices=["C", "F"], default=os.environ.get("RM_UNIT", "C"),
                    help="Unidade de temperatura (padrao C)")
    ap.add_argument("--mode", choices=["W", "%"], default=os.environ.get("RM_MODE", "W"),
                    help="Segundo valor: potencia (W) ou uso (%%). Sem RAPL cai pra %%")
    ap.add_argument("--interval", type=float, default=float(os.environ.get("RM_INTERVAL", "1.0")))
    ap.add_argument("--device", default=os.environ.get("RM_DEVICE") or None,
                    help="Forcar /dev/hidrawN")
    ap.add_argument("--sensor", default=os.environ.get("RM_SENSOR") or None,
                    help="Forcar caminho do tempN_input")
    ap.add_argument("--dry-run", action="store_true", help="So mostra leituras, nao envia")
    ap.add_argument("--info", action="store_true", help="Mostra dispositivo, sensores e firmware e sai")
    ap.add_argument("--test", nargs=2, type=int, metavar=("TEMP", "VALOR"),
                    help="Envia valores fixos (ex: --test 42 65) para testar o display")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    fahrenheit = args.unit == "F"
    sensor = args.sensor or find_cpu_temp_sensor()
    usage = CpuUsage()
    power = CpuPower()
    percent = args.mode == "%"
    if not percent and not power.available:
        print("[aviso] RAPL indisponivel (rode como root ou sem suporte). Usando modo %.",
              file=sys.stderr)
        percent = True

    dev_path = args.device or find_hidraw()

    if args.info:
        print(f"Dispositivo HID : {dev_path or 'NAO ENCONTRADO (VID 1A2C PID 4984)'}")
        print(f"Sensor de temp  : {sensor or 'NAO ENCONTRADO'}")
        print(f"RAPL (potencia) : {power.path or 'indisponivel'}")
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

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    cooler = None
    fails = 0          # falhas seguidas de envio
    last_reset = 0.0   # momento do ultimo reset USB
    connected_msg = False
    time.sleep(0.5)  # primeira janela p/ uso/potencia

    while running:
        try:
            if args.test:
                t, val = args.test
            else:
                t = int(_read(sensor)) / 1000.0
                if fahrenheit:
                    t = t * 1.8 + 32
                val = usage.read() if percent else (power.read() or 0.0)

            pkt = build_packet(t, val, fahrenheit, percent)
            if args.verbose or args.dry_run:
                unit = "F" if fahrenheit else "C"
                print(f"temp={t:.1f}{unit}  {'uso' if percent else 'pot'}={val:.1f}"
                      f"{'%' if percent else 'W'}  pkt={pkt[:8].hex(' ')}", flush=True)

            if not args.dry_run:
                if cooler is None:
                    path = args.device or find_hidraw()
                    if not path:
                        raise FileNotFoundError("cooler 1A2C:4984 nao conectado")
                    cooler = Cooler(path)
                    if not connected_msg:
                        print(f"Conectado em {path}", flush=True)
                        connected_msg = True
                cooler.send_feature(pkt)
                if fails:
                    print(f"[ok] cooler voltou a responder apos {fails} falha(s)", flush=True)
                fails = 0
        except (OSError, ValueError) as e:
            fails += 1
            if fails <= 3 or fails % 20 == 0:
                print(f"[erro] {e} (falha {fails}) - tentando de novo", file=sys.stderr, flush=True)
            dev_for_reset = cooler.path if cooler else None
            if cooler:
                cooler.close()
                cooler = None
            connected_msg = False
            # O firmware do display as vezes trava e passa a recusar os
            # pacotes (EPIPE/EPROTO). Um reset USB destrava sem desligar o PC.
            stalled = isinstance(e, OSError) and e.errno in (errno.EPIPE, errno.EPROTO,
                                                             errno.ETIMEDOUT, errno.EIO)
            if (stalled and fails >= 3 and not args.dry_run
                    and time.monotonic() - last_reset > 30):
                last_reset = time.monotonic()
                node = usb_node_for(dev_for_reset or args.device or find_hidraw())
                if node:
                    try:
                        usb_reset(node)
                        print(f"[recuperacao] cooler travado, reset USB em {node}",
                              file=sys.stderr, flush=True)
                        time.sleep(2)  # aguarda o dispositivo reaparecer
                    except OSError as re_err:
                        print(f"[recuperacao] falhou o reset USB ({re_err})",
                              file=sys.stderr, flush=True)
            time.sleep(3 if fails < 10 else 5)
            continue
        time.sleep(args.interval)

    if cooler:
        cooler.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
