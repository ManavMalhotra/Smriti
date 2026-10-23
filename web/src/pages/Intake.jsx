import { useEffect, useRef, useState } from "react";
import Footer from "../components/Footer";
import { requestJson } from "../lib/api";
import { docTypeLabel, formatRange, statusLabel } from "../lib/format";

const DOC_TYPES = [
  ["auto", "Detect automatically"],
  ["lab_report", "Lab report"],
  ["prescription", "Prescription"],
  ["pharmacy", "Pharmacy slip"],
  ["other", "Other document"],
];

function _jobStatus(job, fallback) {
  if (!job) return fallback;
  return {
    queued: "queued",
    running: "processing",
    done: "done",
    failed: "failed",
  }[job.state] ?? fallback;
}

function _fieldLabel(field) {
  return field.label_raw || field.analyte_id || "Unmapped field";
}

export default function Intake({ patient, onDone, onSignOut }) {
  const [file, setFile] = useState(null);
  const [docType, setDocType] = useState("auto");
  const [docDate, setDocDate] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [detail, setDetail] = useState(null);
  const [job, setJob] = useState(null);
  const fileInputRef = useRef(null);
  const resultHeadingRef = useRef(null);
  const hadResult = useRef(false);

  useEffect(() => {
    if (result) {
      hadResult.current = true;
      resultHeadingRef.current?.focus();
    } else if (hadResult.current) {
      fileInputRef.current?.focus();
    }
  }, [result]);

  useEffect(() => {
    if (!result?.jobId) return;
    let cancelled = false;
    let timer;

    async function poll() {
      try {
        const nextJob = await requestJson(`/api/jobs/${result.jobId}`);
        if (cancelled) return;
        setJob(nextJob);
        if (nextJob.state === "done") {
          const document = await requestJson(`/api/documents/${result.documentId}`);
          if (!cancelled) setDetail(document);
          return;
        }
        if (nextJob.state === "failed") {
          if (!cancelled) setError(nextJob.error || "Local extraction failed.");
          return;
        }
        timer = setTimeout(poll, 2000);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not check extraction progress.");
        }
      }
    }

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [result?.jobId, result?.documentId]);

  function clearFile() {
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function resetUpload() {
    setResult(null);
    setDetail(null);
    setJob(null);
    setError("");
    setDocDate("");
    setConsent(false);
    clearFile();
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");

    if (!file) {
      setError("Choose a document file.");
      return;
    }
    if (!consent) {
      setError("Confirm consent before uploading.");
      return;
    }

    setBusy(true);
    try {
      const body = new FormData();
      body.set("patient_id", patient.id);
      body.set("file", file);
      body.set("consent_scope", "local");
      if (docType !== "auto") body.set("doc_type", docType);
      if (docDate) body.set("doc_date", docDate);

      try {
        const data = await requestJson("/api/documents", { method: "POST", body });
        setResult({
          duplicate: false,
          patient,
          documentId: data.document_id,
          jobId: data.job_id,
          pages: data.pages,
          status: data.status,
          docType: docType === "auto" ? null : docType,
        });
      } catch (err) {
        if (err?.status === 409 && err.data?.duplicate) {
          setResult({
            duplicate: true,
            patient,
            documentId: err.data.document_id ?? "",
            jobId: null,
            pages: err.data.page_count ?? 0,
            status: err.data.status ?? "queued",
            docType: err.data.doc_type ?? null,
          });
          return;
        }
        throw err;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "The upload failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const status = _jobStatus(job, result?.status);
  const detectedType = detail?.doc_type ?? result?.docType;
  const pageCount = detail?.page_count ?? result?.pages;
  const observations = detail?.observations ?? [];
  const medications = detail?.medications ?? [];
  const pageText = detail?.page_text ?? [];

  return (
    <div className="shell">
      <div className="topbar">
        <div className="wordmark">Smriti</div>
        <div className="topbar-actions">
          <button type="button" className="text-button" onClick={onDone}>
            Back to summary
          </button>
          {onSignOut ? (
            <button type="button" className="text-button" onClick={onSignOut}>
              Sign out
            </button>
          ) : null}
        </div>
      </div>

      <main>
        <header className="page-head">
          <h1 tabIndex={-1}>Add a document</h1>
          <p>
            Upload a lab report, prescription, or pharmacy slip for {patient.alias}. Smriti
            detects the document type and extracts fields locally on this device.
          </p>
        </header>

        {result ? (
          <section className="panel" aria-labelledby="intake-result-heading">
            <div className="result-head">
              <div>
                <h2 id="intake-result-heading" ref={resultHeadingRef} tabIndex={-1}>
                  {result.duplicate
                    ? "Already stored"
                    : detail
                      ? "Document processed"
                      : "Document queued"}
                </h2>
                <p className="result-ref">
                  {result.duplicate
                    ? "This file matches a document already in your records. No new document was added."
                    : detail
                      ? "Local OCR and rule extraction finished. Review the fields below."
                      : `The file is stored locally and queued for ${patient.alias}.`}
                </p>
              </div>
              <span className="pill">{statusLabel(status)}</span>
            </div>

            <dl className="result-meta">
              <div>
                <dt>Patient</dt>
                <dd>{patient.alias}</dd>
              </div>
              <div>
                <dt>Document</dt>
                <dd className="mono">{result.documentId || "—"}</dd>
              </div>
              <div>
                <dt>Type</dt>
                <dd>{detectedType ? docTypeLabel(detectedType) : "Detecting…"}</dd>
              </div>
              {!result.duplicate ? (
                <div>
                  <dt>Pages</dt>
                  <dd>{pageCount || "—"}</dd>
                </div>
              ) : null}
            </dl>

            {!result.duplicate && pageCount > 0 ? (
              <div className="page-preview-wrap">
                <img
                  className="page-preview"
                  src={`/api/documents/${result.documentId}/page/1`}
                  alt={`First page of the uploaded ${docTypeLabel(detectedType ?? "other")}`}
                />
                <p className="result-note">
                  First page only. Images and text stay on this device.
                </p>
              </div>
            ) : null}

            {!result.duplicate && !detail && !error ? (
              <p className="result-note" role="status">
                Reading the page locally. Extracted fields will appear here.
              </p>
            ) : null}

            {observations.length > 0 ? (
              <section className="extracted-section" aria-labelledby="fields-heading">
                <h3 id="fields-heading">Extracted fields</h3>
                <div className="table-wrap">
                  <table>
                    <caption className="sr-only">Extracted fields from this document</caption>
                    <thead>
                      <tr>
                        <th scope="col">Field</th>
                        <th scope="col">Value</th>
                        <th scope="col">Unit</th>
                        <th scope="col">Reference</th>
                        <th scope="col">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {observations.map((field) => (
                        <tr key={field.id}>
                          <td>{_fieldLabel(field)}</td>
                          <td className="mono">{field.value_text ?? field.value_num ?? "—"}</td>
                          <td>{field.unit_raw ?? "—"}</td>
                          <td>{formatRange(field.ref_low, field.ref_high)}</td>
                          <td>{statusLabel(field.status)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="result-note">Extracted locally; review is required before relying on a value.</p>
              </section>
            ) : null}

            {medications.length > 0 ? (
              <section className="extracted-section" aria-labelledby="medications-heading">
                <h3 id="medications-heading">Extracted medications</h3>
                <ul className="list">
                  {medications.map((medication) => (
                    <li key={medication.id}>
                      <span>{medication.brand_raw}</span>
                      <span className="unit">
                        {[medication.dose, medication.freq].filter(Boolean).join(" · ")}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {pageText.length > 0 ? (
              <details className="extracted-text">
                <summary>Extracted text</summary>
                {pageText.map((page) => (
                  <div key={page.page}>
                    <h3>Page {page.page}</h3>
                    <pre>{page.text || "No text detected."}</pre>
                  </div>
                ))}
              </details>
            ) : null}

            <div className="form-actions">
              <button type="button" className="button-secondary" onClick={resetUpload}>
                Add another document
              </button>
              <button type="button" className="text-button" onClick={onDone}>
                Back to summary
              </button>
            </div>
          </section>
        ) : (
          <form className="panel" onSubmit={handleSubmit} noValidate>
            <div className="patient-summary">
              <div>
                <p className="eyebrow">Patient</p>
                <p>{patient.alias}</p>
              </div>
              <span className="field-note">Signed in</span>
            </div>

            <fieldset>
              <legend>Document</legend>
              <div className="form-grid two">
                <div className="field field-wide">
                  <label htmlFor="document-file">Document file</label>
                  <input
                    ref={fileInputRef}
                    id="document-file"
                    name="file"
                    type="file"
                    accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf"
                    onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                    required
                  />
                  <p className="field-note">JPEG, PNG, or PDF. The file stays on this device.</p>
                </div>
                <div className="field">
                  <label htmlFor="document-type">Document type</label>
                  <select
                    id="document-type"
                    name="doc_type"
                    value={docType}
                    onChange={(event) => setDocType(event.target.value)}
                  >
                    {DOC_TYPES.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <p className="field-note">Automatic detection runs after upload.</p>
                </div>
                <div className="field">
                  <label htmlFor="document-date">Document date</label>
                  <input
                    id="document-date"
                    name="doc_date"
                    type="date"
                    value={docDate}
                    onChange={(event) => setDocDate(event.target.value)}
                  />
                  <p className="field-note">Optional. Use the date printed on the document.</p>
                </div>
              </div>

              <label className="checkbox-field" htmlFor="consent">
                <input
                  id="consent"
                  name="consent"
                  type="checkbox"
                  checked={consent}
                  onChange={(event) => setConsent(event.target.checked)}
                  required
                />
                <span>
                  I have permission to store and process this document locally. No image or text
                  leaves this device.
                </span>
              </label>
            </fieldset>

            {error ? (
              <div className="alert" role="alert">
                {error}
              </div>
            ) : null}

            <div className="form-actions">
              <button type="submit" className="button-primary" disabled={busy}>
                {busy ? "Uploading…" : "Upload document"}
              </button>
              <span className="field-note">The server checks file type, size, and image quality.</span>
            </div>
          </form>
        )}
      </main>

      <Footer />
    </div>
  );
}
