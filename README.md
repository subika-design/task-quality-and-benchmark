# Task quality and benchmark pipeline

End-to-end workflow split across two repos:

| Step | Command | Repo |
|------|---------|------|
| 1. Prepare images | `bash run_pipeline.sh prepare` | SWE-bench-modified |
| 2. Gold patch eval | `bash run_pipeline.sh gold` | SWE-bench-modified |
| 3. Agent trials | `bash run_pipeline.sh agent` | SWE-agent |
| 4. Prediction eval | `bash run_pipeline.sh eval` | SWE-bench-modified |
| 5. Trial classification | `bash run_pipeline.sh classify` | task-analyze |

Or run everything: `bash run_pipeline.sh all` (includes classify when `CLASSIFY_AFTER_EVAL=true`)

## Quick start

```bash
# 1. One-time bootstrap (venv + both packages + config templates)
bash setup.sh

# 2. Edit pipeline.env — set DATASET and API keys

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
bash run_pipeline.sh classify  # LLM trial classification + per-instance verdict
```

Resume a failed run by re-running individual stages. For agent trials, set `REDO_EXISTING=true` in `pipeline.env` to skip instances that already have trajectories.

Preflight checks run before each step (venv, Python imports, Docker, dataset path, API keys for agent).

## Outputs

- **Images:** built locally as `sweb.eval.x86_64.<instance_id>:latest`
- **Gold report:** `SWE-bench-modified/gold.<RUN_PREFIX>_gold.json`
- **Trajectories:** `SWE-agent/trajectories/<user>/..._trial_<N>/`
- **Predictions:** `..._trial_<N>/preds.json`
- **Eval reports:** `SWE-bench-modified/<model>.<RUN_PREFIX>_trial_<N>.json`
- **Classification report:** `.task_analyze/results/<RUN_PREFIX>.classification.json`

## Trial classification (task-analyze)

After agent trials and eval, `classify` runs LLM analysis (ported from SWE-gen) to label each trial outcome and synthesize a per-instance verdict:

| Label | Meaning |
|-------|---------|
| `GOOD_SUCCESS` | Agent solved legitimately |
| `BAD_SUCCESS` | Agent cheated or tests too weak |
| `GOOD_FAILURE` | Agent failed; instance is fine |
| `BAD_FAILURE` | Instance has spec/test issues |
| `HARNESS_ERROR` | Infrastructure or eval failure |

**Inputs per trial × instance:** `problem_statement` from JSONL, `report.json` + `test_output.txt` from eval logs, `.traj` from SWE-agent, verified `resolved` flag.

**API keys** (in `pipeline.env`): `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` (classification) + `OPENAI_API_KEY` (verdict synthesis).

```bash
task-classify \
  --dataset SWE-agent/tasks/my_tasks.jsonl \
  --run-prefix my_tasks \
  --trials "1 2 3"
```

## Config

All configuration lives in **`pipeline.env`** (paths, run settings, and API keys). Created by `setup.sh` from `pipeline.env.example`. Do not commit `pipeline.env` once it contains secrets.

Key variables:

- `DATASET` — raw task JSONL from taskgen
- `TRIALS` — space-separated trial numbers (e.g. `1 2 3 4 5`)
- `MIN_GOLD_RESOLVE_RATE` — abort before agent if gold resolve rate is too low (default `0.95`, set `0` to disable)
- `NAMESPACE` — use `none` for local Docker images (do not leave empty; bash drops `--namespace ""`)
- `VENV` — shared virtualenv path (default `.venv`, created by `setup.sh`)
- `CLASSIFY_AFTER_EVAL` — run trial classification after eval in `all` (default `true`)
- `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` — API keys for agent and classify steps

If you previously used `SWE-agent/.env`, `setup.sh` migrates keys into `pipeline.env` automatically.
