"""The build runs at normal priority with one compiler per logical CPU unless memory is short, and never at Realtime.

python -I -B tests/test_build_priority.py
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import build_priority  # noqa: E402


class LevelTests(unittest.TestCase):
    def test_default_is_normal(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(build_priority.level(), "normal")

    def test_realtime_is_never_used(self):
        self.assertEqual(build_priority.level("realtime"), "high")
        self.assertEqual(build_priority.level("RealTime"), "high")

    def test_environment_and_aliases(self):
        with mock.patch.dict(os.environ, {"HOOKSHOT_PRIORITY": "BelowNormal"}):
            self.assertEqual(build_priority.level(), "low")
        self.assertEqual(build_priority.level("nonsense"), "normal")

    def test_argument_wins_over_environment(self):
        with mock.patch.dict(os.environ, {"HOOKSHOT_PRIORITY": "low"}):
            self.assertEqual(build_priority.level("high"), "high")


class JobsTests(unittest.TestCase):
    def test_one_per_cpu_when_memory_allows(self):
        self.assertEqual(build_priority.default_jobs(cpus=16, free_mb=64000, job_mb=2000), 16)

    def test_memory_caps_the_jobs(self):
        self.assertEqual(build_priority.default_jobs(cpus=16, free_mb=9000, job_mb=2000), 3)

    def test_at_least_one(self):
        self.assertEqual(build_priority.default_jobs(cpus=16, free_mb=500, job_mb=2000), 1)

    def test_unknown_memory_uses_the_cpus(self):
        with mock.patch.object(build_priority, "available_mb", return_value=None):
            self.assertEqual(build_priority.default_jobs(cpus=12), 12)


@unittest.skipUnless(os.name == "nt", "Windows priority classes")
class WindowsClassTests(unittest.TestCase):
    """A Normal or High process does not pass its class on: each child is started with it"""

    CLASS_OF = {"low": 0x4000, "normal": 0x20, "high": 0x80}

    def child_class(self, lv):
        code = ("import ctypes; k = ctypes.WinDLL('kernel32'); k.GetCurrentProcess.restype = ctypes.c_void_p; "
                "k.GetPriorityClass.argtypes = [ctypes.c_void_p]; print(k.GetPriorityClass(k.GetCurrentProcess()))")
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True,
                             **build_priority.popen_kwargs(lv)).stdout
        return int(out)

    def test_children_get_the_class(self):
        for lv in ("low", "normal", "high"):
            with self.subTest(level=lv):
                self.assertEqual(self.child_class(lv), self.CLASS_OF[lv])

    def test_never_realtime(self):
        self.assertNotEqual(build_priority.popen_kwargs("realtime")["creationflags"], 0x100)   # REALTIME_PRIORITY_CLASS


class SourceTests(unittest.TestCase):
    def test_builder_no_longer_starts_below_normal(self):
        runner = (ROOT / "builder" / "HookshotBuilder" / "Runner.cs").read_text(encoding="utf-8")
        self.assertNotIn("ProcessPriorityClass.BelowNormal;", runner)

    def test_builder_passes_the_chosen_speed(self):
        window = (ROOT / "builder" / "HookshotBuilder" / "MainWindow.xaml.cs").read_text(encoding="utf-8")
        self.assertIn('"--priority"', window)
        self.assertIn('{ "high", "normal", "low" }', window)

    def test_every_language_names_the_speeds(self):
        import re
        strings = (ROOT / "builder" / "HookshotBuilder" / "Strings.cs").read_text(encoding="utf-8")
        enum = strings[strings.index("enum S"):strings.index("}", strings.index("enum S"))]
        names = re.findall(r"\b([A-Z]\w*)\b", re.sub(r"//[^\n]*", "", enum[enum.index("{"):]))
        needed = names.index("SpeedLow") + 1
        for name, body in re.findall(r"static readonly string\[\] (\w+) =\n    \{\n(.*?)\n    \};", strings, re.S):
            with self.subTest(language=name):
                self.assertGreaterEqual(len(re.findall(r'"[^"]*"', body)), needed)

    def test_compilers_are_started_at_the_level(self):
        build = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        start = build.index("def compile_one")
        self.assertIn("build_priority.popen_kwargs()", build[start:build.index("\ndef ", start + 1)])


if __name__ == "__main__":
    unittest.main()
