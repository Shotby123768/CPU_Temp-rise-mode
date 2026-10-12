"""Testes do status.json e do config.json do daemon (sem hardware)."""
import errno
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from test_recovery import ROOT, load_driver

DRIVER = os.path.join(ROOT, "risemode-cooler.py")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_driver()

    def test_priority_cli_over_json_over_env_over_default(self):
        r = self.mod.resolve_settings
        none = {"unit": None, "mode": None, "interval": None}
        self.assertEqual(r(none, {}, {}), {"unit": "C", "mode": "W", "interval": 1.0})
        self.assertEqual(r(none, {}, {"unit": "F", "interval": 0.5}),
                         {"unit": "F", "mode": "W", "interval": 0.5})
        self.assertEqual(r(none, {"unit": "C", "mode": "%"}, {"unit": "F", "mode": "W"}),
                         {"unit": "C", "mode": "%", "interval": 1.0})
        self.assertEqual(r({"unit": "F", "mode": None, "interval": 3.0},
                           {"unit": "C", "interval": 2.0}, {}),
                         {"unit": "F", "mode": "W", "interval": 3.0})

    def test_env_like_1x(self):
        e = self.mod.env_settings
        self.assertEqual(e({"RM_UNIT": "f", "RM_MODE": "%", "RM_INTERVAL": "2"}),
                         {"unit": "F", "mode": "%", "interval": 2.0})
        self.assertEqual(e({"RM_UNIT": "K", "RM_INTERVAL": "x"}), {})

    def test_config_json_keeps_only_valid_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "w") as f:
                json.dump({"unit": "F", "mode": "x", "interval": 50, "evil": 1}, f)
            with open(os.devnull, "w") as null:
                err, sys.stderr = sys.stderr, null
                try:
                    self.assertEqual(self.mod.read_config_json(p), {"unit": "F"})
                    with open(p, "w") as f:
                        f.write("{quebrado")
                    self.assertEqual(self.mod.read_config_json(p), {})
                finally:
                    sys.stderr = err
            self.assertEqual(self.mod.read_config_json(os.path.join(d, "nao-existe")), {})

    def test_error_states(self):
        c = self.mod.classify_error
        self.assertEqual(c(OSError(errno.EPIPE, "x")), "recovering")
        self.assertEqual(c(OSError(errno.EPROTO, "x")), "recovering")
        self.assertEqual(c(FileNotFoundError(errno.ENOENT, "x")), "not_found")
        self.assertEqual(c(OSError(errno.ENODEV, "x")), "not_found")
        self.assertEqual(c(PermissionError(errno.EACCES, "x")), "error")


class StatusFileTest(unittest.TestCase):
    def test_atomic_never_half_written(self):
        mod = load_driver()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "run", "status.json")
            sf = mod.StatusFile(path)
            sf.write({"n": 0})
            big = "x" * 20000  # arquivo grande o bastante para uma escrita parcial aparecer
            stop = threading.Event()
            errors = []

            def reader():
                while not stop.is_set():
                    try:
                        with open(path) as f:
                            json.load(f)
                    except ValueError as e:
                        errors.append(e)

            t = threading.Thread(target=reader)
            t.start()
            for i in range(1500):
                sf.write({"n": i, "pad": big})
            stop.set()
            t.join()
            self.assertEqual(errors, [])
            self.assertEqual(os.listdir(os.path.dirname(path)), ["status.json"])
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o644)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o755)


class DryRunTest(unittest.TestCase):
    """Roda o daemon de verdade em --dry-run e conversa com ele pelos arquivos."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.status = os.path.join(self.tmp.name, "status.json")
        self.config = os.path.join(self.tmp.name, "config.json")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.terminate()
            p.wait(5)
        self.tmp.cleanup()

    def start(self, *extra):
        env = dict(os.environ)
        for k in ("RM_UNIT", "RM_MODE", "RM_INTERVAL", "RM_DEVICE", "RM_SENSOR"):
            env.pop(k, None)
        p = subprocess.Popen(
            [sys.executable, DRIVER, "--dry-run", "--test", "47", "65", "--mode", "%",
             "--status-file", self.status, "--config", self.config] + list(extra),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        self.procs.append(p)
        return p

    def wait_status(self, pred, timeout):
        end = time.monotonic() + timeout
        st = None
        while time.monotonic() < end:
            try:
                with open(self.status) as f:
                    st = json.load(f)
                if pred(st):
                    return st, time.monotonic()
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        self.fail(f"status nao chegou ao esperado em {timeout}s; ultimo: {st}")

    def write_config(self, data):
        tmp = self.config + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.config)

    def test_dry_run_writes_status(self):
        self.start()
        st, _ = self.wait_status(lambda s: True, 5)
        self.assertEqual(st["state"], "ok")
        self.assertIsNone(st["device"])
        self.assertEqual(st["version"], "2.0")
        self.assertEqual((st["temp"], st["value"], st["unit"], st["mode"]), (47, 65, "C", "%"))
        self.assertLess(abs(time.time() - st["updated"]), 3)
        for key in ("rapl", "last_error", "resets"):
            self.assertIn(key, st)

    def test_config_change_applies_without_restart(self):
        self.write_config({"unit": "C", "mode": "%", "interval": 1})
        p = self.start("--mode", "%")
        self.wait_status(lambda s: s["unit"] == "C", 5)
        t0 = time.monotonic()
        self.write_config({"unit": "F", "mode": "%", "interval": 1})
        _, t1 = self.wait_status(lambda s: s["unit"] == "F", 5)
        self.assertLess(t1 - t0, 2.0)
        self.assertIsNone(p.poll(), "o daemon nao pode ter reiniciado/saido")

    def test_cli_beats_config(self):
        self.write_config({"unit": "F", "mode": "%", "interval": 1})
        self.start("--unit", "C")
        st, _ = self.wait_status(lambda s: True, 5)
        self.assertEqual(st["unit"], "C")


if __name__ == "__main__":
    unittest.main()
