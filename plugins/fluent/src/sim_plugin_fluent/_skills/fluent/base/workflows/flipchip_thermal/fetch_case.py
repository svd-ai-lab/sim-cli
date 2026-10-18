"""
Fetch the Ozen Engineering flip-chip demo case file for this workflow.

Downloads Flip_chip_demo_simplified.zip from Ozen's blog and extracts the
.cas.h5 into $SIM_DATASETS/flipchip/. Idempotent - skips if the target
already exists. Stdlib only; runs with plain python3 or `uv run`.

Usage:
    uv run fetch_case.py               # or: python3 fetch_case.py
    uv run fetch_case.py --force       # re-download even if present
    uv run fetch_case.py --dest /tmp   # override $SIM_DATASETS

The case file is hosted by Ozen Engineering, not us. If the URL breaks,
download manually from:
    https://blog.ozeninc.com/resources/flip-chip-thermal-characterization-using-ansys-fluent
and place Flip_chip_demo_simplified.cas.h5 under <dest>/flipchip/.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ZIP_URL = "https://blog.ozeninc.com/hubfs/Flip_chip_demo_simplified.zip"
CASE_NAME = "Flip_chip_demo_simplified.cas.h5"
SUBDIR = "flipchip"
MIN_BYTES = 1_000_000  # sanity floor - real file is ~40 MB
DEFAULT_DEST = Path.home() / ".cache" / "sim-datasets"


def resolve_dest(cli_dest: str | None) -> Path:
    if cli_dest:
        return Path(cli_dest).expanduser().resolve()
    env = os.environ.get("SIM_DATASETS")
    if env:
        return Path(env).expanduser().resolve()
    print(f"[fetch_case] SIM_DATASETS not set - using default: {DEFAULT_DEST}")
    return DEFAULT_DEST


def download(url: str, out: Path) -> None:
    req = Request(url, headers={"User-Agent": "sim-skills-fetch-case/1.0"})
    with urlopen(req) as resp:  # noqa: S310 (trusted URL, stdlib only)
        total = int(resp.headers.get("Content-Length", "0"))
        done = 0
        chunk = 1 << 16
        with out.open("wb") as f:
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                f.write(buf)
                done += len(buf)
                if total:
                    pct = done * 100 // total
                    print(f"\r[fetch_case] downloading {done/1e6:6.1f} / {total/1e6:.1f} MB ({pct}%)",
                          end="", flush=True)
                else:
                    print(f"\r[fetch_case] downloading {done/1e6:6.1f} MB", end="", flush=True)
        print()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_case(zip_path: Path, target: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if m.endswith(".cas.h5")]
        if not members:
            raise RuntimeError(
                f"No .cas.h5 found inside {zip_path.name}. "
                f"Archive contents: {zf.namelist()}"
            )
        member = members[0]
        if len(members) > 1:
            print(f"[fetch_case] multiple .cas.h5 in archive, using {member}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dest", help="Override SIM_DATASETS destination dir")
    ap.add_argument("--force", action="store_true", help="Re-download even if present")
    args = ap.parse_args()

    dest_root = resolve_dest(args.dest)
    target = dest_root / SUBDIR / CASE_NAME

    if target.exists() and not args.force:
        size_mb = target.stat().st_size / 1e6
        print(f"[fetch_case] already present: {target} ({size_mb:.1f} MB) - skipping")
        print(f"[fetch_case] use --force to re-download")
        return 0

    print(f"[fetch_case] fetching from {ZIP_URL}")
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "Flip_chip_demo_simplified.zip"
        try:
            download(ZIP_URL, zip_path)
        except Exception as e:
            print(f"[fetch_case] download failed: {e}", file=sys.stderr)
            print(f"[fetch_case] manual fallback: fetch the zip from", file=sys.stderr)
            print(f"  https://blog.ozeninc.com/resources/flip-chip-thermal-characterization-using-ansys-fluent",
                  file=sys.stderr)
            print(f"  then place {CASE_NAME} under {target.parent}", file=sys.stderr)
            return 1

        extract_case(zip_path, target)

    size = target.stat().st_size
    if size < MIN_BYTES:
        print(f"[fetch_case] extracted file is suspiciously small ({size} bytes) - aborting",
              file=sys.stderr)
        target.unlink()
        return 1

    print(f"[fetch_case] extracted to {target}")
    print(f"[fetch_case] size:   {size/1e6:.1f} MB")
    print(f"[fetch_case] sha256: {sha256(target)}")
    if not os.environ.get("SIM_DATASETS") and not args.dest:
        print()
        print(f"[fetch_case] next step: export SIM_DATASETS={dest_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
