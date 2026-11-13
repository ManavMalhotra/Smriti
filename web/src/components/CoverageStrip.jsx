import { useState } from "react";
import { docTypeLabel, formatDate } from "../lib/format";

function getQuarterKey(dateStr) {
  if (!dateStr || typeof dateStr !== "string") return "";
  const year = dateStr.slice(0, 4);
  const month = parseInt(dateStr.slice(5, 7), 10);
  if (isNaN(month) || month < 1 || month > 12) return "";
  const q = Math.ceil(month / 3);
  return `${year}-Q${q}`;
}

export default function CoverageStrip({ coverage = {}, documents = [], onOpenDocument }) {
  const [selectedQuarter, setSelectedQuarter] = useState(null);
  const quarters = coverage.quarters ?? [];
  const total = quarters.reduce((sum, quarter) => sum + quarter.documents, 0);

  const quarterDocs = selectedQuarter
    ? (documents || []).filter((doc) => {
        const d = doc.doc_date || doc.collection_date;
        return getQuarterKey(d) === selectedQuarter;
      })
    : [];

  return (
    <section className="coverage" aria-labelledby="coverage-heading">
      <div className="coverage-head">
        <h2 id="coverage-heading" className="eyebrow">
          Coverage
        </h2>
        <span className="coverage-total">
          {total} dated {total === 1 ? "document" : "documents"}
          {coverage.undated_documents ? ` · ${coverage.undated_documents} without a clinical date` : ""}
          {coverage.future_documents ? ` · ${coverage.future_documents} future-dated` : ""}
        </span>
      </div>
      <ul className="coverage-list">
        {quarters.map((quarter) => {
          const label = quarter.q.replace("-Q", " Q");
          const isSelected = selectedQuarter === quarter.q;
          return (
            <li
              className={`coverage-cell ${isSelected ? "selected" : ""}`}
              data-docs={quarter.documents}
              key={quarter.q}
              onClick={() => setSelectedQuarter(isSelected ? null : quarter.q)}
              style={{ cursor: "pointer" }}
              title="Click to view documents"
            >
              <span className="coverage-bar" aria-hidden="true" />
              <span className="coverage-quarter">{label}</span>
              <span className="coverage-separator" aria-hidden="true"> · </span>
              <span className="coverage-count">
                {quarter.documents} {quarter.documents === 1 ? "document" : "documents"}
              </span>
            </li>
          );
        })}
      </ul>

      {selectedQuarter ? (
        <div className="quarter-drawer" role="region" aria-label={`Documents in ${selectedQuarter.replace("-Q", " Q")}`}>
          <div className="quarter-drawer-head">
            <h3>{selectedQuarter.replace("-Q", " Q")} Documents</h3>
            <button
              type="button"
              className="text-button"
              onClick={() => setSelectedQuarter(null)}
              aria-label="Close quarter timeline"
            >
              ✕ Close
            </button>
          </div>
          {quarterDocs.length === 0 ? (
            <p className="empty" style={{ margin: "8px 0" }}>
              No dated documents found in this quarter.
            </p>
          ) : (
            <ul className="quarter-doc-list">
              {quarterDocs.map((doc) => (
                <li key={doc.id} className="quarter-doc-item">
                  <div className="quarter-doc-info">
                    <span className="quarter-doc-date">
                      {formatDate(doc.doc_date || doc.collection_date)}
                    </span>
                    <strong className="quarter-doc-title">
                      {doc.facility_name || doc.display_name || docTypeLabel(doc.doc_type)}
                    </strong>
                    <span className="quarter-doc-meta">
                      {docTypeLabel(doc.doc_type)} · {doc.page_count} {doc.page_count === 1 ? "page" : "pages"}
                    </span>
                    {doc.review_count > 0 ? (
                      <span className="pill warning">{doc.review_count} to review</span>
                    ) : (
                      <span className="pill success">Verified</span>
                    )}
                  </div>
                  {onOpenDocument ? (
                    <button
                      type="button"
                      className="button-secondary"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenDocument(doc.id);
                      }}
                    >
                      {doc.review_count > 0 ? "Review Now" : "Open Document"}
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}
