from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,49}$")]
Domain = Literal["ecommerce", "fmcg"]
Baseline = Literal["mom", "yoy", "target"]
Dimension = Literal["day", "channel", "region", "category", "segment"]
SliceDimension = Literal["channel", "region", "category", "segment"]
FilterValue = Annotated[str, StringConstraints(min_length=1, max_length=80)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1600)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Login(Input):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class Period(Input):
    start: date
    end: date
    baseline: Baseline = "mom"

    @model_validator(mode="after")
    def check_period(self):
        if not date(2000, 1, 1) <= self.start <= self.end <= date(2100, 12, 31):
            raise ValueError("日期区间无效")
        if (self.end - self.start).days >= 366:
            raise ValueError("分析区间最多 366 日")
        return self


class AnalysisSpec(Period):
    metric_id: Identifier
    filters: dict[SliceDimension, FilterValue] = Field(default_factory=dict)
    dimensions: list[Dimension] = Field(default_factory=lambda: ["channel"], min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_dimensions(self):
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("下钻维度不可重复")
        return self


class CreateSession(Input):
    metric_id: Identifier | None = None
    question: Text | None = None
    start: date | None = None
    end: date | None = None
    baseline: Baseline = "mom"
    domain_id: Domain | None = None
    auto_start: bool = True

    @model_validator(mode="after")
    def check_source(self):
        if self.metric_id is None and self.question is None:
            raise ValueError("请指定指标或输入分析问题")
        return self


class Message(Input):
    content: Text


class HypothesisChoice(Input):
    template: Identifier
    scope: dict[SliceDimension, FilterValue] = Field(default_factory=dict)


class Planned(Input):
    spec: AnalysisSpec
    hypotheses: list[HypothesisChoice] = Field(min_length=3, max_length=5)


class EventInput(Input):
    domain_id: Domain
    type: Literal["promotion", "outage", "policy", "competitor", "macro", "operation"]
    title: str = Field(min_length=1, max_length=120)
    start: date
    end: date
    scope: dict[SliceDimension, list[FilterValue]] = Field(default_factory=dict)
    impact_note: str = Field(default="", max_length=600)

    @model_validator(mode="after")
    def check_dates(self):
        if self.end < self.start or any(not values or len(values) > 20 for values in self.scope.values()):
            raise ValueError("事件区间或影响范围无效")
        return self


class MetricInput(Input):
    metric_id: Identifier
    name: str = Field(min_length=1, max_length=80)
    domain_id: Domain
    unit: str = Field(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9_*/%]+$")
    model: Literal["atomic", "add", "mul", "ratio"]
    formula: str = Field(default="", max_length=300)
    threshold: float = Field(default=.08, gt=0, le=1)
    source_field: Identifier | None = None


class ScenarioInput(Input):
    name: str = Field(default="情景", min_length=1, max_length=32)
    changes: dict[Identifier, Annotated[float, Field(ge=-0.8, le=1.0)]] = Field(min_length=1, max_length=8)
    save: bool = True


class SnapshotInput(Input):
    label: str = Field(default="分析快照", min_length=1, max_length=80)


class ReportInput(Input):
    title: str | None = Field(default=None, min_length=1, max_length=120)


class ReportStatus(Input):
    status: Literal["draft", "published"]


class CommentInput(Input):
    content: str = Field(min_length=1, max_length=600)
    section: Identifier
    quotation: str = Field(default="", max_length=300)
    mentions: list[str] = Field(default_factory=list, max_length=10)


class SubscriptionInput(Input):
    domain_id: Domain
    interval_days: Literal[1, 7, 30] = 7


class RuntimeSettings(Input):
    confidence_threshold: float = Field(default=.6, ge=0, le=1)
    sandbox_timeout: int = Field(default=20, ge=1, le=20)
    sandbox_memory_mb: int = Field(default=512, ge=256, le=512)
    model_max_tokens: int = Field(default=2500, ge=512, le=8192)


class DataSourceInput(Input):
    url: str = Field(default="http://127.0.0.1:8123", pattern=r"^https?://(?:127\.0\.0\.1|localhost):[0-9]{2,5}/?$")
    database: Identifier = "test_db"


class BusinessLineInput(Input):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=240)


class EvidenceReviewInput(Input):
    decision: Literal["accepted", "needs_review"]
    note: str = Field(default="", max_length=600)
