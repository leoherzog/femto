"""Repository paths used by the harness."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "tests"
HARNESS = TESTS / "harness"
PAGES = TESTS / "pages"
REFERENCE = TESTS / "reference"
DIVERGENCES = TESTS / "divergences"
BUILD = TESTS / "build"
RESULTS = TESTS / "results"
VARIANTS = TESTS / "variants.json"
SECTIONS = TESTS / "sections.json"
MANIFEST = PAGES / "pages.json"


def url_to_path(url: str) -> Path:
    """Map a root-relative URL served by the harness to the file behind it."""
    return REPO / url.lstrip("/").split("?", 1)[0]


def path_to_url(path: Path) -> str:
    return "/" + Path(path).resolve().relative_to(REPO).as_posix()
