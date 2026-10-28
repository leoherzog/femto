"""Presets, fixture pages and the comparison cells each mode runs.

A cell is one comparison: browser x preset x page x page variant x scheme leg x width x direction,
with a reference stylesheet list and a test stylesheet list. Every reduction of the full cross
product is written to the run log through `caps`.
"""
import json
import urllib.parse

from .paths import MANIFEST, VARIANTS

BANDS = [375, 640, 900, 1150, 1400, 1700]            # one width inside each breakpoint band
BOUNDARIES = [576, 768, 1024, 1280, 1536]
EDGES = sorted({w for b in BOUNDARIES for w in (b - 1, b, b + 1)})
ALL_WIDTHS = sorted(set(BANDS) | set(EDGES))
FAST_WIDTHS = [390, 1280]
# scheme leg -> (prefers-color-scheme, data-theme on <html>)
LEGS = {
    "light": ("light", None),
    "dark": ("dark", None),
    "theme-light": ("dark", "light"),   # forced light on a dark OS
    "theme-dark": ("light", "dark"),    # forced dark on a light OS
}
ALL_LEGS = list(LEGS)
KITCHEN_SINK = "kitchen-sink.html"


class MatrixError(Exception):
    pass


def load_presets():
    data = json.loads(VARIANTS.read_text())
    return data["presets"]


def load_pages():
    if not MANIFEST.exists():
        raise MatrixError("tests/pages/pages.json is missing (owned by the fixtures agent)")
    pages = json.loads(MANIFEST.read_text())
    if not isinstance(pages, list):
        raise MatrixError("tests/pages/pages.json must be an array")
    for p in pages:
        p.setdefault("variants", [{}])
        p.setdefault("entries", ["default"])
        p.setdefault("modules", [])
        p.setdefault("sections", [])
        p.setdefault("rtl", False)
        p.setdefault("media", False)
        p.setdefault("stateless_variants", [])
        if not p["variants"]:
            p["variants"] = [{}]
        STATELESS[p["page"]] = set(p["stateless_variants"])
    return pages


def variant_label(v: dict) -> str:
    return "plain" if not v else "&".join(f"{k}={v[k]}" for k in sorted(v))


def page_url(cell, css, theme):
    q = {"css": ",".join(css)}
    if theme:
        q["theme"] = theme
    if cell["dir"] == "rtl":
        q["dir"] = "rtl"
    for k, v in cell["variant"].items():
        if k in ("css", "theme", "dir"):
            raise MatrixError(f"page variant may not set {k}: {cell['variant']}")
        q[k] = v
    return f"/tests/pages/{cell['page']}?" + urllib.parse.urlencode(q, safe="/,")


STATELESS = {}   # page -> variant labels whose state targets are unreachable (manifest stateless_variants)


def make_cell(browser, preset_name, comparison, entry, page, variant, leg, width, direction, ref, test,
              states=True, shots=True):
    media, theme = LEGS[leg]
    if variant_label(variant) in STATELESS.get(page, ()):
        states = False
    return {
        "browser": browser, "preset": preset_name, "comparison": comparison, "entry": entry,
        "page": page, "variant": variant, "variant_label": variant_label(variant),
        "scheme": leg, "media": media, "theme": theme, "width": width, "dir": direction,
        "ref": list(ref), "test": list(test), "states": states, "shots": shots,
    }


def pages_for(pages, entry, names=None, modules=None, sections=None):
    """Manifest pages for an entry, selected by page name, module id or section title (any match).
    With no selector, every page of the entry."""
    out = []
    for p in pages:
        if entry not in p["entries"]:
            continue
        if names or modules or sections:
            hit = (names and p["page"] in names) or (modules and set(modules) & set(p["modules"])) \
                or (sections and set(sections) & set(p["sections"]))
            if not hit:
                continue
        out.append(p)
    return out


def simple_cells(browsers, preset_name, comparison, entry, pages, ref, test, widths, legs, dirs, states, shots,
                 variants=None):
    """Every combination; rtl only for pages with rtl rules unless dirs asks for nothing else."""
    cells = []
    for b in browsers:
        for p in pages:
            for v in p["variants"]:
                if variants and variant_label(v) not in variants:
                    continue
                for d in dirs:
                    if d == "rtl" and not p["rtl"] and dirs != ["rtl"]:
                        continue
                    for w in widths:
                        for leg in legs:
                            cells.append(make_cell(b, preset_name, comparison, entry, p["page"], v, leg, w, d,
                                                   ref, test, states, shots))
    return cells


def full_cells(browsers, presets, pages, tests_for, caps, preset_filter=None):
    """The full matrix with its documented reductions.

    tests_for(preset_name, preset) -> (comparison, ref list, test list).
    """
    cells = []
    note = caps.append
    core = ["default"]
    note(f"full: widths {ALL_WIDTHS} (bands {BANDS} plus each boundary -1/0/+1) only for the kitchen sink "
         f"and pages with media rules; other pages use {FAST_WIDTHS}")
    note("full: rtl runs only on pages with rtl rules (manifest rtl: true), at band widths for wide pages "
         f"and {FAST_WIDTHS} otherwise, in legs light and theme-dark")
    note("full: interactive states run at widths 375 and 1280 on the kitchen sink and media pages (ltr, every "
         "leg), at both widths on other pages, and at 1280 in rtl; other cells compare computed styles and tokens only")
    note("full: page variants other than the plain load run at the fast widths only")
    note("full: screenshots only where states run")
    for name in core:
        if preset_filter and name not in preset_filter:
            continue
        pr = presets[name]
        comparison, ref, test = tests_for(name, pr)
        for b in browsers:
            for p in pages_for(pages, pr["entry"]):
                wide = p["media"] or p["page"] == KITCHEN_SINK
                for v in p["variants"]:
                    plain = not v
                    ltr_w = ALL_WIDTHS if (wide and plain) else FAST_WIDTHS
                    for w in ltr_w:
                        st = w in (375, 1280) or (not wide or not plain)
                        for leg in ALL_LEGS:
                            cells.append(make_cell(b, name, comparison, pr["entry"], p["page"], v, leg, w, "ltr",
                                                   ref, test, states=st, shots=st))
                    if p["rtl"]:
                        rtl_w = BANDS if (wide and plain) else FAST_WIDTHS
                        for w in rtl_w:
                            for leg in ("light", "theme-dark"):
                                st = w == 1280 or w == FAST_WIDTHS[-1]
                                cells.append(make_cell(b, name, comparison, pr["entry"], p["page"], v, leg, w, "rtl",
                                                       ref, test, states=st, shots=st))
    # colors
    if not preset_filter or "colors" in preset_filter:
        pr = presets["colors"]
        comparison, ref, test = tests_for("colors", pr)
        for b in browsers:
            for p in pages_for(pages, "colors"):
                for v in p["variants"]:
                    for leg in ALL_LEGS:
                        cells.append(make_cell(b, "colors", comparison, "colors", p["page"], v, leg, 1280, "ltr", ref, test))
        note("full: colors runs its pages at width 1280 in every leg")
    # options
    opts = [n for n, pr in presets.items() if pr.get("group") == "option" and (not preset_filter or n in preset_filter)]
    if opts:
        note(f"full: options ({', '.join(opts)}) run the kitchen sink at every width in leg light and "
             f"{FAST_WIDTHS} in the other legs (states at 1280 light), and every other page of their entry, in every "
             "page variant, at 1280 in legs light (with states) and theme-dark; no rtl")
    for name in opts:
        pr = presets[name]
        comparison, ref, test = tests_for(name, pr)
        entry_pages = pages_for(pages, pr["entry"])
        for b in browsers:
            for p in entry_pages:
                if p["page"] != KITCHEN_SINK:
                    # Option rules also live on pages the kitchen sink cannot hold (open dialogs in the
                    # modal-is-opening/-closing variants, open dropdowns, side tooltips in hover).
                    for v in p["variants"]:
                        for leg in ("light", "theme-dark"):
                            st = leg == "light"
                            cells.append(make_cell(b, name, comparison, pr["entry"], p["page"], v, leg, 1280, "ltr",
                                                   ref, test, states=st, shots=st))
                    continue
                for w in ALL_WIDTHS:
                    cells.append(make_cell(b, name, comparison, pr["entry"], p["page"], {}, "light", w, "ltr", ref, test,
                                           states=w == 1280, shots=w == 1280))
                for w in FAST_WIDTHS:
                    for leg in ("dark", "theme-light", "theme-dark"):
                        cells.append(make_cell(b, name, comparison, pr["entry"], p["page"], {}, leg, w, "ltr", ref, test,
                                               states=False, shots=False))
    # themes
    themes = [n for n, pr in presets.items() if pr.get("group") == "theme" and (not preset_filter or n in preset_filter)]
    if themes:
        note(f"full: {len(themes)} theme presets run on the kitchen sink only, width 1280, every leg, with states")
    for name in themes:
        pr = presets[name]
        comparison, ref, test = tests_for(name, pr)
        ks = [p for p in pages_for(pages, pr["entry"]) if p["page"] == KITCHEN_SINK]
        for b in browsers:
            for p in ks:
                for leg in ALL_LEGS:
                    cells.append(make_cell(b, name, comparison, pr["entry"], p["page"], {}, leg, 1280, "ltr", ref, test))
    return cells
