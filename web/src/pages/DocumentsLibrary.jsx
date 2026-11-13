import { useEffect, useMemo, useState } from "react";
import Footer from "../components/Footer";
import Topbar from "../components/Topbar";
import { docTypeLabel, formatDate, shortId, statusLabel } from "../lib/format";
import { requestJson } from "../lib/api";

const FILTERS = ["All", "Prescriptions", "Lab reports", "Scans & discharge", "Needs review"];
const DOC_TYPES = ["prescription", "pharmacy", "lab_report", "discharge_summary", "ct", "mri", "xray", "pathology", "radiology", "other"];
const PAGE_SIZE = 20;

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

export default function DocumentsLibrary({ patient, onOpenDocument, onAdd, onQueue, onSignOut, onSummary, onUpdated }) {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [retrying, setRetrying] = useState(null);
  const [filter, setFilter] = useState("All");
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let timer;
    const controller = new AbortController();
    setLoading(true);
    async function load() {
      let again = false;
      try {
        const data = await requestJson(`/api/documents?limit=${PAGE_SIZE}&offset=${offset}&filter=${encodeURIComponent(filter)}`, { signal: controller.signal });
        if (cancelled) return;
        setDocuments(data.documents);
        setHasMore(data.has_more);
        setError("");
        again = data.documents.some((document) => ["queued", "running"].includes(document.job_state));
      } catch (err) {
        if (cancelled) return;
        setError([401, 403].includes(err.status) ? "Your session expired. Sign in again." : "Could not load documents. Refresh to try again.");
      } finally {
        if (!cancelled) {
          setLoading(false);
          if (again) timer = setTimeout(load, 2000);
        }
      }
    }
    load();
    return () => { cancelled = true; clearTimeout(timer); controller.abort(); };
  }, [patient.id, offset, refresh, filter]);
  const groups = useMemo(() => {
    const sorted = documents.slice().sort((a, b) => {
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
      setRefresh((value) => value + 1);
      onUpdated?.();
    } catch (err) {
      setEditError(err.message || "Could not save document details.");
    } finally { setSaving(false); }
  }

  async function retryDocument(document) {
    setRetrying(document.id);
    setError("");
    try {
      await requestJson(`/api/jobs/${document.job_id}/retry`, { method: "POST" });
      setRefresh((value) => value + 1);
      onUpdated?.();
    } catch (err) {
      setError(err.message || "Could not retry local processing.");
    } finally { setRetrying(null); }
  }

  return (
    <div className="shell">
      <Topbar
        current="documents"
        back={{ label: "Summary", onClick: onSummary }}
        onQueue={onQueue}
        onAdd={onAdd}
        onSignOut={onSignOut}
      />
      <main>
        <header className="page-head">
          <h1 tabIndex={-1}>Documents</h1>
          <p>{patient.alias}</p>
        </header>
        <div className="document-filters" role="group" aria-label="Filter documents">
          {FILTERS.map((item) => <button type="button" key={item} className="filter-pill"
            aria-pressed={filter === item} onClick={() => { setDocuments([]); setHasMore(false); setOffset(0); setFilter(item); }}>{item}</button>)}
          <button type="button" className="text-button" onClick={() => setRefresh((value) => value + 1)}>Refresh</button>
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
                  <strong>{document.display_name || `${docTypeLabel(document.doc_type)} · ${shortId(document.id)}`}</strong>
                  <span>{docTypeLabel(document.doc_type)} · {formatDate(documentDate(document))}</span>
                  <span>{document.facility_name || "Facility not recorded"}</span>
                  <span>{document.page_count == null ? "Pages not yet inspected" : `${document.page_count} ${document.page_count === 1 ? "page" : "pages"}`}</span>
                  {document.processed_at ? <span className="result-note">Last processed {formatDate(document.processed_at)}</span> : null}
                </div>
                <div className="document-card-actions">
                  <span className={needsReview(document) ? "document-status needs-review" : "document-status"}>
                     {document.status !== "done" ? statusLabel(document.status) : document.review_count ? `${document.review_count} to review` : statusLabel(document.status)}
                   </span>
                   {document.document_id ? <>
                     <button type="button" className="button-secondary" onClick={() => onOpenDocument(document.document_id)}>Open</button>
                     <button type="button" className="text-button" onClick={() => editDocument(document)}>Edit details</button>
                   </> : <button type="button" className="text-button" onClick={onQueue}>View upload in Queue</button>}
                   {document.retryable ? <button type="button" className="button-secondary" disabled={retrying !== null}
                     onClick={() => retryDocument(document)}>{retrying === document.id ? "Queueing…" : "Retry processing"}</button> : null}
                   {!document.document_id && document.job_state === "failed" ? <button type="button" className="button-secondary" onClick={onAdd}>Re-upload</button> : null}
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
        <div className="form-actions" aria-label="Document pages">
          <button type="button" className="button-secondary" disabled={!offset || loading} onClick={() => { setDocuments([]); setOffset(Math.max(0, offset - PAGE_SIZE)); }}>Previous</button>
          <span>Page {Math.floor(offset / PAGE_SIZE) + 1}</span>
          <button type="button" className="button-secondary" disabled={!hasMore || loading} onClick={() => { setDocuments([]); setOffset(offset + PAGE_SIZE); }}>Next</button>
        </div>
      </main>
      <Footer />
    </div>
  );
}
