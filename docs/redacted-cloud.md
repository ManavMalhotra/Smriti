# Optional redacted cloud extraction

Cloud review is optional. A server-side Gemini key and an explicit per-upload
request are both required; the owner then finalizes masks before any page is sent.
The demo never sends data.

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-cloud.txt
$env:GEMINI_API_KEY = "your-server-side-key"
# Optional override; the default engine is gemini-3.8-flash-high with thinking level high.
$env:GEMINI_MODEL_ID = "gemini-3.8-flash"
```

Restart the service after changing configuration. Never put the key in the web app.
Existing processed documents are not automatically reprocessed.

## Consent and privacy

- Local OCR/text-layer extraction runs first. Uploads stay local unless the owner
  selects optional Gemini review; only those explicitly requested uploads pause.
- `GET /api/documents/{id}/redaction-preview?offset=0` returns at most 20 stored,
  unmodified local JPEG previews, editable full-page mask proposals and hashes.
  Responses use `Cache-Control: no-store`.
- Intake and Queue display a native keyboard-accessible consent dialog. Review
  every page; drag a mask or enter normalized coordinates with the keyboard.
- `POST /api/documents/{id}/consent` accepts strict boolean `approved` and the
  finalized `extra_redaction_boxes`, keyed by source page. Masks are
  `[x,y,width,height,label,id]` in 0–1000 and can be removed, edited or added.
- Only the saved approval and pages with finalized masks burned into fresh images
  are sent. The source PDFs,
  original page images, OCR text and patient-context strings are never sent.
- Previews use black pixel masks and freshly encoded RGB JPEGs without EXIF,
  ICC profiles or comments. The original local image remains unchanged.
- SDK/model/schema failures retain local readings. Interrupted cloud calls are
  not automatically retried. Egress records contain payload hashes, not images.
- Previews are quota-accounted in the existing private candidate store and removed
  by its existing cleanup. Consent metadata cascades when the document is erased.

Automatic PII detection is heuristic, not a de-identification guarantee. Review is
mandatory, especially for handwriting, addresses and non-Latin names. Consent
authorizes Google to receive the masked images; it cannot revoke a completed send.
Check the provider's applicable data-retention terms before enabling cloud use.

Pending consent holds the current frozen FIFO batch only when that upload explicitly
requested cloud review. Ordinary uploads continue through local processing and publish.

## Clinical data and dashboard

Cloud JSON is validated and converted to existing `ExtractedField` candidates.
All new observations remain review-required. Existing biological bounds and the
handwritten-numeric prohibition remain enforced. Event/report dates, organ systems,
regimens and all duplicate-page anchors are stored as additive clinical metadata
in schema v13; transactional publication is retained.

The summary keeps its previous keys and adds `clinical_snapshot`, `organ_groups`,
`medications_timeline` and `master_timeline`. Result series preserve units and each
reading's own reference interval. No reference range is invented. Future-year
comparative lab repairs retain the original date and a review warning.

The dashboard exposes safety findings, organ filters, normal-range bands,
circle/triangle point shapes, conditional medicines, historical events and a
source drawer. Doctor mode adds clinical provenance rather than inventing new
medical interpretations. Old prescriptions are not proof of current medication
use; earlier/stopped prescriptions are separate from the newest/ongoing ones.

## Standardized Clinical Summary

Smriti synthesizes the longitudinal `StandardizedClinicalSummary` locally. Gemini
summary synthesis is disabled because that route previously sent raw OCR text;
document-level cloud review uses approved masked page images instead.
- **Strict Clinical Invariants**:
  1. **Hypertension Verification**: Explicitly identifies whether hypertension is actively diagnosed or documented negative across admissions.
  2. **Hallucination & Boilerplate Removal**: Institutional letterhead boilerplate (e.g. "Trust of Generations Since June", addresses, registration lines) is stripped to eliminate timeline hallucinations.
  3. **Current Medications Date Bounding**: Active ongoing medications are strictly filtered to the patient's latest clinical report date.
  4. **Analyte Exclusion**: Lab test analytes mistakenly captured as drugs (e.g. `Triglycerides 204 mg`, `Protein`, `Globulin`, `ESTIMATED`) are filtered out via `is_valid_medication_name()`.
  5. **Caching**: Results are stored in the existing `stage_artifact` table under `stage='standardized_clinical_summary'`, ensuring zero database schema churn.

## Checks

```powershell
.venv\Scripts\python.exe -m pytest
cd web
npm test
npm run build
```

The cloud tests require `requirements-cloud.txt` and mock Gemini using synthetic
pages. They cover pixel masks, metadata stripping, consent decline/approval,
date/regimen mapping, duplicate anchors, source verification and axe checks.
No live medical documents or paid cloud calls are part of these tests.
