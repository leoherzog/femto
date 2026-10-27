"""Machine-wide locks shared by every harness process on this machine.

* Slots: at most FEMTO_HARNESS_SLOTS (default 4) browser sessions run at once across all harness
  runs. Each worker (one WebDriver session) holds one slot for its lifetime.
* Safari: one Safari session at a time (safaridriver allows one, and it runs on the user's screen).

Locks are fcntl.flock()s on files in FEMTO_HARNESS_LOCK_DIR (default ~/.cache/femto-harness/locks),
so they vanish when the holding process dies.
"""
import contextlib
import fcntl
import os
import random
import time
from pathlib import Path

LOCK_DIR = Path(os.environ.get("FEMTO_HARNESS_LOCK_DIR", Path.home() / ".cache" / "femto-harness" / "locks"))


def slot_count() -> int:
    try:
        return max(1, int(os.environ.get("FEMTO_HARNESS_SLOTS", "4")))
    except ValueError:
        return 4


def _holder(path: Path) -> str:
    try:
        return path.read_text().strip() or "?"
    except OSError:
        return "?"


@contextlib.contextmanager
def _flock(path: Path, label: str, log, blocking_message: str):
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    announced = 0.0
    try:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                now = time.time()
                if now - announced > 60:
                    log(f"{blocking_message} (held by {_holder(path)})")
                    announced = now
                time.sleep(0.5 + random.random())
        f.seek(0)
        f.truncate()
        f.write(f"pid {os.getpid()} {label} since {time.strftime('%H:%M:%S')}\n")
        f.flush()
        yield
    finally:
        try:
            f.seek(0)
            f.truncate()
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()


@contextlib.contextmanager
def slot(label: str, log):
    """Hold one of the machine-wide browser-session slots."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    n = slot_count()
    announced = 0.0
    while True:
        for i in random.sample(range(n), n):
            path = LOCK_DIR / f"slot-{i}.lock"
            f = open(path, "a+")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                f.close()
                continue
            try:
                f.seek(0)
                f.truncate()
                f.write(f"pid {os.getpid()} {label} since {time.strftime('%H:%M:%S')}\n")
                f.flush()
                yield i
            finally:
                f.seek(0)
                f.truncate()
                fcntl.flock(f, fcntl.LOCK_UN)
                f.close()
            return
        now = time.time()
        if now - announced > 60:
            holders = "; ".join(_holder(LOCK_DIR / f"slot-{i}.lock") for i in range(n))
            log(f"{label}: all {n} harness slots busy, waiting ({holders})")
            announced = now
        time.sleep(1 + random.random())


def safari(label: str, log):
    """Hold the machine-wide Safari lock."""
    return _flock(LOCK_DIR / "safari.lock", label, log, f"{label}: waiting for the Safari lock")


def driver_start(label: str, log):
    """Serialize WebDriver startup: concurrent Selenium Manager runs race on ~/.cache/selenium/se-metadata.json."""
    return _flock(LOCK_DIR / "driver-start.lock", label, log, f"{label}: waiting to start a driver")
