#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Both Safari passes of the full matrix: macOS light, then dark, then the appearance it started with.

  uv run tests/safari.py                    full matrix on a light OS, selftest, full matrix on a dark OS
  uv run tests/safari.py --no-selftest      skip the selftest
  uv run tests/safari.py -- --pages kitchen-sink.html --no-states
                                            pass options to both full runs (not --browsers or --run-id)

Quit Safari first, then leave the machine alone until it finishes. The display stays awake while it
runs. The exit status is 0 only when every run passes, every Safari session read the scheme its
pass set, and the appearance held through each run (Auto can switch it at sunrise or sunset).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESERVED = ("--browsers", "--run-id")


def appearance(command):
    out = subprocess.run(
        ["osascript", "-e", f'tell application "System Events" to tell appearance preferences to {command}'],
        capture_output=True, text=True, timeout=60)
    if out.returncode:
        sys.exit(f"osascript: {out.stderr.strip()}\nAllow this terminal to control System Events in "
                 "System Settings > Privacy & Security > Automation.")
    return out.stdout.strip()


def set_scheme(scheme):
    value = "true" if scheme == "dark" else "false"
    appearance(f"set dark mode to {value}")
    if appearance("get dark mode") != value:
        sys.exit("the macOS appearance did not change")
    time.sleep(2)


def problems(scheme, run_id, rig=True):
    found = []
    if rig and (read := schemes_read(run_id)) != {scheme}:
        found.append(f"Safari read OS scheme {', '.join(sorted(read)) or 'nothing'}")
    if appearance("get dark mode") != ("true" if scheme == "dark" else "false"):
        found.append("the macOS appearance changed during the run")
    return "; ".join(found)


def user_safari_open():
    ps = subprocess.run(["ps", "-axo", "args="], capture_output=True, text=True).stdout.splitlines()
    return any(line.split()[0].endswith("/Safari.app/Contents/MacOS/Safari") and "--automation" not in line
               for line in ps if line.strip())


def appearance_auto():
    out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyleSwitchesAutomatically"],
                         capture_output=True, text=True)
    return out.returncode == 0 and out.stdout.strip() == "1"


def harness(*args):
    print(f"\n$ uv run tests/run.py {' '.join(args)}", flush=True)
    return subprocess.run(["uv", "run", "tests/run.py", *args], cwd=ROOT).returncode


def schemes_read(run_id):
    try:
        rig = json.loads((ROOT / "tests/results" / run_id / "result.json").read_text())["rig"]
    except (OSError, ValueError, KeyError):
        return set()
    return {str(s.get("os_scheme")) for s in rig if s.get("browser") == "safari"}


def main():
    argv = sys.argv[1:]
    split = argv.index("--") if "--" in argv else len(argv)
    own, extra = argv[:split], argv[split + 1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage="uv run tests/safari.py [--no-selftest] [--run-id PREFIX] [-- FULL OPTIONS]")
    ap.add_argument("--no-selftest", action="store_true", help="skip the selftest in the light pass")
    ap.add_argument("--run-id", default=f"safari-{datetime.now():%Y%m%d-%H%M%S}",
                    help="prefix of the results folders: PREFIX-light, PREFIX-selftest, PREFIX-dark")
    args = ap.parse_args(own)
    if any(a.split("=")[0] in RESERVED for a in extra):
        ap.error(f"{' and '.join(RESERVED)} are set by this script")

    if sys.platform != "darwin":
        sys.exit("macOS only")
    if user_safari_open():
        sys.exit("Safari is open. Quit it (Cmd-Q): safaridriver cannot start a session while it runs.")
    if appearance_auto():
        print("Appearance is Auto: a switch at sunrise or sunset during a run fails that run.")

    was_dark = appearance("get dark mode") == "true"
    awake = subprocess.Popen(["caffeinate", "-d", "-i", "-w", str(os.getpid())])
    runs = []
    try:
        for scheme in ("light", "dark"):
            set_scheme(scheme)
            run_id = f"{args.run_id}-{scheme}"
            code = harness("full", "--browsers", "safari", "--run-id", run_id, *extra)
            runs.append((f"full, {scheme} OS", run_id, code, problems(scheme, run_id)))
            if scheme == "light" and not args.no_selftest:
                run_id = f"{args.run_id}-selftest"
                code = harness("selftest", "--browsers", "safari", "--run-id", run_id)
                runs.append(("selftest, light OS", run_id, code, problems(scheme, run_id, rig=False)))
    finally:
        appearance(f"set dark mode to {'true' if was_dark else 'false'}")
        awake.terminate()

    print()
    for label, run_id, code, problem in runs:
        status = "PASS" if code == 0 and not problem else "FAIL"
        print(f"{label:<20} {status}  tests/results/{run_id}/" + (f"  {problem}" if problem else ""))
    return 0 if all(code == 0 and not problem for _, _, code, problem in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
