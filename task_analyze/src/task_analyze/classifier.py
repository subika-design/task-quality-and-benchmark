from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
)
from openai import OpenAI
from rich.console import Console

from task_analyze.claude_code_utils import Colors, print_sdk_message
from task_analyze.models import (
    BaselineResult,
    BaselineValidation,
    Classification,
    TaskVerdict,
    TaskVerdictModel,
    TrialClassification,
    TrialClassificationModel,
)


VERDICT_MODEL = "gpt-5.2"
VERDICT_TIMEOUT = 120.0
VERDICT_MAX_TOKENS = 4096

_CLASSIFY_PROMPT_PATH = Path(__file__).parent / "classify_prompt.txt"
_CLASSIFY_PROMPT = _CLASSIFY_PROMPT_PATH.read_text()

_VERDICT_PROMPT_PATH = Path(__file__).parent / "verdict_prompt.txt"
_VERDICT_PROMPT = _VERDICT_PROMPT_PATH.read_text()


def classify_trial(
    context_dir: str | Path,
    trial_name: str,
    *,
    resolved: bool | None,
    model: str = "claude-sonnet-4-5",
    verbose: bool = False,
    timeout: int = 300,
) -> TrialClassification:
    """Classify a single trial outcome for one SWE-bench instance."""
    classifier = TrialClassifier(model=model, verbose=verbose, timeout=timeout)
    return classifier.classify_trial_sync(
        Path(context_dir), trial_name, resolved=resolved
    )


class TrialClassifier:
    """Classifies trial outcomes using Claude Code to identify task quality issues."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-5",
        verbose: bool = False,
        timeout: int = 300,
    ):
        self._model = model
        self._verbose = verbose
        self._timeout = timeout
        self._setup_authentication()

    def _setup_authentication(self) -> None:
        has_oauth = bool(os.getenv("CLAUDE_CODE_OAUTH_TOKEN"))
        has_api_key = bool(os.getenv("ANTHROPIC_API_KEY"))

        if has_oauth:
            if "ANTHROPIC_API_KEY" in os.environ:
                os.environ.pop("ANTHROPIC_API_KEY")
        elif has_api_key:
            if "CLAUDE_CODE_OAUTH_TOKEN" in os.environ:
                os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN")

    async def classify_trial(
        self,
        context_dir: Path,
        trial_name: str,
        *,
        resolved: bool | None,
    ) -> TrialClassification:
        reward = None
        if resolved is True:
            result_str = "pass"
            reward = 1.0
        elif resolved is False:
            result_str = "fail"
            reward = 0.0
        else:
            result_str = f"unknown (resolved={resolved})"

        prompt = _CLASSIFY_PROMPT.format(
            result=result_str,
            context_dir=str(context_dir),
        )

        options = ClaudeAgentOptions(
            permission_mode="bypassPermissions",
            allowed_tools=["Read", "Glob"],
            cwd=str(context_dir),
            model=self._model,
            output_format={
                "type": "json_schema",
                "schema": TrialClassificationModel.model_json_schema(),
            },
        )

        structured_output: Any = None
        try:
            has_auth = bool(
                os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")
            )
            if not has_auth:
                raise RuntimeError(
                    "No authentication configured. Set either CLAUDE_CODE_OAUTH_TOKEN "
                    "(preferred, run 'claude setup-token') or ANTHROPIC_API_KEY"
                )

            if self._verbose:
                print(
                    f"{Colors.YELLOW}[Classifier] Running Claude Code classification "
                    f"(timeout: {self._timeout}s)...{Colors.RESET}",
                    flush=True,
                )
                print(f"{Colors.YELLOW}[Classifier] Trial: {trial_name}{Colors.RESET}", flush=True)
                print(f"{Colors.YELLOW}[Classifier] Context: {context_dir}{Colors.RESET}", flush=True)
                print("-" * 60, flush=True)

            try:
                async with asyncio.timeout(self._timeout):
                    async with ClaudeSDKClient(options=options) as client:
                        await client.query(prompt)

                        async for message in client.receive_response():
                            if self._verbose:
                                print_sdk_message(message)
                            if isinstance(message, ResultMessage):
                                structured_output = message.structured_output
            except TimeoutError:
                if self._verbose:
                    print(
                        f"{Colors.RED}[Classifier] Timed out after {self._timeout}s{Colors.RESET}",
                        flush=True,
                    )
                return TrialClassification(
                    trial_name=trial_name,
                    classification=Classification.HARNESS_ERROR,
                    subtype="Timeout",
                    evidence=f"Classification timed out after {self._timeout} seconds",
                    root_cause="Claude Code classification exceeded time limit",
                    recommendation="Review trial manually or increase timeout",
                    reward=reward,
                )

            if structured_output is None:
                raise RuntimeError(
                    "Claude Agent SDK did not return structured_output for this request"
                )

            if self._verbose:
                print("-" * 60, flush=True)
                print(
                    f"{Colors.GREEN}[Classifier] Classification complete for {trial_name}{Colors.RESET}",
                    flush=True,
                )

            return self._parse_trial_classification_structured(
                structured_output, trial_name, reward
            )

        except Exception as e:
            return TrialClassification(
                trial_name=trial_name,
                classification=Classification.HARNESS_ERROR,
                subtype="Classification Failed",
                evidence=f"Claude Code classification failed: {e}",
                root_cause="Could not analyze trial with Claude Code",
                recommendation="Review trial manually or check authentication",
                reward=reward,
            )

    def _parse_trial_classification_structured(
        self,
        structured_output: Any,
        trial_name: str,
        reward: float | None,
    ) -> TrialClassification:
        try:
            data: Any = structured_output

            if isinstance(data, dict):
                if "structured_output" in data and isinstance(data["structured_output"], dict):
                    data = data["structured_output"]
                if "result" in data and isinstance(data["result"], dict):
                    data = data["result"]

            model = TrialClassificationModel.model_validate(data)
            classification = TrialClassification.from_model(
                trial_name=trial_name, model=model, reward=reward
            )

            if reward == 1.0 and not classification.classification.is_success:
                classification.classification = Classification.BAD_SUCCESS
                classification.subtype = "Inconsistent Output"
                classification.evidence = (
                    f"Claude returned {model.classification} but verified result was pass. "
                    + classification.evidence
                ).strip()
            if reward == 0.0 and classification.classification.is_success:
                classification.classification = Classification.HARNESS_ERROR
                classification.subtype = "Inconsistent Output"
                classification.evidence = (
                    f"Claude returned {model.classification} but verified result was fail. "
                    + classification.evidence
                ).strip()

            return classification
        except Exception as e:
            return TrialClassification(
                trial_name=trial_name,
                classification=Classification.HARNESS_ERROR,
                subtype="Parse Error",
                evidence=f"Could not parse structured output: {e}",
                root_cause="Claude's structured output did not match expected schema",
                recommendation="Review trial manually",
                reward=reward,
            )

    def classify_trial_sync(
        self,
        context_dir: Path,
        trial_name: str,
        *,
        resolved: bool | None,
    ) -> TrialClassification:
        return asyncio.run(self.classify_trial(context_dir, trial_name, resolved=resolved))

    async def classify_trials(
        self,
        items: list[tuple[Path, str, bool | None]],
        console: Console | None = None,
    ) -> list[TrialClassification]:
        if console:
            console.print(f"  Classifying {len(items)} trial(s) with Claude Code...")

        classifications = []
        for i, (context_dir, trial_name, resolved) in enumerate(items):
            if console:
                console.print(f"    [{i + 1}/{len(items)}] {trial_name}...")
            try:
                classification = await self.classify_trial(
                    context_dir, trial_name, resolved=resolved
                )
                classifications.append(classification)
            except Exception as e:
                classifications.append(
                    TrialClassification(
                        trial_name=trial_name,
                        classification=Classification.HARNESS_ERROR,
                        subtype="Classification Error",
                        evidence=str(e),
                        root_cause="Exception during classification",
                        recommendation="Review trial manually",
                        reward=None,
                    )
                )
        return classifications

    def classify_trials_sync(
        self,
        items: list[tuple[Path, str, bool | None]],
        console: Console | None = None,
    ) -> list[TrialClassification]:
        return asyncio.run(self.classify_trials(items, console))


def classify_baseline_result(
    resolved: bool | None,
    error: str | None = None,
) -> BaselineResult:
    passed = resolved is True
    reward = 1.0 if passed else 0.0 if resolved is False else None
    return BaselineResult(agent="gold", passed=passed, reward=reward, error=error)


def compute_task_verdict(
    classifications: list[TrialClassification],
    baseline: BaselineValidation | None = None,
    *,
    instance_id: str = "",
    model: str = VERDICT_MODEL,
    console: Console | None = None,
    verbose: bool = False,
    api_key: str | None = None,
    timeout: float | None = None,
) -> TaskVerdict:
    """Compute overall instance verdict from trial classifications using LLM synthesis."""
    return _compute_task_verdict_openai(
        classifications,
        baseline,
        instance_id=instance_id,
        model=model,
        console=console,
        verbose=verbose,
        api_key=api_key,
        timeout=timeout,
    )


def _compute_task_verdict_openai(
    classifications: list[TrialClassification],
    baseline: BaselineValidation | None = None,
    *,
    instance_id: str = "",
    model: str = VERDICT_MODEL,
    console: Console | None = None,
    verbose: bool = False,
    api_key: str | None = None,
    timeout: float | None = None,
) -> TaskVerdict:
    if not classifications:
        return TaskVerdict(
            is_good=False,
            confidence="low",
            primary_issue="No trials to analyze",
            recommendations=["Run agent trials and eval first"],
        )

    if not (api_key or os.getenv("OPENAI_API_KEY")):
        raise RuntimeError("OPENAI_API_KEY not set for verdict synthesis")

    if baseline:
        if baseline.is_valid:
            baseline_summary = "Passed (gold patch resolved as expected)"
        else:
            baseline_summary = "FAILED:\n" + "\n".join(
                f"  - {issue}" for issue in baseline.issues
            )
    else:
        baseline_summary = "Not run"

    trial_lines = []
    for i, c in enumerate(classifications, 1):
        trial_lines.append(
            f"""Trial {i}: {c.trial_name}
  Classification: {c.classification.value}
  Subtype: {c.subtype}
  Reward: {c.reward}
  Evidence: {c.evidence}
  Root Cause: {c.root_cause}
  Recommendation: {c.recommendation}
"""
        )
    trial_classifications = "\n".join(trial_lines)

    prompt = _VERDICT_PROMPT.format(
        num_trials=len(classifications),
        instance_id=instance_id,
        baseline_summary=baseline_summary,
        trial_classifications=trial_classifications,
    )

    if console:
        console.print("  [dim]Synthesizing verdict with OpenAI...[/dim]")

    if verbose:
        print(
            f"\n{Colors.YELLOW}[Verdict] Synthesizing instance verdict with {model}...{Colors.RESET}",
            flush=True,
        )

    client = OpenAI(
        api_key=api_key or os.getenv("OPENAI_API_KEY"),
        timeout=timeout or VERDICT_TIMEOUT,
    )

    try:
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format=TaskVerdictModel,
            max_completion_tokens=VERDICT_MAX_TOKENS,
        )

        verdict_model = completion.choices[0].message.parsed
        if verdict_model is None:
            raise RuntimeError("OpenAI returned no parsed result for verdict synthesis")

        if verbose:
            print(f"{Colors.GREEN}[Verdict] Verdict synthesis complete{Colors.RESET}\n", flush=True)

    except Exception as exc:
        if verbose:
            print(
                f"{Colors.RED}[Verdict] Failed ({type(exc).__name__}): {exc}{Colors.RESET}\n",
                flush=True,
            )
        raise RuntimeError(f"Verdict synthesis failed: {exc}") from exc

    task_problem_count = sum(1 for c in classifications if c.is_task_problem)
    agent_problem_count = sum(
        1 for c in classifications if c.classification == Classification.GOOD_FAILURE
    )
    success_count = sum(
        1
        for c in classifications
        if c.classification in (Classification.GOOD_SUCCESS, Classification.BAD_SUCCESS)
    )
    harness_error_count = sum(
        1 for c in classifications if c.classification == Classification.HARNESS_ERROR
    )

    return TaskVerdict(
        is_good=verdict_model.is_good,
        confidence=verdict_model.confidence,
        primary_issue=verdict_model.primary_issue,
        recommendations=verdict_model.recommendations,
        task_problem_count=task_problem_count,
        agent_problem_count=agent_problem_count,
        success_count=success_count,
        harness_error_count=harness_error_count,
        classifications=classifications,
        baseline=baseline,
    )
