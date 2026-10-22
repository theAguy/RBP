#!/usr/bin/env bash
set -Eeuo pipefail

# Run once on Newton's login node.  This installs software only; it does not
# open a FASTA and does not launch the R2 probe.

ENV_PREFIX=${RBP_NEWTON_ENV_PREFIX:-"$HOME/.conda/envs/rbpbench-r2-newton"}
BOOTSTRAP_PREFIX=${RBP_NEWTON_CONDA_PREFIX:-"$HOME/.local/rbpbench-miniconda-py311-26.9.3"}
MINICONDA_NAME=Miniconda3-py311_26.9.3-0-Linux-x86_64.sh
MINICONDA_URL="https://repo.anaconda.com/miniconda/$MINICONDA_NAME"
MINICONDA_SHA256=a61d43a0f98c8fddc74a136911605234875e2334af73ec12f7368c469cc0ecd2

find_conda() {
  if command -v conda >/dev/null 2>&1; then
    return 0
  fi
  if command -v module >/dev/null 2>&1; then
    for candidate in miniconda3 miniconda anaconda3; do
      if module load "$candidate" >/dev/null 2>&1 && command -v conda >/dev/null 2>&1; then
        return 0
      fi
    done
  fi
  return 1
}

if ! find_conda; then
  if [[ -x "$BOOTSTRAP_PREFIX/bin/conda" ]]; then
    export PATH="$BOOTSTRAP_PREFIX/bin:$PATH"
  else
    [[ ! -e "$BOOTSTRAP_PREFIX" ]] || {
      printf 'Refusing unknown/incomplete Miniconda prefix: %s\n' "$BOOTSTRAP_PREFIX" >&2
      exit 1
    }
    INSTALLER=$(mktemp "${TMPDIR:-/tmp}/rbp-miniconda.XXXXXX.sh")
    trap 'rm -f "$INSTALLER"' EXIT
    if command -v curl >/dev/null 2>&1; then
      curl --fail --location --proto '=https' --tlsv1.2 --output "$INSTALLER" "$MINICONDA_URL"
    elif command -v wget >/dev/null 2>&1; then
      wget --https-only --output-document="$INSTALLER" "$MINICONDA_URL"
    else
      printf 'Neither curl nor wget is available to bootstrap Miniconda.\n' >&2
      exit 1
    fi
    printf '%s  %s\n' "$MINICONDA_SHA256" "$INSTALLER" | sha256sum --check --status
    bash "$INSTALLER" -b -p "$BOOTSTRAP_PREFIX"
    export PATH="$BOOTSTRAP_PREFIX/bin:$PATH"
  fi
fi

eval "$(conda shell.bash hook)"

if [[ -e "$ENV_PREFIX" ]]; then
  printf 'Refusing to modify an existing environment: %s\n' "$ENV_PREFIX" >&2
  printf 'Set RBP_NEWTON_ENV_PREFIX to a new empty path if a rebuild is needed.\n' >&2
  exit 1
fi

conda create --yes --strict-channel-priority --override-channels --prefix "$ENV_PREFIX" \
  --channel conda-forge --channel bioconda \
  python=3.11 'mmseqs2=18.8cc5c=hd6d6fdc_0'

"$ENV_PREFIX/bin/mmseqs" version | grep -Fx '18.8cc5c' >/dev/null
"$ENV_PREFIX/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 11)'

conda list --prefix "$ENV_PREFIX" --explicit > "$ENV_PREFIX/rbpbench-r2-newton.explicit.txt"
conda list --prefix "$ENV_PREFIX" --json > "$ENV_PREFIX/rbpbench-r2-newton.packages.json"

"$ENV_PREFIX/bin/python" "$(dirname "$0")/write_runtime_receipt.py" \
  --environment-prefix "$ENV_PREFIX"

printf '\nEnvironment ready. Receipt:\n  %s\n' \
  "$ENV_PREFIX/newton_runtime_receipt.json"
printf 'Next: run 02_SUBMIT_R2_PROBE.sh from the extracted bundle.\n'
