"""Synthetic documents for offline intake tests."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

_FONT_PATH = Path("C:/Windows/Fonts/arial.ttf")
_FONT = ImageFont.truetype(str(_FONT_PATH), 28) if _FONT_PATH.exists() else ImageFont.load_default()


def text_image(
    width: int = 1200,
    height: int = 1600,
    lines: int = 24,
    font_size: int = 28,
    margin: int = 80,
    line_gap: int = 55,
) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = (
        ImageFont.truetype(str(_FONT_PATH), font_size)
        if _FONT_PATH.exists()
        else _FONT
    )
    for index in range(lines):
        y = margin + index * line_gap
        if y > height - margin:
            break
        draw.text(
            (margin, y),
            f"HbA1c 8.9 %   Glucose 126 mg/dL   Report {index + 1}",
            fill="black",
            font=font,
        )
    return image


def handwritten_image(width: int = 1200, height: int = 1600, rows: int = 18) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    rng = np.random.default_rng(4)
    for row in range(rows):
        baseline = 90 + row * 75
        points = [
            (x, baseline + 18 * np.sin(x / 60 + row) + rng.normal(0, 3))
            for x in range(70, width - 120, 12)
        ]
        draw.line(points, fill="black", width=int(rng.integers(3, 7)), joint="curve")
    return image


def skewed_image(image: Image.Image, degrees: float = 5.0) -> Image.Image:
    return image.rotate(degrees, expand=True, fillcolor="white")


def shadowed_image(image: Image.Image) -> Image.Image:
    array = np.asarray(image).astype(np.float32)
    gradient = np.linspace(0.55, 1.0, array.shape[1])[None, :, None]
    return Image.fromarray(np.clip(array * gradient, 0, 255).astype(np.uint8))


def blurred_image(image: Image.Image, radius: float = 8.0) -> Image.Image:
    return image.filter(ImageFilter.GaussianBlur(radius=radius))


def jpeg_bytes(image: Image.Image, quality: int = 90, exif: Image.Exif | None = None) -> bytes:
    buffer = io.BytesIO()
    options = {"exif": exif} if exif is not None else {}
    image.save(buffer, format="JPEG", quality=quality, **options)
    return buffer.getvalue()


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def exif_gps_jpeg(image: Image.Image) -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees
    exif[0x010F] = "TestCam"
    exif[0x0110] = "TestModel"
    exif[0x8825] = {
        1: "N",
        2: (12.0, 34.0, 56.0),
        3: "E",
        4: (77.0, 1.0, 0.0),
    }
    return jpeg_bytes(image, exif=exif)


def make_patient(client) -> str:
    response = client.post("/api/patients", json={"alias": "P-01"})
    assert response.status_code == 201
    return response.json()["id"]


def upload(
    client,
    patient_id: str,
    data: bytes,
    filename: str = "page.jpg",
    content_type: str = "image/jpeg",
    **fields,
):
    form = {
        "patient_id": patient_id,
        "doc_type": "lab_report",
        "consent_scope": "local",
    }
    form.update(fields)
    return client.post(
        "/api/documents",
        data=form,
        files={"file": (filename, data, content_type)},
    )


def pdf_bytes(pages: int = 3) -> bytes:
    document = pymupdf.open()
    for page_number in range(pages):
        page = document.new_page(width=595, height=842)
        page.draw_rect(pymupdf.Rect(50, 50, 545, 792), color=(0, 0, 0), width=1)
        page.insert_text((80, 80), f"PAGE {page_number + 1}", fontsize=24)
        for line in range(8 + page_number):
            page.insert_text(
                (80, 120 + line * 30),
                f"HbA1c 8.9 %   Glucose 126 mg/dL   Report {page_number + 1}",
                fontsize=12,
            )
    data = document.tobytes()
    document.close()
    return data
