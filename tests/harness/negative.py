"""`run.py selftest`: controls that prove the harness detects what it must and tolerates what it may.

Each case writes its stylesheets to tests/build/negative/, runs `run.py compare` (or self/hybrid) in a
subprocess exactly as a user would, and checks result.json against an expectation.
"""
import json
import subprocess
import sys
import time

from .paths import BUILD, REFERENCE, RESULTS, TESTS, path_to_url

NEG = BUILD / "negative"
REF = "/tests/reference/femto.css"


def _variant(name, edits):
    """Copy the reference with (old, new, nth occurrence or 'all') text edits applied."""
    text = (REFERENCE / "femto.css").read_text()
    for old, new, which in edits:
        if which == "all":
            if old not in text:
                raise RuntimeError(f"{name}: {old!r} not in reference")
            text = text.replace(old, new)
            continue
        start = -1
        for _ in range(which):
            start = text.index(old, start + 1)
        text = text[:start] + new + text[start + len(old):]
    p = NEG / f"{name}.css"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return path_to_url(p)


def _override(name, css):
    p = NEG / f"{name}.css"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(css)
    return path_to_url(p)


def _records(result, kinds=None):
    for c in result["cells"]:
        for r in (c.get("result") or {}).get("unregistered", []):
            if kinds is None or r["kind"] in kinds:
                yield c, r


def _total(result, pred=lambda c: True):
    return sum((c.get("result") or {}).get("unregisteredTotal", 0) for c in result["cells"] if pred(c))


def build_cases():
    h1_2 = _variant("h1-color-plus2", [("--femto-h1-color: #2d3138;", "--femto-h1-color: #2f3138;", 1)])
    h1_1 = _variant("h1-color-plus1", [("--femto-h1-color: #2d3138;", "--femto-h1-color: #2e3138;", 1)])
    h1h2 = _variant("h1-h2-color-plus2", [("--femto-h1-color: #2d3138;", "--femto-h1-color: #2f3138;", 1),
                                          ("--femto-h2-color: #373c44;", "--femto-h2-color: #393c44;", 1)])
    dark = _variant("dark-media-h1", [("--femto-h1-color: #f0f1f3;", "--femto-h1-color: #c0c1c3;", 1)])
    mq = _variant("breakpoint-577", [("(min-width: 576px)", "(min-width: 577px)", "all")])
    sel = _variant("selection-token", [("--femto-text-selection-color: rgba(2, 154, 232, 0.25);",
                                        "--femto-text-selection-color: rgba(2, 154, 232, 0.5);", 1)])
    hover = _override("hover-only", "a:hover:not(:active) { word-spacing: 3px; }\n")
    rtl = _override("rtl-only", "html[dir=rtl] h1 { word-spacing: 2px; }\n")
    ph = _override("placeholder", "input::placeholder { letter-spacing: 2px; }\n")
    bd = _override("backdrop", "dialog::backdrop { opacity: 0.5; }\n")
    active = _override("active-only", "a:active { word-spacing: 3px; }\n")
    focus = _override("focus-only", "a:focus { word-spacing: 3px; }\n")
    fv = _override("focus-visible-only", "a:focus-visible { word-spacing: 3px; }\n")
    tdark = _override("theme-dark-only", "html[data-theme=dark] h1 { word-spacing: 2px; }\n")
    modal = _override("variant-only", "html.modal-is-open body { word-spacing: 2px; }\n")
    after = _override("after-only", "details summary::after { outline-offset: 7px; }\n")
    before = _override("before-only", "[aria-busy=true]::before { outline-offset: 7px; }\n")
    marker = _override("marker-only", "li::marker { color: rgb(1, 2, 3); }\n")
    fsb = _override("file-selector-button-only", "input[type=file]::file-selector-button { outline-offset: 7px; }\n")
    host = _override("shadow-only", ":host { accent-color: rgb(1, 2, 3); }\n")
    surface_css = _override("token-surface", ":root { --femto-zz-added: 1px; }\n")
    reg_dir = NEG / "registry"
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / "negative.json").write_text(json.dumps([
        {"id": "neg-h1-color", "module": "content/typography", "kind": "style", "selector": "h1, h1 *",
         "property": "*", "reference": "*", "femto": "*", "category": "natural-fix",
         "reason": "Negative control: suppress exactly the h1 color change."},
        {"id": "neg-h1-token", "module": "content/typography", "kind": "token", "token": "--femto-h1-color",
         "property": "*", "reference": "*", "femto": "*", "category": "natural-fix",
         "reason": "Negative control: suppress exactly the h1 color token change."},
        {"id": "neg-h1-token-raw", "module": "content/typography", "kind": "token-raw", "token": "--femto-h1-color",
         "reference": "#2d3138", "femto": "#2f3138", "category": "natural-fix",
         "reason": "Negative control: the raw text of the changed token."},
    ], indent=1))

    def pg(*names):
        return ["--pages", ",".join(names)]

    cases = []

    def case(name, argv, check, describe, states=False):
        cases.append({"name": name, "argv": argv, "check": check, "describe": describe, "states": states})

    def expect_zero(r):
        n = r["totals"]["differences"]
        return n == 0 and not r["harness_errors"], f"{n} differences, {len(r['harness_errors'])} errors"

    case("self", ["self", *pg("kitchen-sink.html"), "--widths", "1280", "--schemes", "light,dark"], expect_zero,
         "reference against itself: zero differences")
    case("chunk-control", ["hybrid", "--control", *pg("kitchen-sink.html"), "--widths", "1280", "--schemes", "light,dark"],
         expect_zero, "reference split at its banners and re-imported: zero differences")

    def color2(r):
        recs = [x for _, x in _records(r)]
        h1 = [x for x in recs if x["kind"] == "style" and x["label"].startswith("h1") and x["prop"] == "color"]
        tok = [x for x in recs if x["kind"] == "token" and x["token"] == "--femto-h1-color"]
        return bool(h1) and bool(tok), f"h1 color diffs {len(h1)}, token diffs {len(tok)}, total {r['totals']['unregistered']}"
    case("color-2-of-255", ["compare", "--ref", REF, "--test", h1_2, *pg("content-typography.html"), "--widths", "1280",
                            "--schemes", "light", "--dirs", "ltr", "--no-states"], color2,
         "h1 color #2d3138 -> #2f3138 (2/255 on red) is detected by style and token comparison")
    case("color-1-of-255", ["compare", "--ref", REF, "--test", h1_1, *pg("content-typography.html"), "--widths", "1280",
                            "--schemes", "light", "--dirs", "ltr", "--no-states"],
         lambda r: ((not any(x["kind"] in ("style", "token") for _, x in _records(r))) and
                    all(x["kind"] == "token-raw" for _, x in _records(r)),
                    f"{r['totals']['unregistered']} unregistered, kinds "
                    f"{sorted({x['kind'] for _, x in _records(r)})}"),
         "h1 color #2d3138 -> #2e3138 (1/255) is tolerated; only the raw token text differs")

    def hover_only(r):
        recs = [x for _, x in _records(r)]
        states = sorted({x.get("state") for x in recs})
        return states == ["hover"] and r["totals"]["unregistered"] > 0, f"states with diffs {states}"
    case("hover-only", ["compare", "--ref", REF, "--test", f"{REF},{hover}", *pg("content-link.html"), "--widths", "1280",
                        "--schemes", "light", "--dirs", "ltr"], hover_only,
         "a rule under :hover:not(:active) shows only in the hover state, never in the base snapshot", states=True)

    def dark_only(r):
        legs = sorted({c["scheme"] for c in r["cells"] if (c.get("result") or {}).get("unregisteredTotal")})
        if legs == ["dark"]:
            return True, f"legs with diffs {legs}"
        # Safari cannot run the media-dark leg: then nothing may differ and the leg must be a registered skip.
        dark = [c for c in r["cells"] if c["scheme"] == "dark"]
        skipped = dark and all(c.get("status") == "skipped" for c in dark) and all(s["entries"] for s in r["skipped_checks"])
        return (not legs and bool(skipped)), f"legs with diffs {legs}; media-dark cells skipped and registered: {bool(skipped)}"
    case("dark-only-token", ["compare", "--ref", REF, "--test", dark, *pg("content-typography.html"), "--widths", "1280",
                             "--all-legs", "--dirs", "ltr", "--no-states"], dark_only,
         "a token changed only in the prefers-color-scheme: dark block shows only in the media-dark leg")

    def mq577(r):
        ws = sorted({c["width"] for c in r["cells"] if (c.get("result") or {}).get("unregisteredTotal")})
        return ws == [576], f"widths with diffs {ws}"
    case("breakpoint-577", ["compare", "--ref", REF, "--test", mq, *pg("kitchen-sink.html"), "--widths", "575,576,577",
                            "--schemes", "light", "--dirs", "ltr", "--no-states"], mq577,
         "every (min-width: 576px) moved to 577px differs at width 576 only (not 575 or 577)")

    def rtl_only(r):
        dirs = sorted({c["dir"] for c in r["cells"] if (c.get("result") or {}).get("unregisteredTotal")})
        return dirs == ["rtl"], f"directions with diffs {dirs}"
    case("rtl-only", ["compare", "--ref", REF, "--test", f"{REF},{rtl}", *pg("kitchen-sink.html"), "--widths", "1280",
                      "--schemes", "light", "--dirs", "ltr,rtl", "--no-states"], rtl_only,
         "a rule under html[dir=rtl] shows only in the rtl run")

    def pseudo_only(name):
        def chk(r):
            ps = sorted({x.get("pseudo") for _, x in _records(r, {"style"})})
            return ps == [name], f"pseudo-elements with diffs {ps}"
        return chk
    case("placeholder", ["compare", "--ref", REF, "--test", f"{REF},{ph}", *pg("forms-basics.html"), "--widths", "1280",
                         "--schemes", "light", "--dirs", "ltr", "--no-states"], pseudo_only("::placeholder"),
         "a ::placeholder-only change is detected on ::placeholder")
    case("backdrop", ["compare", "--ref", REF, "--test", f"{REF},{bd}", *pg("components-modal-show.html"), "--widths", "1280",
                      "--schemes", "light", "--dirs", "ltr", "--no-states", "--variants", "plain"], pseudo_only("::backdrop"),
         "a ::backdrop-only change is detected on ::backdrop")

    def states_with_diffs(r):
        return sorted({x.get("state") for _, x in _records(r, {"style"})})

    def only_states(want):
        def chk(r):
            got = states_with_diffs(r)
            return got == want, f"states with diffs {got}"
        return chk
    case("active-only", ["compare", "--ref", REF, "--test", f"{REF},{active}", *pg("content-link.html"), "--widths", "1280",
                         "--schemes", "light", "--dirs", "ltr"], only_states(["active"]),
         "a rule under a:active shows only in the active state (pointer held down)", states=True)

    def focus_like(must, may):
        def chk(r):
            got = states_with_diffs(r)
            ok = must in got and set(got) <= set(may)
            return ok, f"states with diffs {got} (must include {must}, may include {sorted(may)})"
        return chk
    case("focus-only", ["compare", "--ref", REF, "--test", f"{REF},{focus}", *pg("content-link.html"), "--widths", "1280",
                        "--schemes", "light", "--dirs", "ltr"],
         focus_like("focus", {"focus", "focus-visible", "active"}),
         "a rule under a:focus shows in the focus state (and focus-visible, which is also :focus; active where a "
         "pointer press focuses links), never in the base snapshot or hover", states=True)
    case("focus-visible-only", ["compare", "--ref", REF, "--test", f"{REF},{fv}", *pg("content-link.html"), "--widths", "1280",
                                "--schemes", "light", "--dirs", "ltr"],
         focus_like("focus-visible", {"focus-visible", "focus"}),
         "a rule under a:focus-visible shows in the Tab-driven focus-visible state (and in focus where the browser's "
         "heuristics make programmatic focus visible), never in base, hover or active", states=True)

    def legs_only(want):
        def chk(r):
            legs = sorted({c["scheme"] for c in r["cells"] if (c.get("result") or {}).get("unregisteredTotal")})
            return legs == want, f"legs with diffs {legs}"
        return chk
    case("theme-dark-only", ["compare", "--ref", REF, "--test", f"{REF},{tdark}", *pg("content-typography.html"),
                             "--widths", "1280", "--all-legs", "--dirs", "ltr", "--no-states"], legs_only(["theme-dark"]),
         "a rule under html[data-theme=dark] shows only in the theme-dark leg (data-theme set on <html>)")

    def variant_only(r):
        vs = sorted({c["variant_label"] for c in r["cells"] if (c.get("result") or {}).get("unregisteredTotal")})
        ran = sorted({c["variant_label"] for c in r["cells"]})
        return vs == ["class=modal-is-open"] and "plain" in ran, f"variants with diffs {vs} of {ran}"
    case("variant-only", ["compare", "--ref", REF, "--test", f"{REF},{modal}", *pg("classes-modal.html"), "--widths", "1280",
                          "--schemes", "light", "--dirs", "ltr", "--no-states", "--variants", "plain,class=modal-is-open"],
         variant_only, "a rule under html.modal-is-open shows only in the class=modal-is-open page variant")
    case("after-only", ["compare", "--ref", REF, "--test", f"{REF},{after}", *pg("components-accordion.html"), "--widths", "1280",
                        "--schemes", "light", "--dirs", "ltr", "--no-states"], pseudo_only("::after"),
         "an ::after-only change is detected on ::after")
    case("before-only", ["compare", "--ref", REF, "--test", f"{REF},{before}", *pg("components-loading.html"), "--widths", "1280",
                         "--schemes", "light", "--dirs", "ltr", "--no-states"], pseudo_only("::before"),
         "a ::before-only change is detected on ::before")
    case("marker-only", ["compare", "--ref", REF, "--test", f"{REF},{marker}", *pg("content-typography.html"), "--widths", "1280",
                         "--schemes", "light", "--dirs", "ltr", "--no-states"], pseudo_only("::marker"),
         "a ::marker-only change is detected on ::marker")
    case("file-selector-button-only", ["compare", "--ref", REF, "--test", f"{REF},{fsb}", *pg("forms-input-file.html"),
                                       "--widths", "1280", "--schemes", "light", "--dirs", "ltr", "--no-states"],
         pseudo_only("::file-selector-button"), "a ::file-selector-button-only change is detected on ::file-selector-button")

    def shadow_only(r):
        recs = [x for _, x in _records(r)]
        inside = [x for x in recs if ">>>" in x.get("path", "")]
        outside = [x for x in recs if ">>>" not in x.get("path", "")]
        props = sorted({x.get("prop") for x in recs})
        ok = bool(inside) and props == ["accent-color"] and all(x["label"].startswith("div") for x in outside)
        return ok, (f"{len(inside)} records inside shadow trees, {len(outside)} on hosts "
                    f"({sorted({x['label'][:30] for x in outside})}), properties {props}")
    case("shadow-only", ["compare", "--ref", REF, "--test", f"{REF},{host}", *pg("kitchen-sink.html"), "--widths", "1280",
                         "--schemes", "light", "--dirs", "ltr", "--no-states"], shadow_only,
         "a :host rule (it only applies from stylesheets inside shadow roots) is detected on the shadow hosts and "
         "the shadow trees, nowhere else")

    def surface(r):
        recs = [x for _, x in _records(r)]
        kinds = sorted({x["kind"] for x in recs})
        toks = sorted({x.get("token") for x in recs})
        return kinds == ["surface-added"] and toks == ["--femto-zz-added"], f"kinds {kinds}, tokens {toks}"
    case("token-surface", ["compare", "--ref", REF, "--test", f"{REF},{surface_css}", *pg("content-typography.html"),
                           "--widths", "1280", "--schemes", "light", "--dirs", "ltr", "--no-states"], surface,
         "a token that only the test side declares is reported as surface-added and nothing else")

    def token_only(r):
        kinds = sorted({x["kind"] for _, x in _records(r)})
        toks = sorted({x["token"] for _, x in _records(r, {"token"})})
        return "style" not in kinds and toks == ["--femto-text-selection-color"], f"kinds {kinds}, tokens {toks}"
    case("token-resolution", ["compare", "--ref", REF, "--test", sel, *pg("content-typography.html"), "--widths", "1280",
                              "--schemes", "light", "--dirs", "ltr", "--no-states"], token_only,
         "--femto-text-selection-color (used only by ::selection, which no element style shows) is caught by token resolution")

    def registry(r, prior):
        recs = [x for _, x in _records(r)]
        h1 = [x for x in recs if (x.get("label", "").startswith("h1") or x.get("token") == "--femto-h1-color")]
        h2 = [x for x in recs if (x.get("label", "").startswith("h2") or x.get("token") == "--femto-h2-color")]
        used = r["registered_by_entry"]
        ok = not h1 and bool(h2) and used.get("neg-h1-color", 0) > 0 and used.get("neg-h1-token", 0) > 0
        msg = f"unregistered h1 {len(h1)}, h2 {len(h2)}; registered {used}"
        alone = prior.get("color-2-of-255")
        if alone:
            # The h1-only change of color-2-of-255 must be exactly what the entries absorbed here.
            n = alone["totals"]["unregistered"]
            ok = ok and sum(used.values()) == n
            msg += f"; h1-only control had {n} differences, entries absorbed {sum(used.values())}"
        return ok, msg
    case("registry-suppression", ["compare", "--registry", str(reg_dir), "--ref", REF, "--test", h1h2,
                                  *pg("content-typography.html"), "--widths", "1280", "--schemes", "light", "--dirs", "ltr",
                                  "--no-states"], registry,
         "an entry for the h1 change suppresses the h1 differences and nothing else (the h2 change stays unregistered)")

    def missing(r):
        errs = r["harness_errors"]
        return any("404" in e or "failed to load" in e for e in errs) and r["status"] == "FAIL", f"{len(errs)} errors"
    case("missing-stylesheet", ["compare", "--ref", REF, "--test", "/tests/build/negative/does-not-exist.css",
                                *pg("content-typography.html"), "--widths", "1280", "--schemes", "light", "--dirs", "ltr",
                                "--no-states"], missing, "a stylesheet that fails to load is a harness error")
    return cases


def run_selftest(args):
    run_id = args.run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-selftest"
    cases = build_cases()
    if args.cases:
        want = set(args.cases.split(","))
        cases = [c for c in cases if c["name"] in want]
    browsers = args.browsers or "chrome,firefox"
    if args.no_states:
        dropped = [c["name"] for c in cases if c["states"]]
        cases = [c for c in cases if not c["states"]]
        print(f"--no-states: leaving out the state controls {', '.join(dropped)}", flush=True)
        for c in cases:
            if "--no-states" not in c["argv"]:
                c["argv"] = c["argv"] + ["--no-states"]
    report, ok_all, prior = [], True, {}
    for c in cases:
        rid = f"{run_id}--{c['name']}"
        argv = [sys.executable, str(TESTS / "run.py"), *c["argv"], "--browsers", browsers, "--run-id", rid, "--no-shots"]
        t0 = time.time()
        p = subprocess.run(argv, capture_output=True, text=True)
        path = RESULTS / rid / "result.json"
        if not path.exists():
            ok, msg = False, f"no result.json (exit {p.returncode}): {p.stderr[-800:]}"
        else:
            r = json.loads(path.read_text())
            try:
                ok, msg = c["check"](r, prior) if c["name"] == "registry-suppression" else c["check"](r)
                prior[c["name"]] = r
            except Exception as e:
                ok, msg = False, f"check failed: {e!r}"
            if c["name"] not in ("missing-stylesheet",) and r["harness_errors"] and ok:
                ok, msg = False, msg + f"; harness errors: {r['harness_errors'][:3]}"
        ok_all &= ok
        line = f"{'PASS' if ok else 'FAIL'} {c['name']:22} {time.time() - t0:5.1f}s  {c['describe']}  [{msg}]"
        print(line, flush=True)
        report.append({"case": c["name"], "ok": ok, "detail": msg, "describe": c["describe"], "run": rid,
                       "browsers": browsers, "exit": p.returncode})
    d = RESULTS / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "selftest.json").write_text(json.dumps(report, indent=1))
    print(f"{'PASS' if ok_all else 'FAIL'}: {sum(r['ok'] for r in report)}/{len(report)} controls; wrote {d}/selftest.json")
    return 0 if ok_all else 1
