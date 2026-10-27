"""Worker pool: one thread per browser session, each holding a machine-wide slot (and the Safari lock)."""
import collections
import contextlib
import threading
import time
import traceback

from selenium.common.exceptions import WebDriverException

from . import locks
from .browsers import FRAME_HEIGHT, Session
from .compare import apply_state, run_cell

PSEUDOS = ["::before", "::after", "::marker", "::placeholder", "::file-selector-button", "::backdrop"]


def hid_idle_s():
    """Seconds since the last real keyboard or pointer input on this Mac, Screen Sharing included
    (IOHIDSystem HIDIdleTime). safaridriver's synthesized input does not reset it (verified
    2026-10-27). None when it cannot be read."""
    import subprocess
    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if "HIDIdleTime" in line:
            try:
                return int(line.rsplit("=", 1)[1].strip()) / 1e9
            except ValueError:
                return None
    return None


def _state_mismatch(r):
    return any(" state " in e and "did not match" in e for e in r.get("errors", []))


def start_session(browser, base, log):
    """Start a browser, load the host page and verify the rig on the probe page."""
    sess = Session(browser, base, log)
    try:
        return _verify_session(sess, browser, log)
    except Exception:
        sess.quit()
        raise


def _verify_session(sess, browser, log):
    rig = {"browser": browser, "version": sess.version, "driver": sess.driver_version, "launch_s": sess.launch_s,
           "os_scheme": sess.os_scheme, "host": sess.host}
    ld = sess.ajs("load", "/tests/harness/probe.html", 1280, FRAME_HEIGHT, {})
    if ld.get("errors"):
        rig["probe_errors"] = ld["errors"]
    pr = sess.js("probePseudos")
    rig["pseudo_support"] = {p: bool(pr.get(p)) for p in PSEUDOS}
    sess.pseudos = [p for p in PSEUDOS if pr.get(p)]
    sess.unsupported_pseudos = [p for p in PSEUDOS if not pr.get(p)]
    ok, why = sess.interactive()
    checks = {}
    if ok:
        sess.js("configure", {"entries": [], "pseudos": sess.pseudos})
        for tg in sess.js("stateTargets"):
            for st in tg["states"]:
                try:
                    info = apply_state(sess, "ref", tg, st)
                    checks[f"{st} on {tg['label']}"] = bool(info.get("matched"))
                except WebDriverException as e:
                    checks[f"{st} on {tg['label']}"] = False
                    rig.setdefault("input_errors", []).append(str(e).splitlines()[0])
        failed = [k for k, v in checks.items() if not v]
        if failed:
            ok, why = False, "input verification failed on the rig probe: " + "; ".join(failed)
    rig["input_checks"] = checks
    rig["interactive"] = ok
    if not ok:
        rig["interactive_reason"] = why
        log(f"{browser}: interactive states disabled: {why}")
    sess.can_interact, sess.interact_reason = ok, why
    sess.rig = rig
    return sess


class Pool:
    def __init__(self, cells, registry, opts, run_dir, server, log):
        self.cells, self.registry, self.opts, self.run_dir, self.server, self.log = cells, registry, opts, run_dir, server, log
        self.results, self.rigs, self.errors = [], [], []
        self.lock = threading.Lock()
        self.done = 0
        self.total = len(cells)
        self.t0 = time.time()
        by = collections.defaultdict(list)
        for c in cells:
            by[c["browser"]].append(c)
        # Firefox switches prefers-color-scheme through a pref, so keep each media leg together.
        for b, lst in by.items():
            lst.sort(key=lambda c: (c["media"], c["preset"], c["page"], c["variant_label"], c["dir"], c["width"], c["scheme"]))
        self.queues = {b: collections.deque(lst) for b, lst in by.items()}

    def _next(self, browser):
        with self.lock:
            q = self.queues.get(browser)
            return q.popleft() if q else None

    def _record(self, r):
        with self.lock:
            self.results.append(r)
            self.done += 1
            res = r.get("result") or {}
            self.registry.record_hits(res.get("registered", {}))
            n_err = len(r.get("errors", []))
            first_err = (r.get("errors") or [""])[0]
            if r.get("states_blocked"):
                first_err = first_err or f"states not run: {r['states_blocked']}"
            el = time.time() - self.t0
            self.log(f"[{self.done}/{self.total} {el:6.0f}s] {r['browser']:7} {r['preset']} {r['page']} {r['variant_label']} "
                     f"{r['scheme']} {r['width']} {r['dir']}: {res.get('unregisteredTotal', 0)} unregistered, "
                     f"{res.get('total', 0) - res.get('unregisteredTotal', 0)} registered, {n_err} errors, "
                     f"{r.get('states_run', 0)} states, {r.get('timing', {}).get('total', 0)}s"
                     + (f" [{r['status']}]" if r.get("status") not in ("ok", None) else "")
                     + (f" | {first_err[:300]}" if first_err else ""))

    def _worker(self, browser, n):
        label = f"{self.opts.run_id} {browser}#{n}"
        try:
            with locks.slot(label, self.log):
                guard = locks.safari(label, self.log) if browser == "safari" else contextlib.nullcontext()
                with guard:
                    self._session_loop(browser, label)
        except Exception as e:
            with self.lock:
                self.errors.append(f"{label}: worker failed: {e}\n{traceback.format_exc()}")
            self.log(f"{label}: worker failed: {e}")

    def _session_loop(self, browser, label):
        sess = None
        restarts = 0
        try:
            while True:
                cell = self._next(browser)
                if cell is None:
                    break
                if sess is None:
                    # A loaded machine can time out a session start ("Timed out receiving message
                    # from renderer"); retry twice before failing the worker.
                    for attempt in range(3):
                        try:
                            sess = start_session(browser, self.server.base, self.log)
                            break
                        except WebDriverException as e:
                            if attempt == 2:
                                raise
                            self.log(f"{label}: session start failed ({str(e).splitlines()[0][:200]}); retrying")
                            time.sleep(10)
                    with self.lock:
                        self.rigs.append(sess.rig)
                    self.log(f"{label}: {browser} {sess.version} ({sess.driver_version}), launch {sess.launch_s}s, "
                             f"OS scheme {sess.os_scheme}, pseudo-elements {sess.pseudos}, interactive {sess.can_interact}")
                shot = None
                if self.opts.shots and cell["shots"]:
                    name = "__".join(str(x) for x in (cell["browser"], cell["preset"], cell["page"].removesuffix(".html"),
                                                      cell["variant_label"], cell["scheme"], cell["width"], cell["dir"]))
                    shot = self.run_dir / "shots" / (name.replace("/", "_").replace("=", "-").replace("&", "+") + ".png")
                try:
                    r = run_cell(sess, cell, self.registry, self.opts, shot)
                    if browser == "safari" and r.get("states_run") and _state_mismatch(r):
                        # Real input (someone at the machine or over Screen Sharing) moves the
                        # pointer and focus under the synthesized input. If any arrived during this
                        # cell, wait until the machine is idle and run the cell once more.
                        idle = hid_idle_s()
                        if idle is not None and idle < r.get("timing", {}).get("total", 0) + 2:
                            self.log(f"{label}: real input during the cell (HID idle {idle:.1f}s, "
                                     f"{len(r['errors'])} state errors); retrying once when idle")
                            deadline = time.time() + 600
                            while time.time() < deadline:
                                now_idle = hid_idle_s()
                                if now_idle is None or now_idle >= 10:
                                    break
                                time.sleep(2)
                            first = len(r["errors"])
                            r = run_cell(sess, cell, self.registry, self.opts, shot)
                            r["retried_after_input"] = {"first_errors": first, "hid_idle_s": round(idle, 1)}
                except WebDriverException as e:
                    r = dict(cell, status="error", errors=[f"webdriver: {str(e).splitlines()[0] if str(e) else repr(e)}"],
                             skipped=[], result=None, timing={})
                    sess.quit()
                    sess = None
                    restarts += 1
                    if restarts > 5:
                        self._record(r)
                        raise RuntimeError("too many session restarts")
                except Exception as e:
                    r = dict(cell, status="error", errors=[f"harness exception: {e!r}: {traceback.format_exc(limit=4)}"],
                             skipped=[], result=None, timing={})
                self._record(r)
        finally:
            if sess is not None:
                sess.quit()

    def run(self):
        threads = []
        for browser, n in self.opts.workers.items():
            if browser not in self.queues:
                continue
            for i in range(max(1, min(n, len(self.queues[browser])))):
                if browser == "safari" and i > 0:
                    break
                t = threading.Thread(target=self._worker, args=(browser, i), name=f"{browser}-{i}", daemon=True)
                threads.append(t)
                t.start()
        for t in threads:
            t.join()
        left = sum(len(q) for q in self.queues.values())
        if left:
            self.errors.append(f"{left} cells never ran (workers failed)")
        return self.results
