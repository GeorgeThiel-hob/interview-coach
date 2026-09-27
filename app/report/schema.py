"""Report schema ``report/v1`` (spec 8.2). Exported as JSON Schema for other tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "report/v1"
Level = Literal["strong", "partial", "none"]


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Vacancy(_M):
    title: str = ""
    organisation: str = ""
    summary: str = ""


class RequirementCoverage(_M):
    id: str
    kind: str
    text: str
    evidence_in_documents: Level = "none"
    evidence_in_interview: Level = "none"


class JudgmentView(_M):
    value: float | str
    confidence: float | None = None
    provider: str = "jev"
    uncertain: bool = False
    escalated: bool = False
    rationale: str | None = None


class FeedbackItem(_M):
    text: str
    sources: list[str] = Field(default_factory=list)  # chunk refs (cv:...) or turn:<id>


class FeedbackView(_M):
    strengths: list[FeedbackItem] = Field(default_factory=list)
    add: list[FeedbackItem] = Field(default_factory=list)
    explore: list[FeedbackItem] = Field(default_factory=list)
    outline: list[FeedbackItem] = Field(default_factory=list)


class SpeakingView(_M):
    duration_s: float
    wpm: float
    fillers_per_min: float


class AnswerView(_M):
    turn_id: str
    topic: str
    persona: str | None = None
    question: str
    answer: str
    judgments: dict[str, JudgmentView] = Field(default_factory=dict)
    feedback: FeedbackView | None = None
    speaking: SpeakingView | None = None
    focus_item_id: str | None = None


class FocusItem(_M):
    id: str
    label: str
    linked_requirements: list[str] = Field(default_factory=list)
    severity: float = 0.5
    history: list[str] = Field(default_factory=list)  # mastered/improved/unchanged/regressed/weak
    previous_questions: list[str] = Field(default_factory=list)
    previous_answer: str = ""


class PracticeAction(_M):
    action: str
    why: str
    links: list[str] = Field(default_factory=list)  # turn:<id>, tip:<id>, stat:<name>


class ModelsView(_M):
    jev_version: str = ""
    claude: str = ""
    local: str = ""


class Report(_M):
    schema_: Literal["report/v1"] = Field("report/v1", alias="schema")
    run_id: str
    created_at: str
    language: str = "nl"
    vacancy: Vacancy = Field(default_factory=Vacancy)
    requirements: list[RequirementCoverage] = Field(default_factory=list)
    answers: list[AnswerView] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    focus_items: list[FocusItem] = Field(default_factory=list)
    practice_plan: list[PracticeAction] = Field(default_factory=list)
    models: ModelsView = Field(default_factory=ModelsView)

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True, indent=2)


def json_schema() -> dict[str, Any]:
    return Report.model_json_schema(by_alias=True)
