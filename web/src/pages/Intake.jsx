import { useRef, useState } from "react";
import Footer from "../components/Footer";
import { docTypeLabel, statusLabel } from "../lib/format";

const DOC_TYPES = [
  ["lab_report", "Lab report"],
  ["prescription", "Prescription"],
  ["pharmacy", "Pharmacy slip"],
  ["other", "Other document"],
];

async function requestJson(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("Could not reach the local server. Check that it is running and try again.");
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    // A non-JSON body is treated as a generic failure below.
  }
  return { response, data };
}

export default function Intake({ onDone }) {
  const [patient, setPatient] = useState(null);
  const [alias, setAlias] = useState("");
  const [sex, setSex] = useState("");
  const [file, setFile] = useState(null);
  const [docType, setDocType] = useState("lab_report");
  const [docDate, setDocDate] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const fileInputRef = useRef(null);

  function clearFile() {
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function resetUpload() {
    setResult(null);
    setError("");
    setDocDate("");
    setConsent(false);
    clearFile();
  }

  function changePatient() {
    setPatient(null);
    setAlias("");
    setSex("");
    resetUpload();
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");

    if (!patient && !alias.trim()) {
      setError("Enter a patient alias.");
      return;
    }
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
      let activePatient = patient;
      if (!activePatient) {
        const { response, data } = await requestJson("/api/patients", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ alias: alias.trim(), sex: sex || null }),
        });
        if (!response.ok) {
          throw new Error(data?.error?.message ?? "Could not create the patient record.");
        }
        activePatient = data;
        setPatient(data);
      }

      const body = new FormData();
      body.set("patient_id", activePatient.id);
      body.set("file", file);
      body.set("doc_type", docType);
      body.set("consent_scope", "local");
      if (docDate) body.set("doc_date", docDate);

      const { response, data } = await requestJson("/api/documents", {
        method: "POST",
        body,
      });

      if (response.status === 409) {
        setResult({
          duplicate: true,
          patient: activePatient,
          documentId: data?.document_id ?? "",
          pages: 0,
          status: data?.status ?? "queued",
          docType,
        });
        return;
      }

      if (!response.ok) {
        throw new Error(data?.error?.message ?? "The document could not be uploaded.");
      }

      setResult({
        duplicate: false,
        patient: activePatient,
        documentId: data.document_id,
        pages: data.pages,
        status: data.status,
        docType,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "The upload failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <div className="topbar">
        <div className="wordmark">Smriti</div>
        <div className="topbar-actions">
          <button type="button" className="text-button" onClick={onDone}>
            Back to summary
          </button>
        </div>
      </div>

      <main>
        <header className="page-head">
          <h1>Add a document</h1>
          <p>
            Create a local patient record and upload a lab report, prescription, or pharmacy slip.
            The summary preview uses sample data until the live summary API is connected.
          </p>
        </header>

      {result ? (
        <section className="panel" aria-labelledby="intake-result-heading">
          <div className="result-head">
            <div>
              <h2 id="intake-result-heading">
                {result.duplicate ? "Already stored" : "Document queued"}
              </h2>
              <p className="result-ref">
                {result.duplicate
                  ? "This file matches a document already on this device. No new document was added."
                  : `The file is stored locally and queued for ${result.patient.alias}.`}
              </p>
            </div>
            <span className="pill">{statusLabel(result.status)}</span>
          </div>

          <dl className="result-meta">
            {!result.duplicate ? (
              <div>
                <dt>Patient</dt>
                <dd>{result.patient.alias}</dd>
              </div>
            ) : null}
            <div>
              <dt>Document</dt>
              <dd className="mono">{result.documentId || "—"}</dd>
            </div>
            <div>
              <dt>Type</dt>
              <dd>{docTypeLabel(result.docType)}</dd>
            </div>
            {!result.duplicate ? (
              <div>
                <dt>Pages</dt>
                <dd>{result.pages || "—"}</dd>
              </div>
            ) : null}
          </dl>

          {!result.duplicate && result.pages > 0 ? (
            <div className="page-preview-wrap">
              <img
                className="page-preview"
                src={`/api/documents/${result.documentId}/page/1`}
                alt={`First page of the uploaded ${docTypeLabel(result.docType)}`}
              />
              <p className="result-note">
                First page only. Extraction is queued; OCR and review arrive in P2.
              </p>
            </div>
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
          {patient ? (
            <div className="patient-summary">
              <div>
                <p className="eyebrow">Patient</p>
                <p>{patient.alias}</p>
              </div>
              <button type="button" className="text-button" onClick={changePatient}>
                Change patient
              </button>
            </div>
          ) : (
            <fieldset>
              <legend>Patient</legend>
              <div className="form-grid two">
                <div className="field">
                  <label htmlFor="patient-alias">Patient alias</label>
                  <input
                    id="patient-alias"
                    name="alias"
                    type="text"
                    value={alias}
                    onChange={(event) => setAlias(event.target.value)}
                    maxLength={64}
                    autoComplete="off"
                    required
                  />
                  <p className="field-note">Use initials or a study ID, not a full name.</p>
                </div>
                <div className="field">
                  <label htmlFor="patient-sex">Sex</label>
                  <select
                    id="patient-sex"
                    name="sex"
                    value={sex}
                    onChange={(event) => setSex(event.target.value)}
                  >
                    <option value="">Not recorded</option>
                    <option value="F">Female</option>
                    <option value="M">Male</option>
                    <option value="O">Other</option>
                  </select>
                </div>
              </div>
            </fieldset>
          )}

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
