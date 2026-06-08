from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TrialArtifacts:
    """Paths to artifacts for one instance in one trial."""

    instance_id: str
    trial: int
    run_id: str
    traj_path: Path | None
    eval_dir: Path | None
    report_path: Path | None
    test_output_path: Path | None
    model_patch: str | None
    resolved: bool | None
    report_data: dict | None


def load_dataset(dataset_path: Path) -> dict[str, dict]:
    """Load SWE-bench JSONL dataset keyed by instance_id."""
    instances: dict[str, dict] = {}
    with dataset_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            instance_id = row["instance_id"]
            instances[instance_id] = row
    return instances


def find_trial_trajectory_dir(
    trajectories_root: Path,
    trial: int,
) -> Path | None:
    """Find the SWE-agent trial directory for a given trial number."""
    pattern = f"*_trial_{trial}"
    matches = sorted(trajectories_root.rglob(pattern))
    matches = [p for p in matches if p.is_dir()]
    return matches[0] if matches else None


def find_instance_traj(trial_dir: Path, instance_id: str) -> Path | None:
    """Find .traj file for an instance within a trial directory."""
    instance_dir = trial_dir / instance_id
    if not instance_dir.is_dir():
        return None
    candidates = sorted(instance_dir.glob(f"{instance_id}.traj"))
    return candidates[0] if candidates else None


def load_preds_patch(trial_dir: Path, instance_id: str) -> str | None:
    """Load agent patch from trial-level preds.json."""
    preds_path = trial_dir / "preds.json"
    if not preds_path.exists():
        return None
    try:
        preds = json.loads(preds_path.read_text())
        entry = preds.get(instance_id, {})
        return entry.get("model_patch")
    except Exception:
        return None


def find_eval_dir(
    bench_root: Path,
    run_id: str,
    model_name: str,
    instance_id: str,
) -> Path | None:
    """Find evaluation log directory for an instance."""
    eval_root = bench_root / "logs" / "run_evaluation" / run_id
    if not eval_root.is_dir():
        return None

    model_dir = eval_root / model_name
    if model_dir.is_dir():
        candidate = model_dir / instance_id
        if candidate.is_dir():
            return candidate

    # Fallback: search any model subdirectory
    for model_subdir in eval_root.iterdir():
        if not model_subdir.is_dir():
            continue
        candidate = model_subdir / instance_id
        if candidate.is_dir():
            return candidate
    return None


def load_report(eval_dir: Path, instance_id: str) -> tuple[dict | None, bool | None]:
    """Load report.json and extract resolved flag."""
    report_path = eval_dir / "report.json"
    if not report_path.exists():
        return None, None
    try:
        data = json.loads(report_path.read_text())
        entry = data.get(instance_id, {})
        return entry, entry.get("resolved")
    except Exception:
        return None, None


def discover_trial_artifacts(
    *,
    instance_id: str,
    trial: int,
    run_prefix: str,
    trajectories_root: Path,
    bench_root: Path,
    model_name: str | None = None,
) -> TrialArtifacts | None:
    """Discover all artifacts for one instance × trial combination."""
    trial_dir = find_trial_trajectory_dir(trajectories_root, trial)
    if trial_dir is None:
        return None

    traj_path = find_instance_traj(trial_dir, instance_id)
    model_patch = load_preds_patch(trial_dir, instance_id)

    # Derive model name from preds if not provided
    if model_name is None:
        preds_path = trial_dir / "preds.json"
        if preds_path.exists():
            try:
                preds = json.loads(preds_path.read_text())
                model_name = preds.get(instance_id, {}).get("model_name_or_path")
            except Exception:
                model_name = None
    if model_name is None:
        model_name = trial_dir.name

    run_id = f"{run_prefix}_trial_{trial}"
    eval_dir = find_eval_dir(bench_root, run_id, model_name, instance_id)

    report_data = None
    resolved = None
    report_path = None
    test_output_path = None

    if eval_dir is not None:
        report_path = eval_dir / "report.json"
        test_output_path = eval_dir / "test_output.txt"
        report_data, resolved = load_report(eval_dir, instance_id)

    return TrialArtifacts(
        instance_id=instance_id,
        trial=trial,
        run_id=run_id,
        traj_path=traj_path,
        eval_dir=eval_dir,
        report_path=report_path if report_path and report_path.exists() else None,
        test_output_path=test_output_path if test_output_path and test_output_path.exists() else None,
        model_patch=model_patch,
        resolved=resolved,
        report_data=report_data,
    )


def discover_gold_baseline(
    bench_root: Path,
    gold_run_id: str,
    instance_id: str,
) -> tuple[bool | None, Path | None]:
    """Check gold eval report for an instance."""
    eval_root = bench_root / "logs" / "run_evaluation" / gold_run_id
    if not eval_root.is_dir():
        return None, None

    for model_subdir in eval_root.iterdir():
        if not model_subdir.is_dir():
            continue
        eval_dir = model_subdir / instance_id
        if not eval_dir.is_dir():
            continue
        _, resolved = load_report(eval_dir, instance_id)
        return resolved, eval_dir
    return None, None
