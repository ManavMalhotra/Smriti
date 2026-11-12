import { useMemo, useState } from "react";
import Footer from "../components/Footer";
import { docTypeLabel, formatDate, statusLabel } from "../lib/format";
import { requestJson } from "../lib/api";

const FILTERS = ["All", "Prescriptions", "Lab Reports", "Scans / Discharge", "Needs Review"];
const SCANS = new Set(["ct", "mri", "xray", "radiology", "pathology", "discharge_summary"]);
const DOC_TYPES = ["prescription", "pharmacy", "lab_report", "discharge_summary", "ct", "mri", "xray", "pathology", "radiology", "other"];

function documentDate(document) {
  return document.verified_date || document.collection_date || document.registration_date || document.report_date || document.doc_date || null;
}

function monthLabel(date) {
  if (!date) return "Date not recorded";
  const [year, month] = date.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString("en-GB", {
    month: "long", year: "numeric", timeZone: "UTC",
  });
}

function needsReview(document) {
  return document.status !== "done" || document.review_count > 0;
}

function matches(document, filter) {
  if (filter === "Prescriptions") return ["prescription", "pharmacy"].includes(document.doc_type);
  if (filter === "Lab Reports") return document.doc_type === "lab_report";
  if (filter === "Scans / Discharge") return SCANS.has(document.doc_type);
  if (filter === "Needs Review") return needsReview(document);
  return true;
}

export default function DocumentsLibrary({ patient, documents = [], loading, error, onOpenDocument, onAdd, onQueue, onSignOut, onSummary, onUpdated }) {
  const [filter, setFilter] = useState("All");
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const groups = useMemo(() => {
    const sorted = documents.filter((item) => matches(item, filter)).slice().sort((a, b) => {
      const left = documentDate(a) || "";
      const right = documentDate(b) || "";
      return right.localeCompare(left) || (b.created_at || "").localeCompare(a.created_at || "");
    });
    const grouped = new Map();
    for (const item of sorted) {
      const date = documentDate(item);
      const key = date?.slice(0, 7) || "undated";
      if (!grouped.has(key)) grouped.set(key, { title: monthLabel(date), items: [] });
      grouped.get(key).items.push(item);
    }
    return [...grouped.values()];
  }, [documents, filter]);

  function editDocument(document) {
    setEditing({ id: document.id, display_name: document.display_name || "", doc_type: document.doc_type,
      verified_date: documentDate(document)?.slice(0, 10) || "", facility_name: document.facility_name || "" });
    setEditError("");
  }

  async function saveDocument(event) {
    event.preventDefault();
    setSaving(true);
    setEditError("");
    try {
      await requestJson(`/api/documents/${editing.id}`, { method: "PATCH", body: JSON.stringify({
        display_name: editing.display_name || null, doc_type: editing.doc_type,
        verified_date: editing.verified_date || null, facility_name: editing.facility_name || null,
      }) });
      setEditing(null);
      onUpdated?.();
    } catch (err) {
      setEditError(err.message || "Could not save document details.");
    } finally { setSaving(false); }
  }

  return (
    <div className="shell">
      <div className="topbar">
        <div className="wordmark">Smriti</div>
        <div className="topbar-actions">
          <button type="button" className="text-button" onClick={onSummary}>Health timeline</button>
          <button type="button" className="text-button" onClick={onQueue}>Queue</button>
          <button type="button" className="button-secondary" onClick={onAdd}>Add document</button>
          <button type="button" className="text-button" onClick={onSignOut}>Sign out</button>
        </div>
      </div>
      <main>
        <header className="page-head">
          <h1>Documents</h1>
          <p>{patient.alias} · {documents.length} {documents.length === 1 ? "document" : "documents"}</p>
        </header>
        <div className="document-filters" role="group" aria-label="Filter documents">
          {FILTERS.map((item) => <button type="button" key={item} className="filter-pill"
            aria-pressed={filter === item} onClick={() => setFilter(item)}>{item}</button>)}
        </div>
        {loading && !documents.length ? <p className="empty" role="status">Loading documents…</p> : null}
        {error ? <p className="alert" role="alert">{error}</p> : null}
        {!loading && !error && !groups.length ? <p className="empty">No documents match this filter.</p> : null}
        {groups.map((group) => <section className="document-month" key={group.title} aria-labelledby={`month-${group.title.replaceAll(" ", "-")}`}>
          <h2 id={`month-${group.title.replaceAll(" ", "-")}`}>{group.title}</h2>
          <ul className="document-library-list">
            {group.items.map((document) => <li key={document.id}>
              <article className="document-card">
                <div className="document-card-main">
                  <strong>{document.display_name || docTypeLabel(document.doc_type)}</strong>
                  <span>{docTypeLabel(document.doc_type)} · {formatDate(documentDate(document))}</span>
                  <span>{document.facility_name || "Facility not recorded"}</span>
                  <span>{document.page_count} {document.page_count === 1 ? "page" : "pages"}</span>
                  {document.processed_at ? <span className="result-note">Last processed {formatDate(document.processed_at)}</span> : null}
                </div>
                <div className="document-card-actions">
                  <span className={needsReview(document) ? "document-status needs-review" : "document-status"}>
                    {needsReview(document) ? `${document.review_count ? `${document.review_count} · ` : ""}Needs review` : statusLabel(document.status)}
                  </span>
                  <button type="button" className="button-secondary" onClick={() => onOpenDocument(document.id)}>Open</button>
                  <button type="button" className="text-button" onClick={() => editDocument(document)}>Edit details</button>
                </div>
                {editing?.id === document.id ? <form className="document-edit-form" onSubmit={saveDocument}>
                  <label>Document name<input maxLength={200} value={editing.display_name} placeholder={docTypeLabel(document.doc_type)}
                    onChange={(event) => setEditing((current) => ({ ...current, display_name: event.target.value }))} /></label>
                  <label>Type<select value={editing.doc_type} onChange={(event) => setEditing((current) => ({ ...current, doc_type: event.target.value }))}>
                    {DOC_TYPES.map((type) => <option key={type} value={type}>{docTypeLabel(type)}</option>)}
                  </select></label>
                  <label>Document date<input type="date" value={editing.verified_date} onChange={(event) => setEditing((current) => ({ ...current, verified_date: event.target.value }))} /></label>
                  <label>Facility or doctor<input maxLength={200} value={editing.facility_name}
                    onChange={(event) => setEditing((current) => ({ ...current, facility_name: event.target.value }))} /></label>
                  {editError ? <p className="alert" role="alert">{editError}</p> : null}
                  <div className="form-actions"><button type="submit" className="button-primary" disabled={saving}>{saving ? "Saving…" : "Save details"}</button>
                    <button type="button" className="text-button" onClick={() => setEditing(null)}>Cancel</button></div>
                </form> : null}
              </article>
            </li>)}
          </ul>
        </section>)}
      </main>
      <Footer />
    </div>
  );
}
