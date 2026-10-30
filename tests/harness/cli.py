"""Command line for the parity harness. Run `uv run tests/run.py --help`."""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

from . import build, matrix
from .paths import REFERENCE, REPO, RESULTS
from .registry import Registry

MODES_HELP = """modes:
  fast      one module's pages (or named sections): Chrome and Firefox, widths 390 and 1280, light and
            dark media, rtl on rtl pages. Hybrid build of the preset's reference with the module's
            sections replaced, unless --direct.
  full      the whole matrix (see tests/README.md); Chrome and Firefox in parallel, Safari serialized.
  compare   direct comparison of --ref against --test (or a preset's ref and test lists).
  self      a reference against itself (proves the harness finds no difference).
  hybrid    a preset's reference against a hybrid build (--sections/--modules), or --control.
            --full-plan uses the full matrix's cells and reductions instead of the fast axes.
  coverage  selector coverage of a stylesheet over the fixture pages.
  rig       verify the browser mechanisms and print what each browser supports.
  registry  validate tests/divergences/*.json.
  build     write a hybrid entry and print its URL.
  selftest  negative controls that prove detection (2/255 vs 1/255 colors, hover-only, dark-only,
            breakpoint, rtl-only, ::placeholder, ::backdrop, token-only, registry suppression).
"""


def csv(s):
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


def ints(s):
    return [int(x) for x in csv(s)]


def add_common(p, fast_defaults=True):
    p.add_argument("--browsers", help="comma list of chrome, firefox, safari (default chrome,firefox)")
    p.add_argument("--presets", help="comma list of presets from tests/variants.json")
    p.add_argument("--pages", help="comma list of page files (default: from the manifest)")
    p.add_argument("--widths", help="comma list of iframe widths")
    p.add_argument("--schemes", help="comma list of legs: light, dark, theme-light, theme-dark")
    p.add_argument("--dirs", help="comma list: ltr, rtl (rtl runs on rtl pages only)")
    p.add_argument("--variants", help="comma list of page variant labels (plain, class=modal-is-open, ...)")
    p.add_argument("--no-states", action="store_true", help="skip interactive states")
    p.add_argument("--no-shots", action="store_true", help="skip screenshots")
    p.add_argument("--workers", help="sessions per browser, e.g. chrome=2,firefox=2 (Safari is always 1)")
    p.add_argument("--max-records", type=int, default=300, help="unregistered records kept per cell")
    p.add_argument("--run-id", help="name of the results folder (default: timestamp-mode-pid)")
    p.add_argument("--label", help="free text stored in result.json")
    p.add_argument("--registry", help="registry directory (default tests/divergences)")


def parse(argv):
    ap = argparse.ArgumentParser(prog="uv run tests/run.py", description="femto parity harness",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=MODES_HELP)
    sub = ap.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("fast", help="one module's pages, Chrome and Firefox, two widths, light and dark")
    add_common(p)
    p.add_argument("--modules", help="module ids, e.g. forms/basics,content/button")
    p.add_argument("--sections", help="2.1.1 banner titles separated by ';', e.g. 'Basics form elements;Input type file'")
    p.add_argument("--direct", action="store_true", help="compare the preset's test list instead of a hybrid build")
    p.add_argument("--kitchen-sink", action="store_true", help="also run the kitchen sink")

    p = sub.add_parser("full", help="the whole matrix")
    add_common(p)
    p.add_argument("--self", action="store_true", help="compare every preset's reference against itself")
    p.add_argument("--control", action="store_true",
                   help="compare every preset's reference against its chunk control (split at its banners and re-imported); "
                        "presets without hybrid settings (colors) are left out")
    p.add_argument("--states-only", action="store_true",
                   help="keep only the cells that run interactive states (e.g. a Safari states pass after a --no-states run)")
    p.add_argument("--stateless-only", action="store_true",
                   help="keep only the cells that run no interactive states (with a --states-only run, the whole matrix)")

    for name, hlp in (("compare", "direct comparison"), ("self", "reference against itself"),
                      ("hybrid", "reference against a hybrid build")):
        p = sub.add_parser(name, help=hlp)
        add_common(p)
        p.add_argument("--ref", help="comma list of reference stylesheet URLs (overrides the preset)")
        p.add_argument("--test", help="comma list of test stylesheet URLs (compare only)")
        p.add_argument("--entry", help="page entry filter when --ref is given (default, colors)")
        p.add_argument("--full-widths", action="store_true", help="every width of the full matrix")
        p.add_argument("--all-legs", action="store_true", help="all four scheme legs")
        if name == "hybrid":
            p.add_argument("--modules")
            p.add_argument("--sections", help="banner titles separated by ';'")
            p.add_argument("--control", action="store_true", help="no section replaced (chunk control)")
            p.add_argument("--full-plan", action="store_true",
                           help="the full matrix's cells for the chosen presets (default: default), as full mode plans "
                                "them, instead of the fast axes or --full-widths/--all-legs")

    p = sub.add_parser("coverage", help="selector coverage of a stylesheet")
    p.add_argument("--css", required=True, help="stylesheet URL or path, e.g. /tests/reference/femto.css")
    p.add_argument("--entry", default="default")
    p.add_argument("--pages")
    p.add_argument("--run-id")

    p = sub.add_parser("selftest", help="negative and positive controls proving detection")
    p.add_argument("--browsers", help="default chrome,firefox")
    p.add_argument("--cases", help="comma list of case names")
    p.add_argument("--no-states", action="store_true", help="run every case without interactive states (drops hover-only)")
    p.add_argument("--run-id")

    p = sub.add_parser("rig", help="verify browser mechanisms")
    p.add_argument("--browsers", default="chrome,firefox,safari")
    p.add_argument("--run-id")

    sub.add_parser("registry", help="validate the divergence registry")

    p = sub.add_parser("build", help="write a hybrid entry")
    p.add_argument("--preset", default="default")
    p.add_argument("--sections", help="banner titles separated by ';'")
    p.add_argument("--modules")
    p.add_argument("--control", action="store_true")
    return ap.parse_args(argv)


def git_info():
    def g(*a):
        try:
            return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    return {"commit": g("rev-parse", "HEAD"), "branch": g("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": len(g("status", "--porcelain").splitlines())}


def make_opts(args, mode):
    workers = {"chrome": 1, "firefox": 1, "safari": 1}
    if mode == "full":
        workers.update(chrome=2, firefox=2)
    for kv in csv(getattr(args, "workers", None)):
        k, _, v = kv.partition("=")
        workers[k] = int(v)
    run_id = getattr(args, "run_id", None) or f"{time.strftime('%Y%m%d-%H%M%S')}-{mode}-{os.getpid()}"
    return SimpleNamespace(
        run_id=run_id, workers=workers,
        states=not getattr(args, "no_states", False), shots=not getattr(args, "no_shots", False),
        max_records=getattr(args, "max_records", 300),
    )


def semis(s):
    """Section titles are separated by ';' because titles contain commas."""
    return [x.strip() for x in s.split(";") if x.strip()] if s else []


def wanted_sections(args, pr):
    """Section titles to replace for fast and hybrid modes (None for --control)."""
    h = pr.get("hybrid") or {}
    if getattr(args, "control", False):
        return []
    if getattr(args, "sections", None):
        return semis(args.sections)
    if getattr(args, "modules", None):
        return build.modules_to_sections(h.get("sections", pr["entry"]), csv(args.modules))
    return None


def resolve_tests(args, preset_name, pr, mode, caps, titles=None):
    """(comparison kind, ref list, test list) for a preset under this mode."""
    ref = csv(args.ref) if getattr(args, "ref", None) else pr["ref"]
    if mode == "self" or (mode == "full" and getattr(args, "self", False)):
        return "self", ref, ref
    if mode == "full" and getattr(args, "control", False):
        h = pr.get("hybrid")
        if not h or len(ref) != 1:
            raise build.BuildError(f"preset {preset_name} has no chunk control (no hybrid settings)")
        url = build.hybrid(ref[0], h["sections"], [], h.get("append", []))
        caps.append(f"{preset_name}: chunk control {url}")
        return "control", ref, [url]
    if mode in ("compare", "full") or (mode == "fast" and args.direct):
        test = csv(args.test) if getattr(args, "test", None) else pr["test"]
        return "direct", ref, test
    h = pr.get("hybrid")
    if not h:
        raise build.BuildError(f"preset {preset_name} has no hybrid settings")
    if len(ref) != 1:
        raise build.BuildError("hybrid builds need a single reference stylesheet")
    if titles is None:
        raise build.BuildError("hybrid needs --sections, --modules or --control")
    url = build.hybrid(ref[0], h["sections"], titles, h.get("append", []))
    caps.append(f"{preset_name}: hybrid {url} replaces {'; '.join(titles) if titles else 'nothing (chunk control)'}")
    return ("hybrid" if titles else "control"), ref, [url]


def plan(args, mode, caps):
    presets = matrix.load_presets()
    pages = matrix.load_pages()
    browsers = csv(args.browsers) or ["chrome", "firefox"]
    names = csv(args.presets)
    for n in names:
        if n not in presets:
            raise SystemExit(f"unknown preset {n}; see tests/variants.json")
    if mode == "full":
        if not args.browsers:
            browsers = ["chrome", "firefox", "safari"]
        if getattr(args, "self", False) and getattr(args, "control", False):
            raise SystemExit("full takes --self or --control, not both")
        if getattr(args, "control", False) and not names:
            names = [n for n, pr in presets.items() if pr.get("hybrid")]
            caps.append("full --control: presets without hybrid settings have no banner sections and no chunk control: "
                        + ", ".join(n for n, pr in presets.items() if not pr.get("hybrid")))
        cells = matrix.full_cells(browsers, presets, pages, lambda n, pr: resolve_tests(args, n, pr, mode, caps), caps,
                                  preset_filter=names or None)
        return filter_cells(args, cells, caps)
    if mode == "hybrid" and getattr(args, "full_plan", False):
        if getattr(args, "full_widths", False) or getattr(args, "all_legs", False):
            raise SystemExit("--full-plan sets the widths and legs itself; drop --full-widths and --all-legs")
        if getattr(args, "ref", None):
            raise SystemExit("--full-plan takes --presets, not --ref")
        cells = matrix.full_cells(browsers, presets, pages,
                                  lambda n, pr: resolve_tests(args, n, pr, mode, caps, wanted_sections(args, pr)),
                                  caps, preset_filter=names or ["default"])
        return filter_cells(args, cells, caps)
    widths = ints(args.widths) or (matrix.ALL_WIDTHS if getattr(args, "full_widths", False) else matrix.FAST_WIDTHS)
    legs = csv(args.schemes) or (matrix.ALL_LEGS if getattr(args, "all_legs", False) else ["light", "dark"])
    for leg in legs:
        if leg not in matrix.LEGS:
            raise SystemExit(f"unknown scheme leg {leg}")
    dirs = csv(args.dirs) or ["ltr", "rtl"]
    variants = csv(args.variants) or None
    cells = []
    if mode in ("compare", "self", "hybrid") and getattr(args, "ref", None) and not names:
        entry = args.entry or "default"
        pr = {"entry": entry, "ref": csv(args.ref), "test": csv(args.test) if args.test else csv(args.ref),
              "hybrid": {"sections": entry}}
        names, presets = ["custom"], {"custom": pr}
    if not names:
        names = ["default"]
    for name in names:
        pr = presets[name]
        titles = wanted_sections(args, pr) if mode in ("fast", "hybrid") else None
        if mode == "fast":
            if not (titles or args.pages):
                raise SystemExit("fast needs --modules, --sections or --pages")
            pg = matrix.pages_for(pages, pr["entry"], names=csv(args.pages) or None,
                                  modules=csv(args.modules) or None, sections=titles or None)
            if args.kitchen_sink:
                pg += [p for p in matrix.pages_for(pages, pr["entry"], names=[matrix.KITCHEN_SINK]) if p not in pg]
            if not titles and not args.direct:
                raise SystemExit("fast with only --pages needs --direct (or name --modules/--sections)")
        else:
            pg = matrix.pages_for(pages, pr["entry"], names=csv(args.pages) or None)
        if not pg:
            raise SystemExit(f"no pages for preset {name} (entry {pr['entry']})")
        comparison, ref, test = resolve_tests(args, name, pr, mode, caps, titles)
        cells += matrix.simple_cells(browsers, name, comparison, pr["entry"], pg, ref, test, widths, legs, dirs,
                                     states=True, shots=True, variants=variants)
    return filter_cells(args, cells, caps)


def filter_cells(args, cells, caps):
    full = args.mode == "full" or getattr(args, "full_plan", False)
    pages = set(csv(args.pages)) if getattr(args, "pages", None) and full else None
    widths = set(ints(args.widths)) if full and args.widths else None
    legs = set(csv(args.schemes)) if full and args.schemes else None
    dirs = set(csv(args.dirs)) if full and args.dirs else None
    variants = set(csv(args.variants)) if full and args.variants else None
    states_only = full and getattr(args, "states_only", False)
    stateless_only = full and getattr(args, "stateless_only", False)
    out = [c for c in cells if (not pages or c["page"] in pages) and (not widths or c["width"] in widths)
           and (not legs or c["scheme"] in legs) and (not dirs or c["dir"] in dirs)
           and (not variants or c["variant_label"] in variants) and (not states_only or c["states"])
           and (not stateless_only or not c["states"])]
    if len(out) != len(cells):
        caps.append(f"command-line filters kept {len(out)} of {len(cells)} cells")
    return out


def run_compare(args, mode):
    from .report import build as build_result, summary
    from .runner import Pool
    from .server import Server
    caps = []
    from pathlib import Path
    registry = Registry(Path(args.registry)) if getattr(args, "registry", None) else Registry()
    if registry.errors:
        print("registry errors:\n  " + "\n  ".join(registry.errors), file=sys.stderr)
    try:
        cells = plan(args, mode, caps)
    except (build.BuildError, matrix.MatrixError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except SystemExit as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not cells:
        print("error: no cells to run", file=sys.stderr)
        return 2
    opts = make_opts(args, mode)
    run_dir = RESULTS / opts.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_f = open(run_dir / "log.txt", "a")

    def log(msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        log_f.write(line + "\n")
        log_f.flush()

    for c in caps:
        log(f"cap: {c}")
    log(f"run {opts.run_id}: {len(cells)} cells; workers {opts.workers}; results in {run_dir.relative_to(REPO)}")
    server = Server()
    t0 = time.time()
    pool = Pool(cells, registry, opts, run_dir, server, log)
    results = pool.run()
    missing = [m for m in server.take_missing() if not m.startswith("/favicon.ico")]
    server.close()
    run = {"run_id": opts.run_id, "mode": mode, "argv": sys.argv[1:], "label": getattr(args, "label", None),
           "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)), "duration_s": round(time.time() - t0, 1),
           "git": git_info(), "workers": opts.workers, "registry_files": registry.files}
    results.sort(key=lambda r: (r["browser"], r["preset"], r["page"], r["variant_label"], r["dir"], r["width"], r["scheme"]))
    result = build_result(run, results, registry, pool.errors, pool.rigs, sorted(set(missing)), caps)
    (run_dir / "result.json").write_text(json.dumps(result, indent=1))
    text = summary(result)
    (run_dir / "summary.txt").write_text(text)
    print(text)
    log(f"wrote {run_dir.relative_to(REPO)}/result.json and summary.txt")
    log_f.close()
    return 0 if result["status"] == "PASS" else 1


def run_registry():
    reg = Registry()
    print(f"{len(reg.entries)} entries in {len(reg.files)} files: {', '.join(reg.files)}")
    for e in reg.entries:
        print(f"  {e.get('id')}: {e.get('kind')} {e.get('category')} ({e['_file']})")
    if reg.errors:
        print("errors:")
        for e in reg.errors:
            print(f"  {e}")
        return 1
    print("registry valid")
    return 0


def run_build(args):
    presets = matrix.load_presets()
    pr = presets[args.preset]
    h = pr["hybrid"]
    titles = wanted_sections(args, pr)
    if titles is None:
        raise SystemExit("build needs --sections, --modules or --control")
    print(build.hybrid(pr["ref"][0], h["sections"], titles, h.get("append", [])))
    return 0


def ensure_references():
    """Rebuild the 21 renamed 2.1.1 copies from the tag when any is missing (they are gitignored)."""
    spec = importlib.util.spec_from_file_location("build_references", REFERENCE / "build_references.py")
    refs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(refs)
    if all((REFERENCE / name).exists() for name in refs.COPIES):
        return
    print(f"rebuilding the renamed copies in tests/reference/ from tag {refs.TAG}")
    try:
        status = refs.cmd_copies(None)
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"cannot read tag {refs.TAG}: {e.stderr.decode().strip()} (run git fetch --tags)") from None
    if status:
        raise SystemExit("the rebuilt references fail build_references.py check")


def main(argv=None):
    args = parse(argv if argv is not None else sys.argv[1:])
    if args.mode == "registry":
        return run_registry()
    ensure_references()
    if args.mode == "build":
        return run_build(args)
    if args.mode == "rig":
        from .rig import run_rig
        return run_rig(args)
    if args.mode == "selftest":
        from .negative import run_selftest
        return run_selftest(args)
    if args.mode == "coverage":
        from .coverage import run_coverage
        return run_coverage(args)
    return run_compare(args, args.mode)
