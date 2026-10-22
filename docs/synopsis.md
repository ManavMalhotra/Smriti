# Project Synopsis

**Title:** Smriti — Source-Linked Longitudinal Patient Records from Printed Medical Documents

**Domain:** Health informatics · document intelligence · human-in-the-loop systems

**Duration:** 16 weeks · **Team:** 3 members · **Type:** Research prototype (not a medical device)

---

## 1. Abstract

An Indian patient's medical history is scattered across paper: laboratory reports from three different labs, prescriptions from two doctors, pharmacy slips, and the occasional discharge summary. Nothing links them. The patient cannot answer "is my creatinine getting worse?" and a doctor meeting them for the first time has no basis for that question either.

Existing tools digitise documents. Digitisation is not the hard part any more. The hard parts are (a) proving that a number came from where the system says it came from, (b) knowing when a value is wrong rather than merely uncertain, and (c) measuring any of this on real Indian documents instead of a clean benchmark.

Smriti builds a longitudinal timeline from the documents a patient already owns. Every charted value carries a document, page, and bounding box, recoverable in one click. Printed values pass five arithmetic checks and per-analyte plausibility bounds before they can be charted; values that fail are excluded and shown as excluded. Doctor instructions are extracted into four timing classes and anchored on the document's own dates. Handwritten prescriptions are supported only as assisted transcription: the system proposes, a human confirms every field, and no numeric laboratory value is ever taken from handwriting.

The system runs entirely on local hardware. No document image leaves the device; an optional remote resolver receives only a typed projection of already-extracted values, with no free text, dates, or identifiers.

The headline claim is measured, not asserted: end-to-end correctness of value, field, and unit on 40 real printed documents, with pre-registered thresholds and confidence intervals.

## 2. Problem statement

A patient accumulates 20–60 paper documents over a decade. Three consequences follow:

1. **No longitudinal view.** Trends cannot be seen because the data is not comparable across labs, units, and formats.
2. **No provenance.** When a digitised value is wrong, the patient cannot tell, and neither can the doctor, because there is nothing to check it against.
3. **No trustworthy automation.** Handwriting and poor scans produce confident wrong values, which is worse than no value at all in a medical context.

The gap is not capture. The gap is **trust and measurement**.

## 3. Objectives

| # | Objective | Measured by |
|---|---|---|
| O1 | Extract 30 analytes from printed Indian laboratory reports with correct value, field, and unit | End-to-end ≥ 0.85; field F1 ≥ 0.90 on 40 documents |
| O2 | Guarantee provenance for every charted value | 100 % of rendered values resolve to a document, page, and box |
| O3 | Prevent implausible values from ever being charted | Gate recall ≥ 0.80; zero rejected values charted |
| O4 | Extract follow-up directives with correct timing semantics | Span F1 ≥ 0.75; timing ≥ 0.80; date exact ≥ 0.70 on 150 notes |
| O5 | Support handwritten prescriptions without ever asserting a value | Zero auto-accepted handwritten fields, by construction |
| O6 | Reproduce every reported number offline | Harness regenerates all results from a frozen truth set and cache |

## 4. Scope

**In scope:** printed lab reports, printed prescriptions, pharmacy printouts; 30 analytes across CBC, LFT, KFT, lipid profile, HbA1c, TSH; bounding-box provenance; four directive timing classes; one-page dashboard in patient and clinician modes; PIN-protected sharing with audit; assisted handwriting transcription.

**Out of scope:** imaging, cultures, serology, histopathology; diagnosis or treatment advice; drug interaction checking; guideline-driven scheduling; ABDM/FHIR export; multi-tenancy; chatbots; any cloud processing of document images.

## 5. Methodology

```
upload → quality gate → perspective/deskew → OCR → layout assembly
       → rules resolution → [typed projection → resolver] → normalisation
       → arithmetic + plausibility + swing gates
       → directives + medications → summary payload → dashboard
```

Design decisions worth naming:

- **Rules before models.** Three independent signals resolve most table rows deterministically. The remote resolver is a last resort and must prove its value or be deleted.
- **Projection, not redaction.** An allowlist schema cannot represent a name; a redaction pass cannot prove it removed every one.
- **Rejection over guessing.** Missing gate input is `skipped`, never `pass`.
- **Anchored dates only.** The anchor is the collection date, else the document date, else unknown. The current date is not a valid anchor and the type system does not permit it.

## 6. Evaluation design

| Element | Choice |
|---|---|
| Corpus | 40 real printed documents; 150 annotated notes; 25 handwritten pages if the week-8 gate is green |
| Truth set | Frozen CSV, versioned, hashed; corrections require a version bump |
| Metrics | Field F1, CER, end-to-end, material errors, gate recall, risk–coverage, directive span F1, timing accuracy, date exactness, Cohen's kappa |
| Intervals | 95 % bootstrap, 1000 resamples, recorded seed |
| Protocol | Thresholds pre-registered in SRS §4.1 before any run |
| Reproducibility | Every number regenerated offline from cache |

## 7. Tools and environment

Python 3.11, FastAPI, Pydantic v2, SQLAlchemy, SQLite; PaddleOCR PP-OCRv6_small on CPU; OpenCV, PyMuPDF; React (JS), Vite, Tailwind, Recharts. Development on Windows 11, Ryzen 5 5600H, 8 GB RAM, no GPU requirement.

## 8. Timeline

| Weeks | Phase | Gate |
|---|---|---|
| 1–2 | Requirements, ethics, contract, probes | Ethics submitted; contract locked |
| 3–4 | Ingestion, OCR baseline, 40 documents collected | CER measured |
| 5–6 | Extraction, review loop, first evaluation | One document end to end |
| 7–8 | Safety gates, normalisation, resolver and handwriting gates | ≥ 0.85 end-to-end |
| 9–10 | Handwriting assist (conditional), medications | No handwritten `auto` |
| 11–12 | Directives, dashboard, numbers frozen | All numbers reproducible |
| 13–14 | Usability, demo, video | Demo runs offline |
| 15–16 | Report, viva, submission | Submitted |

## 9. Expected outcomes

1. A working prototype covering the pipeline end to end on local hardware.
2. A measured end-to-end accuracy figure with confidence intervals on real Indian documents.
3. A reusable annotation protocol and truth set for Indian lab report layouts.
4. A documented negative or positive result on whether a remote resolver earns its place.
5. A failure taxonomy for handwriting on Indian prescriptions.

## 10. Limitations, stated up front

- 40 documents is a small corpus; confidence intervals will be wide and are reported, not hidden.
- Drug lexicon coverage is expected to be 30–50 % of commercial Indian brands; this caps medication extraction and is reported as a limitation.
- Handwriting support may be cut at week 8 by design, and the reason will be recorded either way.
- The system is not a medical device, does not diagnose, and does not advise.

## 11. References

1. Digital Personal Data Protection Act, 2023, and DPDP Rules, 2025 (notified November 2025).
2. Ministry of Health and Family Welfare, *Telemedicine Practice Guidelines*, 2020.
3. CDSCO, *Guidance on Medical Devices Software*, CDSCO/MD/GD/MDSW/01/2026, 21 July 2026.
4. Ayushman Bharat Digital Mission, HealthDocumentRecord profile.
5. PaddleOCR PP-OCRv6 model documentation and benchmark tables.
6. ISO/IEC/IEEE 29148:2018, Requirements engineering.
