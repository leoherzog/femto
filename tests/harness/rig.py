"""`run.py rig`: start each browser and verify every mechanism the harness relies on."""
import contextlib
import json
import time

from . import locks
from .browsers import FRAME_HEIGHT, RigError
from .paths import RESULTS
from .runner import start_session
from .server import Server


def check_browser(browser, base, log):
    out = {}
    sess = start_session(browser, base, log)
    try:
        out.update(sess.rig)
        widths = {}
        for w in (375, 577, 1700):
            ld = sess.ajs("load", "/tests/harness/probe.html", w, FRAME_HEIGHT, {})
            info = ld.get("info", {})
            widths[w] = {"innerWidth": info.get("innerWidth"), "matchMedia": info.get("mqWidth"),
                         "css": info.get("cssWidth"), "errors": ld.get("errors")}
        out["widths"] = widths
        schemes = {}
        for media in ("light", "dark"):
            for theme in (None, "light", "dark"):
                key = f"media {media}" + (f" + data-theme {theme}" if theme else "")
                try:
                    t0 = time.time()
                    sess.set_media(media)
                    sw = round(time.time() - t0, 3)
                except RigError as e:
                    schemes[key] = {"skipped": str(e)}
                    continue
                url = "/tests/harness/probe.html" + (f"?theme={theme}" if theme else "")
                ld = sess.ajs("load", url, 1280, FRAME_HEIGHT, {"media": media, "theme": theme})
                info = ld.get("info", {})
                cs = sess.driver.execute_script(
                    "const f=document.getElementById('frame');return f.contentWindow.getComputedStyle(f.contentDocument.getElementById('cs')).color")
                schemes[key] = {"matchMedia_dark": info.get("dark"), "css_dark": info.get("cssDark"),
                                "light_dark_color": cs, "switch_s": sw, "errors": ld.get("errors")}
        out["schemes"] = schemes
        ld = sess.ajs("load", "/tests/harness/probe.html", 1280, FRAME_HEIGHT, {})
        t0 = time.time()
        png = sess.frame_png()
        out["screenshot"] = {"bytes": len(png), "s": round(time.time() - t0, 3)}
        sess.js("configure", {"entries": [], "pseudos": sess.pseudos})
        fr = sess.js("freeze")
        out["freeze_on_probe"] = fr
    finally:
        sess.quit()
    return out


def run_rig(args):
    run_id = args.run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-rig"
    server = Server()
    report = {}
    log = lambda m: print(f"{time.strftime('%H:%M:%S')} {m}", flush=True)
    status = 0
    for b in [x.strip() for x in args.browsers.split(",") if x.strip()]:
        try:
            with locks.slot(f"{run_id} rig {b}", log):
                guard = locks.safari(f"{run_id} rig", log) if b == "safari" else contextlib.nullcontext()
                with guard:
                    report[b] = check_browser(b, server.base, log)
        except Exception as e:
            report[b] = {"error": repr(e)}
            status = 1
        print(f"{b}: {json.dumps(report[b], indent=1)}", flush=True)
    server.close()
    d = RESULTS / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "rig.json").write_text(json.dumps(report, indent=1))
    print(f"wrote {d}/rig.json")
    return status
