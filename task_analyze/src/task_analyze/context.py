from __future__ import annotations

import json
import shutil
from pathlib import Path

from task_analyze.discovery import TrialArtifacts


def _truncate(text: str, max_len: int = 4000) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n... ({len(text)} chars total, truncated)"


def build_trajectory_summary(traj_path: Path, max_steps: int = 40) -> str:
    """Build a condensed trajectory summary from a SWE-agent .traj file."""
    data = json.loads(traj_path.read_text())
    trajectory = data.get("trajectory", [])
    info = data.get("info", {})

    lines = [
        f"Total steps: {len(trajectory)}",
        f"Exit status: {info.get('exit_status', 'unknown')}",
    ]

    model_stats = info.get("model_stats", {})
    if model_stats:
        lines.append(f"API calls: {model_stats.get('api_calls', 'unknown')}")
        lines.append(f"Instance cost: {model_stats.get('instance_cost', 'unknown')}")

    submission = info.get("submission")
    if submission:
        lines.append("")
        lines.append("=== Final submission (patch) ===")
        lines.append(_truncate(str(submission), 8000))

    lines.append("")
    lines.append("=== Trajectory steps ===")

    if not trajectory:
        lines.append("(empty trajectory)")
        return "\n".join(lines)

    start_idx = max(0, len(trajectory) - max_steps)
    if start_idx > 0:
        lines.append(f"(showing last {max_steps} of {len(trajectory)} steps)")

    for i, step in enumerate(trajectory[start_idx:], start=start_idx + 1):
        action = step.get("action", "")
        observation = step.get("observation", "")
        response = step.get("response", "") or step.get("thought", "")
        lines.append(f"\n--- Step {i} ---")
        if response:
            lines.append(f"Thought: {_truncate(str(response), 500)}")
        if action:
            lines.append(f"Action: {_truncate(str(action), 1500)}")
        if observation:
            lines.append(f"Observation: {_truncate(str(observation), 2000)}")

    return "\n".join(lines)


def prepare_classification_context(
    artifacts: TrialArtifacts,
    instance_metadata: dict,
    staging_root: Path,
) -> Path:
    """Stage files for Claude Code to read during classification."""
    context_dir = staging_root / artifacts.instance_id / f"trial_{artifacts.trial}"
    if context_dir.exists():
        shutil.rmtree(context_dir)
    context_dir.mkdir(parents=True)

    # Instance metadata (subset relevant for classification)
    metadata = {
        "instance_id": artifacts.instance_id,
        "repo": instance_metadata.get("repo"),
        "base_commit": instance_metadata.get("base_commit"),
        "problem_statement": instance_metadata.get("problem_statement"),
        "hints_text": instance_metadata.get("hints_text"),
        "FAIL_TO_PASS": instance_metadata.get("FAIL_TO_PASS"),
        "PASS_TO_PASS": instance_metadata.get("PASS_TO_PASS"),
        "language": instance_metadata.get("language"),
        "task_type": instance_metadata.get("task_type"),
    }
    (context_dir / "instance_metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    if artifacts.report_path and artifacts.report_path.exists():
        shutil.copy2(artifacts.report_path, context_dir / "report.json")

    if artifacts.test_output_path and artifacts.test_output_path.exists():
        content = artifacts.test_output_path.read_text(errors="replace")
        (context_dir / "test_output.txt").write_text(
            _truncate(content, 50000),
            encoding="utf-8",
        )

    patch = artifacts.model_patch
    if patch:
        (context_dir / "model_patch.diff").write_text(patch, encoding="utf-8")

    if artifacts.traj_path and artifacts.traj_path.exists():
        summary = build_trajectory_summary(artifacts.traj_path)
        (context_dir / "trajectory_summary.txt").write_text(summary, encoding="utf-8")
        # Symlink full traj for optional deep inspection (avoid copy of huge files)
        try:
            (context_dir / "trajectory.traj").symlink_to(artifacts.traj_path.resolve())
        except OSError:
            pass

    return context_dir
