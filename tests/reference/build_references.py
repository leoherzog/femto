#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Builds and checks the parity oracle in tests/reference/ from git tag v2.1.1.

  uv run tests/reference/build_references.py copies     write the 42 renamed 2.1.1 files, then check them
  uv run tests/reference/build_references.py options    compile the 3 option references (needs npm and network)
  uv run tests/reference/build_references.py check      verify all 45 references (offline, stdlib only)

The rename touches identifiers only: "--pico-" becomes "--femto-" and the ".pico-" class prefix
(only used by pico.colors.css) becomes ".femto-". Comments, including the "Pico CSS" header, are kept
byte for byte as provenance. tests/ is exempt from the name rule (PLAN Decision 10).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REF = REPO / "tests" / "reference"
TAG = "v2.1.1"
COLORS = (
    "amber blue cyan fuchsia green grey indigo jade lime orange pink pumpkin purple red sand slate "
    "violet yellow zinc"
).split()

# Published reference name -> 2.1.1 source path.
COPIES = {
    "femto.css": "css/pico.css",
    "femto.classless.css": "css/pico.classless.css",
    "femto.fluid.classless.css": "css/pico.fluid.classless.css",
    "femto.colors.css": "css/pico.colors.css",
    **{f"femto.{c}.css": f"css/pico.{c}.css" for c in COLORS},
    **{f"femto.classless.{c}.css": f"css/pico.classless.{c}.css" for c in COLORS},
}

# Option references: output name -> Sass configuration, in the style of scss/pico.classless.scss.
OPTIONS = {
    "femto.responsive-spacings.css": "$enable-responsive-spacings: true",
    "femto.no-transitions.css": "$enable-transitions: false",
    "femto.fixed-typography.css": "$enable-responsive-typography: false",
}

# SHA-256 of each option reference as compiled and autoprefixed, before the rename (sass 1.85.1).
# `check` reverses the rename and compares, so the round trip is verified offline.
OPTION_SHA256 = {
    "femto.responsive-spacings.css": "7637fffa49de24fc1edafb76d6a943b7c23c90d7ff9112c5d5dae534dfb98570",
    "femto.no-transitions.css": "79171aff5baac3bf84befd7474053285542a317ba3004922f81fb58cb8e4286b",
    "femto.fixed-typography.css": "559dcd1b39833aa6cd121418daca858a2fd08d6b079d00fc076013fdcc220a3b",
}

# The 2.1.1 build used `sass` from yarn.lock (1.85.1). See README.md for why 1.106.1 is not used.
DEFAULT_SASS = "1.85.1"
SASS_FLAGS = ["--no-source-map", "--style", "expanded", "--no-error-css"]  # 2.1.1 build:css flags

# 2.1.1 autoprefix step: `postcss --config css --replace css/*.css` with css/postcss.config.js and
# browserslist "defaults". Versions are the ones yarn.lock resolves for each package; caniuse-lite
# 1.0.30001702 is what autoprefixer and browserslist resolve to (the root pin 1.0.30001704 is not
# theirs), so it is forced with overrides together with the rest of the data-bearing tree.
AUTOPREFIX_PACKAGE = {
    "name": "femto-reference-build",
    "private": True,
    "devDependencies": {
        "autoprefixer": "10.4.21",
        "browserslist": "4.24.4",
        "caniuse-lite": "1.0.30001702",
        "postcss": "8.5.3",
        "postcss-cli": "11.0.1",
    },
    "overrides": {
        "caniuse-lite": "1.0.30001702",
        "browserslist": "4.24.4",
        "electron-to-chromium": "1.5.113",
        "node-releases": "2.0.19",
        "update-browserslist-db": "1.1.3",
        "fraction.js": "4.3.7",
        "normalize-range": "0.1.2",
        "picocolors": "1.1.1",
        "postcss-value-parser": "4.2.0",
        "postcss": "8.5.3",
    },
    "browserslist": ["defaults"],
}

RENAME = ((re.compile(r"--pico-"), "--femto-"), (re.compile(r"\.pico-(?=color-|background-)"), ".femto-"))
UNRENAME = ((re.compile(r"--femto-"), "--pico-"), (re.compile(r"\.femto-(?=color-|background-)"), ".pico-"))


def git_show(path: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), "show", f"{TAG}:{path}"], capture_output=True, check=True).stdout


def substitute(text: str, table) -> tuple[str, int]:
    total = 0
    for pattern, repl in table:
        text, n = pattern.subn(repl, text)
        total += n
    return text, total


def strip_comments(css: str) -> str:
    """Remove /* */ comments outside strings."""
    out, i, n, quote = [], 0, len(css), None
    while i < n:
        c = css[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(css[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
            out.append(c)
        elif css.startswith("/*", i):
            end = css.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def rename(source: bytes) -> tuple[bytes, int]:
    text = source.decode("utf-8")
    if re.search(r"(?i)femto", text):
        raise SystemExit("source already contains 'femto'; the round trip check would be meaningless")
    renamed, count = substitute(text, RENAME)
    return renamed.encode("utf-8"), count


def verify(name: str, source: bytes, output: bytes) -> list[str]:
    """Return problems: the reverse substitution must restore the source byte for byte, and no
    "pico" may remain outside comments."""
    problems = []
    back, _ = substitute(output.decode("utf-8"), UNRENAME)
    if back.encode("utf-8") != source:
        problems.append(f"{name}: reverse substitution does not restore the source byte for byte")
    leftovers = re.findall(r"(?i).{0,20}pico.{0,20}", strip_comments(output.decode("utf-8")))
    if leftovers:
        problems.append(f"{name}: 'pico' outside comments: {leftovers[:3]}")
    return problems


def cmd_copies(_args) -> int:
    REF.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, src in COPIES.items():
        source = git_show(src)
        output, count = rename(source)
        (REF / name).write_bytes(output)
        total += count
        print(f"wrote tests/reference/{name} from {TAG}:{src} ({count} identifiers renamed)")
    print(f"{len(COPIES)} files, {total} identifiers renamed")
    return cmd_check(_args)


def run(cmd, cwd, **kw):
    print("$", " ".join(str(c) for c in cmd), f"(cwd {cwd})")
    return subprocess.run(cmd, cwd=cwd, check=True, **kw)


def diff_summary(a: bytes, b: bytes, label: str) -> str:
    al, bl = a.decode().splitlines(), b.decode().splitlines()
    changed = [l for l in difflib.unified_diff(al, bl, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    return f"{label}: {sum(1 for l in changed if l[0] == '-')} lines removed, {sum(1 for l in changed if l[0] == '+')} added"


def cmd_options(args) -> int:
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="femto-ref-"))
    src, build = work / "src", work / "build" / "css"
    if src.exists():
        shutil.rmtree(src)
    if build.exists():
        shutil.rmtree(build)
    src.mkdir(parents=True)
    build.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(REPO), "archive", TAG, "scss", "css/postcss.config.js"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(src)], input=archive, check=True)
    shutil.copy(src / "css" / "postcss.config.js", build / "postcss.config.js")
    entries = {"pico.css": "pico.scss", "pico.classless.css": "pico.classless.scss"}
    for out, setting in OPTIONS.items():
        scss = out.replace(".css", ".scss")
        (src / "scss" / scss).write_text(f'// femto option reference\n@use "index" with (\n  {setting}\n);\n')
        entries[out] = scss
    for out, scss in entries.items():
        run(["npx", "--yes", f"sass@{args.sass}", *SASS_FLAGS, f"src/scss/{scss}", f"build/css/{out}"], work)
    (work / "package.json").write_text(json.dumps(AUTOPREFIX_PACKAGE, indent=2) + "\n")
    run(["npm", "install", "--no-audit", "--no-fund", "--loglevel", "error"], work)
    run([str(work / "node_modules" / ".bin" / "postcss"), "--config", "build/css", "--replace", *[f"build/css/{o}" for o in entries]], work, stderr=subprocess.DEVNULL)

    control_ok = True
    for name in ("pico.css", "pico.classless.css"):
        built, oracle = (build / name).read_bytes(), git_show(f"css/{name}")
        same = built == oracle
        control_ok &= same
        print(f"CONTROL sass {args.sass}: {name} {'byte-identical to' if same else 'DIFFERS from'} {TAG}:css/{name}")
        if not same:
            print("  " + diff_summary(oracle, built, "oracle -> built"))
    if not control_ok and not args.force:
        print(f"control failed; nothing written. Work folder kept at {work}")
        return 1
    (REF / "options").mkdir(parents=True, exist_ok=True)
    problems = []
    for out in OPTIONS:
        compiled = (build / out).read_bytes()
        output, count = rename(compiled)
        problems += verify(out, compiled, output)
        (REF / "options" / out).write_bytes(output)
        digest = hashlib.sha256(compiled).hexdigest()
        same = "matches" if digest == OPTION_SHA256[out] else "DIFFERS from"
        print(f"wrote tests/reference/options/{out} ({count} identifiers renamed); compile SHA-256 {digest} {same} the recorded one")
        print("  " + diff_summary(git_show("css/pico.css"), compiled, f"vs {TAG}:css/pico.css"))
    for p in problems:
        print("FAIL", p)
    print(f"work folder: {work}")
    return 1 if problems else 0


def cmd_check(_args) -> int:
    problems = []
    for name, src in COPIES.items():
        path = REF / name
        if not path.exists():
            problems.append(f"{name}: missing")
            continue
        problems += verify(name, git_show(src), path.read_bytes())
    extra = sorted(p.name for p in REF.glob("*.css") if p.name not in COPIES)
    if extra:
        problems.append(f"unexpected files in tests/reference/: {extra}")
    for out in OPTIONS:
        path = REF / "options" / out
        if not path.exists():
            problems.append(f"options/{out}: missing")
            continue
        text = path.read_bytes()
        back, _ = substitute(text.decode(), UNRENAME)
        if hashlib.sha256(back.encode()).hexdigest() != OPTION_SHA256[out]:
            problems.append(f"options/{out}: reverse substitution does not match the recorded compile (SHA-256)")
        if re.search(r"(?i)femto", back):
            problems.append(f"options/{out}: reverse substitution leaves 'femto'")
        leftovers = re.findall(r"(?i).{0,20}pico.{0,20}", strip_comments(text.decode()))
        if leftovers:
            problems.append(f"options/{out}: 'pico' outside comments: {leftovers[:3]}")
    for p in problems:
        print("FAIL", p)
    print(f"checked {len(COPIES)} renamed copies and {len(OPTIONS)} option references: {'FAIL' if problems else 'PASS'}")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("copies")
    opt = sub.add_parser("options")
    opt.add_argument("--sass", default=DEFAULT_SASS, help=f"sass version for npx (default {DEFAULT_SASS})")
    opt.add_argument("--work", help="work folder (default: a new temp folder)")
    opt.add_argument("--force", action="store_true", help="write the option references even if the control fails")
    sub.add_parser("check")
    args = parser.parse_args()
    return {"copies": cmd_copies, "options": cmd_options, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
