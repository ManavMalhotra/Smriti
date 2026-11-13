import { useEffect, useState } from "react";
import Footer from "../components/Footer";
import JobProgress from "../components/JobProgress";
import RedactionConsent from "../components/RedactionConsent";
import Topbar from "../components/Topbar";
import { requestJson } from "../lib/api";
import { docTypeLabel, formatDate, shortId, statusLabel } from "../lib/format";

const PAGE_SIZE = 20;

export default function Queue({ patient, onDone, onAdd, onOpenDocument, onSignOut, cloudReviewAvailable = false, onDocuments }) {
  const [scope, setScope] = useState("all");
  const [offset, setOffset] = useState(0);
  const [jobs, setJobs] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const awaiting = jobs.find((job) => job.status === "awaiting_cloud_consent");

  useEffect(() => {
    let cancelled = false;
    let timer;
    let sessionLost = false;
    let detailStopped = false;
    const controller = new AbortController();
    setLoading(true);

    async function poll() {
      let again = scope === "active";
      try {
        const data = await requestJson(`/api/jobs?scope=${scope}&limit=${PAGE_SIZE}&offset=${offset}`, { signal: controller.signal });
        if (cancelled) return;
        setJobs(data.jobs);
        setHasMore(data.has_more);
        setError("");
        again = again || (scope === "all" && data.jobs.some((job) => ["queued", "running"].includes(job.state)));
        if (selected && !detailStopped && data.jobs.some((job) => job.id === selected)) {
          try {
            const next = await requestJson(`/api/jobs/${selected}`, { signal: controller.signal });
            if (cancelled) return;
            setDetail(next);
            setDetailError("");
            detailStopped = ["done", "failed"].includes(next.state);
          } catch (err) {
            if (cancelled) return;
            sessionLost = [401, 403].includes(err?.status);
            detailStopped = err?.status === 404 || sessionLost;
            setDetailError(sessionLost ? "Your session expired. Sign in again to check progress." : err?.status === 404 ? "This job is no longer available." : "Connection interrupted; your last progress remains shown.");
          }
        }
      } catch (err) {
        if (cancelled) return;
        sessionLost = [401, 403].includes(err?.status);
        again = ["all", "active"].includes(scope);
        setError(sessionLost ? "Your session expired. Sign in again to check progress." : again ? "Connection interrupted; checking again. Stored documents are safe." : "Connection interrupted. Refresh to try again. Stored documents are safe.");
      } finally {
        if (!cancelled) {
          setLoading(false);
          if (again && !sessionLost) timer = setTimeout(poll, 2000);
        }
      }
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [patient.id, scope, offset, selected, refresh]);

  function changePage(nextScope, nextOffset) {
    if (nextScope === scope && nextOffset === offset) return;
    setScope(nextScope);
    setOffset(nextOffset);
    setJobs([]);
    setSelected(null);
    setDetail(null);
    setDetailError("");
  }

  function select(id) {
    setSelected(selected === id ? null : id);
    setDetail(null);
    setDetailError("");
  }

  async function retry(id) {
    try {
      await requestJson(`/api/jobs/${id}/retry`, { method: "POST" });
      setScope("all");
      setOffset(0);
      setDetail(null);
      setRefresh((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not retry the job.");
    }
  }

  async function remove(id) {
    if (!window.confirm("Delete this failed document and its stored pages?")) return;
    try {
      await requestJson(`/api/jobs/${id}`, { method: "DELETE" });
      setSelected(null);
      setDetail(null);
      setRefresh((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the job.");
    }
  }

  return (
    <div className="shell">
      <Topbar
        current="queue"
        back={{ label: "Back to summary", onClick: onDone }}
        onDocuments={onDocuments}
        onAdd={onAdd}
        onSignOut={onSignOut}
      />
      <main>
        {cloudReviewAvailable && awaiting ? <RedactionConsent key={awaiting.document_id} documentId={awaiting.document_id} cloudAvailable={cloudReviewAvailable}
          onResolved={() => { setJobs((current) => current.map((job) => job.id === awaiting.id ? { ...job, status: "running" } : job)); setRefresh((value) => value + 1); }} /> : null}
        <header className="page-head"><h1 tabIndex={-1}>Queue</h1></header>
        <div className="form-actions queue-controls" aria-label="Job lists">
          <button type="button" className="button-secondary" aria-pressed={scope === "all"} onClick={() => changePage("all", 0)}>All</button>
          <button type="button" className="button-secondary" aria-pressed={scope === "active"} onClick={() => changePage("active", 0)}>Active</button>
          <button type="button" className="button-secondary" aria-pressed={scope === "failed"} onClick={() => changePage("failed", 0)}>Failed</button>
          <button type="button" className="button-secondary" aria-pressed={scope === "recent"} onClick={() => changePage("recent", 0)}>Finished</button>
          <button type="button" className="text-button" onClick={() => setRefresh((value) => value + 1)}>Refresh</button>
        </div>
        {error ? <p className="alert" role="alert">{error}</p> : null}
        {loading && !jobs.length ? <p className="empty" role="status">Loading jobs…</p> : null}
        {!loading && !error && !jobs.length ? <p className="empty">{{ all: "No uploaded jobs.", active: "No active jobs.", failed: "No failed jobs.", recent: "No finished jobs." }[scope]}</p> : null}
        <ul className="queue-list">
          {jobs.map((job) => (
            <li key={job.id}>
              <section className="panel" aria-labelledby={`job-${job.id}`}>
                <div className="result-head">
                  <div>
                    <h2 id={`job-${job.id}`}>{job.doc_type ? docTypeLabel(job.doc_type) : "Document"} <span className="mono">{shortId(job.document_id ?? job.id)}</span></h2>
                    {job.created_at ? <p className="result-note">Uploaded {formatDate(job.created_at)}</p> : null}
                  </div>
                  <span className="pill">{statusLabel({ running: "processing", queued: "queued", failed: "failed", done: "done" }[job.state])}</span>
                </div>
                <JobProgress job={selected === job.id && detail ? { ...detail, id: job.id } : job} compact={selected !== job.id || !detail} detailsOpen />
                {selected === job.id && detailError ? <p className="alert" role="status">{detailError}</p> : null}
                {selected === job.id && !detail && !detailError ? <p role="status">Loading processing details…</p> : null}
                <div className="form-actions">
                  <button type="button" className="text-button" aria-expanded={selected === job.id} onClick={() => select(job.id)}>{selected === job.id ? "Hide details" : "Show details"}</button>
                  {job.document_id && ["failed", "queued"].includes(job.state) ? (
                    <button type="button" className="button-secondary" onClick={() => retry(job.id)}>Retry</button>
                  ) : null}
                  {job.state === "failed" ? (
                    <button type="button" className="text-button" onClick={() => remove(job.id)}>Delete</button>
                  ) : null}
                  {job.document_id ? <button type="button" className="button-secondary" onClick={() => onOpenDocument(job.document_id, job.current_page ?? 1)}>{job.state === "done" ? "Review extracted fields" : "Open document"}</button> : null}
                </div>
              </section>
            </li>
          ))}
        </ul>
        <div className="form-actions" aria-label="Job pages">
          <button type="button" className="button-secondary" disabled={offset === 0 || loading} onClick={() => changePage(scope, Math.max(0, offset - PAGE_SIZE))}>Previous</button>
          <span>Page {Math.floor(offset / PAGE_SIZE) + 1}</span>
          <button type="button" className="button-secondary" disabled={!hasMore || loading} onClick={() => changePage(scope, offset + PAGE_SIZE)}>Next</button>
        </div>
      </main>
      <Footer />
    </div>
  );
}
