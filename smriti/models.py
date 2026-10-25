"""Pydantic v2 models. The summary contract is frozen here and in the web fixture."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Sex = Literal["M", "F", "O"]
DocType = Literal[
    "lab_report",
    "prescription",
    "pharmacy",
    "discharge_summary",
    "ct",
    "mri",
    "xray",
    "pathology",
    "radiology",
    "other",
]
CaptureType = Literal["printed", "handwritten"]
DocumentStatus = Literal["queued", "processing", "done", "failed", "rejected_quality"]
ObservationStatus = Literal["auto", "review", "rejected"]
MappingRule = Literal["exact", "synonym", "unresolved"]
TimingType = Literal["relative", "absolute", "conditional", "prn"]
TimeUnit = Literal["day", "week", "month", "year"]
AnchorEvent = Literal["collection_date", "doc_date", "unknown"]
DirectiveState = Literal["open", "done", "superseded", "unknown_date"]
MedicationStatus = Literal["prescribed", "reported_stopped", "reported_ongoing"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictModel):
    username: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    password: str = Field(min_length=8, max_length=128)
    alias: str = Field(min_length=1, max_length=64)
    sex: Sex | None = None
    dob: date | None = None


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PatientOut(StrictModel):
    id: str
    alias: str
    username: str | None = None
    sex: Sex | None = None
    dob: date | None = None
    created_at: datetime


class ConsentCreate(StrictModel):
    scope: Literal["local", "local_plus_projection"]
    version: str = "1.0"


class ObservationReview(StrictModel):
    action: Literal["accept", "correct", "reject"]
    value_num: str | None = Field(default=None, max_length=64)
    unit_norm: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=500)


class SummaryPatient(StrictModel):
    id: str
    alias: str
    sex: Sex | None = None
    dob: date | None = None


class Quarter(StrictModel):
    q: str
    documents: int = Field(ge=0)


class Gap(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_date: date = Field(alias="from")
    to: date
    months: int = Field(ge=0)
    text: str


class Coverage(StrictModel):
    first_date: date | None = None
    last_date: date | None = None
    quarters: list[Quarter]
    gaps: list[Gap]


class Problem(StrictModel):
    id: str
    label: str
    source_doc_id: str


class MedicationSummary(StrictModel):
    id: str
    brand_raw: str
    salt: str | None = None
    dose: str | None = None
    freq: str | None = None
    state: MedicationStatus
    source_doc_id: str | None = None
    reported_at: datetime | None = None


class ResultPoint(StrictModel):
    date: date
    value: float
    flag_printed: str | None = None
    observation_id: str
    document_id: str
    page: int = Field(ge=1)
    bbox: list[float]
    status: Literal["auto", "review"] = "auto"

    @field_validator("bbox")
    @classmethod
    def _valid_box(cls, value: list[float]) -> list[float]:
        if len(value) != 4 or any(not 0 <= coordinate <= 1 for coordinate in value):
            raise ValueError("bbox must be four values in [0, 1]")
        return value


class Excluded(StrictModel):
    document_id: str
    reason: str


class Result(StrictModel):
    analyte_id: str
    display: str
    unit: str | None = None
    ref_low: float | None = None
    ref_high: float | None = None
    points: list[ResultPoint]
    excluded: list[Excluded]


class Pending(StrictModel):
    kind: Literal["directive", "medication"]
    id: str
    text: str
    action_type: str | None = None
    due_date: date | None = None
    anchor_event: AnchorEvent | None = None
    state: str | None = None


class DocumentSummary(StrictModel):
    id: str
    doc_type: DocType
    doc_date: date | None = None
    collection_date: date | None = None
    registration_date: date | None = None
    facility_name: str | None = None
    page_count: int = Field(ge=1)
    status: DocumentStatus
    review_count: int = Field(default=0, ge=0)


class Summary(StrictModel):
    patient: SummaryPatient
    coverage: Coverage
    problems: list[Problem]
    medications: list[MedicationSummary]
    results: list[Result]
    pending: list[Pending]
    documents: list[DocumentSummary]
