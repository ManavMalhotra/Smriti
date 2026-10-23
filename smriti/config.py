"""Configuration is read once, here. No other module reads the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
VALID_PROFILES = ("local-gpu", "demo")


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
    max_pages: int = 20
    max_pixels: int = 50_000_000
    hwr_margin: float = 0.15
    share_ttl_minutes: int = 30

    @property
    def demo(self) -> bool:
        return self.profile == "demo"


def load_settings() -> Settings:
    profile = os.getenv("SMRITI_PROFILE", "local-gpu")
    if profile not in VALID_PROFILES:
        raise ValueError(f"unknown SMRITI_PROFILE: {profile!r}")

    return Settings(
        profile=profile,
        db_path=Path(os.getenv("SMRITI_DB_PATH", str(BASE_DIR / "data" / "smriti.db"))),
        upload_dir=Path(os.getenv("SMRITI_UPLOAD_DIR", str(BASE_DIR / "data" / "uploads"))),
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
        max_pages=int(os.getenv("SMRITI_MAX_PAGES", "20")),
        max_pixels=int(os.getenv("SMRITI_MAX_PIXELS", "50000000")),
        hwr_margin=float(os.getenv("SMRITI_HWR_MARGIN", "0.15")),
    )
