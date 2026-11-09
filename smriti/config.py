"""Configuration is read once, here. No other module reads the environment."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
VALID_PROFILES = ("local-gpu", "demo")
MAX_BATCH_SUBMISSIONS = 10
MAX_WORKSET_PAGES = 20
SPOOL_CHUNK_BYTES = 1024 * 1024
MAX_SPOOLERS = 2
MAX_SPOOL_RAW_FILES = 20
# shortcut: 64 KiB multipart overhead is an unmeasured guardrail, revisit after isolated upload measurements.
MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_MULTIPART_FIELDS = 5


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    profile: str = "local-gpu"
    db_path: Path = BASE_DIR / "data" / "smriti.db"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    spool_dir: Path = BASE_DIR / "data" / "spool"
    log_dir: Path = BASE_DIR / "data" / "logs"
    resolver_enabled: bool = False
    resolver_provider: str = "local_rules"
    ocr_model: str = "PP-OCRv5_mobile"
    ocr_det_model: str = "PP-OCRv5_mobile_det"
    ocr_rec_model: str = "en_PP-OCRv5_mobile_rec"
    worker_enabled: bool = True
    worker_poll_seconds: float = 2.0
    session_ttl_days: int = 7
    login_attempts: int = 5
    login_window_minutes: int = 5
    quality_blur: float = 100.0
    quality_min_short_edge: int = 1000
    quality_max_aspect: float = 4.0
    quality_min_ink_ratio: float = 0.0005
    upscale_long_edge: int = 1500
    max_upload_bytes: int = 25 * 1024 * 1024
    max_pixels: int = 50_000_000
    hwr_margin: float = 0.15
    share_ttl_minutes: int = 30
    vlm_enabled: bool = True
    max_batch_submissions: int = MAX_BATCH_SUBMISSIONS
    max_workset_pages: int = MAX_WORKSET_PAGES
    max_spoolers: int = MAX_SPOOLERS
    debug_retain_failed_spool: bool = False
    preparation_timeout_seconds: float = 300.0
    ocr_startup_seconds: float = 60.0
    ocr_page_seconds: float = 120.0
    vlm_startup_seconds: float = 30.0
    vlm_request_seconds: float = 240.0
    vlm_overhead_seconds: float = 60.0
    vlm_min_available_bytes: int = 2 * 1024**3
    cleanup_wait_seconds: float = 5.0
    ram_sample_seconds: float = 1.0
    gpu_poll_seconds: float = 2.0
    gpu_query_timeout_seconds: float = 3.0
    # shortcut: unmeasured laptop guards, calibrate with the separately approved RT-22 corpus.
    active_output_bytes: int = 2 * 1024**3
    min_free_disk_bytes: int = 1024**3
    max_page_text_bytes: int = 1024**2
    max_page_words: int = 100_000
    max_artifact_bytes: int = 16 * 1024**2
    native_memory_bytes: int = 6 * 1024**3
    inspection_timeout_seconds: float = 300.0
    helper_timeout_seconds: float = 300.0
    log_file_bytes: int = 10 * 1024**2
    log_backups: int = 5
    log_max_age_days: int = 7
    log_event_bytes: int = 4096
    log_queue_events: int = 512
    log_shutdown_seconds: float = 2.0

    def __post_init__(self) -> None:
        for name in ("max_upload_bytes", "max_pixels", "max_batch_submissions", "max_workset_pages", "max_spoolers"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_workset_pages > MAX_WORKSET_PAGES:
            raise ValueError("execution windows must contain at most 20 pages")
        if self.max_batch_submissions > MAX_BATCH_SUBMISSIONS or self.max_spoolers > MAX_SPOOLERS:
            raise ValueError("runtime admission exceeds the approved submission/spooler caps")
        if type(self.debug_retain_failed_spool) is not bool:
            raise ValueError("debug_retain_failed_spool must be a boolean")
        for name in (
            "worker_poll_seconds", "preparation_timeout_seconds", "ocr_startup_seconds", "ocr_page_seconds",
            "vlm_startup_seconds", "vlm_request_seconds", "vlm_overhead_seconds", "cleanup_wait_seconds",
            "ram_sample_seconds", "gpu_poll_seconds", "gpu_query_timeout_seconds",
            "inspection_timeout_seconds", "helper_timeout_seconds", "log_shutdown_seconds",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.vlm_startup_seconds < 30 or self.vlm_request_seconds < 120:
            raise ValueError("VLM startup/request budgets cannot shorten the existing 30s/120s limits")
        if self.cleanup_wait_seconds > 5 or not 1 <= self.ram_sample_seconds <= 2:
            raise ValueError("cleanup waits must be at most 5s; RAM samples must be 1–2s apart")
        if self.gpu_poll_seconds < 2 or self.gpu_query_timeout_seconds > 3:
            raise ValueError("GPU polls must be at least 2s apart with at most a 3s query deadline")
        if not math.isfinite(self.ocr_timeout_seconds(self.max_workset_pages)) or not math.isfinite(self.vlm_timeout_seconds(self.max_workset_pages)):
            raise ValueError("execution-window deadlines must remain finite")
        for name in (
            "active_output_bytes", "min_free_disk_bytes", "max_page_text_bytes", "max_page_words",
            "max_artifact_bytes", "native_memory_bytes", "vlm_min_available_bytes", "log_file_bytes", "log_backups",
            "log_max_age_days", "log_event_bytes", "log_queue_events",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.log_event_bytes > 4096 or self.log_queue_events > 512 or self.log_shutdown_seconds > 2:
            raise ValueError("logging exceeds the approved record/queue/shutdown bounds")
        if self.log_file_bytes < self.log_event_bytes or self.log_backups > 5 or self.log_max_age_days > 7:
            raise ValueError("logging retention exceeds the approved bounds")

    @property
    def max_request_bytes(self) -> int:
        return self.max_upload_bytes + MULTIPART_OVERHEAD_BYTES

    @property
    def spool_capacity_bytes(self) -> int:
        return MAX_SPOOL_RAW_FILES * self.max_upload_bytes + self.max_spoolers * MULTIPART_OVERHEAD_BYTES

    def ocr_timeout_seconds(self, pages: int) -> float:
        if type(pages) is not int or not 0 <= pages <= self.max_workset_pages:
            raise ValueError("OCR pages must fit the workset cap")
        return self.ocr_startup_seconds + self.ocr_page_seconds * pages

    def vlm_timeout_seconds(self, pages: int) -> float:
        if type(pages) is not int or not 0 <= pages <= self.max_workset_pages:
            raise ValueError("VLM pages must fit the workset cap")
        return self.vlm_startup_seconds + self.vlm_request_seconds * pages + self.vlm_overhead_seconds

    @property
    def demo(self) -> bool:
        return self.profile == "demo"


def load_settings() -> Settings:
    profile = os.getenv("SMRITI_PROFILE", "local-gpu")
    if profile not in VALID_PROFILES:
        raise ValueError(f"unknown SMRITI_PROFILE: {profile!r}")
    debug_retention = os.getenv("DEBUG_RETAIN_FAILED_SPOOL", "0")
    if debug_retention not in ("0", "1"):
        raise ValueError("DEBUG_RETAIN_FAILED_SPOOL must be exactly 0 or 1")

    return Settings(
        profile=profile,
        db_path=Path(os.getenv("SMRITI_DB_PATH", str(BASE_DIR / "data" / "smriti.db"))),
        upload_dir=Path(os.getenv("SMRITI_UPLOAD_DIR", str(BASE_DIR / "data" / "uploads"))),
        spool_dir=Path(os.getenv("SMRITI_SPOOL_DIR", str(BASE_DIR / "data" / "spool"))),
        log_dir=Path(os.getenv("SMRITI_LOG_DIR", str(BASE_DIR / "data" / "logs"))),
        # The demo profile never egresses, whatever the environment says.
        resolver_enabled=False if profile == "demo" else _bool("SMRITI_RESOLVER_ENABLED", False),
        resolver_provider=os.getenv("SMRITI_RESOLVER_PROVIDER", "local_rules"),
        ocr_model=os.getenv("SMRITI_OCR_MODEL", "PP-OCRv5_mobile"),
        ocr_det_model=os.getenv("SMRITI_OCR_DET_MODEL", "PP-OCRv5_mobile_det"),
        ocr_rec_model=os.getenv("SMRITI_OCR_REC_MODEL", "en_PP-OCRv5_mobile_rec"),
        worker_enabled=_bool("SMRITI_WORKER_ENABLED", True),
        worker_poll_seconds=float(os.getenv("SMRITI_WORKER_POLL_SECONDS", "2")),
        session_ttl_days=int(os.getenv("SMRITI_SESSION_TTL_DAYS", "7")),
        login_attempts=int(os.getenv("SMRITI_LOGIN_ATTEMPTS", "5")),
        login_window_minutes=int(os.getenv("SMRITI_LOGIN_WINDOW_MINUTES", "5")),
        quality_blur=float(os.getenv("SMRITI_QUALITY_BLUR", "100")),
        quality_min_short_edge=int(os.getenv("SMRITI_QUALITY_MIN_SHORT_EDGE", "1000")),
        quality_max_aspect=float(os.getenv("SMRITI_QUALITY_MAX_ASPECT", "4.0")),
        quality_min_ink_ratio=float(os.getenv("SMRITI_QUALITY_MIN_INK", "0.0005")),
        upscale_long_edge=int(os.getenv("SMRITI_UPSCALE_LONG_EDGE", "1500")),
        max_upload_bytes=int(os.getenv("SMRITI_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
        max_pixels=int(os.getenv("SMRITI_MAX_PIXELS", "50000000")),
        hwr_margin=float(os.getenv("SMRITI_HWR_MARGIN", "0.15")),
        vlm_enabled=_bool("SMRITI_VLM_ENABLED", True),
        max_batch_submissions=int(os.getenv("SMRITI_MAX_BATCH_SUBMISSIONS", "10")),
        max_workset_pages=int(os.getenv("SMRITI_MAX_WORKSET_PAGES", "20")),
        max_spoolers=int(os.getenv("SMRITI_MAX_SPOOLERS", "2")),
        debug_retain_failed_spool=debug_retention == "1",
        preparation_timeout_seconds=float(os.getenv("SMRITI_PREPARATION_TIMEOUT_SECONDS", "300")),
        ocr_startup_seconds=float(os.getenv("SMRITI_OCR_STARTUP_SECONDS", "60")),
        ocr_page_seconds=float(os.getenv("SMRITI_OCR_PAGE_SECONDS", "120")),
        vlm_startup_seconds=float(os.getenv("SMRITI_VLM_STARTUP_SECONDS", "30")),
        vlm_request_seconds=float(os.getenv("SMRITI_VLM_REQUEST_SECONDS", "240")),
        vlm_overhead_seconds=float(os.getenv("SMRITI_VLM_OVERHEAD_SECONDS", "60")),
        vlm_min_available_bytes=int(os.getenv("SMRITI_VLM_MIN_AVAILABLE_BYTES", str(2 * 1024**3))),
        cleanup_wait_seconds=float(os.getenv("SMRITI_CLEANUP_WAIT_SECONDS", "5")),
        ram_sample_seconds=float(os.getenv("SMRITI_RAM_SAMPLE_SECONDS", "1")),
        gpu_poll_seconds=float(os.getenv("SMRITI_GPU_POLL_SECONDS", "2")),
        gpu_query_timeout_seconds=float(os.getenv("SMRITI_GPU_QUERY_TIMEOUT_SECONDS", "3")),
        active_output_bytes=int(os.getenv("SMRITI_ACTIVE_OUTPUT_BYTES", str(2 * 1024**3))),
        min_free_disk_bytes=int(os.getenv("SMRITI_MIN_FREE_DISK_BYTES", str(1024**3))),
        max_page_text_bytes=int(os.getenv("SMRITI_MAX_PAGE_TEXT_BYTES", str(1024**2))),
        max_page_words=int(os.getenv("SMRITI_MAX_PAGE_WORDS", "100000")),
        max_artifact_bytes=int(os.getenv("SMRITI_MAX_ARTIFACT_BYTES", str(16 * 1024**2))),
        native_memory_bytes=int(os.getenv("SMRITI_NATIVE_MEMORY_BYTES", str(6 * 1024**3))),
        inspection_timeout_seconds=float(os.getenv("SMRITI_INSPECTION_TIMEOUT_SECONDS", "300")),
        helper_timeout_seconds=float(os.getenv("SMRITI_HELPER_TIMEOUT_SECONDS", "300")),
        log_file_bytes=int(os.getenv("SMRITI_LOG_FILE_BYTES", str(10 * 1024**2))),
        log_backups=int(os.getenv("SMRITI_LOG_BACKUPS", "5")),
        log_max_age_days=int(os.getenv("SMRITI_LOG_MAX_AGE_DAYS", "7")),
        log_event_bytes=int(os.getenv("SMRITI_LOG_EVENT_BYTES", "4096")),
        log_queue_events=int(os.getenv("SMRITI_LOG_QUEUE_EVENTS", "512")),
        log_shutdown_seconds=float(os.getenv("SMRITI_LOG_SHUTDOWN_SECONDS", "2")),
    )
