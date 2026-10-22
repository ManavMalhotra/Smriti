# Ethics and Consent

Status: draft for institutional ethics committee submission.
This document is the project's own protocol, not legal advice. The committee's requirements override anything here.

---

## 1. Purpose

Smriti processes real medical documents belonging to consenting individuals. That creates three obligations this protocol must satisfy:

1. Participants understand what is collected and what is not.
2. Consent is specific, revocable, and recorded per document.
3. Data cannot leave the participant's device in a form that identifies them.

## 2. What is collected

| Category | Content | Necessity |
|---|---|---|
| Document images | Scans or photographs of printed lab reports and prescriptions | Required for extraction |
| Extracted values | Analyte, value, unit, printed range, flag, bounding box | The research output |
| Document dates | Collection date and document date, if printed | Required for anchoring directives |
| Patient alias | A pseudonym chosen by the operator | Display only; never a real name |
| Consent records | Scope, version, timestamp, revocation | Proof of permission |
| Audit records | Who did what, when | Accountability |
| Optional patient reports | "I stopped this medicine" statements | Feature under evaluation |

**Never collected:** Aadhaar, phone number, address, insurance identifiers, photographs of the participant, or any document the participant has not explicitly offered.

## 3. Consent model

Consent is:

- **Written**, on the form in §9.
- **Per document**, recorded in the `consent` table before processing begins.
- **Specific**, naming the purposes in §4.
- **Revocable** at any time, without justification, with deletion following §7.
- **Not bundled** with any other agreement.

A document with no consent row is never queued, never processed, and never egressed (`FR-ING-09`, `FR-EGR-03`).

### Participants

- Adults (18+), competent to consent.
- Document owners only. A participant may not consent on behalf of a family member whose name appears on a shared report.
- Recruitment is voluntary. No incentive is offered, and no academic penalty attaches to refusal.

### Pressure to consider

Documents are often a family's, and a friend or relative asking is still a request. The information sheet states plainly: *you may decline, and nothing changes between us.* The operator does not collect from anyone who hesitates.

## 4. Data flow and the trust boundary

```
document image ──▶ local machine only ──▶ never transmitted
OCR text       ──▶ local machine only
typed projection ──▶ optional remote resolver ──▶ numbers + vocabulary tokens only
```

The remote path is **off by default**. When enabled, it sends a schema-bounded projection containing no name, no date, no identifier, no free text, no image, and no link to other documents. The form discloses this in §9.3, as required by OR-02.

Participants may refuse the remote path and still take part. Refusal disables that path for their documents only.

## 5. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Device loss or theft exposes documents | Low | High | Full-disk encryption; device never left unattended in public; uploads in one directory, deletable in one action |
| Re-identification from released annotations | Low | High | No images released; aliases only; direct identifiers removed manually before release |
| Participant distress on seeing abnormal values | Medium | Medium | Intended-use banner; no diagnosis; no colour-coded "danger"; offer to stop at any point |
| Coercion by a family member to share documents | Low | Medium | Voluntary participation stated in writing; withdrawal without explanation |
| Accidental inclusion of a third party's data (a family report) | Medium | Medium | Intake check: if another person's name appears, the document is not accepted |
| Remote resolver receives more than intended | Low | High | Projection schema enforced at construction and in CI; no free-text field exists; one test fails on any image byte |
| Operator error during annotation | Medium | Low | Double annotation of 30 notes; kappa ≥ 0.70 before the remainder |
| Data retained after the project ends | Medium | Medium | Deletion protocol in §7, executed at submission |

## 6. De-identification for corpus release and demo

Released artifacts are text and figures only. No document images are released, ever.

Before release:

1. Remove names, hospital names, doctor names, registration numbers, UHIDs, phone numbers, addresses, and dates of birth.
2. Replace each with a stable placeholder (`PERSON_1`, `FACILITY_1`) so structure survives.
3. Re-read the artifact and confirm no residual identifier.
4. Record the release hash.

**This project does not claim anonymisation of documents.** It claims that documents are never released and never transmitted. The distinction matters and is stated in the report.

## 7. Retention and deletion

- Documents are retained only for the project duration.
- A participant may request deletion at any time. `DELETE /api/patients/{id}` removes database rows and files, and writes one audit row recording that deletion occurred (not what was deleted).
- At submission, all real documents and derived artifacts are deleted from every device, and the deletion is recorded in the project log.
- Backups are included in deletion. A backup that survives is a data breach waiting to happen.

## 8. Incident handling

If a document is exposed, transmitted, or lost:

1. Stop processing.
2. Record what was exposed, to whom, and when.
3. Inform the participant in plain language within 72 hours.
4. Inform the guide and the ethics committee.
5. Fix the cause before resuming; do not resume on a promise.

---

## 9. Participant information sheet and consent form

### 9.1 Information sheet

> **Project:** Smriti — a prototype that organises paper medical records.
>
> **What we are asking.** We would like to photograph or scan some of your printed medical documents — laboratory reports and prescriptions — and use them to test whether our software can read them accurately.
>
> **What we will do with them.** The documents stay on the researcher's laptop. Software reads the text and builds a timeline. We do not send the document anywhere, and we do not post it online.
>
> **What leaves the laptop.** Nothing that identifies you. If the optional remote service is enabled, only a table of numbers and standard medical terms is sent — no name, no date, no address, no image. You may refuse this and still take part.
>
> **What we will not do.** We will not diagnose you, advise treatment, or tell you what your results mean. This is a research prototype, not a medical device.
>
> **Your choices.** You may say no. You may withdraw at any time, for any reason or none, and ask us to delete everything. Withdrawal does not affect your relationship with the researchers or the institution.
>
> **Risks.** The main risk is a privacy breach if the laptop is lost. It is encrypted, and the documents are kept in one folder that can be deleted in one step.
>
> **Contact.** [Guide name, department, institutional email]

### 9.2 Consent form

| # | Statement | Initial |
|---|---|---|
| 1 | I have read the information sheet, or it has been read to me, and I understand it. | |
| 2 | I am 18 or older and I am the owner of the documents I am providing. | |
| 3 | I agree that my printed medical documents may be photographed and processed for this project. | |
| 4 | I understand that no document image will be transmitted off the researcher's device. | |
| 5 | *(Optional)* I agree that a de-identified table of values derived from my documents may be sent to a third-party service for the optional comparison. | |
| 6 | *(Optional)* I agree that de-identified text from my documents may be included in the project report and demo. | |
| 7 | I understand that this is a research prototype, that it does not diagnose or advise, and that I should consult a doctor for medical decisions. | |
| 8 | I understand that I may withdraw at any time and request deletion. | |

Name (participant): ______________________  Signature: ______________  Date: __________

Name (researcher): _______________________  Signature: ______________  Date: __________

*Statement 5 may be left blank. A blank statement 5 means no remote processing for this participant.*

### 9.3 Disclosure that must appear verbatim

> A de-identified table derived from your document may be processed by a third-party service. The table contains only numbers and standard medical terms. It contains no name, date, address, identifier, or image, and cannot be linked back to you by the service.

---

## 10. Ethics committee checklist

- [ ] Synopsis and SRS attached
- [ ] Information sheet (§9.1)
- [ ] Consent form (§9.2) with the OR-02 disclosure (§9.3)
- [ ] Data flow diagram showing the trust boundary
- [ ] Risk table with mitigations (§5)
- [ ] Deletion protocol (§7)
- [ ] Incident protocol (§8)
- [ ] Confirmation that no vulnerable population is involved
- [ ] Confirmation that no document image leaves the device
- [ ] Supervisor sign-off

## 11. What this project does not do

It does not provide medical advice. It does not diagnose. It does not tell a participant that a value is dangerous. It does not store data in the cloud. It does not sell, share, or publish documents.
