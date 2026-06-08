from __future__ import annotations

from pathlib import Path

import typer

from task_analyze.classifier import VERDICT_MODEL
from task_analyze.run import ClassifyArgs, run_classify

app = typer.Typer(
    name="task-classify",
    help="Classify SWE-bench trial outcomes and synthesize instance verdicts",
    no_args_is_help=True,
)


@app.command()
def main(
    dataset: Path = typer.Option(..., "--dataset", "-d", help="Path to task JSONL"),
    run_prefix: str = typer.Option(
        None, "--run-prefix", help="Run prefix (defaults to dataset basename)"
    ),
    trials: str = typer.Option(
        "1 2 3 4 5", "--trials", help="Space-separated trial numbers"
    ),
    trajectories_root: Path = typer.Option(
        Path("SWE-agent/trajectories"),
        "--trajectories-root",
        help="Root directory for SWE-agent trajectories",
    ),
    bench_root: Path = typer.Option(
        Path("SWE-bench-modified"),
        "--bench-root",
        help="SWE-bench-modified root directory",
    ),
    output_dir: Path = typer.Option(
        Path(".task_analyze/results"),
        "--output-dir",
        help="Directory for classification results",
    ),
    gold_run_id: str = typer.Option(
        None, "--gold-run-id", help="Gold eval run_id (default: <run_prefix>_gold)"
    ),
    instance_ids: str = typer.Option(
        None, "--instances", help="Comma-separated instance IDs to classify (default: all)"
    ),
    analysis_model: str = typer.Option(
        "claude-sonnet-4-5",
        "--analysis-model",
        help="Model for Claude Code classification",
    ),
    verdict_model: str = typer.Option(
        VERDICT_MODEL, "--verdict-model", help="OpenAI model for verdict synthesis"
    ),
    classification_timeout: int = typer.Option(
        300, "--classification-timeout", help="Timeout per classification (seconds)"
    ),
    verdict_timeout: int = typer.Option(
        180, "--verdict-timeout", help="Timeout for verdict synthesis (seconds)"
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose output"),
    skip_classify: bool = typer.Option(
        False, "--skip-classify", help="Skip LLM classification (verdict only if pre-loaded)"
    ),
) -> None:
    """
    Classify agent trial outcomes and synthesize per-instance verdicts.

    Requires agent trials + eval to have been run first. Reads:
    - Instance metadata from JSONL (problem_statement, FAIL_TO_PASS, etc.)
    - Eval reports from SWE-bench logs (report.json, test_output.txt)
    - Agent trajectories from SWE-agent (.traj files)
    """
    prefix = run_prefix or dataset.stem
    trial_list = [int(t) for t in trials.split()]
    ids = [s.strip() for s in instance_ids.split(",")] if instance_ids else None

    run_classify(
        ClassifyArgs(
            dataset_path=dataset,
            run_prefix=prefix,
            trials=trial_list,
            trajectories_root=trajectories_root,
            bench_root=bench_root,
            output_dir=output_dir,
            gold_run_id=gold_run_id,
            instance_ids=ids,
            analysis_model=analysis_model,
            verdict_model=verdict_model,
            classification_timeout=classification_timeout,
            verdict_timeout=verdict_timeout,
            verbose=verbose,
            skip_classify=skip_classify,
        )
    )


if __name__ == "__main__":
    app()
