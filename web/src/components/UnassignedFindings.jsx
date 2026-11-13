import { useMemo, useState } from "react";
import Panel from "./Panel";
import { shortId } from "../lib/format";

export default function UnassignedFindings({
  results = [],
  timeline = [],
  onOpenDocument,
  onSummaryUpdate,
}) {
  const [expanded, setExpanded] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [rejectNotice, setRejectNotice] = useState("");

  const handleBulkReject = async () => {
    if (!window.confirm("Bulk reject all unassigned lab footnotes and boilerplate text?")) return;
    setRejecting(true);
    setRejectNotice("");
    try {
      const res = await fetch("/api/observations/bulk-reject-boilerplate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (res.ok) {
        const data = await res.json();
        setRejectNotice(`Cleaned up ${data.rejected_count} boilerplate items.`);
        if (data.summary && onSummaryUpdate) {
          onSummaryUpdate(data.summary);
        }
      }
    } catch {
      // Best effort
    } finally {
      setRejecting(false);
    }
  };

  // Collect all extracted items not charted in the numerical results
  const items = useMemo(() => {
    const list = [];
    const seen = new Set();

    // Non-lab facts or unmapped observations from timeline reports
    const chartedAnalytes = new Set(results.map((r) => r.analyte_id));
    for (const report of timeline) {
      for (const fact of report.facts ?? []) {
        const isCharted = fact.fact_type === "lab" && chartedAnalytes.has(fact.analyte_id);
        if (!isCharted) {
          const key = `fact-${fact.id || `${fact.document_id}-${fact.page}-${fact.label_raw}`}`;
          if (!seen.has(key)) {
            seen.add(key);
            list.push({
              id: key,
              label: fact.label_raw || fact.label_norm || fact.fact_type || "Finding",
              value: fact.value_text || fact.value_num || fact.evidence_quote || "—",
              unit: fact.unit_norm,
              reason: fact.reason || (fact.fact_type !== "lab" ? fact.fact_type : "Unmapped parameter"),
              document_id: fact.document_id || report.document_id,
              page: fact.page || report.page_start || 1,
              type: fact.fact_type || "other",
            });
          }
        }
      }
    }

    return list;
  }, [results, timeline]);

  if (items.length === 0) {
    return null;
  }

  const displayed = expanded ? items : items.slice(0, 5);

  return (
    <Panel title="Other extracted findings">
      <details className="unassigned-drawer" open={expanded} onToggle={(e) => setExpanded(e.target.open)}>
        <summary style={{ cursor: "pointer", fontWeight: 600, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>
            {items.length} unassigned {items.length === 1 ? "finding / note" : "findings / notes"} (Click to {expanded ? "collapse" : "expand"})
          </span>
          <button
            type="button"
            className="button-secondary danger"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              handleBulkReject();
            }}
            disabled={rejecting}
            style={{ fontSize: "12px", padding: "4px 8px" }}
          >
            {rejecting ? "Cleaning..." : "🧹 Bulk Reject Boilerplate"}
          </button>
        </summary>

        {rejectNotice ? (
          <p className="pill success" style={{ margin: "10px 0" }}>
            {rejectNotice}
          </p>
        ) : null}

        <div className="unassigned-head" style={{ marginTop: "12px" }}>
          <p className="result-note">
            {items.length} extracted {items.length === 1 ? "value or note is" : "values or notes are"} not
            plotted on the lab charts.
          </p>
        </div>

        <div className="table-wrap">
          <table>
            <caption className="sr-only">Extracted findings not plotted on charts</caption>
            <thead>
              <tr>
                <th scope="col">Finding</th>
                <th scope="col">Extracted text / value</th>
                <th scope="col">Note</th>
                <th scope="col">Source</th>
                {onOpenDocument ? <th scope="col">Action</th> : null}
              </tr>
            </thead>
            <tbody>
              {displayed.map((item) => (
                <tr key={item.id}>
                  <td>
                    <strong>{item.label}</strong>
                  </td>
                  <td>
                    <span className="mono">
                      {item.value}
                      {item.unit ? ` ${item.unit}` : ""}
                    </span>
                  </td>
                  <td>
                    <span className="pill">{item.reason}</span>
                  </td>
                  <td>
                    <span className="doc-id">
                      #{shortId(item.document_id)} · Page {item.page}
                    </span>
                  </td>
                  {onOpenDocument ? (
                    <td>
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => onOpenDocument(item.document_id, item.page)}
                        aria-label={`Open source document for ${item.label}`}
                      >
                        View source
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {items.length > 5 ? (
          <div className="unassigned-actions" style={{ marginTop: "8px" }}>
            <button
              type="button"
              className="text-button"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? "Show fewer" : `Show all ${items.length} unassigned findings`}
            </button>
          </div>
        ) : null}
      </details>
    </Panel>
  );
}
