from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Classification(str, Enum):
    """Top-level classification of a trial outcome."""

    HARNESS_ERROR = "HARNESS_ERROR"
    GOOD_FAILURE = "GOOD_FAILURE"
    BAD_FAILURE = "BAD_FAILURE"
    GOOD_SUCCESS = "GOOD_SUCCESS"
    BAD_SUCCESS = "BAD_SUCCESS"

    @property
    def is_task_problem(self) -> bool:
        return self in (Classification.BAD_FAILURE, Classification.BAD_SUCCESS)

    @property
    def is_success(self) -> bool:
        return self in (Classification.GOOD_SUCCESS, Classification.BAD_SUCCESS)


class TrialClassificationModel(BaseModel):
    """Pydantic model for LLM structured output."""

    classification: Literal[
        "HARNESS_ERROR", "GOOD_FAILURE", "BAD_FAILURE", "GOOD_SUCCESS", "BAD_SUCCESS"
    ] = Field(description="Top-level classification")

    subtype: str = Field(
        description="Specific subtype from the taxonomy (e.g., 'Timeout', 'Underspecified Instruction')"
    )

    evidence: str = Field(
        description="Specific evidence from files: test names, error messages, code snippets"
    )

    root_cause: str = Field(
        description="1-2 sentence explanation of what caused this outcome"
    )

    recommendation: str = Field(
        description="How to fix the task (if BAD_FAILURE or BAD_SUCCESS), or 'N/A' if task is fine"
    )


class TaskVerdictModel(BaseModel):
    """Pydantic model for LLM structured output for the overall instance verdict."""

    is_good: bool = Field(description="Whether the instance is good (true) or needs review (false)")
    confidence: Literal["high", "medium", "low"] = Field(description="Confidence level")
    primary_issue: str | None = Field(
        default=None, description="Primary issue if instance needs review, else null"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Actionable recommendations (3-5 for bad instances)"
    )
    reasoning: str | None = Field(
        default=None, description="1-2 sentence explanation of the verdict (optional)"
    )


@dataclass
class TrialClassification:
    """Classification result for a single trial run on one instance."""

    trial_name: str
    classification: Classification
    subtype: str
    evidence: str
    root_cause: str
    recommendation: str
    reward: float | None = None

    @property
    def is_task_problem(self) -> bool:
        return self.classification.is_task_problem

    @classmethod
    def from_model(
        cls,
        trial_name: str,
        model: TrialClassificationModel,
        reward: float | None = None,
    ) -> TrialClassification:
        return cls(
            trial_name=trial_name,
            classification=Classification(model.classification),
            subtype=model.subtype,
            evidence=model.evidence,
            root_cause=model.root_cause,
            recommendation=model.recommendation,
            reward=reward,
        )


@dataclass
class BaselineResult:
    """Result from gold-patch baseline evaluation (SWE-bench oracle equivalent)."""

    agent: Literal["gold"]
    passed: bool
    reward: float | None
    error: str | None = None

    @property
    def is_expected(self) -> bool:
        return self.passed


@dataclass
class BaselineValidation:
    """Gold-patch baseline for a SWE-bench instance."""

    gold: BaselineResult | None = None

    @property
    def is_valid(self) -> bool:
        return self.gold is None or self.gold.is_expected

    @property
    def issues(self) -> list[str]:
        issues = []
        if self.gold and not self.gold.is_expected:
            issues.append("CRITICAL: gold patch did not resolve - reference solution broken")
        return issues


@dataclass
class TaskVerdict:
    """Final verdict on instance quality based on trial classifications."""

    is_good: bool
    confidence: Literal["high", "medium", "low"]
    primary_issue: str | None
    recommendations: list[str] = field(default_factory=list)
    task_problem_count: int = 0
    agent_problem_count: int = 0
    success_count: int = 0
    harness_error_count: int = 0
    classifications: list[TrialClassification] = field(default_factory=list)
    baseline: BaselineValidation | None = None

    def summary(self) -> str:
        if self.is_good:
            return f"GOOD INSTANCE (confidence: {self.confidence})"
        return f"NEEDS REVIEW: {self.primary_issue}"


@dataclass
class InstanceAnalysisResult:
    """Complete analysis for one SWE-bench instance."""

    instance_id: str
    trials_run: int
    success_rate: float
    classifications: list[TrialClassification]
    verdict: TaskVerdict
    baseline: BaselineValidation | None = None


@dataclass
class AnalysisResult:
    """Complete analysis across all instances in a dataset."""

    dataset_path: str
    run_prefix: str
    instances: list[InstanceAnalysisResult]
    output_dir: str
