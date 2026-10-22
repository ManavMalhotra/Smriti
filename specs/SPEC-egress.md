# SPEC-egress

| | |
|---|---|
| Module | `egress` |
| Status | Draft for review |
| Depends on | `extraction` |
| SRS | FR-RED-01…08 (rewritten), new FR-EGR, SI-04, SI-05, NFR-11, NFR-16 |
| Files | `smriti/egress.py`, `smriti/projection.py`, `api/routers/documents.py` |

## 1. Objective

Shrink the human review queue by asking a model to resolve field-assembly ambiguity, **without letting any document, image, identifier, or free text leave the device.**

The unit of egress is not a page. It is a typed projection: a de-identified table of vocabulary tokens and numbers, constructed from an allowlist schema. A person's name cannot be transmitted because the schema has no field that could hold one. This is stricter than SRS v1.0, which permits redacted *images*; stricter is allowed, but §3.5.2 and FR-EXT-05 must be rewritten in v1.1 so the documents do not describe two different systems.

This module is **deletable by design.** If it does not earn its keep (§5), it is removed and the project gets simpler.

## 2. Commands

```bash
pytest tests/test_egress.py tests/test_projection.py -q
python -m smriti.egress --document <id> --dry-run   # print payload, send nothing
python -m smriti.egress --document <id> --send      # requires consent row + flag on
python -m smriti.egress --audit --since 2026-10-01  # list what left the device
```

`--dry-run` is the default mode and the only mode available in `SMRITI_PROFILE=demo`.

## 3. Structure

```
smriti/
  projection.py  FieldCandidate[] → Projection (allowlist), and response validation
  egress.py      policy gate → provider adapter → audit row → cache
data/vocab/
  analytes.txt   the 30 canonical names + synonyms
  units.txt      accepted unit strings
  flags.txt      H, L, N, blank
  table_words.txt  header and footer tokens observed in real documents
```

Provider adapters sit behind one interface, `Resolver.resolve(projection) -> Mapping[roi_id, analyte_id]`:

| Adapter | Use |
|---|---|
| `LocalRules` | default; no network; always available |
| `Null` | profile=demo; returns nothing, records nothing |
| `Sarvam` | Indian-hosted, paid |
| `Gemini` | free tier; only on synthetic corpus |
| `OpenAICompatible` | self-hosted open weights, zero egress |

## 4. Code style

- `Projection` is a frozen Pydantic model. Construction is the only way to build a payload; there is no `dict` path to the HTTP client.
- Every outbound string is either a member of `data/vocab/*.txt` or matches `^-?\d+(\.\d+)?$`. Enforced at construction and asserted again immediately before send.
- The provider receives `projection.model_dump_json()` and nothing else. No headers carrying patient IDs, no query strings, no filenames.
- One audit row per attempt, including refusals: `{document_id, payload_sha256, model_id, prompt_version, outcome, reason, ts}`.
- Timeout 30 s, at most one retry (NFR-11), and a defined terminal state `cloud_unavailable`.

### The payload

```json
{
  "schema": "smriti-projection/1",
  "task": "assign_each_number_to_one_analyte",
  "tables": [{
    "rows": [
      {"roi":"r1c1","tokens":["Hemoglobin"],      "numbers":[]},
      {"roi":"r1c2","tokens":[],                  "numbers":["13.2"]},
      {"roi":"r1c3","tokens":["g/dL"],            "numbers":[]},
      {"roi":"r1c4","tokens":[],                  "numbers":["13.0","17.0"]}
    ]
  }]
}
```

Present: vocab tokens, numbers, row ids, schema version.
Absent: name, age, sex, UHID, MRN, phone, address, dates, facility, doctor, filename, image, free text, cross-document linkage.

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Unit | `test_projection_rejects_free_text` — property test over arbitrary strings | allowlist is exhaustive, not aspirational |
| Unit | `test_number_regex_only` | no identifier can pass as a number |
| Invariant | `test_no_image_bytes_ever` — monkeypatch the HTTP client; any non-JSON or binary body fails | SI-04 |
| Invariant | `test_no_consent_no_egress` | SI-05 |
| Invariant | `test_demo_profile_never_sends` | D-05 |
| Invariant | `test_egress_off_by_default` | FR-RED-08 |
| Integration | response with an unknown `roi_id` or an out-of-vocab analyte is discarded | never trust the return path |
| Experiment | 40 docs, flag off vs on, review-queue length compared | **≥ 30% shrink or delete the module** |

The last row is the module's reason to exist. It is an acceptance test, not a nice-to-have.

## 6. Boundaries

- **Never** transmit image bytes, base64 image data, or a URL that resolves to a document (SI-04).
- **Never** transmit free text, dates, names, or any field outside the projection schema.
- **Never** send without a `consent` row for that document (SI-05) — consent is checked per document, not per user.
- **Never** send in `SMRITI_PROFILE=demo`, regardless of flags.
- **Never** send by default; the flag is off and must be turned on per document.
- **Never** trust the response: validate `roi_id ∈ request`, analyte ∈ vocabulary, else discard.
- **Never** log payload content — only its hash (NFR-07).

## 7. FR traceability

| SRS | Disposition |
|---|---|
| FR-RED-01 (crop header/footer before egress) | **Deleted** — no image egress; nothing to crop |
| FR-RED-02 (regex identifiers, black-fill) | **Deleted** — projection has no text field to redact |
| FR-RED-03 (strip EXIF) | **Moved** to `intake`; executes before storage |
| FR-RED-04 (re-OCR redacted image) | **Deleted** — superseded by allowlist construction |
| FR-RED-05 (manual black-boxing of handwriting) | **Deleted** — no handwritten page egresses |
| FR-RED-06 (redaction + egress rows) | **Rewritten** — one `egress` row per attempt with `payload_sha256` |
| FR-RED-07 (never transmit raw image) | **Strengthened** — never transmit any image |
| FR-RED-08 (local-only default) | Unchanged; `test_egress_off_by_default` |
| new FR-EGR-01 | Projection schema enforced at construction |
| new FR-EGR-02 | Consent row required per document |
| new FR-EGR-03 | Queue shrink ≥ 30% or module deleted |

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | Does the rule resolver already resolve enough that `egress` fails its own gate? | Week 8 | Delete the module — that is a legitimate result, and it shortens the report |
| 2 | Sarvam vs self-hosted open weights | Week 10, only if the module survives | Self-hosted wins on egress; record it as an ADR |
| 3 | Does a projection need the *order* of rows to reason about adjacency? | Week 8 | Row ids carry order; if that leaks structure, drop to unordered sets and accept lower accuracy |
