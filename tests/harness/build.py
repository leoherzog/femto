"""Reference splitting and hybrid entries.

A hybrid entry @imports a 2.1.1 reference split at its banner comments, in order, with chosen sections
replaced by their femto files from tests/sections.json. With no section replaced it is the chunk
control, which must compare clean against the monolithic reference.

Files are written under tests/build/ atomically and only when their content changes, so concurrent
harness runs can share them.
"""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .paths import BUILD, REPO, SECTIONS, path_to_url

BANNER_TITLE = re.compile(r"^ \* (.+)$")


class BuildError(Exception):
    pass


def write_atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def banners(lines):
    """[(index of '/**', [title lines])] for every banner: '/**', one or more ' * title', ' */'."""
    out = []
    for i, line in enumerate(lines):
        if line != "/**":
            continue
        titles, j = [], i + 1
        while j < len(lines) and BANNER_TITLE.match(lines[j]) and lines[j] != " */":
            titles.append(BANNER_TITLE.match(lines[j]).group(1))
            j += 1
        if titles and j < len(lines) and lines[j] == " */":
            out.append((i, titles))
    return out


def split(ref_url: str):
    """Split a reference stylesheet into chunks. Returns [{title, url}] with '(preamble)' first."""
    path = REPO / ref_url.lstrip("/")
    if not path.exists():
        raise BuildError(f"reference {ref_url} does not exist")
    text = path.read_text()
    lines = text.split("\n")
    found = banners(lines)
    if not found:
        raise BuildError(f"no banner comments in {ref_url}")
    starts = [0] + [i for i, _ in found] + [len(lines)]
    titles = ["(preamble)"] + [t[0] for _, t in found]
    stem = path.name.removesuffix(".css")
    if path.parent.name == "options":
        stem = "options-" + stem
    out = []
    for n, title in enumerate(titles):
        a, b = starts[n], starts[n + 1]
        chunk = "\n".join(lines[a:b])
        if b < len(lines):
            chunk += "\n"
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "preamble"
        p = BUILD / "chunks" / stem / f"{n:02d}-{slug}.css"
        write_atomic(p, chunk)
        out.append({"title": title, "url": path_to_url(p)})
    if "".join((REPO / c["url"].lstrip("/")).read_text() for c in out) != text:
        raise BuildError(f"chunks of {ref_url} do not reassemble the file")
    return out


def load_sections():
    if not SECTIONS.exists():
        raise BuildError("tests/sections.json is missing (owned by the refs agent)")
    return json.loads(SECTIONS.read_text())


def section_files(entry: str):
    """{title: [root-relative femto URLs]} for an entry of tests/sections.json, in file order."""
    data = load_sections()
    root = data.get("files_root", "css/").strip("/")
    if entry not in data.get("entries", {}):
        raise BuildError(f"tests/sections.json has no entry {entry!r}")
    out = {}
    for s in data["entries"][entry]["sections"]:
        out[s["title"]] = [f"/{root}/{f}" for f in s.get("files", [])]
    return out


def modules_to_sections(entry: str, modules):
    """Section titles whose femto files include css/<module>.css."""
    files = section_files(entry)
    titles = []
    for m in modules:
        hit = [t for t, fs in files.items() if f"/css/{m}.css" in fs]
        if not hit:
            raise BuildError(f"module {m} is not mapped to any section of entry {entry} in tests/sections.json")
        titles += [t for t in hit if t not in titles]
    return titles


def hybrid(ref_url: str, sections_entry: str, replace, append=(), name=None):
    """Write a hybrid entry and return its root-relative URL.

    replace: section titles whose reference chunk is swapped for the femto files.
    append:  root-relative URLs imported at the end when any section is replaced (theme or option file).
    """
    chunks = split(ref_url)
    files = section_files(sections_entry)
    titles = [c["title"] for c in chunks]
    expected = list(files)
    if titles != expected:
        raise BuildError(f"banner titles of {ref_url} differ from tests/sections.json entry {sections_entry}: "
                         f"{titles} vs {expected}")
    replace = list(replace)
    unknown = [t for t in replace if t not in files]
    if unknown:
        raise BuildError(f"unknown sections {unknown}; known: {expected}")
    lines, missing = [], []
    for c in chunks:
        if c["title"] in replace:
            if not files[c["title"]]:
                raise BuildError(f"section {c['title']} has no femto files to replace it")
            for u in files[c["title"]]:
                if not (REPO / u.lstrip("/")).exists():
                    missing.append(u)
                lines.append(f'@import url("{u}"); /* {c["title"]} */')
        else:
            lines.append(f'@import url("{c["url"]}");')
    if replace:
        for u in append:
            if not (REPO / u.lstrip("/")).exists():
                missing.append(u)
            lines.append(f'@import url("{u}");')
    if missing:
        raise BuildError("femto files missing for the hybrid build: " + ", ".join(missing))
    stem = Path(ref_url).name.removesuffix(".css")
    if not name:
        if not replace:
            name = "control"
        else:
            slug = "+".join(re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") for t in replace)
            if len(slug) > 60:
                slug = slug[:40] + "-" + hashlib.sha1(slug.encode()).hexdigest()[:8]
            name = "hybrid-" + slug
    header = (f"/* Generated by tests/harness/build.py: {ref_url} split at its banners"
              + (f", with {', '.join(replace)} replaced by femto files" if replace else " (chunk control)") + ". */\n")
    p = BUILD / "hybrid" / stem / f"{name}.css"
    write_atomic(p, header + "\n".join(lines) + "\n")
    return path_to_url(p)
