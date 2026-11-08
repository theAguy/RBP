"""Import-safe CLI shim that freezes numerical thread variables before PyTorch loads."""

from __future__ import annotations

import os


for _name in (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_name] = "4"


def main(argv: list[str] | None = None) -> int:
    # Importing rbpbench.rescnn loads PyTorch, so this import must remain here.
    from rbpbench.rescnn.runner_004a2 import main as runner_main

    return runner_main(argv)
