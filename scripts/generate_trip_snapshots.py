"""Generate deterministic Issue 23 trip product snapshots locally."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.services.trip_snapshot_generation import generate_issue23_snapshots


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("fixtures/trips"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    for path in generate_issue23_snapshots(args.output_dir, overwrite=args.overwrite):
        print(path)


if __name__ == "__main__":
    main()
