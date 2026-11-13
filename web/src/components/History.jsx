import { useState } from "react";
import Panel from "./Panel";
import SourcePills from "./SourcePills";
import {
  categoryLabel,
  docTypeLabel,
  formatDate,
  statusLabel,
} from "../lib/format";

const RECENT = 8;

function fromReport(report) {
  return {
    key: `report-${report.id}`,
    date: report.report_date,
    documentId: report.document_id,
    page: report.page_start ?? 1,
    title: report.title || categoryLabel(report.category),
    category: report.category,
    facility: report.facility_name,
    summary: report.summary || report.facts?.[0]?.value_text || "",
    status: report.status,
    reviewCount: report.review_count ?? 0,
  };
}

function fromDocument(document) {
  return {
    key: `document-${document.id}`,
    date: document.collection_date || document.registration_date || document.doc_date,
    documentId: document.id,
    page: 1,
    title: docTypeLabel(document.doc_type),
    category: null,
    facility: document.facility_name,
    summary: "",
    status: document.status,
    reviewCount: document.review_count ?? 0,
  };
}

export function buildHistory(reports = [], documents = []) {
  const covered = new Set(reports.map((report) => report.document_id));
  const entries = [
    ...reports.map(fromReport),
    ...documents.filter((document) => !covered.has(document.id)).map(fromDocument),
  ];
  return entries.sort((left, right) => {
    if (left.date === right.date) return 0;
    if (!left.date) return 1;
    if (!right.date) return -1;
    return right.date.localeCompare(left.date);
  });
}

export default function History({
  reports = [],
  documents = [],
  loading = false,
  error = "",
  onOpen,
  events,
  onSource,
  title,
}) {
  const [expanded, setExpanded] = useState(false);
  const entries = Array.isArray(events) ? events.map((item) => ({ ...item, key: item.id, date: item.event_date,
    documentId: item.doc_id, page: item.page_num, summary: item.value_text })) : buildHistory(reports, documents);
  const visible = expanded ? entries : entries.slice(0, RECENT);
  const panelTitle = title || (Array.isArray(events) ? "Health timeline" : "History");

  return (
    <Panel title={panelTitle}>
      {loading && !entries.length ? (
        <p className="empty" role="status">
          Loading history…
        </p>
      ) : null}
      {error ? (
        <div className="alert" role="alert">
          {error}
        </div>
      ) : null}
      {!loading && !error && !entries.length ? (
        <p className="empty">No records yet.</p>
      ) : null}

      {visible.length ? (
        <ol className="timeline-list">
          {visible.map((entry) => (
            <li key={entry.key} className="timeline-item">
              <div className="timeline-date">{formatDate(entry.date)}</div>
              <div className="timeline-body">
                <div className="timeline-title">
                  <span>{entry.title}</span>
                  {entry.category && !Array.isArray(events) ? <span className="pill">{categoryLabel(entry.category)}</span> : null}
                  {entry.status && entry.status !== "done" ? (
                    <span className="pill">{statusLabel(entry.status)}</span>
                  ) : null}
                </div>
                {entry.summary ? <p className="timeline-summary">{entry.summary}</p> : null}
                {entry.is_backdated_from_summary ? <p className="result-note">Recorded in Discharge Summary ({formatDate(entry.report_date)})</p> : null}
                {entry.date_needs_review ? <p className="alert">AI date correction — verify the source date.</p> : null}
                <p className="result-note">
                  {[entry.facility, entry.reviewCount > 0 ? `${entry.reviewCount} to review` : null]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                {Array.isArray(events) ? <SourcePills item={entry} onSource={onSource} /> : <button
                  type="button"
                  className="text-button"
                  onClick={() => onOpen?.(entry.documentId, entry.page)}
                  aria-label={`Open ${entry.title} from ${formatDate(entry.date)}`}
                >
                  Open source
                </button>}
              </div>
            </li>
          ))}
        </ol>
      ) : null}

      {entries.length > RECENT ? (
        <button
          type="button"
          className="text-button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "Show recent" : `Show all ${entries.length}`}
        </button>
      ) : null}
    </Panel>
  );
}
