"""`run.py coverage`: which selectors of a stylesheet match nothing on the fixture pages.

For every style rule (inside @media, @supports and other conditional blocks too, and nested rules
resolved against their parent), each selector in the list is stripped of dynamic pseudo-classes and
pseudo-elements and evaluated with querySelectorAll on every page of the entry, in every manifest
variant and in rtl for rtl pages, plus the shadow roots of [data-shadow] hosts. Selectors that match
nothing anywhere are reported per 2.1.1 banner section; the files a stylesheet @imports are parsed
in its place and reported per file, so css/femto.css reports by module. Rules with :hover, :active,
:focus, :focus-visible or :focus-within are also checked against data-states: the element that
carries the pseudo-class (or, for hover, active and focus-within, one of its descendants) must
declare a matching state somewhere.
"""
import json
import re
import time

from . import locks
from .browsers import FRAME_HEIGHT
from .build import banners
from .matrix import load_pages, pages_for, variant_label
from .paths import REPO, RESULTS
from .runner import start_session
from .server import Server

DYNAMIC_STATES = ("focus-visible", "focus-within", "focus", "hover", "active")
DYNAMIC_OTHER = ("visited", "target", "user-invalid", "user-valid", "autofill", "link", "any-link")
SKIP_BLOCK_AT = ("@keyframes", "@-webkit-keyframes", "@font-face", "@property", "@page", "@counter-style",
                 "@font-feature-values", "@view-transition")


def _strip_comments(css):
    out, i, n = [], 0, len(css)
    while i < n:
        if css.startswith("/*", i):
            j = css.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        c = css[i]
        if c in "\"'":
            j = i + 1
            while j < n and css[j] != c:
                j += 2 if css[j] == "\\" else 1
            out.append(css[i:j + 1])
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _blocks(css):
    """Yield (prelude, body or None) at depth 0; body None for statements ending in ';'."""
    i, n = 0, len(css)
    start = 0
    while i < n:
        c = css[i]
        if c in "\"'":
            j = i + 1
            while j < n and css[j] != c:
                j += 2 if css[j] == "\\" else 1
            i = j + 1
            continue
        if c == ";":
            yield css[start:i].strip(), None
            start = i + 1
        elif c == "{":
            depth, j = 1, i + 1
            while j < n and depth:
                if css[j] in "\"'":
                    q = css[j]
                    j += 1
                    while j < n and css[j] != q:
                        j += 2 if css[j] == "\\" else 1
                elif css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                j += 1
            yield css[start:i].strip(), css[i + 1:j - 1]
            i = j
            start = j
            continue
        i += 1


def split_list(sel):
    parts, depth, cur, q = [], 0, "", None
    for c in sel:
        if q:
            cur += c
            q = None if c == q else q
            continue
        if c in "\"'":
            q = c
        depth += c in "(["
        depth -= c in ")]"
        if c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        parts.append(cur.strip())
    return parts


def rules(css, parents=None, at=None):
    """[(selector list text resolved against parents, at-rule context)] for every style rule."""
    out = []
    for prelude, body in _blocks(css):
        if body is None or not prelude:
            continue
        low = prelude.lower()
        if low.startswith("@"):
            if low.startswith(SKIP_BLOCK_AT):
                continue
            out += rules(body, parents, (at + " " if at else "") + prelude)
            continue
        sels = split_list(prelude)
        if parents:
            resolved = []
            for p in parents:
                for s in sels:
                    if "&" in s:
                        resolved.append(s.replace("&", f":is({p})"))
                    else:
                        resolved.append(f":is({p}) {s}")
            sels = resolved
        out.append((sels, at))
        if "{" in body:
            out += rules(body, sels, at)
    return out


def _compounds(sel):
    """Split a complex selector into [(combinator, compound)] at depth 0."""
    out, depth, cur, comb, q, i = [], 0, "", "", None, 0
    while i < len(sel):
        c = sel[i]
        if q:
            cur += c
            q = None if c == q else q
            i += 1
            continue
        if c in "\"'":
            q = c
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        if depth == 0 and (c.isspace() or c in ">+~"):
            j = i
            while j < len(sel) and (sel[j].isspace() or sel[j] in ">+~"):
                j += 1
            token = sel[i:j].strip() or " "
            if cur:
                out.append((comb, cur))
                cur = ""
            comb = token
            i = j
            continue
        cur += c
        i += 1
    if cur:
        out.append((comb, cur))
    return out


def _join(parts):
    s = ""
    for comb, comp in parts:
        comp = comp or "*"
        if not s:
            s = comp if comb in ("", " ") else f"{comb} {comp}"
        else:
            s += " " + comp if comb == " " else f" {comb} {comp}"
    return s.strip()


LEGACY_PSEUDO_EL = ("before", "after", "first-line", "first-letter")
SELECTOR_FUNCS = ("is", "where", "matches", "-webkit-any", "-moz-any", "has")
DYN_NAME = re.compile(r":(" + "|".join(re.escape(s) for s in DYNAMIC_STATES + DYNAMIC_OTHER) + r")(?![\w-])|:-(?:webkit|moz|ms)-")


def _close(s, j):
    """Index of the parenthesis closing s[j] == '('."""
    depth, q = 0, None
    for k in range(j, len(s)):
        c = s[k]
        if q:
            q = None if c == q else q
        elif c in "\"'":
            q = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return k
    return len(s) - 1


def _strip_compound(s):
    """Drop pseudo-elements and dynamic pseudo-classes from a compound selector. A :not() that
    contains a dynamic pseudo-class could be true, so it is dropped whole; inside :is()/:where()
    an argument left empty becomes '*'."""
    out, i, n = "", 0, len(s)
    while i < n:
        c = s[i]
        if c in "\"'":
            j = i + 1
            while j < n and s[j] != c:
                j += 2 if s[j] == "\\" else 1
            out += s[i:j + 1]
            i = j + 1
            continue
        if c == "[":
            j = s.find("]", i)
            j = n - 1 if j < 0 else j
            out += s[i:j + 1]
            i = j + 1
            continue
        if c == ":":
            el = s.startswith("::", i)
            j = i + (2 if el else 1)
            while j < n and (s[j].isalnum() or s[j] in "-_"):
                j += 1
            name = s[i + (2 if el else 1):j].lower()
            end = _close(s, j) if j < n and s[j] == "(" else j - 1
            arg = s[j + 1:end] if j < n and s[j] == "(" else None
            if el or name in LEGACY_PSEUDO_EL or name in DYNAMIC_STATES or name in DYNAMIC_OTHER or name.startswith("-"):
                i = end + 1
                continue
            if arg is not None and name == "not":
                if DYN_NAME.search(arg) or "::" in arg:
                    i = end + 1
                    continue
                out += f":not({_strip_list(arg)})"
            elif arg is not None and name in SELECTOR_FUNCS:
                out += f":{name}({_strip_list(arg, star=True)})"
            else:
                out += s[i:end + 1]
            i = end + 1
            continue
        out += c
        i += 1
    return out


def _strip_complex(sel):
    parts = [(comb, _strip_compound(comp) or "*") for comb, comp in _compounds(sel)]
    full = _join(parts)
    return "* " + full if full.startswith((">", "+", "~")) else full


def _strip_list(arg, star=False):
    items = [_strip_complex(x) for x in split_list(arg)]
    return ", ".join(x if x.strip() else "*" for x in items) or ("*" if star else "")


def _states_in(comp):
    """Dynamic states a compound needs. Inside :not() they are ignored; inside :has() a focus state
    means focus-within on the compound's element."""
    found, stack, i, q = [], [], 0, None
    while i < len(comp):
        c = comp[i]
        if q:
            q = None if c == q else q
        elif c in "\"'":
            q = c
        elif c == "(":
            m = re.search(r":([\w-]+)$", comp[:i])
            stack.append(m.group(1).lower() if m else "")
        elif c == ")":
            if stack:
                stack.pop()
        elif c == ":" and not comp.startswith("::", i) and comp[i - 1:i] != ":":
            m = re.match(r":(focus-visible|focus-within|focus|hover|active)(?![\w-])", comp[i:])
            if m and "not" not in stack:
                st = m.group(1)
                if "has" in stack and st in ("focus", "focus-visible"):
                    st = "focus-within"
                if st not in found:
                    found.append(st)
        i += 1
    return found


def strip(sel):
    """(stripped selector, [(state, stripped prefix ending at the compound that needs it)])"""
    parts = _compounds(sel)
    prefixes, done = [], []
    for comb, comp in parts:
        done.append((comb, _strip_compound(comp) or "*"))
        for st in _states_in(comp):
            pre = _join(done)
            prefixes.append((st, "* " + pre if pre.startswith((">", "+", "~")) else pre))
    return _strip_complex(sel), prefixes


def section_rules(text):
    lines = text.split("\n")
    found = banners(lines)
    starts = [0] + [i for i, _ in found] + [len(lines)]
    titles = ["(preamble)"] + [t[0] for _, t in found]
    out = []
    for n, title in enumerate(titles):
        chunk = "\n".join(lines[starts[n]:starts[n + 1]])
        for sels, at in rules(_strip_comments(chunk)):
            out.append((title, sels, at))
    return out


IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?(["']?)([^"')\s]+)\1\s*\)?\s*(.*)""", re.I | re.S)


def stylesheet_rules(path, title=None, at=None):
    """section_rules() of a stylesheet, preceded by the rules of each top-level @import, read from disk
    relative to it, so an @import entry such as css/femto.css is parsed module by module. An imported
    file's rules before its first banner are titled by its path; a media or layer() condition on an
    @import becomes the at-rule context of its rules."""
    text = path.read_text()
    out = []
    for prelude, body in _blocks(_strip_comments(text)):
        m = IMPORT.fullmatch(prelude) if body is None else None
        if not m:
            continue
        child = (REPO / m.group(2).lstrip("/")) if m.group(2).startswith("/") else (path.parent / m.group(2))
        if not child.is_file():
            raise SystemExit(f"{path.relative_to(REPO).as_posix()} imports {m.group(2)}, which does not exist on disk")
        cond = f"@import {m.group(3).strip()}" if m.group(3).strip() else None
        ctx = " ".join(c for c in (at, cond) if c) or None
        out += stylesheet_rules(child.resolve(), child.resolve().relative_to(REPO).as_posix(), ctx)
    for t, sels, a in section_rules(text):
        out.append((title if title and t == "(preamble)" else t, sels, " ".join(c for c in (at, a) if c) or None))
    return out


def run_coverage(args):
    path = REPO / args.css.lstrip("/") if args.css.startswith("/") else (REPO / args.css)
    if not path.exists():
        raise SystemExit(f"{args.css} does not exist")
    url = "/" + path.resolve().relative_to(REPO).as_posix()
    items = []
    for title, sels, at in stylesheet_rules(path.resolve()):
        for s in sels:
            st, prefixes = strip(s)
            items.append({"id": str(len(items)), "section": title, "selector": s, "stripped": st, "at": at,
                          "prefixes": [{"state": a, "stripped": b} for a, b in prefixes]})
    pages = pages_for(load_pages(), args.entry, names=[p.strip() for p in args.pages.split(",")] if args.pages else None)
    run_id = args.run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-coverage"
    log = lambda m: print(f"{time.strftime('%H:%M:%S')} {m}", flush=True)
    server = Server()
    slot = locks.slot(f"{run_id} coverage", log)
    slot.__enter__()
    sess = start_session("chrome", server.base, log)
    matched = {it["id"]: 0 for it in items}
    errors = {}
    covered = {}
    host_sel = [it for it in items if ":host" in it["stripped"]]
    loads = 0
    try:
        sess.set_media("light")
        sess.js("configure", {"entries": [], "pseudos": sess.pseudos})
        payload = [{"id": it["id"], "stripped": it["stripped"], "prefixes": it["prefixes"]}
                   for it in items if ":host" not in it["stripped"]]
        for p in pages:
            for v in p["variants"]:
                for d in (["ltr", "rtl"] if p["rtl"] else ["ltr"]):
                    q = f"css={url}" + ("&dir=rtl" if d == "rtl" else "") + "".join(f"&{k}={val}" for k, val in v.items())
                    ld = sess.ajs("load", f"/tests/pages/{p['page']}?{q}", 1280, FRAME_HEIGHT, {})
                    loads += 1
                    if ld.get("errors"):
                        log(f"{p['page']} {variant_label(v)} {d}: {ld['errors']}")
                    res = sess.js("coverage", payload)
                    for k, o in res.items():
                        matched[k] += o["matched"]
                        if o["error"]:
                            errors[k] = o["error"]
                        for sk, sv in o["states"].items():
                            cur = covered.setdefault(k, {}).setdefault(sk, {"elements": 0, "covered": False})
                            cur["elements"] += sv["elements"]
                            cur["covered"] |= sv["covered"]
                    hosts = sess.driver.execute_script(
                        "const d=document.getElementById('frame').contentDocument;"
                        "return [...d.querySelectorAll('*')].filter(e => e.shadowRoot).length")
                    for it in host_sel:
                        matched[it["id"]] += hosts
    finally:
        sess.quit()
        server.close()
        slot.__exit__(None, None, None)
    by_section = {}
    dyn = []
    for it in items:
        sec = by_section.setdefault(it["section"], {"selectors": 0, "unmatched": [], "unevaluable": []})
        sec["selectors"] += 1
        if it["id"] in errors and not matched[it["id"]]:
            sec["unevaluable"].append({"selector": it["selector"], "stripped": it["stripped"], "error": errors[it["id"]], "at": it["at"]})
        elif not matched[it["id"]]:
            sec["unmatched"].append({"selector": it["selector"], "stripped": it["stripped"], "at": it["at"]})
        else:
            for sk, sv in covered.get(it["id"], {}).items():
                if sv["elements"] and not sv["covered"]:
                    dyn.append({"section": it["section"], "selector": it["selector"], "needs": sk, "elements": sv["elements"]})
    out = {"css": url, "entry": args.entry, "pages": [p["page"] for p in pages], "loads": loads,
           "selectors": len(items), "unmatched": sum(len(s["unmatched"]) for s in by_section.values()),
           "unevaluable": sum(len(s["unevaluable"]) for s in by_section.values()),
           "states_missing": len(dyn), "sections": by_section, "dynamic_without_states": dyn}
    d = RESULTS / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "coverage.json").write_text(json.dumps(out, indent=1))
    L = [f"selector coverage of {url} over {len(pages)} {args.entry} pages ({loads} loads): {len(items)} selectors, "
         f"{out['unmatched']} match nothing, {out['unevaluable']} not evaluable, {len(dyn)} dynamic rules without data-states"]
    for title, sec in by_section.items():
        if not (sec["unmatched"] or sec["unevaluable"]):
            continue
        L.append(f"\n{title} ({sec['selectors']} selectors)")
        for u in sec["unmatched"]:
            L.append(f"  no match: {u['selector']}" + (f"   [{u['at']}]" if u["at"] else ""))
        for u in sec["unevaluable"]:
            L.append(f"  not evaluable: {u['selector']} -> {u['stripped']} ({u['error'][:80]})")
    if dyn:
        L.append("\nDynamic rules whose elements declare no matching data-states:")
        for x in dyn:
            L.append(f"  [{x['section']}] {x['selector']}  (needs {x['needs']}; {x['elements']} candidate elements)")
    txt = "\n".join(L) + "\n"
    (d / "coverage.txt").write_text(txt)
    print(txt)
    print(f"wrote {d}/coverage.json and coverage.txt")
    return 0
