#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Mechanical checks for PLAN.md acceptance criteria 4, 5, 6, 7, 10 and 11, plus shipped-file hygiene.

  uv run tests/static_checks.py                 run every check
  uv run tests/static_checks.py --only 6,7      run some (ids: 4 5 6 7 hygiene vendor 10 11)
  uv run tests/static_checks.py --root DIR      check another checkout (6, 7, hygiene and vendor need no git)

Each check prints PASS or FAIL with evidence lines; the exit status is 1 if any check fails.
"hygiene" and "vendor" are not acceptance criteria. They cover PLAN rules the lint
(eslint.config.mjs, @eslint/css 2.0.1) cannot see:

  lint gap                                                     covered by
  @layer (Baseline Widely, so use-baseline allows it)          7
  @container style() queries (@container itself is Widely)     7
  relative color syntax, rgb(from ...) (rgb() is Widely)       7
  color-mix(in oklab, ...) or any other space                  7
  anything inside custom property values: use-baseline skips
    --* declarations, so light-dark(), if(), rgb(from ...) and
    color-mix() there are never checked                        7
  @import with layer()/supports()/media, or in a module file   6
  --pico- names, non-ASCII bytes, missing header comment        hygiene
  -ms- rules, dropped -moz-/-webkit- pseudo-classes and
    pseudo-elements, a -moz- pseudo inside a selector list     vendor

Not covered by either, so reviewers must check: declarations placed directly inside an @media
or @supports nested in a rule (use-baseline only inspects declarations whose parent is a rule),
nesting traps (docs/research/scripts/nesting_traps.py), and duplicate rules.

"Shipped files" are everything under css/ except the 2.1.1 build output css/pico*.css and
css/postcss.config.js, which Phase 5 deletes. Until then those two are skipped, not checked.
CSS checks look at code only: comments are removed first and, for the forbidden-syntax scans,
string contents (including url("data:...") icons) are blanked, so a comment that mentions
@layer, or an SVG that uses rgb(), is not a violation. Mentions in comments are listed as notes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ENTRIES = ("femto.css", "femto.classless.css", "femto.fluid.classless.css")
EXEMPT_NAME_PATHS = ("docs/research/", "tests/")  # PLAN Decision 10
EXEMPT_NAME_FILES = ("PLAN.md", "PROMPT.md")
MAX_LINES = 12  # evidence lines per finding list

FORBIDDEN = [
    ("@layer", re.compile(r"@layer\b", re.I)),
    ("@scope", re.compile(r"@scope\b", re.I)),
    ("if(", re.compile(r"(?<![\w-])if\(", re.I)),
    ("@function", re.compile(r"@function\b", re.I)),
    ("@mixin", re.compile(r"@mixin\b", re.I)),
    ("@apply", re.compile(r"@apply\b", re.I)),
    ("@custom-media", re.compile(r"@custom-media\b", re.I)),
    ("@container style(", re.compile(r"@container\b[^{;]*?(?<![\w-])style\(", re.I)),
]
DROPPED_PSEUDO = re.compile(
    r"::-webkit-file-upload-button|::-webkit-input-placeholder|::-moz-list-bullet|::-moz-selection|:-moz-ui-invalid|:-moz-focusring",
    re.I,
)
KEPT_PREFIXED_PROPERTIES = {
    "-webkit-text-size-adjust",
    "-webkit-user-select",
    "-webkit-backdrop-filter",
    "-webkit-tap-highlight-color",
    "-webkit-appearance",
}
COLOR_FUNCTION = re.compile(
    r"(?<![\w-])(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix|light-dark|contrast-color)\(", re.I
)


class Result:
    def __init__(self, title: str):
        self.title, self.failures, self.evidence, self.notes = title, [], [], []

    def fail(self, line: str):
        self.failures.append(line)

    def ok(self, line: str):
        self.evidence.append(line)

    def note(self, line: str):
        self.notes.append(line)

    @property
    def passed(self) -> bool:
        return not self.failures

    def print(self):
        print(f"\n== {self.title}")
        print("PASS" if self.passed else "FAIL")
        for prefix, lines in (("  FAIL ", self.failures), ("  ", self.evidence), ("  note: ", self.notes)):
            for line in lines:
                print(prefix + line)


def capped(items: list[str], what: str) -> list[str]:
    out = items[:MAX_LINES]
    if len(items) > MAX_LINES:
        out.append(f"... and {len(items) - MAX_LINES} more {what}")
    return out


# ---------------------------------------------------------------------------- CSS scanning


def blank(text: str, start: int, end: int) -> str:
    """Replace text[start:end] with spaces, keeping newlines so offsets and lines stay valid."""
    return text[:start] + re.sub(r"[^\n]", " ", text[start:end]) + text[end:]


def scan_css(text: str) -> tuple[str, str, list[tuple[int, str]]]:
    """Return (code without comments, code without comments or string contents, comments).

    Comments are found outside strings; unquoted url(...) contents count as strings."""
    no_comments, masked, comments = text, text, []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            masked = blank(masked, i + 1, min(j, n))
            i = j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            comments.append((i, text[i:j]))
            no_comments = blank(no_comments, i, j)
            masked = blank(masked, i, j)
            i = j
        elif text[i : i + 4].lower() == "url(" and (i == 0 or not re.match(r"[\w-]", text[i - 1])):
            j = i + 4
            while j < n and text[j] in " \t\n":
                j += 1
            if j < n and text[j] not in "\"'":
                k = text.find(")", j)
                k = n if k < 0 else k
                masked = blank(masked, j, k)
                i = k
            else:
                i = j
        else:
            i += 1
    return no_comments, masked, comments


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def top_level_statements(code: str) -> list[tuple[int, str]]:
    """Split comment-free CSS into top-level statements: (offset, prelude) per at-rule statement
    or block. Strings are skipped when matching braces."""
    out, i, n, start, depth, quote = [], 0, len(code), None, 0, None
    while i < n:
        c = code[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif depth == 0 and start is None and not c.isspace():
            start = i
        if not quote:
            if c == "{":
                if depth == 0:
                    out.append((start, code[start:i].strip()))
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    start = None
            elif c == ";" and depth == 0 and start is not None:
                out.append((start, code[start : i + 1].strip()))
                start = None
        i += 1
    if start is not None and code[start:].strip():
        out.append((start, code[start:].strip()))
    return out


def call_args(masked: str, open_paren: int) -> tuple[str, int]:
    """Return the argument text of the call whose '(' is at open_paren, and its end offset."""
    depth, i = 0, open_paren
    while i < len(masked):
        if masked[i] == "(":
            depth += 1
        elif masked[i] == ")":
            depth -= 1
            if depth == 0:
                return masked[open_paren + 1 : i], i
        i += 1
    return masked[open_paren + 1 :], len(masked)


def depth0(args: str) -> str:
    """The argument text with every nested (...) group removed."""
    out, depth = [], 0
    for c in args:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0:
            out.append(c)
    return "".join(out)


# ---------------------------------------------------------------------------- repo helpers


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def effective_files(root: Path) -> list[str]:
    """Files that would be tracked after committing the working tree: the index minus files
    deleted on disk, plus untracked files that are not ignored."""
    z = lambda *a: [p for p in git(root, "ls-files", "-z", *a).stdout.split("\0") if p]
    return sorted((set(z()) - set(z("--deleted"))) | set(z("--others", "--exclude-standard")))


def name_exempt(path: str) -> bool:
    return path.startswith(EXEMPT_NAME_PATHS) or path in EXEMPT_NAME_FILES


def shipped_files(root: Path) -> tuple[list[Path], list[str]]:
    """(shipped files under css/, skipped 2.1.1 leftovers)."""
    css = root / "css"
    shipped, skipped = [], []
    if not css.is_dir():
        return shipped, skipped
    for p in sorted(css.rglob("*")):
        if not p.is_file() or p.name == ".DS_Store":
            continue
        rel = p.relative_to(root).as_posix()
        if p.parent == css and (re.match(r"pico.*\.css$", p.name) or p.name == "postcss.config.js"):
            skipped.append(rel)
            continue
        shipped.append(p)
    return shipped, skipped


def describe_shipped(r: Result, shipped: list[Path], skipped: list[str]) -> list[Path]:
    css_files = [p for p in shipped if p.suffix == ".css"]
    if skipped:
        r.note(f"skipped {len(skipped)} 2.1.1 build files in css/ (css/pico*.css, css/postcss.config.js) until Phase 5")
    if not css_files:
        r.fail("no shipped femto CSS files under css/ (nothing converted yet)")
    else:
        r.ok(f"{len(css_files)} shipped CSS files under css/")
    return css_files


# ---------------------------------------------------------------------------- criteria


def criterion_4(root: Path) -> Result:
    r = Result("Criterion 4: no *.scss, scripts/, PostCSS config or yarn.lock in git; no build script")
    files = effective_files(root)
    r.ok(f"{len(files)} files tracked or to be tracked (git ls-files, minus deleted, plus untracked not ignored)")
    checks = [
        ("*.scss file", [f for f in files if f.endswith(".scss")]),
        ("scripts/ file", [f for f in files if f.startswith("scripts/")]),
        (
            "PostCSS config",
            [f for f in files if re.fullmatch(r"(postcss\.config\.(c|m)?(js|ts)|\.postcssrc(\.(json|ya?ml|(c|m)?js))?)", Path(f).name)],
        ),
        ("yarn.lock", [f for f in files if Path(f).name == "yarn.lock"]),
    ]
    for what, hits in checks:
        if hits:
            r.fail(f"{len(hits)} {what}(s) in git:")
            r.failures += ["    " + h for h in capped(hits, "files")]
        else:
            r.ok(f"no {what} in git")
    pkg = root / "package.json"
    if not pkg.exists():
        r.fail("package.json missing")
        return r
    scripts = json.loads(pkg.read_text()).get("scripts", {}) or {}
    build = [k for k in scripts if re.match(r"(pre|post)?build(:|$)", k)]
    tools = [k for k, v in scripts.items() if re.search(r"\b(sass|postcss|autoprefixer|clean-?css|cleancss|esbuild|lightningcss)\b", str(v))]
    if build:
        r.fail(f"package.json build scripts: {', '.join(build)}")
    if tools:
        r.fail(f"package.json scripts that run a CSS build tool: {', '.join(sorted(set(tools) - set(build)) or tools)}")
    if not build and not tools:
        r.ok(f"package.json scripts: {', '.join(scripts) or '(none)'}; no build script")
    return r


def markdown_sections(lines: list[str]) -> list[tuple[int, int, str]]:
    """(start, end, heading) for each ATX heading, end exclusive, skipping fenced code."""
    heads, fence = [], None
    for i, line in enumerate(lines):
        m = re.match(r"^(```|~~~)", line)
        if m:
            fence = None if fence == m.group(1) else (fence or m.group(1))
            continue
        if fence:
            continue
        h = re.match(r"^(#{1,6})\s+(.*)", line)
        if h:
            heads.append((i, len(h.group(1)), h.group(2).strip()))
    out = []
    for k, (i, level, text) in enumerate(heads):
        end = next((j for j, lv, _ in heads[k + 1 :] if lv <= level), len(lines))
        out.append((i, end, text))
    return out


def criterion_5(root: Path) -> Result:
    r = Result("Criterion 5: 'pico' only in LICENSE.md and the README migration section (outside docs/research, tests, PLAN.md, PROMPT.md)")
    spec = ["--", ".", ":!docs/research", ":!tests", ":!PLAN.md", ":!PROMPT.md"]
    literal = git(root, "grep", "-il", "pico", *spec, check=False).stdout.split()
    untracked = git(root, "grep", "-il", "--untracked", "pico", *spec, check=False).stdout.split()
    hits = sorted(set(literal) | set(untracked))
    r.ok(f"git grep -il pico (tracked: {len(literal)} files; with --untracked: {len(untracked)} files)")
    bad = [h for h in hits if h not in ("LICENSE.md", "README.md")]
    if bad:
        r.fail(f"{len(bad)} file(s) other than LICENSE.md and README.md mention pico:")
        r.failures += ["    " + b for b in capped(bad, "files")]
    else:
        r.ok("only " + (", ".join(hits) if hits else "no files") + " mention pico")
    names = [f for f in effective_files(root) if re.search(r"pico", f, re.I) and not name_exempt(f)]
    if names:
        r.fail(f"{len(names)} tracked path(s) with 'pico' in the name:")
        r.failures += ["    " + n for n in capped(names, "paths")]
    else:
        r.ok("no tracked path outside the exempt folders has 'pico' in its name")
    readme = root / "README.md"
    if "README.md" in hits and readme.exists():
        lines = readme.read_text(encoding="utf-8").split("\n")
        migration = [(s, e, t) for s, e, t in markdown_sections(lines) if re.search(r"migrat", t, re.I)]
        outside = [i for i, l in enumerate(lines) if re.search(r"pico", l, re.I) and not any(s <= i < e for s, e, _ in migration)]
        if not migration:
            r.fail("README.md mentions pico but has no migration section (no heading matching /migrat/i)")
        else:
            r.ok("README migration section(s): " + "; ".join(f"'{t}' lines {s + 1}-{e}" for s, e, t in migration))
        if outside:
            r.fail(f"README.md mentions pico on {len(outside)} line(s) outside the migration section:")
            r.failures += [f"    README.md:{i + 1}: {lines[i].strip()[:100]}" for i in outside[:MAX_LINES]]
            if len(outside) > MAX_LINES:
                r.failures.append(f"    ... and {len(outside) - MAX_LINES} more lines")
    return r


def criterion_6(root: Path) -> Result:
    r = Result("Criterion 6: only the three entry files use @import, and imports precede every other rule")
    shipped, skipped = shipped_files(root)
    css_files = describe_shipped(r, shipped, skipped)
    css = root / "css"
    for entry in ENTRIES:
        if not (css / entry).exists():
            r.fail(f"entry css/{entry} is missing")
    for p in css_files:
        rel = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8", errors="replace")
        code, _, comments = scan_css(text)
        statements = top_level_statements(code)
        imports = [(o, s) for o, s in statements if re.match(r"@import\b", s, re.I)]
        nested = [m.start() for m in re.finditer(r"@import\b", code, re.I) if m.start() not in {o for o, _ in imports}]
        for o in nested:
            r.fail(f"{rel}:{line_of(text, o)}: @import inside a block")
        for o, c in comments:
            if re.search(r"@import\b", c, re.I):
                r.note(f"{rel}:{line_of(text, o)}: a comment mentions @import (not code)")
        is_entry = p.parent == css and p.name in ENTRIES
        if not is_entry:
            for o, s in imports:
                r.fail(f"{rel}:{line_of(text, o)}: @import in a non-entry file: {s[:80]}")
            continue
        seen_rule = None
        for o, s in statements:
            if re.match(r"@charset\b", s, re.I):
                continue
            if re.match(r"@import\b", s, re.I):
                if seen_rule is not None:
                    r.fail(f"{rel}:{line_of(text, o)}: @import after a rule (line {line_of(text, seen_rule)})")
                m = re.fullmatch(r'@import\s+(["\'])([^"\']+)\1\s*;', s, re.I)
                if not m:
                    r.fail(f"{rel}:{line_of(text, o)}: not a plain @import \"path\"; (no url(), layer(), supports() or media): {s[:80]}")
                    continue
                target = m.group(2)
                if re.match(r"([a-z]+:|/)", target, re.I):
                    r.fail(f"{rel}:{line_of(text, o)}: import path is not relative: {target}")
                    continue
                dest = (p.parent / target).resolve()
                if not dest.is_file():
                    r.fail(f"{rel}:{line_of(text, o)}: imported file does not exist: {target}")
                elif dest.parent == css.resolve() and dest.name in ENTRIES:
                    r.fail(f"{rel}:{line_of(text, o)}: imports another entry ({target}); chains must be one level deep")
            elif seen_rule is None:
                seen_rule = o
        r.ok(f"{rel}: {len(imports)} @import rules, all before the first other rule" if not any(f.startswith(rel) for f in r.failures) else f"{rel}: {len(imports)} @import rules")
    return r


def criterion_7(root: Path) -> Result:
    r = Result("Criterion 7: no @layer, @scope, if(, @function, @mixin, @apply, @custom-media, @container style(; no 'from' in color functions; every color-mix( uses 'in srgb'")
    shipped, skipped = shipped_files(root)
    css_files = describe_shipped(r, shipped, skipped)
    counts = {"color-mix": 0, "color functions": 0}
    for p in css_files:
        rel = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8", errors="replace")
        _, masked, comments = scan_css(text)
        for label, pattern in FORBIDDEN:
            for m in pattern.finditer(masked):
                r.fail(f"{rel}:{line_of(text, m.start())}: {label}")
            for o, c in comments:
                if pattern.search(c):
                    r.note(f"{rel}:{line_of(text, o)}: a comment mentions {label} (not code)")
        for m in COLOR_FUNCTION.finditer(masked):
            name = m.group(1).lower()
            args, _ = call_args(masked, m.end() - 1)
            top = depth0(args)
            counts["color functions"] += 1
            if re.search(r"(?<![\w-])from(?![\w-])", top, re.I):
                r.fail(f"{rel}:{line_of(text, m.start())}: relative color syntax: {name}({args.strip()[:60]})")
            if name == "color-mix":
                counts["color-mix"] += 1
                if not re.match(r"\s*in\s+srgb\s*,", args, re.I):
                    r.fail(f"{rel}:{line_of(text, m.start())}: color-mix without 'in srgb': color-mix({args.strip()[:60]})")
    if css_files:
        r.ok(f"scanned {counts['color functions']} color function calls, {counts['color-mix']} of them color-mix()")
    return r


def hygiene(root: Path) -> Result:
    r = Result("Shipped-file hygiene: no --pico- names, ASCII only, each file starts with a header comment, CSS only")
    shipped, skipped = shipped_files(root)
    css_files = describe_shipped(r, shipped, skipped)
    for p in shipped:
        if p.suffix != ".css":
            r.fail(f"{p.relative_to(root).as_posix()}: not a CSS file")
    for p in css_files:
        rel = p.relative_to(root).as_posix()
        raw = p.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        for m in re.finditer(r"--pico-", text):
            r.fail(f"{rel}:{line_of(text, m.start())}: --pico- name")
        for i, b in enumerate(raw):
            if b > 0x7F:
                line = raw.count(b"\n", 0, i) + 1
                r.fail(f"{rel}:{line}: non-ASCII byte 0x{b:02x} (escape it, e.g. content: \"\\200b\")")
                break
        m = re.match(r"/\*(.*?)\*/", text, re.S)
        if not m or not re.search(r"\w", m.group(1)):
            r.fail(f"{rel}: does not start with a header comment" + (" (leading whitespace or BOM)" if text.lstrip().startswith("/*") else ""))
        else:
            words = re.sub(r"\s+", " ", m.group(1)).strip()
            sentences = len(re.findall(r"[.!?](\s|$)", words))
            if sentences > 3:
                r.note(f"{rel}: header comment has about {sentences} sentences (PLAN asks for one to three)")
    if css_files and r.passed:
        r.ok("all shipped CSS files pass")
    return r


def rule_preludes(masked: str) -> list[tuple[int, str]]:
    """(offset, prelude) for every block at any depth, from code with comments and strings blanked."""
    out, last = [], 0
    for i, c in enumerate(masked):
        if c in ";}":
            last = i + 1
        elif c == "{":
            prelude = masked[last:i]
            stripped = prelude.lstrip()
            out.append((last + len(prelude) - len(stripped), stripped.rstrip()))
            last = i + 1
    return out


def split_selectors(prelude: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for c in prelude:
        depth += c in "(["
        depth -= c in ")]"
        if c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += c
    return parts + [cur.strip()]


def vendor(root: Path) -> Result:
    r = Result("Vendor prefixes (PLAN Conversion rules): no -ms-, none of the dropped pseudo-classes and pseudo-elements, each -moz- pseudo in its own rule")
    shipped, skipped = shipped_files(root)
    css_files = describe_shipped(r, shipped, skipped)
    used = {}
    for p in css_files:
        rel = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8", errors="replace")
        _, masked, _ = scan_css(text)
        for m in re.finditer(r"(?<![\w-])-ms-[\w-]+", masked):
            r.fail(f"{rel}:{line_of(text, m.start())}: -ms- rule ({m.group(0)})")
        for m in DROPPED_PSEUDO.finditer(masked):
            r.fail(f"{rel}:{line_of(text, m.start())}: dropped {m.group(0)}")
        for o, prelude in rule_preludes(masked):
            if prelude.startswith("@") or not re.search(r"::?-moz-", prelude):
                continue
            selectors = split_selectors(prelude)
            if len(selectors) > 1:
                r.fail(f"{rel}:{line_of(text, o)}: -moz- pseudo in a list of {len(selectors)} selectors: {' , '.join(selectors)[:90]}")
        for m in re.finditer(r"(?:^|[{;\s])(-(?:webkit|moz|o)-[\w-]+)\s*:(?!:)", masked):
            if m.group(1) not in KEPT_PREFIXED_PROPERTIES:
                used.setdefault(m.group(1), []).append(f"{rel}:{line_of(text, m.start())}")
    for prop, where in sorted(used.items()):
        r.note(f"prefixed property not in the PLAN keep list: {prop} ({len(where)}x, first {where[0]}); keep only if 03 §2 says it is needed")
    return r


def criterion_10(root: Path) -> Result:
    r = Result("Criterion 10: npm pack --dry-run lists only css/, README.md, LICENSE.md and package.json")
    proc = subprocess.run(["npm", "pack", "--dry-run", "--json", "--ignore-scripts"], cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        r.fail(f"npm pack --dry-run failed: {proc.stderr.strip()[:200]}")
        return r
    data = json.loads(proc.stdout)
    files = [f["path"] for pack in data for f in pack.get("files", [])]
    r.ok(f"npm pack --dry-run --json --ignore-scripts: {len(files)} files in {data[0].get('filename', '?')}")
    bad = [f for f in files if not (f.startswith("css/") or f in ("README.md", "LICENSE.md", "package.json"))]
    if bad:
        r.fail(f"{len(bad)} packed file(s) outside css/, README.md, LICENSE.md, package.json:")
        r.failures += ["    " + b for b in capped(sorted(bad), "files")]
    else:
        top = sorted({f.split("/")[0] + ("/" if "/" in f else "") for f in files})
        r.ok("packed: " + ", ".join(top))
    return r


def criterion_11(root: Path) -> Result:
    r = Result("Criterion 11: LICENSE.md keeps the Pico copyright and adds a femto line; no Pico logo files")
    lic = root / "LICENSE.md"
    if not lic.exists():
        r.fail("LICENSE.md missing")
    else:
        lines = [l.strip() for l in lic.read_text(encoding="utf-8").split("\n")]
        pico = "Copyright (c) 2019-2024 Pico"
        if pico in lines:
            r.ok(f"LICENSE.md keeps '{pico}'")
        else:
            r.fail(f"LICENSE.md lacks the line '{pico}'")
        others = [l for l in lines if re.match(r"copyright\b", l, re.I) and l != pico]
        if others:
            r.ok("LICENSE.md adds: " + " | ".join(others))
            if not any(re.search(r"femto", l, re.I) for l in others):
                r.note("the added copyright line does not name femto; confirm it is the femto line")
        else:
            r.fail("LICENSE.md has no copyright line besides the Pico one")
    files = effective_files(root)
    logos = [f for f in files if not name_exempt(f) and (re.search(r"logo", Path(f).name, re.I) or f in (".github/logo-dark.svg", ".github/logo-light.svg"))]
    for f in (".github/logo-dark.svg", ".github/logo-light.svg"):
        if (root / f).exists() and f not in logos:
            logos.append(f)
    images = []
    for f in files:
        if name_exempt(f) or not re.search(r"\.(svg|png|ico|jpe?g|gif|webp|avif)$", f, re.I):
            continue
        p = root / f
        if p.is_file() and re.search(rb"pico", p.read_bytes(), re.I) and f not in logos:
            images.append(f)
    if logos or images:
        r.fail(f"{len(logos) + len(images)} logo or Pico image file(s) remain:")
        r.failures += ["    " + f for f in capped(sorted(logos + images), "files")]
    else:
        r.ok("no logo files and no image mentioning pico outside docs/research and tests")
    return r


CHECKS = {
    "4": criterion_4,
    "5": criterion_5,
    "6": criterion_6,
    "7": criterion_7,
    "hygiene": hygiene,
    "vendor": vendor,
    "10": criterion_10,
    "11": criterion_11,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="comma-separated check ids: " + " ".join(CHECKS))
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="repository root")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    ids = args.only.split(",") if args.only else list(CHECKS)
    unknown = [i for i in ids if i not in CHECKS]
    if unknown:
        parser.error(f"unknown check ids: {unknown}")
    results = []
    for i in ids:
        try:
            results.append(CHECKS[i](root))
        except Exception as exc:  # a crashed check is a failed check
            res = Result(f"Check {i}")
            res.fail(f"check crashed: {type(exc).__name__}: {exc}")
            results.append(res)
    for res in results:
        res.print()
    failed = [res for res in results if not res.passed]
    print(f"\nSUMMARY: {len(results) - len(failed)} PASS, {len(failed)} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
