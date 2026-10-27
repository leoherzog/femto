"""result.json and summary.txt for a run, and the exit status."""
import collections
import json
import time


def _fmt_rec(r):
    if r["kind"] == "style":
        ps = r.get("pseudo") or ""
        return f"{r.get('state', 'base')}: {r['label']} {ps} {r['prop']}: {r['ref']!r} -> {r['test']!r}  @ {r['path']}"
    if r["kind"] == "token":
        return f"token {r['token']} via {r['prop']} at {r['label']}: {r['ref']!r} -> {r['test']!r}"
    if r["kind"] == "token-raw":
        return f"token-raw {r['token']} at {r['label']}: {r['ref']!r} -> {r['test']!r}"
    if r["kind"] in ("surface-added", "surface-missing"):
        return f"{r['kind']} {r['token']}"
    return json.dumps(r)


def cell_name(c):
    return f"{c['browser']} {c['preset']} {c['page']} {c['variant_label']} {c['scheme']} {c['width']} {c['dir']}"


def build(run, cells, registry, pool_errors, rigs, missing, caps, extra=None):
    """Aggregate cell records into the run result."""
    unreg_cells, errors, skipped = [], [], collections.OrderedDict()
    blocked = {}
    registered = collections.Counter()
    per_group = collections.OrderedDict()
    pixels = []
    unregistered_total = 0
    for c in cells:
        res = c.get("result") or {}
        ut = res.get("unregisteredTotal", 0)
        unregistered_total += ut
        if ut:
            unreg_cells.append(c)
        for e in c.get("errors", []):
            errors.append(f"{cell_name(c)}: {e}")
        if c.get("states_blocked"):
            blocked.setdefault((c["browser"], c["states_blocked"]), []).append(cell_name(c))
        for chk in c.get("skipped", []):
            ids = registry.match_skipped(chk, c)
            key = (chk, c["browser"], tuple(ids))
            s = skipped.setdefault(key, {"check": chk, "browser": c["browser"], "entries": ids, "cells": 0})
            s["cells"] += 1
            for i in ids:
                registry.hits[i] = registry.hits.get(i, 0) + 1
        registered.update(res.get("registered", {}))
        g = (c["browser"], c["preset"], c["page"])
        pg = per_group.setdefault(g, {"cells": 0, "unregistered": 0, "registered": 0, "errors": 0, "pixel_cells": 0,
                                      "skipped_cells": 0, "seconds": 0.0})
        pg["cells"] += 1
        pg["unregistered"] += ut
        pg["registered"] += res.get("total", 0) - ut
        pg["errors"] += len(c.get("errors", []))
        pg["skipped_cells"] += c.get("status") == "skipped"
        pg["seconds"] += c.get("timing", {}).get("total", 0) or 0
        px = (c.get("pixels") or {}).get("pixels")
        if px:
            pg["pixel_cells"] += 1
            pixels.append({"cell": cell_name(c), **c["pixels"]})
    for (browser, why), names in blocked.items():
        errors.append(f"{browser}: interactive states not run in {len(names)} cells that ask for them "
                      f"(first: {names[0]}): {why}")
    for m in missing:
        errors.append(f"HTTP 404 for {m}")
    errors += pool_errors
    errors += [f"registry: {e}" for e in registry.errors]
    unregistered_skips = [s for s in skipped.values() if not s["entries"]]
    status = "PASS" if not (unregistered_total or errors or unregistered_skips) else "FAIL"
    samples = {}
    for c in cells:
        for k, s in ((c.get("result") or {}).get("samples") or {}).items():
            cur = samples.setdefault(k, [])
            for r in s:
                if len(cur) < 3:
                    cur.append(dict(r, cell=cell_name(c)))
    slim = []
    for c in cells:
        d = {k: v for k, v in c.items() if k != "result"}
        res = c.get("result") or {}
        d["result"] = {k: v for k, v in res.items() if k != "samples"}
        slim.append(d)
    return {
        **run,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": status,
        "totals": {
            "cells": len(cells),
            "cells_by_browser": dict(collections.Counter(c["browser"] for c in cells)),
            "differences": sum((c.get("result") or {}).get("total", 0) for c in cells),
            "unregistered": unregistered_total,
            "unregistered_cells": len(unreg_cells),
            "registered": sum(registered.values()),
            "harness_errors": len(errors),
            "unregistered_skipped_checks": len(unregistered_skips),
            "pixel_diff_cells": len(pixels),
            "pixel_diff_cells_gt8": sum(1 for p in pixels if p.get("pixels_gt8")),
            "states_run": sum(c.get("states_run", 0) for c in cells),
        },
        "caps": caps,
        "rig": rigs,
        "harness_errors": errors,
        "skipped_checks": list(skipped.values()),
        "registered_by_entry": dict(registered),
        "registered_samples": samples,
        "unused_entries": registry.unused(),
        "pixels": pixels,
        "groups": [{"browser": b, "preset": p, "page": pg, **v} for (b, p, pg), v in per_group.items()],
        "cells": slim,
        **(extra or {}),
    }


def summary(result, limit=40) -> str:
    t = result["totals"]
    L = []
    L.append(f"femto parity {result['run_id']}  mode={result['mode']}  {result['status']}")
    L.append(f"{result.get('duration_s', 0):.0f}s, {t['cells']} cells " +
             "(" + ", ".join(f"{b} {n}" for b, n in t["cells_by_browser"].items()) + f"), {t['states_run']} states")
    L.append(f"differences {t['differences']}: unregistered {t['unregistered']} in {t['unregistered_cells']} cells, "
             f"registered {t['registered']}")
    L.append("")
    shown = 0
    if t["unregistered"]:
        L.append("UNREGISTERED DIFFERENCES (first per cell):")
        for c in result["cells"]:
            res = c.get("result") or {}
            if not res.get("unregisteredTotal"):
                continue
            L.append(f"  {cell_name(c)}: {res['unregisteredTotal']}")
            for r in res.get("unregistered", [])[:5]:
                L.append(f"    {_fmt_rec(r)}")
            shown += 1
            if shown >= limit:
                L.append(f"  ... see result.json")
                break
        L.append("")
    errs = result["harness_errors"]
    L.append(f"HARNESS ERRORS: {len(errs)}")
    for e in errs[:limit]:
        L.append(f"  {e[:400]}")
    if len(errs) > limit:
        L.append(f"  ... {len(errs) - limit} more in result.json")
    L.append("")
    L.append(f"SKIPPED CHECKS: {len(result['skipped_checks'])}")
    for s in result["skipped_checks"]:
        reg = ", ".join(s["entries"]) if s["entries"] else "UNREGISTERED"
        L.append(f"  {s['browser']} {s['check']}: {s['cells']} cells, {reg}")
    L.append("")
    L.append(f"REGISTERED BY ENTRY: {len(result['registered_by_entry'])}")
    for k, n in sorted(result["registered_by_entry"].items()):
        L.append(f"  {k}: {n}")
    L.append("")
    un = result["unused_entries"]
    L.append(f"UNUSED REGISTRY ENTRIES: {len(un)}")
    for u in un:
        L.append(f"  {u['id']} ({u['file']}, {u['kind']})")
    L.append("")
    if result["caps"]:
        L.append("MATRIX CAPS:")
        for c in result["caps"]:
            L.append(f"  {c}")
        L.append("")
    L.append(f"PIXEL DIFFS (reported, not gating): {t['pixel_diff_cells_gt8']} cells with pixels off by more than "
             f"8/255, {t['pixel_diff_cells']} with any difference")
    for p in sorted(result["pixels"], key=lambda p: -p.get("pixels_gt8", 0))[:10]:
        L.append(f"  {p['cell']}: {p.get('pixels_gt8', 0)} px > 8/255, {p['pixels']} px in all")
    L.append("")
    L.append("PER BROWSER / PRESET / PAGE:")
    for g in result["groups"]:
        L.append(f"  {g['browser']:7} {g['preset']:28} {g['page']:36} cells {g['cells']:4}  unreg {g['unregistered']:5}  "
                 f"reg {g['registered']:6}  err {g['errors']:3}  px {g['pixel_cells']:3}  {g['seconds']:7.1f}s")
    return "\n".join(L) + "\n"
