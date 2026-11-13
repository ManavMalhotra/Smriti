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
ReportCategory = Literal[
    "lab", "imaging", "prescription", "discharge", "pathology", "other"
]
ReportStatus = Literal["auto", "review", "rejected"]
FactType = Literal[
    "lab",
    "measurement",
    "impression",
    "imaging_finding",
    "diagnosis",
    "recommendation",
    "note",
    "other",
]
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

    @field_validator("username", "alias", mode="before")
    @classmethod
    def _trim_identity(cls, value):
        return value.strip() if isinstance(value, str) else value


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


class CloudConsentCreate(StrictModel):
    approved: bool = Field(strict=True)
    extra_redaction_boxes: dict[str, list[list[object]]] = Field(default_factory=dict)

    @field_validator("extra_redaction_boxes", mode="before")
    @classmethod
    def valid_redactions(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Redaction masks must be a page map")
        cleaned = {}
        for page, boxes in value.items():
            page_str = str(page).strip()
            if not page_str.isdecimal() or not 1 <= int(page_str) <= 2**31 - 1:
                raise ValueError("Invalid redaction page")
            if not isinstance(boxes, list):
                raise ValueError("Redaction masks must be lists")
            valid_boxes = []
            for box in boxes:
                if not isinstance(box, (list, tuple)):
                    raise ValueError("Redaction masks must be lists")
                b = list(box)
                if len(b) == 4 and all(type(v) is int for v in b):
                    # Convert [x0, y0, x1, y1] to [x, y, width, height, "custom", "id"]
                    if b[2] > b[0] and b[3] > b[1]:
                        b = [b[0], b[1], b[2] - b[0], b[3] - b[1], "custom", "box-1"]
                    else:
                        b = [b[0], b[1], b[2], b[3], "custom", "box-1"]
                if (len(b) != 6
                        or any(type(v) is not int for v in b[:4])
                        or not isinstance(b[4], str) or not isinstance(b[5], str)
                        or any(not 0 <= v <= 1000 for v in b[:4])
                        or b[2] < 1 or b[3] < 1 or b[0] + b[2] > 1000 or b[1] + b[3] > 1000
                        or len(b[4]) > 100 or not b[5] or len(b[5]) > 80):
                    raise ValueError("Masks must be [x, y, width, height, label, id] within page bounds")
                valid_boxes.append(b)
            cleaned[page_str] = valid_boxes
        if sum(len(boxes) for boxes in cleaned.values()) > 1000:
            raise ValueError("Too many redaction boxes (maximum 1000 allowed)")
        return cleaned


class ObservationReview(StrictModel):
    action: Literal["accept", "correct", "reject"]
    analyte_id: str | None = Field(default=None, max_length=64)
    raw_label: str | None = Field(default=None, max_length=256)
    value_num: str | None = Field(default=None, max_length=64)
    value_text: str | None = Field(default=None, max_length=4000)
    unit_norm: str | None = Field(default=None, max_length=32)
    ref_low: str | None = Field(default=None, max_length=64)
    ref_high: str | None = Field(default=None, max_length=64)
    flag: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=500)


class ManualObservationCreate(StrictModel):
    raw_label: str = Field(min_length=1, max_length=256)
    analyte_id: str | None = Field(default=None, max_length=64)
    value_num: str | None = Field(default=None, max_length=64)
    value_text: str | None = Field(default=None, max_length=4000)
    unit_norm: str | None = Field(default=None, max_length=32)
    ref_low: str | None = Field(default=None, max_length=64)
    ref_high: str | None = Field(default=None, max_length=64)
    flag: str | None = Field(default=None, max_length=32)
    page: int = Field(default=1, ge=1)
    bbox: list[float] | None = None

    @field_validator("bbox")
    @classmethod
    def _valid_box(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        if len(value) != 4 or any(not 0 <= c <= 1 for c in value):
            raise ValueError("bbox must be four coordinates between 0 and 1")
        return value


class MedicationUpdate(StrictModel):
    brand_raw: str | None = Field(default=None, max_length=160)
    salt: str | None = Field(default=None, max_length=160)
    dose: str | None = Field(default=None, max_length=100)
    freq: str | None = Field(default=None, max_length=100)
    status: MedicationStatus | None = None
    start_date: date | None = None


class ReportUpdate(StrictModel):
    report_date: date | None = None
    category: ReportCategory | None = None
    title: str | None = Field(default=None, max_length=200)
    facility_name: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)


class DocumentUpdate(StrictModel):
    display_name: str | None = Field(default=None, max_length=200)
    doc_type: DocType | None = None
    verified_date: date | None = None
    facility_name: str | None = Field(default=None, max_length=200)


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
    undated_documents: int = Field(default=0, ge=0)
    future_documents: int = Field(default=0, ge=0)


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
    page_num: int | None = None
    bbox_2d: list[int] | None = None
    engine: str | None = None
    event_date: date | None = None
    regimen_type: str | None = None
    confidence_note: str | None = None
    source_anchors: list[dict] = Field(default_factory=list)


class ResultPoint(StrictModel):
    date: date
    value: float
    flag_printed: str | None = None
    observation_id: str
    document_id: str
    page: int = Field(ge=1)
    bbox: list[float]
    status: Literal["auto", "review"] = "auto"
    ref_min: float | None = None
    ref_max: float | None = None
    abnormal_flag: str | None = None
    engine: str | None = None
    source_anchors: list[dict] = Field(default_factory=list)

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
    display_name: str | None = None
    verified_date: date | None = None
    doc_type: DocType
    doc_date: date | None = None
    collection_date: date | None = None
    registration_date: date | None = None
    report_date: date | None = None
    patient_uhid: str | None = None
    patient_mrd: str | None = None
    doctor_reg_no: str | None = None
    hospital: str | None = None
    facility_name: str | None = None
    page_count: int = Field(ge=1)
    status: DocumentStatus
    processed_at: datetime | None = None
    review_count: int = Field(default=0, ge=0)


class ChronicCondition(StrictModel):
    name: str
    status: Literal["active", "negative", "resolved", "suspected", "not_reported"]
    details: str | None = None
    source_doc_id: str | None = None


class YearHistoryEntry(StrictModel):
    year: int | None = None
    title: str
    summary: str | None = None
    category: str = "clinical_event"
    source_doc_id: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    exact_date: str | None = None
    status: Literal["auto", "review"] = "review"


class OngoingMedication(StrictModel):
    brand_name: str
    dose: str | None = None
    freq: str | None = None
    indication: str | None = None
    report_date: str | None = None
    source_doc_id: str | None = None
    is_latest_report: bool = True


class StandardizedClinicalSummary(StrictModel):
    patient_name: str | None = None
    age: int | str | None = None
    gender: str | None = None
    hypertension: ChronicCondition | None = None
    chronic_conditions: list[ChronicCondition] = Field(default_factory=list)
    genetic_family_history: str | None = None
    past_history: str | None = None
    ongoing_treatment: str | None = None
    year_wise_history: list[YearHistoryEntry] = Field(default_factory=list)
    current_medications: list[OngoingMedication] = Field(default_factory=list)
    concise_history_summary: str | None = None
    generated_at: str | None = None
    model_id: str | None = None
    is_cloud_generated: bool = False
    cloud_error: str | None = None


class Summary(StrictModel):
    patient: SummaryPatient
    coverage: Coverage
    problems: list[Problem]
    medications: list[MedicationSummary]
    results: list[Result]
    pending: list[Pending]
    documents: list[DocumentSummary]
    clinical_snapshot: dict[str, list[dict]] = Field(default_factory=dict)
    organ_groups: dict[str, list[dict]] = Field(default_factory=dict)
    medications_timeline: dict[str, list[dict]] = Field(default_factory=dict)
    master_timeline: list[dict] = Field(default_factory=list)
    standardized_summary: StandardizedClinicalSummary | None = None


class TimelineFact(StrictModel):
    id: str
    report_id: str | None = None
    document_id: str
    fact_type: FactType
    label_raw: str | None = None
    label_norm: str | None = None
    value_num: str | None = None
    value_text: str | None = None
    unit_norm: str | None = None
    page: int = Field(ge=1)
    bbox: list[float]
    status: ObservationStatus
    reason: str | None = None
    evidence_quote: str | None = None

    @field_validator("bbox")
    @classmethod
    def _valid_box(cls, value: list[float]) -> list[float]:
        if len(value) != 4 or any(not 0 <= coordinate <= 1 for coordinate in value):
            raise ValueError("bbox must be four values in [0, 1]")
        return value


class TimelineReport(StrictModel):
    id: str
    document_id: str
    category: ReportCategory
    report_type: str
    report_date: date | None = None
    facility_name: str | None = None
    title: str | None = None
    summary: str | None = None
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    status: ReportStatus
    reason: str | None = None
    review_count: int = Field(default=0, ge=0)
    facts: list[TimelineFact]


class Timeline(StrictModel):
    patient_id: str
    reports: list[TimelineReport]
