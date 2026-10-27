#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["selenium==4.51.0", "pillow==13.0.0"]
# ///
"""femto parity harness. Usage: uv run tests/run.py <mode> [options]; see tests/README.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
