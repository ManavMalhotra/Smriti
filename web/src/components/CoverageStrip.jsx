export default function CoverageStrip({ coverage }) {
  const quarters = coverage.quarters ?? [];
  const total = quarters.reduce((sum, quarter) => sum + quarter.documents, 0);

  return (
    <section className="coverage" aria-labelledby="coverage-heading">
      <div className="coverage-head">
        <h2 id="coverage-heading" className="eyebrow">
          Coverage
        </h2>
        <span className="coverage-total">
          {total} {coverage.undated_documents || coverage.future_documents ? "dated " : ""}{total === 1 ? "document" : "documents"}
          {coverage.undated_documents ? ` · ${coverage.undated_documents} without a clinical date` : ""}
          {coverage.future_documents ? ` · ${coverage.future_documents} future-dated` : ""}
        </span>
      </div>
      <ul className="coverage-list">
        {quarters.map((quarter) => {
          const label = quarter.q.replace("-Q", " Q");
          return (
            <li className="coverage-cell" data-docs={quarter.documents} key={quarter.q}>
              <span className="coverage-bar" aria-hidden="true" />
              <span className="coverage-quarter">{label}</span>
              <span className="coverage-count">
                {quarter.documents} {quarter.documents === 1 ? "document" : "documents"}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
