#!/usr/bin/env bash
# Bootstrap the pipeline: one venv, both packages, config templates.
#
# Usage:
#   bash setup.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR"
BENCH="$ROOT/SWE-bench-modified"
AGENT="$ROOT/SWE-agent"
VENV="$ROOT/.venv"

log() { echo "[setup] $*"; }
fail() { echo "[setup] ERROR: $*" >&2; exit 1; }

find_python() {
  local cmd version major minor
  for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
      version="$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
      major="${version%%.*}"
      minor="${version#*.}"
      if (( major > 3 || (major == 3 && minor >= 11) )); then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_CMD="$(find_python || true)"
if [[ -z "$PYTHON_CMD" ]]; then
  fail "Python 3.11+ is required. Install python3.11 or newer and re-run setup.sh"
fi
log "Using $PYTHON_CMD ($("$PYTHON_CMD" --version))"

if ! command -v docker &>/dev/null; then
  log "WARNING: docker not found in PATH. Install Docker before running prepare/gold/agent/eval."
elif ! docker info &>/dev/null 2>&1; then
  log "WARNING: docker is installed but not running. Start Docker before running the pipeline."
fi

if [[ ! -d "$VENV" ]]; then
  log "Creating virtualenv at $VENV"
  "$PYTHON_CMD" -m venv "$VENV"
else
  log "Virtualenv already exists at $VENV"
fi

# shellcheck source=/dev/null
source "$VENV/bin/activate"
pip install -q --upgrade pip

log "Installing SWE-bench-modified"
pip install -q -e "$BENCH"

log "Installing SWE-agent"
pip install -q -e "$AGENT"

if [[ ! -f "$ROOT/pipeline.env" ]]; then
  cp "$ROOT/pipeline.env.example" "$ROOT/pipeline.env"
  log "Created pipeline.env from pipeline.env.example"
else
  log "Keeping existing pipeline.env"
fi

if [[ ! -f "$AGENT/.env" ]]; then
  cp "$AGENT/.env.example" "$AGENT/.env"
  log "Created SWE-agent/.env from .env.example — add your API keys there"
else
  log "Keeping existing SWE-agent/.env"
fi

log ""
log "Setup complete."
log "Next steps:"
log "  1. Edit pipeline.env — set DATASET to your task JSONL"
log "  2. Edit SWE-agent/.env — set ANTHROPIC_API_KEY (and GITHUB_TOKEN if needed)"
log "  3. bash run_pipeline.sh all"
