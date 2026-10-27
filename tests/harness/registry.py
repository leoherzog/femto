"""Divergence registry: tests/divergences/*.json (every file but schema.json).

Each file is a JSON array of entries. Every difference the harness finds must match at least one
entry, or the run fails. The schema is documented in tests/divergences/schema.json and
tests/README.md. Matching of style and token differences happens in the page (differ.js), because
selectors are evaluated against the live test document; this module validates entries, filters
them per comparison cell with `where`, and matches skipped checks.
"""
import json
import re
from pathlib import Path

from .paths import DIVERGENCES

KINDS = ("style", "token", "token-raw", "surface-added", "surface-missing", "skipped-check")
CATEGORIES = ("natural-fix", "dropped-hack", "new-token", "option-mechanism", "browser-limit")
WHERE_KEYS = ("browsers", "presets", "entries", "variants", "pages", "schemes", "widths", "dirs", "states")
STATES = ("base", "hover", "focus", "focus-visible", "active")
FIELDS = ("id", "module", "kind", "selector", "token", "pseudo", "property", "reference", "femto",
          "check", "where", "category", "reason", "notes")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _is_regex(v):
    return isinstance(v, str) and len(v) > 2 and v.startswith("/") and v.rfind("/") > 0


def _check_pattern(v, field, errs, where):
    if v is None:
        return
    if not isinstance(v, str):
        errs.append(f"{where}: {field} must be a string")
        return
    if _is_regex(v):
        k = v.rfind("/")
        flags = v[k + 1:]
        if set(flags) - set("imsu"):
            errs.append(f"{where}: {field} regex flags {flags!r} not allowed (use i, m, s, u)")
        try:
            re.compile(v[1:k])
        except re.error as e:
            errs.append(f"{where}: {field} is not a valid regex: {e}")


def _pattern_match(pat, value) -> bool:
    if pat is None or pat == "*":
        return True
    if _is_regex(pat):
        k = pat.rfind("/")
        flags = re.I if "i" in pat[k + 1:] else 0
        return re.search(pat[1:k], value or "", flags) is not None
    return pat == value


def validate_entry(e, where, errs, ids):
    if not isinstance(e, dict):
        errs.append(f"{where}: entry is not an object")
        return
    for k in e:
        if k not in FIELDS:
            errs.append(f"{where}: unknown field {k!r}")
    eid = e.get("id")
    if not isinstance(eid, str) or not ID_RE.match(eid):
        errs.append(f"{where}: id must match {ID_RE.pattern}")
    elif eid in ids:
        errs.append(f"{where}: duplicate id {eid!r} (also in {ids[eid]})")
    else:
        ids[eid] = where
    where = f"{where} [{eid}]"
    if not isinstance(e.get("module"), str) or not e["module"]:
        errs.append(f"{where}: module is required")
    kind = e.get("kind")
    if kind not in KINDS:
        errs.append(f"{where}: kind must be one of {', '.join(KINDS)}")
    if e.get("category") not in CATEGORIES:
        errs.append(f"{where}: category must be one of {', '.join(CATEGORIES)}")
    if not isinstance(e.get("reason"), str) or not e["reason"].strip():
        errs.append(f"{where}: reason must be a non-empty string")
    if kind == "style":
        for f in ("selector", "property", "reference", "femto"):
            if f not in e:
                errs.append(f"{where}: style entries need {f}")
    if kind == "token":
        for f in ("token", "property", "reference", "femto"):
            if f not in e:
                errs.append(f"{where}: token entries need {f}")
    if kind == "token-raw":
        for f in ("token", "reference", "femto"):
            if f not in e:
                errs.append(f"{where}: token-raw entries need {f}")
    if kind in ("surface-added", "surface-missing") and "token" not in e:
        errs.append(f"{where}: {kind} entries need token")
    if kind == "skipped-check":
        if "check" not in e:
            errs.append(f"{where}: skipped-check entries need check")
        if e.get("category") != "browser-limit":
            errs.append(f"{where}: skipped-check entries use category browser-limit")
    if "selector" in e and (not isinstance(e["selector"], str) or not e["selector"].strip()):
        errs.append(f"{where}: selector must be a non-empty string")
    for f in ("token", "pseudo", "property", "reference", "femto", "check"):
        _check_pattern(e.get(f), f, errs, where)
    w = e.get("where", {})
    if not isinstance(w, dict):
        errs.append(f"{where}: where must be an object")
        return
    for k, v in w.items():
        if k not in WHERE_KEYS:
            errs.append(f"{where}: unknown where key {k!r} (allowed: {', '.join(WHERE_KEYS)})")
        elif not isinstance(v, list) or not v:
            errs.append(f"{where}: where.{k} must be a non-empty list")
        elif k == "widths":
            for x in v:
                if not (isinstance(x, int) or (isinstance(x, dict) and set(x) <= {"min", "max"} and x)):
                    errs.append(f"{where}: where.widths items are integers or {{min, max}} objects")
        elif k == "states":
            for x in v:
                if x not in STATES:
                    errs.append(f"{where}: where.states items are {', '.join(STATES)}")
        elif not all(isinstance(x, str) for x in v):
            errs.append(f"{where}: where.{k} items must be strings")


class Registry:
    def __init__(self, directory: Path = DIVERGENCES):
        self.directory = directory
        self.entries, self.errors, self.files = [], [], []
        ids = {}
        for p in sorted(directory.glob("*.json")):
            if p.name == "schema.json":
                continue
            self.files.append(p.name)
            try:
                data = json.loads(p.read_text())
            except json.JSONDecodeError as e:
                self.errors.append(f"{p.name}: invalid JSON: {e}")
                continue
            if not isinstance(data, list):
                self.errors.append(f"{p.name}: top level must be an array")
                continue
            for n, e in enumerate(data):
                validate_entry(e, f"{p.name}#{n}", self.errors, ids)
                if isinstance(e, dict):
                    self.entries.append(dict(e, _file=p.name))
        if not directory.is_dir():
            self.errors.append(f"registry directory {directory} does not exist")
        self.hits = {e.get("id"): 0 for e in self.entries}

    @staticmethod
    def _where_ok(e, cell) -> bool:
        w = e.get("where") or {}
        if "browsers" in w and cell["browser"] not in w["browsers"]:
            return False
        if "presets" in w and cell["preset"] not in w["presets"]:
            return False
        if "entries" in w and cell["entry"] not in w["entries"]:
            return False
        if "variants" in w:
            names = {cell["preset"], cell["entry"], cell["variant_label"], cell["comparison"]}
            if not names & set(w["variants"]):
                return False
        if "pages" in w and cell["page"] not in w["pages"]:
            return False
        if "schemes" in w and cell["scheme"] not in w["schemes"]:
            return False
        if "dirs" in w and cell["dir"] not in w["dirs"]:
            return False
        if "widths" in w:
            ok = False
            for x in w["widths"]:
                if isinstance(x, int):
                    ok |= cell["width"] == x
                else:
                    ok |= x.get("min", 0) <= cell["width"] <= x.get("max", 10 ** 6)
            if not ok:
                return False
        return True

    def for_cell(self, cell) -> list:
        """Entries that apply to a comparison cell, in the shape differ.js expects."""
        out = []
        for e in self.entries:
            if e.get("kind") == "skipped-check" or not self._where_ok(e, cell):
                continue
            d = {k: e[k] for k in ("id", "kind", "selector", "token", "pseudo", "property", "reference", "femto") if k in e}
            if "states" in (e.get("where") or {}):
                d["states"] = e["where"]["states"]
            out.append(d)
        return out

    def match_skipped(self, check: str, cell) -> list:
        ids = [e["id"] for e in self.entries
               if e.get("kind") == "skipped-check" and _pattern_match(e.get("check"), check) and self._where_ok(e, cell)]
        return ids

    def record_hits(self, counts: dict):
        for k, n in counts.items():
            if k in self.hits:
                self.hits[k] += n

    def unused(self):
        return [{"id": e["id"], "file": e["_file"], "kind": e.get("kind")} for e in self.entries if not self.hits.get(e.get("id"))]
