"""Testes do helper set-config (o que roda como root via pkexec)."""
import importlib.machinery
import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_helper():
    path = os.path.join(ROOT, "set-config")
    loader = importlib.machinery.SourceFileLoader("set_config", path)
    spec = importlib.util.spec_from_loader("set_config", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.h = load_helper()

    def test_accepts_allowed_values(self):
        p = self.h.parse_args
        self.assertEqual(p(["unit=C"]), {"unit": "C"})
        self.assertEqual(p(["unit=F"]), {"unit": "F"})
        self.assertEqual(p(["mode=W"]), {"mode": "W"})
        self.assertEqual(p(["mode=%"]), {"mode": "%"})
        self.assertEqual(p(["interval=1"]), {"interval": 1})
        self.assertEqual(p(["interval=10"]), {"interval": 10})
        self.assertEqual(p(["interval=2.5"]), {"interval": 2.5})
        self.assertEqual(p(["interval=3.0"]), {"interval": 3})
        self.assertEqual(p(["unit=F", "mode=%", "interval=2"]),
                         {"unit": "F", "mode": "%", "interval": 2})
        self.assertEqual(p([]), {})

    def test_rejects_everything_else(self):
        bad = [
            ["unit=c"], ["unit=f"], ["unit=K"], ["unit="], ["unit"], ["unit=C=F"],
            ["unit=C "], [" unit=C"], ["unit=CC"], ["unit=C\n"], ["unit=C;rm -rf /"],
            ["mode=w"], ["mode=%%"], ["mode=percent"], ["mode=W%"],
            ["interval=0"], ["interval=0.99"], ["interval=11"], ["interval=10.01"],
            ["interval=-1"], ["interval=abc"], ["interval=1e1"], ["interval=nan"],
            ["interval=inf"], ["interval=0x5"], ["interval= 5"], ["interval=5 "],
            ["interval=1.234"], ["interval=٣"], ["interval=05.5.5"], ["interval=100"],
            ["foo=1"], ["path=/etc/passwd"], ["--config=/tmp/x"], ["-h"], [""],
            ["UNIT=C"], ["unit=C", "unit=F"], ["unit=C", "mode=W", "interval=1", "unit=F"],
            ["unit=" + "C" * 100],
        ]
        for argv in bad:
            with self.subTest(argv=argv):
                with self.assertRaises(self.h.Invalid):
                    self.h.parse_args(argv)


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.h = load_helper()
        self.tmp = tempfile.TemporaryDirectory()
        self.h.CONFIG_PATH = os.path.join(self.tmp.name, "etc", "config.json")
        patcher = mock.patch.object(self.h.os, "geteuid", return_value=0)
        self.euid = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.h.main(argv)
        return code, out.getvalue(), err.getvalue()

    def read(self):
        with open(self.h.CONFIG_PATH) as f:
            return json.load(f)

    def test_creates_defaults_and_merges(self):
        self.assertEqual(self.run_main([])[0], 0)
        self.assertEqual(self.read(), {"unit": "C", "mode": "W", "interval": 1})
        self.assertEqual(self.run_main(["unit=F"])[0], 0)
        self.assertEqual(self.run_main(["mode=%"])[0], 0)
        self.assertEqual(self.read(), {"unit": "F", "mode": "%", "interval": 1})
        mode = stat.S_IMODE(os.stat(self.h.CONFIG_PATH).st_mode)
        self.assertEqual(mode, 0o644)
        dmode = stat.S_IMODE(os.stat(os.path.dirname(self.h.CONFIG_PATH)).st_mode)
        self.assertEqual(dmode, 0o755)
        leftovers = [n for n in os.listdir(os.path.dirname(self.h.CONFIG_PATH))
                     if n != "config.json"]
        self.assertEqual(leftovers, [])

    def test_invalid_input_writes_nothing(self):
        self.run_main(["unit=F"])
        before = self.read()
        code, _, err = self.run_main(["unit=F", "mode=bogus"])
        self.assertEqual(code, 2)
        self.assertIn("invalido", err)
        self.assertEqual(self.read(), before)

    def test_garbage_in_existing_file_is_dropped(self):
        os.makedirs(os.path.dirname(self.h.CONFIG_PATH))
        with open(self.h.CONFIG_PATH, "w") as f:
            json.dump({"unit": "F", "mode": "x", "interval": 99, "evil": "$(id)"}, f)
        self.assertEqual(self.run_main([])[0], 0)
        self.assertEqual(self.read(), {"unit": "F", "mode": "W", "interval": 1})

    def test_corrupt_existing_file_is_replaced(self):
        os.makedirs(os.path.dirname(self.h.CONFIG_PATH))
        with open(self.h.CONFIG_PATH, "w") as f:
            f.write('{"unit": "F", ')
        self.assertEqual(self.run_main(["interval=3"])[0], 0)
        self.assertEqual(self.read(), {"unit": "C", "mode": "W", "interval": 3})

    def test_refuses_non_root(self):
        self.euid.return_value = 1000
        code, _, err = self.run_main(["unit=F"])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.h.CONFIG_PATH))


if __name__ == "__main__":
    unittest.main()
