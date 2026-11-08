"""How hard a build may use the PC: the priority of the build's processes and how many compilers run at once.

HookshotBuilder used to start the build at Below normal priority. On Windows a Below normal process's children are Below normal
too, so every clang was, and on hybrid CPUs (Intel 12th gen and later: performance and efficiency cores) Windows keeps
low-priority work on the efficiency cores: the compile ran on the slow cores while the fast ones idled. Users found that
raising the build's priority in Task Manager (some went to Realtime) made the build several times faster.

HOOKSHOT_PRIORITY (or make_game.py --priority) chooses:
  normal  the default: the build gets the whole CPU, and the desktop, a browser or a video still respond
  low     Below normal, as before: for playing or working on the PC while it builds; slower, very slow on hybrid CPUs
  high    High: a little faster than normal when other programs are busy, at the cost of a sluggish desktop
Realtime is never used: Realtime compilers on every core starve the mouse, the keyboard, audio and disk writes, and Windows
gives it only to administrators anyway (others silently get High). "realtime" is taken as high.

A process at Normal or above does not pass its class on (only Idle and Below normal are inherited), so every process the
build starts gets the class explicitly: popen_kwargs().

HOOKSHOT_JOBS (or --jobs) still sets the number of compilers; without it, default_jobs() picks one per logical CPU, fewer when
the free memory would not hold them.
"""
import os
import sys

LEVELS = ("low", "normal", "high")
_WINDOWS_CLASS = {"low": 0x00004000, "normal": 0x00000020, "high": 0x00000080}   # BELOW_NORMAL, NORMAL, HIGH _PRIORITY_CLASS
_NICE = {"low": 10, "normal": 0, "high": 0}   # (Linux: raising priority needs root; high is normal there)

# (a compiler's memory, MB, on average over a build: the lifted chunks are big C files. Measured with llvm-mingw's clang at -O1:
# 2.5 GB for the largest chunk (42 MB of C), about half that for the usual 23 MB ones. Too many compilers for the memory and
# Windows pages, and the whole build crawls: worse than fewer compilers)
JOB_MB = 1600


def level(value=None):
    """The level asked for (an argument, else HOOKSHOT_PRIORITY), normal when unset or unknown"""
    value = (value or os.environ.get("HOOKSHOT_PRIORITY") or "normal").strip().lower()
    value = {"realtime": "high", "belownormal": "low", "below": "low", "abovenormal": "high", "above": "high"}.get(value, value)
    return value if value in LEVELS else "normal"


def apply_to_self(value=None):
    """This process at the level (it may have been started Below normal by an older HookshotBuilder), and the level in the
    environment for the steps it starts"""
    lv = level(value)
    os.environ["HOOKSHOT_PRIORITY"] = lv
    try:
        if os.name == "nt":
            import ctypes
            k = ctypes.WinDLL("kernel32")
            k.GetCurrentProcess.restype = ctypes.c_void_p
            k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            k.SetPriorityClass(k.GetCurrentProcess(), _WINDOWS_CLASS[lv])
        elif _NICE[lv]:
            os.nice(max(0, _NICE[lv] - os.nice(0)))
    except (OSError, AttributeError, ValueError, TypeError):
        pass
    return lv


def popen_kwargs(value=None):
    """subprocess.Popen/run arguments that start a process at the level"""
    lv = level(value)
    if os.name == "nt":
        return {"creationflags": _WINDOWS_CLASS[lv]}
    return {}   # (Linux: niceness is inherited, apply_to_self is enough)


def available_mb():
    """The physical memory free for new processes, MB; None when it cannot be read"""
    try:
        if os.name == "nt":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            s = Status()
            s.dwLength = ctypes.sizeof(Status)
            if ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(s)):
                return s.ullAvailPhys // (1 << 20)
            return None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, AttributeError):
        pass
    return None


def default_jobs(cpus=None, free_mb=None, job_mb=JOB_MB):
    """One compiler per logical CPU, as many as the free memory holds (a 1 GB margin kept), at least one"""
    cpus = cpus if cpus is not None else (os.cpu_count() or 2)
    free_mb = free_mb if free_mb is not None else available_mb()
    jobs = cpus
    if free_mb is not None:
        jobs = min(jobs, (free_mb - 1024) // job_mb)
    return max(1, int(jobs))


if __name__ == "__main__":
    print("level %s, %s MB free, %d jobs" % (level(sys.argv[1] if len(sys.argv) > 1 else None), available_mb(), default_jobs()))
