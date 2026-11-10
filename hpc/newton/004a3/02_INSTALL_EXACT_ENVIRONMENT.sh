#!/usr/bin/env bash
set -Eeuo pipefail

printf '%s\n' \
  'Direct environment installation is disabled.' \
  'Use 02_SUBMIT_ENVIRONMENT.sh after the reviewed 004A-3C-2 authorization.' >&2
exit 1
