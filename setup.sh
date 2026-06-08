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

log "Installing task-analyze (trial classification)"
pip install -q -e "$ROOT/task_analyze"

if [[ ! -f "$ROOT/pipeline.env" ]]; then
  cp "$ROOT/pipeline.env.example" "$ROOT/pipeline.env"
  log "Created pipeline.env from pipeline.env.example"
else
  log "Keeping existing pipeline.env"
fi

# One-time migration: copy API keys from legacy SWE-agent/.env into pipeline.env
LEGACY_ENV="$AGENT/.env"
PIPELINE_ENV="$ROOT/pipeline.env"
if [[ -f "$LEGACY_ENV" && -f "$PIPELINE_ENV" ]]; then
  if "$PYTHON_CMD" - "$LEGACY_ENV" "$PIPELINE_ENV" <<'PY'
import sys
from pathlib import Path

legacy_path = Path(sys.argv[1])
pipeline_path = Path(sys.argv[2])
keys = ("GITHUB_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


legacy = parse_env(legacy_path)
lines = pipeline_path.read_text().splitlines()
changed = False

for key in keys:
    legacy_val = legacy.get(key, "")
    if not legacy_val:
        continue
    replaced = False
    for idx, line in enumerate(lines):
        if not line.startswith(f"{key}="):
            continue
        replaced = True
        current = line.split("=", 1)[1].strip().strip('"').strip("'")
        if not current:
            lines[idx] = f'{key}="{legacy_val}"'
            changed = True
        break
    if not replaced:
        lines.append(f'{key}="{legacy_val}"')
        changed = True

if changed:
    pipeline_path.write_text("\n".join(lines) + "\n")
    print("migrated")
PY
  then
    log "Migrated API keys from SWE-agent/.env into pipeline.env"
    log "You can remove $LEGACY_ENV after verifying pipeline.env"
  fi
fi

log ""
log "Setup complete."
log "Next steps:"
log "  1. Edit pipeline.env — set DATASET and API keys (GITHUB_TOKEN, ANTHROPIC_API_KEY, OPENAI_API_KEY)"
log "  2. bash run_pipeline.sh all"
