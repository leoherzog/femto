#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Mechanical checks for PLAN.md acceptance criteria 4, 5, 6, 7, 9, 10, 11 and 12, plus shipped-file hygiene and theme-file text.

  uv run tests/static_checks.py                 run every check
  uv run tests/static_checks.py --only 6,7      run some (ids: 4 5 6 7 hygiene vendor themes 9 10 11 12)
  uv run tests/static_checks.py --root DIR      check another checkout (6, 7, hygiene, vendor and themes need no git)

Each check prints PASS or FAIL with evidence lines; the exit status is 1 if any check fails.
"hygiene", "vendor" and "themes" are not acceptance criteria. The first two cover PLAN rules the lint
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

"themes" covers what the harness cannot see in a theme file: tokens-light-dark-raw-text accepts
any light-dark() text, so it compares each file's ten tokens with its 2.1.1 reference as text.

Criterion 9 checks the coverage table in tests/README.md ("Coverage: 2.1.1 modules and settings")
against tag v2.1.1's $modules keys and settings, tests/sections.json, tests/pages/pages.json and the
imports of css/femto.css.

"Shipped files" are everything under css/. dist/ ships too, but npm run build writes it from css/,
so criterion 12 checks it against a fresh build.
CSS checks look at code only: comments are removed first and, for the forbidden-syntax scans,
string contents (including url("data:...") icons) are blanked, so a comment that mentions
@layer, or an SVG that uses rgb(), is not a violation. Mentions in comments are listed as notes.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENTRIES = ("femto.css",)
BUILD_SCRIPT = "node build.mjs"  # PLAN Decision 1: the one build, esbuild via build.mjs
DEV_DEPENDENCIES = {"esbuild", "eslint", "@eslint/css"}
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
    r"::-webkit-input-placeholder|::-moz-list-bullet|::-moz-selection|:-moz-ui-invalid|:-moz-focusring",
    re.I,
)
KEPT_PREFIXED_PROPERTIES = {
    "-webkit-text-size-adjust",
    "-webkit-user-select",
    "-webkit-backdrop-filter",
    "-webkit-tap-highlight-color",
    "-webkit-appearance",
    # Link only (content/link.css): before 26.2, Safari's text-decoration sets only the line.
    "-webkit-text-decoration",
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


def shipped_files(root: Path) -> list[Path]:
    """Shipped files under css/."""
    css = root / "css"
    if not css.is_dir():
        return []
    return [p for p in sorted(css.rglob("*")) if p.is_file() and p.name != ".DS_Store"]


def describe_shipped(r: Result, shipped: list[Path]) -> list[Path]:
    css_files = [p for p in shipped if p.suffix == ".css"]
    if not css_files:
        r.fail("no shipped femto CSS files under css/ (nothing converted yet)")
    else:
        r.ok(f"{len(css_files)} shipped CSS files under css/")
    return css_files


# ---------------------------------------------------------------------------- criteria


def criterion_4(root: Path) -> Result:
    r = Result("Criterion 4: no *.scss, scripts/, PostCSS config or yarn.lock in git; the only build script runs build.mjs")
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
    data = json.loads(pkg.read_text())
    scripts = data.get("scripts", {}) or {}
    build = [k for k in scripts if re.match(r"(pre|post)?build(:|$)", k) and k != "build"]
    tools = [k for k, v in scripts.items() if re.search(r"\b(sass|postcss|autoprefixer|clean-?css|cleancss|esbuild|lightningcss)\b", str(v))]
    bad = []
    if scripts.get("build") != BUILD_SCRIPT:
        bad.append(f"package.json build script is {scripts.get('build')!r}, expected {BUILD_SCRIPT!r}")
    if build:
        bad.append(f"package.json build scripts besides build: {', '.join(build)}")
    if tools:
        bad.append(f"package.json scripts that run a CSS build tool directly: {', '.join(tools)}")
    for line in bad:
        r.fail(line)
    if not bad:
        r.ok(f"package.json scripts: {', '.join(scripts)}; build is {BUILD_SCRIPT!r}")
    extra = sorted(set(data.get("devDependencies", {})) - DEV_DEPENDENCIES)
    if extra or data.get("dependencies"):
        r.fail(f"package.json depends on more than {', '.join(sorted(DEV_DEPENDENCIES))}: {', '.join(extra + sorted(data.get('dependencies', {})))}")
    else:
        r.ok(f"package.json devDependencies: {', '.join(data.get('devDependencies', {}))}")
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
    r = Result("Criterion 6: Only femto.css contains @import, and its imports come before every other rule")
    shipped = shipped_files(root)
    css_files = describe_shipped(r, shipped)
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
                    r.fail(f"{rel}:{line_of(text, o)}: imports the entry ({target}); chains must be one level deep")
            elif seen_rule is None:
                seen_rule = o
        r.ok(f"{rel}: {len(imports)} @import rules, all before the first other rule" if not any(f.startswith(rel) for f in r.failures) else f"{rel}: {len(imports)} @import rules")
    return r


def criterion_7(root: Path) -> Result:
    r = Result("Criterion 7: no @layer, @scope, if(, @function, @mixin, @apply, @custom-media, @container style(; no 'from' in color functions; every color-mix( uses 'in srgb'")
    shipped = shipped_files(root)
    css_files = describe_shipped(r, shipped)
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
    shipped = shipped_files(root)
    css_files = describe_shipped(r, shipped)
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
            words = re.sub(r"\s+", " ", m.group(1).lstrip("!")).strip()
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
    shipped = shipped_files(root)
    css_files = describe_shipped(r, shipped)
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


THEME_TOKENS = (
    "text-selection-color",
    "primary",
    "primary-background",
    "primary-underline",
    "primary-hover",
    "primary-hover-background",
    "primary-focus",
    "primary-inverse",
    "primary-inverse-filter",
    "switch-thumb-box-shadow",
)
THEME_BLOCKS = {
    "light": "[data-theme=light], :root:not([data-theme=dark]), :host(:not([data-theme=dark]))",
    "dark-media": "@media only screen and (prefers-color-scheme: dark) >> :root:not([data-theme]), :host(:not([data-theme]))",
    "dark": "[data-theme=dark]",
    "spinner": "[aria-busy=true]:not(input, select, textarea):is(button, [type=submit], [type=button], [type=reset], [role=button]):not(.outline)::before",
}


def reference_rules(text: str) -> dict[str, dict[str, str]]:
    """Declarations of each rule in a compiled 2.1.1 reference, keyed by its at-rule path and selector."""
    rules: dict[str, dict[str, str]] = {}
    stack: list[str] = []
    pending: list[str] = []
    for line in re.sub(r"/\*.*?\*/", "", text, flags=re.S).splitlines():
        s = line.strip()
        if not s:
            continue
        if s.endswith("{"):
            stack.append(" ".join(pending + [s[:-1].strip()]))
            pending = []
        elif s == "}":
            if stack:
                stack.pop()
        elif s.endswith(","):
            pending.append(s)
        elif m := re.fullmatch(r"([\w-]+):\s*(.*);", s):
            rules.setdefault(" >> ".join(stack), {})[m.group(1)] = m.group(2)
    return rules


def themes(root: Path) -> Result:
    r = Result("Theme files: each css/themes/<color>.css is the ten tokens of its 2.1.1 reference, text for text")
    files = sorted((root / "css/themes").glob("*.css"))
    if not files:
        r.note("no css/themes/*.css yet")
        return r
    for p in files:
        rel = p.relative_to(root).as_posix()
        color = p.stem
        ref = root / "tests/reference" / ("femto.css" if color == "azure" else f"femto.{color}.css")
        if not ref.exists():
            r.fail(f"{rel}: no reference {ref.relative_to(root).as_posix()}")
            continue
        rules = reference_rules(ref.read_text())
        blocks = {name: rules.get(sel, {}) for name, sel in THEME_BLOCKS.items()}
        light, dark = blocks["light"], blocks["dark"]
        expected = []
        for t in THEME_TOKENS:
            if t == "primary-inverse-filter":
                value = blocks["spinner"].get("filter")
            else:
                name = "--femto-" + t
                if blocks["dark-media"].get(name) != dark.get(name):
                    r.fail(f"{rel}: reference {name} differs between the prefers-color-scheme and data-theme=dark blocks")
                value = None
                if name in light and name in dark:
                    value = light[name] if light[name] == dark[name] else f"light-dark({light[name]}, {dark[name]})"
            if value is None:
                r.fail(f"{rel}: reference has no value for --femto-{t}")
            expected.append((f"--femto-{t}", value))
        code = re.sub(r"/\*.*?\*/", "", p.read_text(), flags=re.S)
        m = re.fullmatch(r"\s*:root,\s*:host\s*\{([^{}]*)\}\s*", code)
        if not m:
            r.fail(f"{rel}: not a single rule on :root, :host")
            continue
        got = [tuple(part.strip() for part in d.split(":", 1)) for d in m.group(1).split(";") if d.strip()]
        if [g[0] for g in got] != [e[0] for e in expected]:
            r.fail(f"{rel}: declares {[g[0] for g in got]}, expected the ten theme tokens in azure.css order")
            continue
        for (name, value), (_, want) in zip(got, expected):
            if want is not None and value != want:
                r.fail(f"{rel}: {name}: {value} (2.1.1 reference text: {want})")
    if r.passed:
        r.ok(f"{len(files)} theme files match their references")
    return r


COVERAGE_HEADING = "Coverage: 2.1.1 modules and settings"  # the criterion 9 section of tests/README.md


def table_rows(lines: list[str]) -> list[list[str]]:
    """Body rows of the Markdown tables in lines, as stripped cells (header and rule rows dropped)."""
    rows, body = [], False
    for line in lines:
        if not line.startswith("|"):
            body = False
        elif re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", line.strip()):
            body = True
        elif body:
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def criterion_9(root: Path) -> Result:
    r = Result("Criterion 9: tests/README.md maps every 2.1.1 $modules key and Sass setting to its femto file or mechanism")
    lines = (root / "tests/README.md").read_text(encoding="utf-8").split("\n")
    sections = markdown_sections(lines)
    top = next(((s, e) for s, e, h in sections if h.startswith(COVERAGE_HEADING)), None)
    if top is None:
        r.fail(f"tests/README.md has no '{COVERAGE_HEADING}' section")
        return r
    sub = {h: table_rows(lines[s:e]) for s, e, h in sections if top[0] < s < top[1]}
    for h in ("Modules", "Settings"):
        if not sub.get(h):
            r.fail(f"tests/README.md '{COVERAGE_HEADING}' has no '{h}' table")
    if not r.passed:
        return r
    shown = {}
    for f in ("scss/_settings.scss", "scss/colors/utilities/_settings.scss"):
        proc = git(root, "show", f"v2.1.1:{f}", check=False)
        if proc.returncode != 0:
            r.fail(f"git show v2.1.1:{f} failed (run git fetch --tags): {proc.stderr.strip()[:200]}")
            return r
        shown[f] = proc.stdout
    block = re.search(r"\$modules: map\.merge\(\s*\((.*?)\),\s*\$modules", shown["scss/_settings.scss"], re.S)
    keys = re.findall(r'"([\w/-]+)":\s*true', block.group(1)) if block else []
    if len(keys) != 33:
        r.fail(f"expected 33 $modules keys in v2.1.1:scss/_settings.scss, found {len(keys)}")
    # Modules: every key once, in $modules order, with the femto files of its sections at their import positions.
    mods = sub["Modules"]
    listed = [m.group(1) if (m := re.fullmatch(r"`([^`]+)`", row[0])) else row[0] for row in mods]
    if set(listed) != set(keys) or len(listed) != len(keys):
        r.fail(f"Modules table lists {len(listed)} modules; missing {[k for k in keys if k not in listed]}, "
               f"extra or repeated {[k for k in listed if k not in keys or listed.count(k) > 1]}")
    elif listed != keys:
        r.fail("Modules table rows are not in $modules order")
    imports = re.findall(r'^@import "([^"]+)";', (root / "css/femto.css").read_text(encoding="utf-8"), re.M)
    want_pos = {f: i + 1 for i, f in enumerate(imports)}
    sections_json = json.loads((root / "tests/sections.json").read_text(encoding="utf-8"))
    by_title = {s["title"]: s["files"] for s in sections_json["entries"]["default"]["sections"] if s["title"] != "(preamble)"}
    pages = {p["page"] for p in json.loads((root / "tests/pages/pages.json").read_text(encoding="utf-8"))}
    got_pos, titles_seen = {}, []
    for name, row in zip(listed, mods):
        if len(row) != 4:
            r.fail(f"Modules row {name}: {len(row)} cells, expected 4")
            continue
        titles = [t.strip() for t in row[1].replace("`", "").split(";")]
        titles_seen += titles
        unknown = [t for t in titles if t not in by_title]
        if unknown:
            r.fail(f"Modules row {name}: sections not in tests/sections.json: {unknown}")
        files = re.findall(r"`([\w/.-]+\.css)` \((\d+)\)", row[2])
        for f, n in files:
            if f in got_pos:
                r.fail(f"Modules row {name}: {f} is numbered in more than one row")
            got_pos[f] = int(n)
        expected = sorted(f for t in titles if t in by_title for f in by_title[t])
        if sorted(f for f, _ in files) != expected:
            r.fail(f"Modules row {name}: numbered files {sorted(f for f, _ in files)}, tests/sections.json gives {expected}")
        missing_pages = [p for p in re.findall(r"`([\w.-]+\.html)`", row[3]) if p not in pages]
        if missing_pages:
            r.fail(f"Modules row {name}: pages not in tests/pages/pages.json: {missing_pages}")
    if got_pos != want_pos:
        bad = sorted(set(got_pos.items()) ^ set(want_pos.items()))
        r.fail(f"Modules table positions differ from css/femto.css's {len(imports)} imports: " + ", ".join(f"{f} ({n})" for f, n in bad[:MAX_LINES]))
    left = sorted(set(by_title) - set(titles_seen))
    if left:
        r.fail(f"tests/sections.json sections in no Modules row: {left}")
    # Settings: every !default setting of both 2.1.1 settings files, the pico.colors ones marked as such.
    setting = lambda text: set(re.findall(r"^\$([\w-]+):[^;]*!default;", text, re.M))
    want = {"core": setting(shown["scss/_settings.scss"]), "pico.colors": setting(shown["scss/colors/utilities/_settings.scss"])}
    got = {"core": set(), "pico.colors": set()}
    for row in sub["Settings"]:
        names = re.findall(r"`\$([\w-]+)`", row[0])
        if not names or len(row) != 4 or not all(row[1:]):
            r.fail(f"Settings row {row[0]!r}: expected a setting name and three non-empty cells")
        got["pico.colors" if "pico.colors" in row[0] else "core"].update(names)
    for k in want:
        if got[k] != want[k]:
            r.fail(f"Settings table, {k} settings: missing {sorted(want[k] - got[k])}, extra {sorted(got[k] - want[k])}")
    if r.passed:
        r.ok(f"{len(keys)} $modules keys from v2.1.1:scss/_settings.scss, in order, each with its tests/sections.json sections and fixture pages")
        r.ok(f"{len(imports)} imports of css/femto.css, each in one Modules row at its position")
        r.ok(f"{len(want['core'])} settings from scss/_settings.scss and {len(want['pico.colors'])} from scss/colors/utilities/_settings.scss in the Settings table")
    return r


def criterion_10(root: Path) -> Result:
    r = Result("Criterion 10: npm pack --dry-run lists only css/, dist/, README.md, LICENSE.md and package.json")
    proc = subprocess.run(["npm", "pack", "--dry-run", "--json", "--ignore-scripts"], cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        r.fail(f"npm pack --dry-run failed: {proc.stderr.strip()[:200]}")
        return r
    data = json.loads(proc.stdout)
    files = [f["path"] for pack in data for f in pack.get("files", [])]
    r.ok(f"npm pack --dry-run --json --ignore-scripts: {len(files)} files in {data[0].get('filename', '?')}")
    bad = [f for f in files if not (f.startswith(("css/", "dist/")) or f in ("README.md", "LICENSE.md", "package.json"))]
    if bad:
        r.fail(f"{len(bad)} packed file(s) outside css/, dist/, README.md, LICENSE.md, package.json:")
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


def criterion_12(root: Path) -> Result:
    r = Result("Criterion 12: dist/ is exactly what npm run build writes from css/")
    if not (root / "node_modules/esbuild").is_dir():
        r.fail("node_modules/esbuild is missing; run npm ci")
        return r
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copytree(root / "css", work / "css")
        for name in ("package.json", "build.mjs"):
            shutil.copy2(root / name, work / name)
        (work / "node_modules").symlink_to(root / "node_modules", target_is_directory=True)
        proc = subprocess.run(["npm", "run", "build", "--silent"], cwd=work, capture_output=True, text=True)
        if proc.returncode != 0:
            r.fail(f"npm run build failed: {(proc.stderr or proc.stdout).strip()[:300]}")
            return r
        if proc.stderr.strip():
            r.note(f"build warnings: {proc.stderr.strip()[:300]}")
        fresh = {p.relative_to(work).as_posix(): p.read_bytes() for p in sorted((work / "dist").rglob("*")) if p.is_file()}
    have = {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted((root / "dist").rglob("*")) if p.is_file() and p.name != ".DS_Store"}
    tracked = set(effective_files(root))
    for f in sorted(fresh.keys() | have.keys()):
        if f not in have:
            r.fail(f"{f}: missing (npm run build writes it)")
        elif f not in fresh:
            r.fail(f"{f}: not written by npm run build")
        elif have[f] != fresh[f]:
            r.fail(f"{f}: differs from a fresh build")
        elif f not in tracked:
            r.fail(f"{f}: up to date but ignored by git")
        else:
            r.ok(f"{f}: {len(fresh[f])} bytes, same as a fresh build")
    if not r.passed:
        r.fail("run npm run build (the Build workflow also commits a rebuilt dist/ after each push)")
    return r


CHECKS = {
    "4": criterion_4,
    "5": criterion_5,
    "6": criterion_6,
    "7": criterion_7,
    "hygiene": hygiene,
    "vendor": vendor,
    "themes": themes,
    "9": criterion_9,
    "10": criterion_10,
    "11": criterion_11,
    "12": criterion_12,
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
