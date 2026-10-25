#!/usr/bin/env bash
set -Eeuo pipefail

: "${RBP_SMOKE_ROOT:?RBP_SMOKE_ROOT missing}"
: "${RBP_ENV_PREFIX:?RBP_ENV_PREFIX missing}"
ROOT=$(cd "$RBP_SMOKE_ROOT" && pwd -P)
PY="$RBP_ENV_PREFIX/bin/python"
MMSEQS="$RBP_ENV_PREFIX/bin/mmseqs"
RUNTIME="$ROOT/runtime"
mkdir "$RUNTIME"
MESSAGE="smoke job stopped before acceptance"

finish() {
  local rc=$?
  trap - EXIT
  set +e
  "$PY" "$ROOT/hpc/darwin/002c_r3r5_smoke/package_smoke_return.py" \
    --root "$ROOT" --exit-code "$rc" --message "$MESSAGE" >"$RUNTIME/return_paths.txt" 2>"$RUNTIME/return_packaging.stderr"
  local package_rc=$?
  if (( package_rc != 0 )); then
    printf 'Return packaging failed:\n' >&2
    cat "$RUNTIME/return_packaging.stderr" >&2
    exit 90
  fi
  cat "$RUNTIME/return_paths.txt"
  exit "$rc"
}
trap finish EXIT

{
  printf '{"slurm_job_id":"%s","host":"%s","cpus":"%s","memory_per_node":"%s","source_commit":"%s"}\n' \
    "${SLURM_JOB_ID:-}" "$(hostname)" "${SLURM_CPUS_PER_TASK:-}" "${SLURM_MEM_PER_NODE:-}" "$(tr -d '\n' < "$ROOT/SOURCE_COMMIT.txt")"
} > "$RUNTIME/job_metadata.json"

"$PY" "$ROOT/hpc/darwin/002c_r3r5_smoke/verify_smoke_package.py" package "$ROOT" > "$RUNTIME/package_verification.log"
export PYTHONPATH="$ROOT/src" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
"$PY" -m rbpbench.splits.r3r5.darwin verify-environment \
  --bundle-root "$ROOT" --runtime-receipt "$RBP_ENV_PREFIX/newton_runtime_receipt.json" \
  > "$RUNTIME/environment_verification.log"

WORK="$RUNTIME/repo"
mkdir "$WORK"
cp -R "$ROOT/src" "$ROOT/tests" "$ROOT/configs" "$ROOT/hpc" "$ROOT/pyproject.toml" "$WORK/"
git -C "$WORK" init -q
git -C "$WORK" add src tests configs hpc pyproject.toml
git -C "$WORK" -c user.name='RBP smoke fixture' -c user.email='noreply@example.invalid' commit -q -m 'Synthetic smoke checkout'

cd "$WORK"
export PYTHONPATH="$WORK/src" RBP_R3R5_MMSEQS_BIN="$MMSEQS" OMP_NUM_THREADS=4
set +e
/usr/bin/time -v -o "$RUNTIME/resource.txt" \
  "$PY" -m unittest tests.test_splits_r3r5_real_binary -v \
  > "$RUNTIME/test_stdout.log" 2> "$RUNTIME/test_stderr.log"
TEST_RC=$?
set -e
cat "$RUNTIME/test_stdout.log" "$RUNTIME/test_stderr.log" > "$RUNTIME/result_check.log"
(( TEST_RC == 0 )) || { MESSAGE="real-binary smoke test process exited $TEST_RC"; exit "$TEST_RC"; }
grep -Eq '^Ran 2 tests in ' "$RUNTIME/result_check.log" || { MESSAGE="test output did not report exactly two tests"; exit 41; }
grep -Eq '^OK$' "$RUNTIME/result_check.log" || { MESSAGE="test output did not end in an unqualified OK"; exit 42; }
if grep -Eqi 'skipped=|skip[ped]*' "$RUNTIME/result_check.log"; then
  MESSAGE="one or more real-binary tests were skipped"
  exit 43
fi
MESSAGE="exactly two synthetic real-MMseqs2 tests passed; none skipped"
exit 0
