#!/usr/bin/env python
"""Run preflight to check 455d availability for all 13 candidates.

Writes research/expansion_v1_preflight.json (write-once artifact).

Usage:
    python scripts/run_expansion_preflight.py --out research/expansion_v1_preflight.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from momentum.expansion.config import BUCKET_ASSIGNMENT
from momentum.expansion.preflight import run_preflight


_CANDIDATES = list(BUCKET_ASSIGNMENT.keys())


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="Output path for preflight JSON")
    p.add_argument("--required-days", type=int, default=455)
    args = p.parse_args()

    print(f"Running preflight for {len(_CANDIDATES)} candidates (required {args.required_days}d)...")
    result = run_preflight(symbols=_CANDIDATES, required_days=args.required_days)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(args.out, result.to_dict())

    print(f"Universe size: {result.universe_size}")
    print(f"Eligible: {result.universe}")
    print(f"Ineligible: {list(result.ineligible.keys())}")

    if result.universe_size == 0:
        print("ERROR: no symbol eligible. Aborting.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
