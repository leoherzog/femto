"""One comparison cell: load the reference, collect, load the test side in a fresh iframe, collect,
diff in the page, replay interactive states on both sides, then screenshot both sides."""
import io
import time

from .browsers import FRAME_HEIGHT, RigError
from .matrix import page_url


def _merge(total, part):
    if not part:
        return
    total["total"] += part.get("total", 0)
    total["unregisteredTotal"] += part.get("unregisteredTotal", 0)
    room = total["_cap"] - len(total["unregistered"])
    if room > 0:
        total["unregistered"].extend(part.get("unregistered", [])[:room])
    for k, n in part.get("registered", {}).items():
        total["registered"][k] = total["registered"].get(k, 0) + n
    for k, s in part.get("samples", {}).items():
        cur = total["samples"].setdefault(k, [])
        cur.extend(s[: max(0, 2 - len(cur))])
    for k, n in part.get("counts", {}).items():
        total["counts"][k] = total["counts"].get(k, 0) + n


def apply_state(sess, side, target, state):
    """Apply one state with real input, collect (and on the test side diff) the module subtree.

    Pointer states retry once when the state did not match, after letting scrolling settle."""
    i = target["el"]
    key = f"{i}|{state}"
    info, extra = None, {}
    if state in ("hover", "active"):
        for attempt in range(2):
            if attempt:
                time.sleep(0.15)
            p = sess.ajs("pointAt", i)
            extra = {"hit": p["hit"], "hitLabel": p["hitLabel"], "retries": attempt}
            if p.get("outside"):
                info = {"matched": False}
                continue
            if state == "hover":
                sess.move(p["x"], p["y"])
                info = sess.ajs("afterState", side, i, state, key)
            else:
                sess.press(p["x"], p["y"])
                try:
                    info = sess.ajs("afterState", side, i, state, key)
                finally:
                    sess.release(p["x"], p["y"])
            sess.park()
            if info.get("matched"):
                break
            sess.js("resetState")
    elif state == "focus":
        sess.js("focusEl", i)
        info = sess.ajs("afterState", side, i, state, key)
    elif state == "focus-visible":
        prep = sess.js("prepTab", i, 1)
        sess.tab()
        info = sess.ajs("afterState", side, i, state, key)
        extra = {"method": "tab", "from": prep.get("from")}
        if not info["matched"]:
            sess.js("resetState")
            prep = sess.js("prepTab", i, -1)
            sess.tab(shift=True)
            info = sess.ajs("afterState", side, i, state, key)
            extra = {"method": "shift-tab", "from": prep.get("from")}
        if not info["matched"] and sess.browser == "safari":
            # Safari's Option+Tab never lands on summary or input[type=color]. Right after those
            # key presses (keyboard modality) a programmatic focus() matches :focus-visible there.
            sess.js("resetState")
            sess.js("focusEl", i)
            info = sess.ajs("afterState", side, i, state, key)
            extra = {"method": "focus-after-tab"}
    else:
        return {"matched": False, "error": f"unknown state {state!r} in data-states"}
    sess.js("resetState")
    info.update(extra)
    return info


def run_cell(sess, cell, registry, opts, shot_path=None):
    """Run one cell and return its result record (cell fields plus result, errors, skipped, timing)."""
    t0 = time.time()
    out = dict(cell)
    out.update(errors=[], skipped=[], timing={}, states_run=0, elements=None)
    res = {"total": 0, "unregisteredTotal": 0, "unregistered": [], "registered": {}, "samples": {}, "counts": {},
           "_cap": opts.max_records}
    media, theme = cell["media"], cell["theme"]

    # Safari cannot emulate prefers-color-scheme: run the OS scheme and register the missing leg.
    if sess.browser == "safari" and media != sess.os_scheme:
        out["skipped"].append(f"media:{media}")
        if theme is None:
            out["status"] = "skipped"
            out["timing"]["total"] = round(time.time() - t0, 2)
            res.pop("_cap", None)
            out["result"] = res
            return out
        media = sess.os_scheme
        out["media_used"] = media
    for ps in sess.unsupported_pseudos:
        out["skipped"].append(f"pseudo:{ps}")

    try:
        sess.set_media(media)
    except RigError as e:
        out["errors"].append(f"rig: {e}")
        out["status"] = "error"
        res.pop("_cap", None)
        out["result"] = res
        return out

    conf = sess.js("configure", {"entries": registry.for_cell(cell), "maxRecords": opts.max_records,
                                 "pseudos": sess.pseudos})
    out["errors"] += conf.get("errors", [])
    do_states = cell["states"] and opts.states
    if do_states and not sess.can_interact:
        do_states = False
        out["states_blocked"] = sess.interact_reason
    elif do_states and sess.browser == "safari":
        # The Safari window can lose focus mid-run (another app comes to the front, the screen
        # locks); pointer and focus states then cannot match, so check before every cell.
        ok, why = sess.interactive()
        if not ok:
            do_states = False
            out["states_blocked"] = why
    pngs = {}
    targets = None
    for side in ("ref", "test"):
        ts = time.time()
        url = page_url(cell, cell[side], theme)
        ld = sess.ajs("load", url, cell["width"], FRAME_HEIGHT, {"media": media, "theme": theme})
        out["errors"] += [f"{side} load: {e}" for e in ld.get("errors", [])]
        if "elements" not in ld:
            out["status"] = "error"
            res.pop("_cap", None)
            out["result"] = res
            return out
        col = sess.ajs("collect", side)
        out["errors"] += [f"{side} collect: {e}" for e in col.get("errors", [])]
        out["timing"][f"{side}_load"] = round(ld["ms"] / 1000, 2)
        out["timing"][f"{side}_styles"] = round(col["msStyles"] / 1000, 2)
        out["timing"][f"{side}_tokens"] = round(col["msTokens"] / 1000, 2)
        if side == "ref":
            out["elements"] = col["elements"]
            out["pseudo_elements"] = col["pseudo"]
            out["tokens"] = col["tokens"]
            out["anchors"] = col["anchors"]
            out["token_groups"] = col["groups"]
        if side == "test":
            d = sess.js("diff")
            out["errors"] += [f"diff: {e}" for e in d.get("errors", [])]
            _merge(res, d)
            out["timing"]["diff"] = round(d.get("ms", 0) / 1000, 2)
        if do_states:
            tss = time.time()
            got = sess.js("stateTargets")
            if side == "ref":
                targets = got
            elif [(t["el"], t["states"]) for t in got] != [(t["el"], t["states"]) for t in targets]:
                out["errors"].append("state targets differ between sides")
            for tg in targets:
                for st in tg["states"]:
                    info = apply_state(sess, side, tg, st)
                    if side == "ref":
                        out["states_run"] += 1
                    if not info.get("matched"):
                        # A state the browser can never give this kind of element (Safari:
                        # :focus-visible on input[type=date]) is a skipped check when registered.
                        check = f"state:{st}:{tg.get('tag', '')}" + (f"[type={tg['type']}]" if tg.get("type") else "")
                        if not info.get("error") and registry.match_skipped(check, cell):
                            if check not in out["skipped"]:
                                out["skipped"].append(check)
                            continue
                        why = info.get("error") or (f"not hit-testable, covered by {info.get('hitLabel')}"
                                                    if info.get("hit") is False else "")
                        out["errors"].append(f"{side} state {st} did not match on {tg['label']} at {tg['path']}"
                                             + (f" ({why})" if why else ""))
                    if side == "test" and info.get("result"):
                        out["errors"] += [f"state diff: {e}" for e in info["result"].get("errors", [])]
                        _merge(res, info["result"])
                    if info.get("error"):
                        out["errors"].append(f"{side} state {st} on {tg['label']}: {info['error']}")
                    for e in info.get("errors", []):
                        out["errors"].append(f"{side} state {st} on {tg['label']}: {e}")
            out["timing"][f"{side}_states"] = round(time.time() - tss, 2)
        if cell["shots"] and opts.shots:
            sess.ajs("prepShot")
            pngs[side] = sess.frame_png()
            sess.js("unmask")
        out["timing"][side] = round(time.time() - ts, 2)
    if len(pngs) == 2:
        out["pixels"] = pixel_diff(pngs["ref"], pngs["test"], shot_path)
    res.pop("_cap", None)
    out["result"] = res
    out["status"] = "ok"
    out["timing"]["total"] = round(time.time() - t0, 2)
    return out


def pixel_diff(a: bytes, b: bytes, path=None):
    """Count differing pixels between two PNGs; save ref, test and a diff mask when any differ."""
    from PIL import Image, ImageChops
    ia, ib = Image.open(io.BytesIO(a)).convert("RGB"), Image.open(io.BytesIO(b)).convert("RGB")
    if ia.size != ib.size:
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            ia.save(path.with_name(path.stem + "-ref.png"))
            ib.save(path.with_name(path.stem + "-test.png"))
        return {"pixels": -1, "size": [list(ia.size), list(ib.size)]}
    d = ImageChops.difference(ia, ib)
    if not d.getbbox():
        return {"pixels": 0}
    r, g, bl = d.split()
    m = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    hist = m.histogram()
    px = sum(hist[1:])
    out = {"pixels": px, "pixels_gt8": sum(hist[9:]), "bbox": list(d.getbbox())}
    # Chrome's raster differs by 1/255 in places from load to load; keep images only for real changes.
    if path and out["pixels_gt8"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        m.point(lambda v: 255 if v else 0).save(path)
        ia.save(path.with_name(path.stem + "-ref.png"))
        ib.save(path.with_name(path.stem + "-test.png"))
        out["image"] = str(path)
    return out
