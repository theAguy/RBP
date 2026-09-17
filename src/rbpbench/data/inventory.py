"""Create a deterministic SHA-256 inventory of source artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from rbpbench.data.audit import sha256_file


def read_path_list(list_path: Path) -> list[Path]:
    paths = []
    for line in list_path.read_text().splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            paths.append(Path(value))
    return paths


def build_inventory(paths: Sequence[Path], root: Path) -> dict:
    files = []
    for relative_path in paths:
        path = root / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"missing source artifact: {relative_path}")
        files.append(
            {
                "path": relative_path.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {"schema_version": 1, "files": files}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", type=Path, required=True, help="Text file listing artifacts")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Artifact root directory")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON manifest")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = build_inventory(read_path_list(args.list), args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
