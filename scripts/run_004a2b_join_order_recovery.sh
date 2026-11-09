#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

ACCEPTED_JOIN_CORRECTION="554e9c0"
ENV_PREFIX="/opt/miniconda3/envs/rbpbench-rescnn-004a2"
OUTPUT_ROOT="$ROOT/artifacts/task004a_rescnn_pilot/004a2_local_smoke_join_recovery"
LOG_ROOT="$ROOT/artifacts/task004a_rescnn_pilot/004a2b_join_recovery_logs"

fail() {
  echo "STOP BEFORE JOIN-ORDER RECOVERY: $*" >&2
  exit 2
}

git merge-base --is-ancestor "$ACCEPTED_JOIN_CORRECTION" HEAD \
  || fail "accepted correction $ACCEPTED_JOIN_CORRECTION is not an ancestor of HEAD"
[[ -z "$(git status --porcelain --untracked-files=all)" ]] \
  || fail "worktree is not clean"
[[ ! -e "$OUTPUT_ROOT" ]] || fail "join-recovery output root already exists"
[[ ! -e "$LOG_ROOT" ]] || fail "join-recovery log root already exists"

prior_paths=(
  "$ROOT/artifacts/task004a_rescnn_pilot/004a2b_execution_logs/attempt.txt"
  "$ROOT/artifacts/task004a_rescnn_pilot/004a2b_execution_logs/stderr_time.log"
  "$ROOT/artifacts/task004a_rescnn_pilot/004a2b_execution_logs/stdout.log"
  "$ROOT/artifacts/task004a_rescnn_pilot/004a2b_recovery_logs/attempt.txt"
  "$ROOT/artifacts/task004a_rescnn_pilot/004a2b_recovery_logs/stderr_time.log"
  "$ROOT/artifacts/task004a_rescnn_pilot/004a2b_recovery_logs/stdout.log"
  "$ROOT/artifacts/task004a_rescnn_pilot/004a2b_final_execution_logs/attempt.txt"
  "$ROOT/artifacts/task004a_rescnn_pilot/004a2b_final_execution_logs/stderr_time.log"
  "$ROOT/artifacts/task004a_rescnn_pilot/004a2b_final_execution_logs/stdout.log"
  "$ROOT/artifacts/task004a_rescnn_pilot/004a2_local_smoke/STOPPED.json"
)
prior_digests=(
  "239e3e5da9c1c1e921a25b509f8abc8e90fad430e4f782a15f5291a3f0f48b75"
  "d961658c4a705fda988a59f7f03d0403b1d07f55d95073d9818db25e0387a0a4"
  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  "dcbc0730d62a369771297c79fa5bf9956dcd3f13a60369f1ea4778114800cf5f"
  "ce641b0c630cb7ee05b8a97b8bd82a80eb8f8f10e9a2ecf791f1b1c29d508494"
  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  "f3becc0cebf47eb0eba26259a3a1dae10e2a44b0785ea60433ea3652295f2697"
  "f916e23735a01628768a7dc15938587a59fc3ae644fe236758145bc5f9bebdd3"
  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  "4b41db852867bd67558792c5b386be499504db894c58a1ba78c87340a6bf4909"
)
for index in 0 1 2 3 4 5 6 7 8 9; do
  path="${prior_paths[$index]}"
  expected="${prior_digests[$index]}"
  [[ -f "$path" && ! -L "$path" ]] || fail "prior evidence is missing: $path"
  actual="$(shasum -a 256 "$path" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || fail "prior evidence drifted: $path"
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
  'Task 004A-2B authorized join-order recovery' \
  "start_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "head=$(git rev-parse HEAD)" \
  "accepted_join_correction=$ACCEPTED_JOIN_CORRECTION" \
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
  echo "Task 004A-2B join-order recovery stopped with exit status $status. Do not retry." >&2
  echo "Preserve $LOG_ROOT and $OUTPUT_ROOT (if created)." >&2
  exit "$status"
fi

SELECTION="$OUTPUT_ROOT/selected/local_data_contract_smoke.json"
[[ -f "$SELECTION" && ! -L "$SELECTION" ]] \
  || fail "runner exited successfully without an accepted selection record"
[[ ! -e "$OUTPUT_ROOT/STOPPED.json" ]] \
  || fail "runner exited successfully but a stop record exists"

echo "Task 004A-2B join-order recovery completed once. Do not rerun or start Task 004A-3."
echo "Return for independent reconciliation: $LOG_ROOT and $OUTPUT_ROOT"
