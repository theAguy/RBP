#!/usr/bin/env python3
"""Build the complete Task 004A-3 runtime manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from rbpbench.rescnn.environment_004a3 import write_runtime_manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    write_runtime_manifest(args.prefix, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
