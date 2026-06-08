from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from task_analyze.classifier import (
    TrialClassifier,
    VERDICT_MODEL,
    classify_baseline_result,
    compute_task_verdict,
)
from task_analyze.context import prepare_classification_context
from task_analyze.discovery import (
    discover_gold_baseline,
    discover_trial_artifacts,
    load_dataset,
)
from task_analyze.models import (
    AnalysisResult,
    BaselineValidation,
    Classification,
    InstanceAnalysisResult,
    TaskVerdict,
    TrialClassification,
)


def _setup_claude_auth_preference(console: Console) -> None:
    has_oauth = bool(os.getenv("CLAUDE_CODE_OAUTH_TOKEN"))
    has_api_key = bool(os.getenv("ANTHROPIC_API_KEY"))

    if has_oauth:
        if "ANTHROPIC_API_KEY" in os.environ:
            os.environ.pop("ANTHROPIC_API_KEY")
        console.print("[dim]Claude Code authentication: OAuth token (preferred)[/dim]")
    elif has_api_key:
        if "CLAUDE_CODE_OAUTH_TOKEN" in os.environ:
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN")
        console.print("[dim]Claude Code authentication: API key (fallback)[/dim]")
    else:
        console.print("[yellow]No Claude Code authentication configured[/yellow]")
        console.print(
            "[yellow]  Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY[/yellow]"
        )


@dataclass
class ClassifyArgs:
    dataset_path: Path
    run_prefix: str
    trials: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])
    trajectories_root: Path = Path("SWE-agent/trajectories")
    bench_root: Path = Path("SWE-bench-modified")
    output_dir: Path = Path(".task_analyze/results")
    staging_dir: Path = Path(".task_analyze/staging")
    gold_run_id: str | None = None
    instance_ids: list[str] | None = None
    analysis_model: str = "claude-sonnet-4-5"
    verdict_model: str = VERDICT_MODEL
    classification_timeout: int = 300
    verdict_timeout: int = 180
    verbose: bool = False
    skip_classify: bool = False


def run_classify(args: ClassifyArgs) -> AnalysisResult:
    """Run trial classification and verdict synthesis for all instances."""
    console = Console()

    dataset_path = args.dataset_path.resolve()
    if not dataset_path.is_file():
        console.print(f"[red]Error: Dataset not found: {dataset_path}[/red]")
        raise SystemExit(1)

    trajectories_root = args.trajectories_root.resolve()
    bench_root = args.bench_root.resolve()
    output_dir = args.output_dir.resolve()
    staging_dir = args.staging_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    _setup_claude_auth_preference(console)

    instances = load_dataset(dataset_path)
    if args.instance_ids:
        instances = {k: v for k, v in instances.items() if k in args.instance_ids}

    gold_run_id = args.gold_run_id or f"{args.run_prefix}_gold"

    console.print(
        Panel.fit(
            f"Instances: {len(instances)} | Trials: {args.trials} | Run prefix: {args.run_prefix}",
            title="Task Classification",
        )
    )

    instance_results: list[InstanceAnalysisResult] = []

    for instance_id, metadata in instances.items():
        console.print(f"\n[bold blue]Instance: {instance_id}[/bold blue]")

        gold_resolved, _ = discover_gold_baseline(bench_root, gold_run_id, instance_id)
        baseline = BaselineValidation()
        if gold_resolved is not None:
            baseline.gold = classify_baseline_result(gold_resolved)
            if baseline.gold.is_expected:
                console.print("  [green]Gold baseline: resolved[/green]")
            else:
                console.print("  [red]Gold baseline: NOT resolved[/red]")
        else:
            console.print("  [dim]Gold baseline: not found[/dim]")

        classify_items: list[tuple[Path, str, bool | None]] = []
        trial_outcomes: list[tuple[int, bool | None]] = []

        for trial in args.trials:
            artifacts = discover_trial_artifacts(
                instance_id=instance_id,
                trial=trial,
                run_prefix=args.run_prefix,
                trajectories_root=trajectories_root,
                bench_root=bench_root,
            )

            if artifacts is None:
                console.print(f"  [dim]Trial {trial}: no trajectory dir found[/dim]")
                continue

            if artifacts.traj_path is None:
                console.print(f"  [dim]Trial {trial}: no .traj file[/dim]")
                continue

            if artifacts.resolved is None and artifacts.eval_dir is None:
                console.print(
                    f"  [yellow]Trial {trial}: trajectory found but no eval report "
                    f"(run eval first)[/yellow]"
                )
                continue

            context_dir = prepare_classification_context(
                artifacts, metadata, staging_dir
            )
            trial_name = f"trial_{trial}"
            classify_items.append((context_dir, trial_name, artifacts.resolved))
            trial_outcomes.append((trial, artifacts.resolved))
            status = "resolved" if artifacts.resolved else "unresolved"
            console.print(f"  Trial {trial}: {status}")

        classifications: list[TrialClassification] = []
        if not args.skip_classify and classify_items:
            console.print("  [bold]Classifying trials...[/bold]")
            classifier = TrialClassifier(
                model=args.analysis_model,
                verbose=args.verbose,
                timeout=args.classification_timeout,
            )
            classifications = classifier.classify_trials_sync(classify_items, console)
        elif args.skip_classify:
            console.print("  [dim]Classification skipped[/dim]")

        successes = sum(1 for _, r in trial_outcomes if r is True)
        success_rate = successes / len(trial_outcomes) if trial_outcomes else 0.0

        verdict = compute_task_verdict(
            classifications,
            baseline,
            instance_id=instance_id,
            model=args.verdict_model,
            console=console,
            verbose=args.verbose,
            timeout=args.verdict_timeout,
        )

        instance_result = InstanceAnalysisResult(
            instance_id=instance_id,
            trials_run=len(trial_outcomes),
            success_rate=success_rate,
            classifications=classifications,
            verdict=verdict,
            baseline=baseline,
        )
        instance_results.append(instance_result)
        _print_instance_summary(instance_result, console)

    result = AnalysisResult(
        dataset_path=str(dataset_path),
        run_prefix=args.run_prefix,
        instances=instance_results,
        output_dir=str(output_dir),
    )

    _write_results(result, output_dir)
    _print_final_report(result, console)
    return result


def _print_instance_summary(result: InstanceAnalysisResult, console: Console) -> None:
    verdict = result.verdict
    if verdict.is_good:
        console.print(
            f"  [green]Verdict: GOOD ({verdict.confidence} confidence)[/green]"
        )
    else:
        console.print(
            f"  [red]Verdict: NEEDS REVIEW ({verdict.confidence} confidence)[/red]"
        )
        if verdict.primary_issue:
            console.print(f"  [yellow]Issue: {verdict.primary_issue}[/yellow]")


def _write_results(result: AnalysisResult, output_dir: Path) -> None:
    report_path = output_dir / f"{result.run_prefix}.classification.json"

    payload = {
        "dataset_path": result.dataset_path,
        "run_prefix": result.run_prefix,
        "instances": [],
    }

    for inst in result.instances:
        inst_data = {
            "instance_id": inst.instance_id,
            "trials_run": inst.trials_run,
            "success_rate": inst.success_rate,
            "verdict": {
                "is_good": inst.verdict.is_good,
                "confidence": inst.verdict.confidence,
                "primary_issue": inst.verdict.primary_issue,
                "recommendations": inst.verdict.recommendations,
                "task_problem_count": inst.verdict.task_problem_count,
                "agent_problem_count": inst.verdict.agent_problem_count,
                "success_count": inst.verdict.success_count,
                "harness_error_count": inst.verdict.harness_error_count,
            },
            "classifications": [
                {
                    "trial_name": c.trial_name,
                    "classification": c.classification.value,
                    "subtype": c.subtype,
                    "evidence": c.evidence,
                    "root_cause": c.root_cause,
                    "recommendation": c.recommendation,
                    "reward": c.reward,
                }
                for c in inst.classifications
            ],
            "gold_baseline_resolved": (
                inst.baseline.gold.passed if inst.baseline and inst.baseline.gold else None
            ),
        }
        payload["instances"].append(inst_data)

    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _print_final_report(result: AnalysisResult, console: Console) -> None:
    console.print("\n")
    console.print(Panel.fit("[bold]Classification Summary[/bold]"))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Instance")
    table.add_column("Trials")
    table.add_column("Resolve Rate")
    table.add_column("Verdict")
    table.add_column("Confidence")

    good_count = 0
    for inst in result.instances:
        verdict = inst.verdict
        if verdict.is_good:
            good_count += 1
            verdict_str = "[green]GOOD[/green]"
        else:
            verdict_str = "[red]NEEDS REVIEW[/red]"

        table.add_row(
            inst.instance_id,
            str(inst.trials_run),
            f"{inst.success_rate:.0%}",
            verdict_str,
            verdict.confidence,
        )

    console.print(table)
    console.print(
        f"\n[bold]{good_count}/{len(result.instances)}[/bold] instances marked good"
    )
    console.print(f"[dim]Results written to: {result.output_dir}[/dim]")

    for inst in result.instances:
        if not inst.verdict.is_good and inst.classifications:
            console.print(f"\n[bold]{inst.instance_id} trial details:[/bold]")
            for c in inst.classifications:
                console.print(
                    f"  {c.trial_name}: {c.classification.value} - {c.subtype}"
                )
                console.print(f"    [dim]{c.evidence[:200]}[/dim]")

    report_file = Path(result.output_dir) / f"{result.run_prefix}.classification.json"
    console.print(f"[dim]Full report: {report_file}[/dim]")
