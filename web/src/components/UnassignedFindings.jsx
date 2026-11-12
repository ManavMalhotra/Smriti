import { useMemo, useState } from "react";
import Panel from "./Panel";
import { shortId } from "../lib/format";

export default function UnassignedFindings({
  results = [],
  timeline = [],
  onOpenDocument,
}) {
  const [expanded, setExpanded] = useState(false);

  // Collect all extracted items not charted in the numerical results
  const items = useMemo(() => {
    const list = [];
    const seen = new Set();

    // 1. Excluded readings from results
    for (const res of results) {
      for (const exc of res.excluded ?? []) {
        const key = `exc-${exc.document_id}-${res.analyte_id}-${exc.reason}`;
        if (!seen.has(key)) {
          seen.add(key);
          list.push({
            id: key,
            label: res.display,
            value: "Excluded reading",
            reason: exc.reason || "Excluded from numerical trend",
            document_id: exc.document_id,
            page: 1,
            type: "excluded",
          });
        }
      }
    }

    // 2. Non-lab facts or unmapped observations from timeline reports
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
    <Panel title="Something missing?">
      <div className="unassigned-head">
        <p className="result-note">
          {items.length} extracted {items.length === 1 ? "value or note is" : "values or notes are"} not
          plotted on the main lab charts (such as prose impressions, unmapped parameters, or excluded readings).
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
        <div className="unassigned-actions">
          <button
            type="button"
            className="text-button"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Show less" : `Show all ${items.length} unassigned findings`}
          </button>
        </div>
      ) : null}
    </Panel>
  );
}
