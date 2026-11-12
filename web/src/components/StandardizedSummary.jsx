import { useState } from "react";
import Panel from "./Panel";
import { formatDate } from "../lib/format";

const RECENT = 5;

export default function StandardizedSummary({ summary, onOpenDocument }) {
  const [expanded, setExpanded] = useState(false);
  if (!summary) return null;

  const records = summary.year_wise_history ?? [];
  const visible = expanded ? records : records.slice(0, RECENT);

  return (
    <Panel title="Recent reports">
      {!records.length ? <p className="empty">No report summaries yet.</p> : (
        <ol className="report-summary-list">
          {visible.map((record, index) => (
            <li key={`${record.source_doc_id}-${record.source_page}-${index}`}>
              <div className="timeline-title">
                <strong>{record.title}</strong>
                <span className="pill">{record.status === "review" ? "Needs review" : "From report"}</span>
              </div>
              <p className="result-note">{record.exact_date ? formatDate(record.exact_date) : "Date not recorded"}</p>
              {record.summary ? <p className="timeline-summary">{record.summary}</p> : null}
              {record.source_doc_id ? <button type="button" className="text-button"
                onClick={() => onOpenDocument?.(record.source_doc_id, record.source_page || 1)}>
                Open source{record.source_page ? ` · page ${record.source_page}` : ""}
              </button> : null}
            </li>
          ))}
        </ol>
      )}
      {records.length > RECENT ? <button type="button" className="text-button" aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}>{expanded ? "Show recent" : `Show all ${records.length}`}</button> : null}
    </Panel>
  );
}
