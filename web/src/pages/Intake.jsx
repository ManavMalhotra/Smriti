import { useEffect, useRef, useState } from "react";
import Footer from "../components/Footer";
import JobProgress from "../components/JobProgress";
import RedactionConsent from "../components/RedactionConsent";
import { requestJson } from "../lib/api";
import { docTypeLabel, shortId, statusLabel } from "../lib/format";

const DOC_TYPES = [
  ["auto", "Detect automatically"],
  ["lab_report", "Lab report"],
  ["prescription", "Prescription"],
  ["pharmacy", "Pharmacy slip"],
  ["discharge_summary", "Discharge summary"],
  ["ct", "CT report"],
  ["mri", "MRI report"],
  ["xray", "X-ray report"],
  ["pathology", "Pathology report"],
  ["radiology", "Imaging report"],
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

function needsPolling(row) {
  return row.result?.jobId && !row.pollStopped && row.job?.state !== "failed" && row.job?.state !== "done";
}

function unsent(row) {
  return ["pending", "uploading", "rejected", "upload_failed"].includes(row.state);
}

function fileSize(bytes) {
  return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Intake({ patient, onDone, onOpenDocument, onSignOut, onQueue, onDocuments, navigationGuard, cloudReviewAvailable = false }) {
  const [rows, setRows] = useState([]);
  const [submitted, setSubmitted] = useState(false);
  const [docType, setDocType] = useState("auto");
  const [docDate, setDocDate] = useState("");
  const [consent, setConsent] = useState(false);
  const [cloudReview, setCloudReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sessionError, setSessionError] = useState("");
  const rowsRef = useRef([]);
  const nextId = useRef(0);
  const active = useRef(false);
  const stopped = useRef(false);
  const uploading = useRef(false);
  const wakePolling = useRef(() => {});
  const uploadController = useRef(null);
  const batchOptions = useRef(null);
  const fileInputRef = useRef(null);
  const resultHeadingRef = useRef(null);
  const single = rows.length === 1 ? rows[0] : null;
  const result = single?.result;
  const job = single?.job;
  const awaiting = cloudReviewAvailable && rows.find((row) => row.job?.status === "awaiting_cloud_consent");

  useEffect(() => {
    if (!navigationGuard) return;
    navigationGuard.current = confirmLeaving;
    return () => { navigationGuard.current = null; };
  }, [navigationGuard]);

  function updateRows(next) {
    rowsRef.current = next;
    setRows(next);
  }

  function updateRow(id, changes) {
    updateRows(rowsRef.current.map((row) => row.id === id ? { ...row, ...changes } : row));
  }

  function stopForSession() {
    stopped.current = true;
    setSessionError("Your session is no longer available. Sign in again before uploading or checking progress. Stored documents are safe.");
  }

  useEffect(() => {
    if (submitted && !busy) resultHeadingRef.current?.focus();
  }, [submitted, busy]);

  useEffect(() => {
    updateRows([]);
    setSubmitted(false);
    setConsent(false);
    setCloudReview(false);
    setDocType("auto");
    setDocDate("");
    setSessionError("");
    setError("");
    setBusy(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
    uploading.current = false;
    active.current = true;
    stopped.current = false;
    let cancelled = false;
    let timer;
    let polling = false;
    const controller = new AbortController();

    async function poll() {
      if (polling || cancelled || stopped.current) return;
      polling = true;
      clearTimeout(timer);
      try {
        for (const row of rowsRef.current.filter(needsPolling)) {
          if (cancelled || stopped.current) break;
          if (!rowsRef.current.some((item) => item.id === row.id)) continue;
          try {
            let nextJob = row.job;
            if (nextJob?.state !== "done") {
              nextJob = await requestJson(`/api/jobs/${row.result.jobId}`, { signal: controller.signal });
              if (cancelled || stopped.current) return;
              updateRow(row.id, { job: nextJob, pollError: "", result: {
                ...row.result,
                documentId: nextJob.document_id ?? row.result.documentId,
                pages: nextJob.total_pages ?? nextJob.total ?? row.result.pages,
              } });
            }
          } catch (err) {
            if (cancelled) return;
            if ([401, 403].includes(err?.status)) {
              stopForSession();
              break;
            }
            const missing = err?.status === 404;
            updateRow(row.id, { pollStopped: missing, pollError: missing ? "This document or job is no longer available." : "Connection interrupted; checking again. Your last progress is shown below." });
          }
        }
      } finally {
        polling = false;
        if (!cancelled && !stopped.current && rowsRef.current.some(needsPolling)) {
          timer = setTimeout(poll, 2000);
        }
      }
    }

    wakePolling.current = poll;
    poll();
    return () => {
      cancelled = true;
      active.current = false;
      stopped.current = true;
      clearTimeout(timer);
      controller.abort();
      uploadController.current?.abort();
    };
  }, [patient.id]);

  useEffect(() => {
    function beforeUnload(event) {
      if (!rowsRef.current.some(unsent)) return;
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, []);

  function confirmLeaving() {
    return !rowsRef.current.some(unsent) || window.confirm("Files not yet uploaded will be lost. Stored documents will keep processing. Leave this upload?");
  }

  function navigate(callback) {
    if (!confirmLeaving()) return;
    stopped.current = true;
    uploadController.current?.abort();
    callback();
  }

  function resetUpload() {
    if (uploading.current || !confirmLeaving()) return;
    updateRows([]);
    setSubmitted(false);
    setError("");
    setDocType("auto");
    setDocDate("");
    setConsent(false);
    setCloudReview(false);
    requestAnimationFrame(() => fileInputRef.current?.focus());
  }

  async function uploadFiles(selected) {
    if (uploading.current || stopped.current) return;
    uploading.current = true;
    setBusy(true);
    setSubmitted(true);
    setError("");
    const controller = new AbortController();
    uploadController.current = controller;
    try {
      for (const row of selected) {
        if (!active.current || stopped.current) break;
        updateRow(row.id, { state: "uploading", uploadError: "" });
        try {
          const options = batchOptions.current;
          const body = new FormData();
          body.set("patient_id", patient.id);
          body.set("file", row.file);
          body.set("consent_scope", options.cloudReview ? "local_plus_projection" : "local");
          if (options.docType !== "auto") body.set("doc_type", options.docType);
          if (options.docDate) body.set("doc_date", options.docDate);
          const data = await requestJson("/api/documents", { method: "POST", body, signal: controller.signal });
          if (!active.current || controller.signal.aborted) return;
           updateRow(row.id, { state: "uploaded", result: { duplicate: Boolean(data.duplicate), documentId: data.document_id, jobId: data.job_id, pages: data.pages, status: data.status, docType: options.docType === "auto" ? null : options.docType } });
          wakePolling.current();
        } catch (err) {
          if (!active.current || controller.signal.aborted) return;
          if (err?.status === 409 && err.data?.duplicate) {
             updateRow(row.id, { state: "duplicate", result: { duplicate: true, documentId: err.data.document_id ?? "", jobId: err.data.document_id ? null : err.data.job_id, pages: err.data.page_count ?? null, status: err.data.status ?? "queued", docType: err.data.doc_type ?? null } });
             wakePolling.current();
          } else {
            updateRow(row.id, { state: err?.status >= 400 && err?.status < 500 ? "rejected" : "upload_failed", uploadError: err instanceof Error ? err.message : "The upload failed. Try again." });
            if ([401, 403].includes(err?.status)) stopForSession();
          }
        }
      }
    } finally {
      if (uploadController.current === controller) {
        uploading.current = false;
        if (active.current) setBusy(false);
      }
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (uploading.current || stopped.current) return;
    setError("");
    if (!rows.length) {
      setError("Choose a document file.");
      fileInputRef.current?.focus();
      return;
    }
    if (!consent) {
      setError("Confirm consent before uploading.");
      document.getElementById("consent")?.focus();
      return;
    }
    batchOptions.current = { docType, docDate, cloudReview };
    uploadFiles(rowsRef.current.filter((row) => row.state === "pending"));
  }

  const status = _jobStatus(job, result?.status);
  const failed = job?.state === "failed";
  const detectedType = result?.docType;
  const pageCount = result?.pages;
  const uploadedCount = rows.filter((row) => row.result && !row.result.duplicate).length;
  const processedCount = rows.filter((row) => row.job?.state === "done").length;
  const duplicateCount = rows.filter((row) => row.result?.duplicate).length;
  const failedCount = rows.filter((row) => ["rejected", "upload_failed"].includes(row.state) || row.job?.state === "failed").length;

  return (
    <div className="shell">
      <div className="topbar">
        <div className="wordmark">Smriti</div>
        <div className="topbar-actions">
          <button type="button" className="text-button" onClick={() => navigate(onDone)}>
            Back to summary
          </button>
          {onQueue ? <button type="button" className="text-button" onClick={() => navigate(onQueue)}>Queue</button> : null}
          {onDocuments ? <button type="button" className="text-button" onClick={() => navigate(onDocuments)}>Documents</button> : null}
          {onSignOut ? (
            <button type="button" className="text-button" onClick={() => navigate(onSignOut)}>
              Sign out
            </button>
          ) : null}
        </div>
      </div>

      <main>
        {awaiting ? <RedactionConsent key={awaiting.result?.documentId ?? awaiting.job?.document_id} documentId={awaiting.result?.documentId ?? awaiting.job?.document_id} cloudAvailable={cloudReviewAvailable}
          onResolved={() => { updateRow(awaiting.id, { job: { ...awaiting.job, status: "running" } }); wakePolling.current(); }} /> : null}
        <header className="page-head">
          <h1 tabIndex={-1}>Add a document</h1>
          <p>
            Upload medical documents for {patient.alias}. Smriti detects the document
            type and extracts fields locally on this device.
          </p>
        </header>

        {sessionError ? <div className="alert" role="alert">{sessionError}</div> : null}

        {submitted && !result ? (
          <section className="panel" aria-labelledby="batch-heading">
            <h2 id="batch-heading" ref={resultHeadingRef} tabIndex={-1}>{busy ? "Uploading documents…" : rows.length === 1 ? "Upload failed" : "Your documents"}</h2>
            <p className="batch-counts" role="status">{uploadedCount} uploaded · {processedCount} processed · {duplicateCount} already stored · {failedCount} failed</p>
            <ul className="upload-list">
              {rows.map((row, index) => (
                <li key={row.id}>
                  <section aria-labelledby={`file-${row.id}`}>
                    <div className="upload-row-head">
                      <h3 id={`file-${row.id}`}>{row.file.name}{rows.filter((item) => item.file.name === row.file.name).length > 1 ? <span className="sr-only"> (file {index + 1})</span> : null}</h3>
                      <span className="pill">{row.result ? row.result.duplicate ? "Already stored" : statusLabel(_jobStatus(row.job, row.result.status)) : { pending: "Waiting to upload", uploading: "Uploading…", rejected: "Rejected", upload_failed: "Upload failed" }[row.state]}</span>
                    </div>
                    <p className="result-note">{fileSize(row.file.size)}{row.result?.pages ? ` · ${row.result.pages} ${row.result.pages === 1 ? "page" : "pages"}` : ""}</p>
                    {row.uploadError ? <p className="alert" role="alert">{row.uploadError}</p> : null}
                    {row.pollError ? <p className="alert" role="status">{row.pollError}</p> : null}
                    {row.job?.state === "failed" ? <p className="alert" role="alert">{row.job.error || "Local extraction failed."}{row.result?.documentId ? " The document remains stored." : " No document was created."}</p> : null}
                    {row.result?.duplicate ? <p className="result-note">This file is already in your records. No new document was added.</p> : null}
                    {row.result?.jobId ? <JobProgress job={row.job ?? { id: row.result.jobId, state: row.result.status, total: row.result.pages }} /> : null}
                    <div className="form-actions">
                      {["rejected", "upload_failed"].includes(row.state) ? <button type="button" className="button-secondary" disabled={busy || Boolean(sessionError)} onClick={() => uploadFiles([row])}>Retry upload</button> : null}
                      {row.result?.documentId && onOpenDocument ? <button type="button" className="button-secondary" onClick={() => navigate(() => onOpenDocument(row.result.documentId))}>{row.job?.state === "done" ? "Review extracted fields" : "Open document"}</button> : null}
                    </div>
                  </section>
                </li>
              ))}
            </ul>
            <div className="form-actions"><button type="button" className="button-secondary" disabled={busy} onClick={resetUpload}>Add more documents</button></div>
          </section>
        ) : null}

        {result ? (
          <section className="panel" aria-labelledby="intake-result-heading">
            <div className="result-head">
              <div>
                <h2 id="intake-result-heading" ref={resultHeadingRef} tabIndex={-1}>
                  {result.duplicate
                     ? result.documentId ? "Already stored" : "Upload already queued"
                    : failed
                      ? "Extraction failed"
                      : job?.state === "done"
                        ? "Document processed"
                        : "Document queued"}
                </h2>
                <p className="result-ref">
                  {result.duplicate
                    ? "This file matches a document already in your records. No new document was added."
                    : failed
                       ? result.documentId ? "The document is stored, but local extraction failed." : "Source preparation failed. No document was created."
                      : job?.state === "done"
                         ? "Results saved. Open the document to review them."
                        : `The file is stored locally and queued for ${patient.alias}.`}
                </p>
              </div>
              <span className="pill">{statusLabel(status)}</span>
            </div>

            <p className="uploaded-filename">{single.file.name}</p>

            {job?.error || single.pollError ? (
              <div className="alert" role={job?.error ? "alert" : "status"}>
                {job?.error || single.pollError}
              </div>
            ) : null}

            <dl className="result-meta">
              <div>
                <dt>Patient</dt>
                <dd>{patient.alias}</dd>
              </div>
              <div>
                <dt>Document</dt>
                <dd className="mono">{result.documentId ? shortId(result.documentId) : "—"}</dd>
              </div>
              <div>
                <dt>Type</dt>
                <dd>{detectedType ? docTypeLabel(detectedType) : failed ? "Unavailable" : job?.state === "done" ? "See document" : "Detecting…"}</dd>
              </div>
              {!result.duplicate ? (
                <div>
                  <dt>Pages</dt>
                  <dd>{pageCount || "—"}</dd>
                </div>
              ) : null}
            </dl>

            {result.jobId ? <JobProgress job={job ?? { id: result.jobId, state: result.status, total: result.pages }} /> : null}

             {!result.duplicate && result.documentId && pageCount > 0 ? (
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

            <div className="form-actions">
              {onOpenDocument && result.documentId ? (
                <button
                  type="button"
                   className={job?.state === "done" ? "button-primary" : "button-secondary"}
                  onClick={() => navigate(() => onOpenDocument(result.documentId))}
                >
                   {job?.state === "done" ? "Review extracted fields" : "Open document"}
                </button>
              ) : null}
              <button type="button" className="button-secondary" disabled={busy} onClick={resetUpload}>
                Add another document
              </button>
              <button type="button" className="text-button" onClick={() => navigate(onDone)}>
                Back to summary
              </button>
            </div>
          </section>
        ) : !submitted ? (
          <form className="panel" onSubmit={handleSubmit} noValidate>
            <fieldset disabled={busy || Boolean(sessionError)}>
              <legend>Document</legend>
              <div className="form-grid two">
                <div className="field field-wide">
                  <label htmlFor="document-file">Document file</label>
                  <input
                    ref={fileInputRef}
                    id="document-file"
                    name="file"
                     type="file"
                     multiple
                    accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf"
                    onChange={(event) => {
                      updateRows(Array.from(event.target.files ?? []).map((file) => ({ id: ++nextId.current, file, state: "pending" })));
                      setConsent(false);
                      setError("");
                    }}
                    required
                  />
                  <p className="field-note">JPEG, PNG, or PDF. The file stays on this device.</p>
                  {rows.length ? <ul className="upload-list pending-files">{rows.map((row) => <li key={row.id}><div className="upload-row-head"><span>{row.file.name} <small>{fileSize(row.file.size)}</small></span><button type="button" className="text-button" aria-label={`Remove ${row.file.name}`} onClick={() => { updateRows(rowsRef.current.filter((item) => item.id !== row.id)); if (fileInputRef.current) fileInputRef.current.value = ""; }}>Remove</button></div></li>)}</ul> : null}
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
                  <p className="field-note">Optional override for all selected files. Automatic detection runs after upload.</p>
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
                  <p className="field-note">Optional override for all selected files. Use the date printed on the documents.</p>
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
                  I have permission to store and process these documents locally. Gemini review is separate and off by default.
                </span>
              </label>
              {cloudReviewAvailable ? <label className="checkbox-field" htmlFor="cloud-review">
                <input id="cloud-review" type="checkbox" checked={cloudReview}
                  onChange={(event) => setCloudReview(event.target.checked)} />
                <span>Request optional Gemini review. The document pauses for mask review; only pages you approve with finalized masks are sent.</span>
              </label> : null}
            </fieldset>

            {error ? (
              <div className="alert" role="alert">
                {error}
              </div>
            ) : null}

            <div className="form-actions">
              <button type="submit" className="button-primary" disabled={busy || Boolean(sessionError)}>
                {busy ? "Uploading…" : rows.length > 1 ? `Upload ${rows.length} documents` : "Upload document"}
              </button>
              <span className="field-note">The server checks file type, size, and image quality.</span>
            </div>
          </form>
        ) : null}
      </main>

      <Footer />
    </div>
  );
}
