# Task quality and benchmark pipeline

End-to-end workflow split across two repos:

| Step | Command | Repo |
|------|---------|------|
| 1. Prepare images | `bash run_pipeline.sh prepare` | SWE-bench-modified |
| 2. Gold patch eval | `bash run_pipeline.sh gold` | SWE-bench-modified |
| 3. Agent trials | `bash run_pipeline.sh agent` | SWE-agent |
| 4. Prediction eval | `bash run_pipeline.sh eval` | SWE-bench-modified |

Or run everything: `bash run_pipeline.sh all`

## Quick start

```bash
# 1. One-time bootstrap (venv + both packages + config templates)
bash setup.sh

# 2. Edit two files:
#    pipeline.env     → set DATASET to your task JSONL
#    SWE-agent/.env   → set ANTHROPIC_API_KEY (and GITHUB_TOKEN if needed)

# 3. Run
bash run_pipeline.sh all
```

Equivalent via Make: `make setup` then `make all`.

Prerequisites: **Python 3.11+**, **Docker** (running), and API keys for the agent model.

## Usage

```bash
bash run_pipeline.sh prepare   # Docker images for each task
bash run_pipeline.sh gold      # Sanity check with gold patches (gate)
bash run_pipeline.sh agent     # Convert JSONL + run trials → preds.json
bash run_pipeline.sh eval      # Grade each trial's preds.json
```

Resume a failed run by re-running individual stages. For agent trials, set `REDO_EXISTING=true` in `pipeline.env` to skip instances that already have trajectories.

Preflight checks run before each step (venv, Python imports, Docker, dataset path, API keys for agent).

## Outputs

- **Images:** built locally as `sweb.eval.x86_64.<instance_id>:latest`
- **Gold report:** `SWE-bench-modified/gold.<RUN_PREFIX>_gold.json`
- **Trajectories:** `SWE-agent/trajectories/<user>/..._trial_<N>/`
- **Predictions:** `..._trial_<N>/preds.json`
- **Eval reports:** `SWE-bench-modified/<model>.<RUN_PREFIX>_trial_<N>.json`

## Config

| File | Purpose |
|------|---------|
| `pipeline.env` | Run parameters: `DATASET`, trials, workers, gold gate |
| `SWE-agent/.env` | API keys (`ANTHROPIC_API_KEY`, `GITHUB_TOKEN`) |

Both are created by `setup.sh` from their `.example` templates. `ROOT` and `RUN_PREFIX` default automatically; you typically only need to set `DATASET`.

Key `pipeline.env` variables:

- `DATASET` — raw task JSONL from taskgen
- `TRIALS` — space-separated trial numbers (e.g. `1 2 3 4 5`)
- `MIN_GOLD_RESOLVE_RATE` — abort before agent if gold resolve rate is too low (default `0.95`, set `0` to disable)
- `NAMESPACE` — use `none` for local Docker images (do not leave empty; bash drops `--namespace ""`)
- `VENV` — shared virtualenv path (default `.venv`, created by `setup.sh`)
