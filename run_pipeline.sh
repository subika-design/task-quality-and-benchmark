#!/usr/bin/env bash
# Orchestrate SWE-bench-modified (Docker + grading) and SWE-agent (trials + preds.json).
#
# Usage:
#   bash setup.sh                          # one-time bootstrap
#   # edit pipeline.env (DATASET) and SWE-agent/.env (API keys)
#   bash run_pipeline.sh prepare
#   bash run_pipeline.sh gold
#   bash run_pipeline.sh agent
#   bash run_pipeline.sh eval
#   bash run_pipeline.sh all
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${PIPELINE_ENV:-$SCRIPT_DIR/pipeline.env}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
else
  echo "Config not found: $ENV_FILE" >&2
  echo "Run: bash setup.sh" >&2
  exit 1
fi

ROOT="${ROOT:-$SCRIPT_DIR}"
BENCH="${BENCH:-$ROOT/SWE-bench-modified}"
AGENT="${AGENT:-$ROOT/SWE-agent}"
if [[ ! -d "$BENCH" ]]; then
  BENCH="$ROOT/SWE-bench-modified"
fi
if [[ ! -d "$AGENT" ]]; then
  AGENT="$ROOT/SWE-agent"
fi
DATASET="${DATASET:?Set DATASET in pipeline.env}"
RUN_PREFIX="${RUN_PREFIX:-$(basename "${DATASET%.jsonl}")}"
SWEAGENT_DATASET="${SWEAGENT_DATASET:-${DATASET%.jsonl}_sweagent.jsonl}"
ARCH="${ARCH:-x86_64}"
MAX_WORKERS_BENCH="${MAX_WORKERS_BENCH:-4}"
MAX_WORKERS_AGENT="${MAX_WORKERS_AGENT:-8}"
MIN_GOLD_RESOLVE_RATE="${MIN_GOLD_RESOLVE_RATE:-0.95}"
REDO_EXISTING="${REDO_EXISTING:-false}"
AGENT_CONFIG_DEFAULT="${AGENT_CONFIG_DEFAULT:-config/default.yaml}"
AGENT_CONFIG_MODEL="${AGENT_CONFIG_MODEL:-config/opus47.yaml}"
VENV="${VENV:-$ROOT/.venv}"
if [[ "$VENV" != /* ]]; then
  VENV="$ROOT/$VENV"
fi
TRIALS="${TRIALS:-1 2 3 4 5}"

# Read TRIALS into array (space-separated in env)
read -r -a TRIAL_ARRAY <<< "$TRIALS"

log() { echo "[pipeline] $*"; }
fail() { log "ERROR: $*"; exit 1; }

activate_venv() {
  if [[ -f "${VENV}/bin/activate" ]]; then
    # shellcheck source=/dev/null
    source "${VENV}/bin/activate"
    PYTHON="${VENV}/bin/python"
  elif [[ -n "${AGENT_VENV:-}" && -f "$AGENT_VENV" ]]; then
    # Legacy: per-agent venv from older pipeline.env
    # shellcheck source=/dev/null
    source "$AGENT_VENV"
    PYTHON="$(command -v python)"
  else
    PYTHON="${PYTHON:-${PYTHON_BENCH:-${PYTHON_AGENT:-python}}}"
  fi
  PYTHON_BENCH="$PYTHON"
  PYTHON_AGENT="$PYTHON"
}

check_venv() {
  if [[ ! -x "$PYTHON" ]]; then
    fail "Python not found at $PYTHON. Run: bash setup.sh"
  fi
}

check_import() {
  local module="$1"
  if ! "$PYTHON" -c "import ${module}" &>/dev/null; then
    fail "Python module '${module}' not importable. Run: bash setup.sh"
  fi
}

check_docker() {
  if ! command -v docker &>/dev/null; then
    fail "docker not found in PATH. Install Docker before running this step."
  fi
  if ! docker info &>/dev/null 2>&1; then
    fail "docker is not running. Start the Docker daemon and retry."
  fi
}

check_dataset() {
  if [[ ! -f "$DATASET" ]]; then
    fail "DATASET not found: $DATASET (set DATASET in pipeline.env)"
  fi
  if [[ "$DATASET" == *"/path/to/"* ]]; then
    fail "DATASET is still the placeholder path. Edit pipeline.env and set DATASET."
  fi
}

check_api_keys() {
  local env_file="$AGENT/.env"
  if [[ ! -f "$env_file" ]]; then
    fail "Missing $env_file. Run: bash setup.sh, then add API keys."
  fi
  local anthropic_key
  anthropic_key="$(grep -E '^ANTHROPIC_API_KEY=' "$env_file" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)"
  if [[ -z "$anthropic_key" ]]; then
    fail "ANTHROPIC_API_KEY not set in $env_file"
  fi
}

preflight() {
  local cmd="$1"
  activate_venv
  check_venv

  case "$cmd" in
    prepare|gold|eval)
      check_import swebench
      check_docker
      check_dataset
      ;;
    convert)
      check_import sweagent
      check_dataset
      ;;
    agent)
      check_import sweagent
      check_docker
      check_dataset
      check_api_keys
      ;;
    all)
      check_import swebench
      check_import sweagent
      check_docker
      check_dataset
      check_api_keys
      ;;
    *)
      return 0
      ;;
  esac
}

# SWE-bench optional_str accepts "none" for no Docker Hub namespace (local builds).
bench_namespace() {
  local ns="${NAMESPACE:-none}"
  if [[ -z "$ns" ]]; then
    ns="none"
  fi
  echo "$ns"
}

find_gold_report() {
  local run_id="${RUN_PREFIX}_gold"
  local report
  report="$(find "$BENCH" -maxdepth 1 -name "gold.${run_id}.json" -print -quit 2>/dev/null || true)"
  if [[ -n "$report" ]]; then
    echo "$report"
    return 0
  fi
  report="$(find "$BENCH" -maxdepth 1 -name "*.${run_id}.json" -print -quit 2>/dev/null || true)"
  [[ -n "$report" ]] && echo "$report"
}

check_gold_gate() {
  local report
  report="$(find_gold_report)"
  if [[ -z "$report" ]]; then
    log "WARNING: Gold report not found; skipping resolve-rate gate."
    return 0
  fi
  log "Gold report: $report"
  "$PYTHON_BENCH" - "$report" "$MIN_GOLD_RESOLVE_RATE" <<'PY'
import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1])
min_rate = float(sys.argv[2])
data = json.loads(report_path.read_text())
total = data.get("total_instances") or 0
resolved = data.get("resolved_instances") or 0
if total == 0:
    print("Gold gate: no instances in report", file=sys.stderr)
    sys.exit(1)
rate = resolved / total
print(f"Gold resolve rate: {resolved}/{total} = {rate:.1%}")
if min_rate <= 0:
    sys.exit(0)
if rate < min_rate:
    print(
        f"Gold gate FAILED: {rate:.1%} < required {min_rate:.1%}. "
        "Fix install_config/parsers/test labels before running the agent.",
        file=sys.stderr,
    )
    sys.exit(1)
print("Gold gate passed.")
PY
}

find_trial_preds() {
  local trial="$1"
  find "$AGENT/trajectories" -path "*_trial_${trial}/preds.json" -print -quit 2>/dev/null || true
}

step_prepare_images() {
  log "Step 1: prepare_images"
  cd "$BENCH"
  "$PYTHON_BENCH" -m swebench.harness.prepare_images \
    --dataset_name "$DATASET" \
    --max_workers "$MAX_WORKERS_BENCH" \
    --arch "$ARCH" \
    --namespace "$(bench_namespace)" \
    --env_image_tag latest \
    --tag latest
}

step_gold_eval() {
  log "Step 2: gold patch evaluation"
  cd "$BENCH"
  "$PYTHON_BENCH" -m swebench.harness.run_evaluation \
    --dataset_name "$DATASET" \
    --max_workers "$MAX_WORKERS_BENCH" \
    --arch "$ARCH" \
    --namespace "$(bench_namespace)" \
    --env_image_tag latest \
    --instance_image_tag latest \
    --predictions_path gold \
    --run_id "${RUN_PREFIX}_gold"
  check_gold_gate
}

step_convert_tasks() {
  log "Converting tasks for SWE-agent"
  cd "$AGENT"
  "$PYTHON_AGENT" convert_tasks.py "$DATASET" -o "$SWEAGENT_DATASET" --arch "$ARCH"
}

step_agent_trials() {
  log "Step 3: agent trials"
  step_convert_tasks
  cd "$AGENT"
  local redo_flag=()
  if [[ "${REDO_EXISTING,,}" == "true" ]]; then
    redo_flag=(--redo_existing)
  else
    redo_flag=(--redo_existing false)
  fi
  for t in "${TRIAL_ARRAY[@]}"; do
    log "Trial $t"
    sweagent run-batch \
      --config "$AGENT_CONFIG_DEFAULT" \
      --config "$AGENT_CONFIG_MODEL" \
      --instances.type file \
      --instances.path "$SWEAGENT_DATASET" \
      --instances.deployment.platform "linux/amd64" \
      --suffix "_trial_${t}" \
      "${redo_flag[@]}" \
      --num_workers "$MAX_WORKERS_AGENT"
  done
}

step_pred_eval() {
  log "Step 4: prediction evaluation per trial"
  cd "$BENCH"
  for t in "${TRIAL_ARRAY[@]}"; do
    local preds
    preds="$(find_trial_preds "$t")"
    if [[ -z "$preds" ]]; then
      log "Skipping trial $t: no preds.json found under $AGENT/trajectories"
      continue
    fi
    log "Evaluating trial $t: $preds"
    "$PYTHON_BENCH" -m swebench.harness.run_evaluation \
      --dataset_name "$DATASET" \
      --max_workers "$MAX_WORKERS_BENCH" \
      --arch "$ARCH" \
      --namespace "$(bench_namespace)" \
      --env_image_tag latest \
      --instance_image_tag latest \
      --predictions_path "$preds" \
      --run_id "${RUN_PREFIX}_trial_${t}"
  done
}

usage() {
  cat <<EOF
Usage: $(basename "$0") <command>

Commands:
  prepare   Build Docker instance images (SWE-bench-modified)
  gold      Run gold-patch sanity check + optional resolve-rate gate
  convert   Convert task JSONL to SWE-agent format only
  agent     Convert + run agent trials
  eval      Evaluate preds.json for each trial
  all       prepare → gold → agent → eval

First-time setup: bash setup.sh
Config: $ENV_FILE (override with PIPELINE_ENV=/path/to/env)
EOF
}

main() {
  local cmd="${1:-all}"
  case "$cmd" in
    -h|--help|help)
      usage
      exit 0
      ;;
    prepare|gold|convert|agent|eval|all)
      preflight "$cmd"
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac

  case "$cmd" in
    prepare) step_prepare_images ;;
    gold) step_gold_eval ;;
    convert) step_convert_tasks ;;
    agent) step_agent_trials ;;
    eval) step_pred_eval ;;
    all)
      step_prepare_images
      step_gold_eval
      step_agent_trials
      step_pred_eval
      ;;
  esac
  log "Done: $cmd"
}

main "$@"
