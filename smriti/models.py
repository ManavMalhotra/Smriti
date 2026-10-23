"""Pydantic v2 models. The summary contract is frozen here and in the web fixture."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Sex = Literal["M", "F", "O"]
DocType = Literal["lab_report", "prescription", "pharmacy", "other"]
CaptureType = Literal["printed", "handwritten"]
DocumentStatus = Literal["queued", "processing", "done", "failed", "rejected_quality"]
ObservationStatus = Literal["auto", "review", "rejected"]
MappingRule = Literal["exact", "synonym", "unresolved"]
TimingType = Literal["relative", "absolute", "conditional", "prn"]
TimeUnit = Literal["day", "week", "month", "year"]
AnchorEvent = Literal["collection_date", "doc_date", "unknown"]
DirectiveState = Literal["open", "done", "superseded", "unknown_date"]
MedicationStatus = Literal["prescribed", "reported_stopped", "reported_ongoing"]
EgressOutcome = Literal["sent", "refused_no_consent", "refused_schema", "failed", "cached"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatientCreate(StrictModel):
    alias: str = Field(min_length=1, max_length=64)
    sex: Sex | None = None
    dob: date | None = None


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


class DocumentOut(StrictModel):
    id: str
    patient_id: str
    doc_type: DocType
    capture_type: CaptureType
    doc_date: date | None = None
    collection_date: date | None = None
    lab_name: str | None = None
    page_count: int = Field(ge=1)
    quality_score: float | None = None
    status: DocumentStatus
    doc_type_confidence: float | None = None
    processed_at: datetime | None = None
    created_at: datetime


class PageTextOut(StrictModel):
    page: int = Field(ge=1)
    text: str
    engine: str


class ObservationOut(StrictModel):
    id: str
    document_id: str
    analyte_id: str | None = None
    label_raw: str | None = None
    value_num: str | None = None
    value_text: str | None = None
    unit_raw: str | None = None
    unit_norm: str | None = None
    ref_low: str | None = None
    ref_high: str | None = None
    flag_printed: str | None = None
    bbox: list[float]
    page: int = Field(ge=1)
    engine: str
    confidence: float | None = None
    status: ObservationStatus
    reason: str | None = None
    mapping_rule: MappingRule | None = None
    created_at: datetime

    @field_validator("bbox")
    @classmethod
    def _valid_box(cls, value: list[float]) -> list[float]:
        if len(value) != 4 or any(not 0 <= coordinate <= 1 for coordinate in value):
            raise ValueError("bbox must be four values in [0, 1]")
        return value


class DirectiveOut(StrictModel):
    id: str
    document_id: str
    span_text: str
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)
    action_type: str
    timing_type: TimingType
    time_value: int | None = Field(default=None, ge=0)
    time_unit: TimeUnit | None = None
    anchor_event: AnchorEvent
    condition_text: str | None = None
    target: str | None = None
    anchor_date: date | None = None
    due_date: date | None = None
    state: DirectiveState


class MedicationOut(StrictModel):
    id: str
    patient_id: str
    brand_raw: str
    salt: str | None = None
    dose: str | None = None
    freq: str | None = None
    start_date: date | None = None
    status: MedicationStatus
    reported_at: datetime | None = None
    source_doc_id: str | None = None


class EgressOut(StrictModel):
    id: str
    document_id: str
    payload_sha256: str
    model_id: str | None = None
    prompt_version: str | None = None
    schema_version: str
    outcome: EgressOutcome
    reason: str | None = None
    ts: datetime


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
    page_count: int = Field(ge=1)
    status: DocumentStatus


class Summary(StrictModel):
    patient: SummaryPatient
    coverage: Coverage
    problems: list[Problem]
    medications: list[MedicationSummary]
    results: list[Result]
    pending: list[Pending]
    documents: list[DocumentSummary]
