"""Testes da recuperacao automatica (sem hardware).

Rode da raiz do projeto:  python3 -m unittest discover -s tests -v
"""
import errno
import importlib.util
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_driver():
    spec = importlib.util.spec_from_file_location(
        "risemode_cooler", os.path.join(ROOT, "risemode-cooler.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Stop(Exception):
    """Interrompe o loop do main() quando o teste ja viu o que precisava."""


class FakeClock:
    """Substitui o modulo time: sleep so avanca o relogio e fica registrado."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []
        self.on_sleep = None

    def monotonic(self):
        return self.now

    def time(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s
        if self.on_sleep:
            self.on_sleep(s)


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_driver()
        self.clock = FakeClock()
        self.mod.time = types.SimpleNamespace(
            monotonic=self.clock.monotonic, time=self.clock.time, sleep=self.clock.sleep)
        self.events = []     # linha do tempo: ("send", ok?), ("reset", node)
        self.fail_plan = []  # True = proximo envio lanca EPIPE
        test = self

        class FakeCooler:
            def __init__(self, path):
                self.path = path

            def close(self):
                pass

            def send_feature(self, payload):
                fail = test.fail_plan.pop(0) if test.fail_plan else False
                test.events.append(("send", not fail, test.clock.now))
                if fail:
                    raise OSError(errno.EPIPE, "Broken pipe")

        self.mod.Cooler = FakeCooler
        self.mod.find_hidraw = lambda: "/dev/hidraw5"
        self.mod.usb_node_for = lambda path: "/dev/bus/usb/001/007"
        self.mod.usb_reset = lambda node: self.events.append(("reset", node, self.clock.now))
        self.argv = sys.argv
        self.stdout, self.stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = open(os.devnull, "w")

    def tearDown(self):
        sys.stdout.close()
        sys.argv = self.argv
        sys.stdout, sys.stderr = self.stdout, self.stderr

    def run_until(self, ok_sends):
        """Roda o main() ate acontecerem `ok_sends` envios bem sucedidos."""
        def check(_):
            if sum(1 for e in self.events if e[0] == "send" and e[1]) >= ok_sends:
                raise Stop
        self.clock.on_sleep = check
        sys.argv = ["risemode-cooler", "--test", "42", "65", "--mode", "%"]
        with self.assertRaises(Stop):
            self.mod.main()

    def test_epipe_resets_on_first_failure_and_resumes_fast(self):
        self.fail_plan = [False, True]  # 1o envio ok, 2o trava com EPIPE

        self.run_until(ok_sends=3)

        kinds = [e[0] for e in self.events]
        # ok, falha, reset imediato, envio volta
        self.assertEqual(kinds[:4], ["send", "send", "reset", "send"])
        self.assertFalse(self.events[1][1])
        self.assertTrue(self.events[3][1])
        self.assertEqual(kinds.count("reset"), 1)

        fail_t = self.events[1][2]
        back_t = self.events[3][2]
        self.assertLessEqual(back_t - fail_t, 4.0, "display parado por mais de ~4 s")

        # Entre a falha e a volta, nenhum sleep maior que 0,5 s.
        recovery_sleeps = self._sleeps_between(fail_t, back_t)
        self.assertTrue(recovery_sleeps, "esperava ao menos uma espera curta apos o reset")
        self.assertTrue(all(s <= 0.5 for s in recovery_sleeps), recovery_sleeps)

    def test_device_reappears_late(self):
        """O hidraw some por ~1,5 s apos o reset e volta com outro numero."""
        self.fail_plan = [False, True]
        appear_at = {}

        def fake_find():
            if "t" in appear_at and self.clock.now < appear_at["t"]:
                return None
            return "/dev/hidraw6" if "t" in appear_at else "/dev/hidraw5"

        def fake_reset(node):
            appear_at["t"] = self.clock.now + 1.5
            self.events.append(("reset", node, self.clock.now))

        self.mod.find_hidraw = fake_find
        self.mod.usb_reset = fake_reset
        self.run_until(ok_sends=2)

        resumed = [e for e in self.events if e[0] == "send"][-1]
        reset = [e for e in self.events if e[0] == "reset"][0]
        self.assertTrue(resumed[1])
        self.assertLessEqual(resumed[2] - reset[2], 2.0)

    def test_second_stall_within_30s_waits_3s(self):
        """Travou de novo dentro de 30 s: nao reseta, tenta a cada 3 s."""
        self.fail_plan = [False, True, False, True, False]
        self.run_until(ok_sends=3)
        self.assertEqual([e[0] for e in self.events].count("reset"), 1)
        second_fail = [e for e in self.events if e[0] == "send" and not e[1]][1]
        after = self._sleeps_between(second_fail[2], second_fail[2] + 10)
        self.assertEqual(after[0], 3)

    def test_other_errors_wait_three_failures(self):
        mod = self.mod
        eproto = OSError(errno.EPROTO, "Protocol error")
        epipe = OSError(errno.EPIPE, "Broken pipe")
        self.assertFalse(mod.should_reset(eproto, 1, 999))
        self.assertFalse(mod.should_reset(eproto, 2, 999))
        self.assertTrue(mod.should_reset(eproto, 3, 999))
        self.assertTrue(mod.should_reset(epipe, 1, 999))
        self.assertFalse(mod.should_reset(epipe, 1, 10))   # dentro dos 30 s
        self.assertFalse(mod.should_reset(OSError(errno.ENOENT, "x"), 5, 999))
        self.assertFalse(mod.should_reset(ValueError("x"), 5, 999))

    def _sleeps_between(self, t0, t1):
        """Sleeps iniciados no intervalo [t0, t1) do relogio falso."""
        out, t = [], 1000.0
        for s in self.clock.sleeps:
            if t0 <= t < t1:
                out.append(s)
            t += s
        return out


if __name__ == "__main__":
    unittest.main()
