#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

ACCEPTED_PREREQUISITE_CORRECTION="15ef4f0"
ENV_PREFIX="/opt/miniconda3/envs/rbpbench-rescnn-004a2"
OUTPUT_ROOT="$ROOT/artifacts/task004a_rescnn_pilot/004a2_local_smoke"
FIRST_LOG_ROOT="$ROOT/artifacts/task004a_rescnn_pilot/004a2b_execution_logs"
SECOND_LOG_ROOT="$ROOT/artifacts/task004a_rescnn_pilot/004a2b_recovery_logs"
LOG_ROOT="$ROOT/artifacts/task004a_rescnn_pilot/004a2b_final_execution_logs"

fail() {
  echo "STOP BEFORE FINAL EXECUTION: $*" >&2
  exit 2
}

git merge-base --is-ancestor "$ACCEPTED_PREREQUISITE_CORRECTION" HEAD \
  || fail "accepted correction $ACCEPTED_PREREQUISITE_CORRECTION is not an ancestor of HEAD"
[[ -z "$(git status --porcelain --untracked-files=all)" ]] \
  || fail "worktree is not clean"
[[ ! -e "$OUTPUT_ROOT" ]] || fail "scientific output root already exists"
[[ ! -e "$LOG_ROOT" ]] || fail "final execution log root already exists"

evidence_paths=(
  "$FIRST_LOG_ROOT/attempt.txt"
  "$FIRST_LOG_ROOT/stderr_time.log"
  "$FIRST_LOG_ROOT/stdout.log"
  "$SECOND_LOG_ROOT/attempt.txt"
  "$SECOND_LOG_ROOT/stderr_time.log"
  "$SECOND_LOG_ROOT/stdout.log"
)
evidence_digests=(
  "239e3e5da9c1c1e921a25b509f8abc8e90fad430e4f782a15f5291a3f0f48b75"
  "d961658c4a705fda988a59f7f03d0403b1d07f55d95073d9818db25e0387a0a4"
  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  "dcbc0730d62a369771297c79fa5bf9956dcd3f13a60369f1ea4778114800cf5f"
  "ce641b0c630cb7ee05b8a97b8bd82a80eb8f8f10e9a2ecf791f1b1c29d508494"
  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
for index in 0 1 2 3 4 5; do
  path="${evidence_paths[$index]}"
  expected="${evidence_digests[$index]}"
  [[ -f "$path" && ! -L "$path" ]] || fail "prior stop evidence is missing: $path"
  actual="$(shasum -a 256 "$path" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] \
    || fail "prior stop evidence drifted: $path"
done

required_files=(
  "$ROOT/configs/models/task004a_v1.toml"
  "$ROOT/dataset_K562_multilabel_with_NEGs.csv"
  "$ROOT/manifests/dataset_audit.json"
  "$ROOT/configs/proteins.tsv"
  "$ROOT/manifests/sequence_decode_002b2.json"
  "$ROOT/manifests/sequence_partitions_002c_v2.json"
  "$ROOT/manifests/task003b_phase_a_003b3.json"
  "$ROOT/manifests/task004a2_local_environment.json"
  "$ROOT/artifacts/task003b_simple_baselines/inputs/membership.tsv.gz"
  "$ROOT/artifacts/splits/sequence_partitions_v1/decode/generations/decode_907eac7a0a69415a/sequence_partitions_width_500.fasta"
)
for path in "${required_files[@]}"; do
  [[ -f "$path" && ! -L "$path" ]] || fail "required plain file is missing: $path"
done

RUNNER="$ENV_PREFIX/bin/rbp-rescnn-smoke"
[[ -x "$RUNNER" && ! -L "$RUNNER" ]] || fail "accepted CLI is missing: $RUNNER"

mkdir "$LOG_ROOT"
printf '%s\n' \
  'Task 004A-2B final authorized execution attempt' \
  "start_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "head=$(git rev-parse HEAD)" \
  "accepted_prerequisite_correction=$ACCEPTED_PREREQUISITE_CORRECTION" \
  "runner=$RUNNER" \
  > "$LOG_ROOT/attempt.txt"

set +e
/usr/bin/time -l "$RUNNER" \
  --repo-root "$ROOT" \
  --config "$ROOT/configs/models/task004a_v1.toml" \
  --csv "$ROOT/dataset_K562_multilabel_with_NEGs.csv" \
  --dataset-audit "$ROOT/manifests/dataset_audit.json" \
  --proteins "$ROOT/configs/proteins.tsv" \
  --decode-manifest "$ROOT/manifests/sequence_decode_002b2.json" \
  --partition-manifest "$ROOT/manifests/sequence_partitions_002c_v2.json" \
  --phase-a-manifest "$ROOT/manifests/task003b_phase_a_003b3.json" \
  --membership "$ROOT/artifacts/task003b_simple_baselines/inputs/membership.tsv.gz" \
  --environment-manifest "$ROOT/manifests/task004a2_local_environment.json" \
  --output-dir "$OUTPUT_ROOT" \
  > "$LOG_ROOT/stdout.log" \
  2> "$LOG_ROOT/stderr_time.log"
status=$?
set -e

printf 'exit_status=%s\nend_utc=%s\n' \
  "$status" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  >> "$LOG_ROOT/attempt.txt"

if [[ "$status" -ne 0 ]]; then
  echo "Task 004A-2B final attempt stopped with exit status $status. Do not retry." >&2
  echo "Preserve $LOG_ROOT and $OUTPUT_ROOT (if created)." >&2
  exit "$status"
fi

SELECTION="$OUTPUT_ROOT/selected/local_data_contract_smoke.json"
[[ -f "$SELECTION" && ! -L "$SELECTION" ]] \
  || fail "runner exited successfully without an accepted selection record"
[[ ! -e "$OUTPUT_ROOT/STOPPED.json" ]] \
  || fail "runner exited successfully but a stop record exists"

echo "Task 004A-2B completed once. Do not rerun or start Task 004A-3."
echo "Return for independent reconciliation: $LOG_ROOT and $OUTPUT_ROOT"
